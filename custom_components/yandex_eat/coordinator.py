from __future__ import annotations



import logging

from dataclasses import dataclass

from datetime import timedelta

from typing import TYPE_CHECKING, Any



from homeassistant.config_entries import ConfigEntry

from homeassistant.core import HomeAssistant

from homeassistant.exceptions import ConfigEntryAuthFailed

from homeassistant.helpers.aiohttp_client import async_create_clientsession

from homeassistant.helpers.storage import Store

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed



from .api import YandexEatApi

from .const import (
    CONF_EXTRA_ORDER_NRS,
    CONF_SCAN_INTERVAL,
    CONF_X_TOKEN,
    CONF_RESTAURANT_AS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_RESTAURANT_AS,
    DOMAIN,
    KNOWN_ORDERS_STORE_VERSION,
    RESTAURANT_AS_MARKET,
)

from .models import OrderHistoryEntry, Service, TrackedOrder

from .yandex_session import YandexSession



_LOGGER = logging.getLogger(__name__)



if TYPE_CHECKING:

    YandexEatConfigEntry = ConfigEntry[YandexEatCoordinator]

else:

    YandexEatConfigEntry = ConfigEntry





@dataclass(frozen=True)

class YandexEatCoordinatorData:

    orders: dict[str, TrackedOrder]

    recent_orders: tuple[OrderHistoryEntry, ...]





class YandexEatCoordinator(DataUpdateCoordinator[YandexEatCoordinatorData]):

    config_entry: YandexEatConfigEntry



    def __init__(self, hass: HomeAssistant, entry: YandexEatConfigEntry) -> None:

        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

        super().__init__(

            hass,

            _LOGGER,

            name=f"{DOMAIN}_{entry.unique_id}",

            update_interval=timedelta(seconds=scan_interval),

            config_entry=entry,

        )

        self.entry = entry

        self.api: YandexEatApi | None = None

        self._known_orders_store = Store(
            hass,
            KNOWN_ORDERS_STORE_VERSION,
            f"{DOMAIN}_known_orders_{entry.entry_id}",
        )



    async def _async_setup_api(self) -> None:

        session = async_create_clientsession(self.hass)

        yandex = YandexSession(session, x_token=self.entry.data[CONF_X_TOKEN])

        if not await yandex.refresh_cookies():

            raise ConfigEntryAuthFailed("Invalid or expired Yandex token")

        self.api = YandexEatApi(yandex)

    def _parse_extra_order_nrs(self) -> set[str]:
        raw = self.entry.options.get(CONF_EXTRA_ORDER_NRS, "")
        if not isinstance(raw, str) or not raw.strip():
            return set()
        return {part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()}

    async def _async_load_known_order_nrs(self) -> set[str]:
        data = await self._known_orders_store.async_load()
        if not isinstance(data, dict):
            return set()
        stored = data.get("order_nrs")
        if not isinstance(stored, list):
            return set()
        return {str(order_nr) for order_nr in stored if order_nr}

    async def _async_save_known_order_nrs(self, order_nrs: set[str]) -> None:
        trimmed = sorted(order_nrs)[-500:]
        await self._known_orders_store.async_save({"order_nrs": trimmed})



    async def _async_update_data(self) -> YandexEatCoordinatorData:

        if self.api is None:

            await self._async_setup_api()

        assert self.api is not None

        restaurant_as = Service.EDA
        restaurant_pref = self.entry.options.get(CONF_RESTAURANT_AS, DEFAULT_RESTAURANT_AS)
        if restaurant_pref == RESTAURANT_AS_MARKET:
            restaurant_as = Service.MARKET

        try:

            known_order_nrs = await self._async_load_known_order_nrs()
            known_order_nrs.update(self._parse_extra_order_nrs())

            orders = await self.api.async_get_all_tracked_orders()
            for order in orders:
                if order.id:
                    known_order_nrs.add(order.id)

            recent = await self.api.async_get_recent_orders(
                restaurant_as=restaurant_as,
                extra_order_nrs=frozenset(known_order_nrs),
            )

            for entry in recent:
                known_order_nrs.add(entry.order_nr)
            await self._async_save_known_order_nrs(known_order_nrs)

        except ConfigEntryAuthFailed:

            self.entry.async_start_reauth(self.hass)

            raise

        except Exception as err:

            raise UpdateFailed(str(err)) from err

        return YandexEatCoordinatorData(

            orders={order.id: order for order in orders if order.id},

            recent_orders=tuple(recent),

        )



    @property

    def active_orders(self) -> list[TrackedOrder]:

        return [o for o in self.data.orders.values() if o.is_active]



    @property

    def recent_orders(self) -> list[OrderHistoryEntry]:

        return list(self.data.recent_orders)



    @property

    def last_order(self) -> OrderHistoryEntry | None:

        if not self.data.recent_orders:

            return None

        return self.data.recent_orders[0]



    @property

    def nearby_orders(self) -> list[TrackedOrder]:

        return [o for o in self.active_orders if o.courier_nearby]



    @property

    def primary_order(self) -> TrackedOrder | None:

        orders = self.active_orders

        if not orders:

            return None

        if len(orders) == 1:

            return orders[0]

        nearby = [order for order in orders if order.courier_nearby]

        if nearby:

            return nearby[0]

        with_eta = [

            order

            for order in orders

            if order.tracking_info and order.tracking_info.remaining_time is not None

        ]

        if with_eta:

            return min(with_eta, key=lambda order: order.tracking_info.remaining_time)  # type: ignore[union-attr]

        return orders[0]



    def order_attributes(self, order: TrackedOrder) -> dict[str, Any]:

        attrs = dict(order.raw)

        attrs["service"] = order.service.value

        attrs["courier_nearby"] = order.courier_nearby

        if order.tracking_info:

            attrs["tracking_info"] = order.tracking_info.raw

            if order.tracking_info.remaining_time is not None:

                attrs["eta_minutes"] = order.tracking_info.remaining_time

        return attrs



    def recent_order_dict(self, order: OrderHistoryEntry) -> dict[str, Any]:

        return {

            "order_nr": order.order_nr,

            "name": order.name,

            "date": order.date,

            "status": order.status,

            "cost": order.cost,

            "service": order.service.value,

        }


