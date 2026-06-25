from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import YandexEatApi
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_X_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    NEARBY_ETA_MINUTES,
    SCAN_INTERVAL_FAST,
    SCAN_INTERVAL_URGENT,
)
from .models import (
    COURIER_TRACKING_STATUSES,
    OrderHistoryEntry,
    TrackedOrder,
    is_cancelled_order,
    parse_order_cost,
    parse_order_year,
)
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
        self._base_scan_interval = int(scan_interval)

        super().__init__(

            hass,

            _LOGGER,

            name=f"{DOMAIN}_{entry.unique_id}",

            update_interval=timedelta(seconds=self._base_scan_interval),

            config_entry=entry,

        )

        self.entry = entry

        self.api: YandexEatApi | None = None



    async def _async_setup_api(self) -> None:

        session = async_create_clientsession(self.hass)

        yandex = YandexSession(session, x_token=self.entry.data[CONF_X_TOKEN])

        if not await yandex.refresh_cookies():

            raise ConfigEntryAuthFailed("Invalid or expired Yandex token")

        self.api = YandexEatApi(yandex)



    async def _async_update_data(self) -> YandexEatCoordinatorData:

        if self.api is None:

            await self._async_setup_api()

        assert self.api is not None

        try:

            orders = await self.api.async_get_all_tracked_orders()

            recent = await self.api.async_get_recent_orders()

        except ConfigEntryAuthFailed:

            self.entry.async_start_reauth(self.hass)

            raise

        except Exception as err:

            raise UpdateFailed(str(err)) from err

        data = YandexEatCoordinatorData(
            orders={order.id: order for order in orders if order.id},
            recent_orders=tuple(recent),
        )
        self._apply_poll_interval([o for o in data.orders.values() if o.is_active])
        return data

    def _compute_poll_interval(self, active_orders: list[TrackedOrder]) -> int:
        if not active_orders:
            return self._base_scan_interval

        interval = self._base_scan_interval
        for order in active_orders:
            if order.courier_nearby:
                interval = min(interval, SCAN_INTERVAL_URGENT)
                continue
            courier_eta = order.courier_eta_minutes
            if courier_eta is not None and courier_eta <= NEARBY_ETA_MINUTES:
                interval = min(interval, SCAN_INTERVAL_FAST)
                continue
            if order.order_status in COURIER_TRACKING_STATUSES:
                interval = min(interval, max(self._base_scan_interval, 60))

        return max(interval, SCAN_INTERVAL_URGENT)

    def _apply_poll_interval(self, active_orders: list[TrackedOrder]) -> None:
        new_seconds = self._compute_poll_interval(active_orders)
        old_seconds = int(self.update_interval.total_seconds()) if self.update_interval else 0
        self.update_interval = timedelta(seconds=new_seconds)
        if new_seconds < old_seconds:
            self.hass.async_create_task(self.async_request_refresh())



    @property

    def active_orders(self) -> list[TrackedOrder]:

        return [o for o in self.data.orders.values() if o.is_active]



    @property
    def recent_orders(self) -> list[OrderHistoryEntry]:
        return list(self.data.recent_orders)

    def spent_orders(self) -> list[OrderHistoryEntry]:
        return [
            order
            for order in self.recent_orders
            if not is_cancelled_order(order.status) and parse_order_cost(order.cost) > 0
        ]

    @property
    def total_spent(self) -> float:
        return sum(parse_order_cost(order.cost) for order in self.spent_orders())

    @property
    def total_spent_this_year(self) -> float:
        year = dt_util.now().year
        return sum(
            parse_order_cost(order.cost)
            for order in self.spent_orders()
            if parse_order_year(order.order_nr, order.date, fallback_year=year) == year
        )

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
            if order.courier_eta_minutes is not None
        ]

        if with_eta:
            return min(with_eta, key=lambda order: order.courier_eta_minutes)  # type: ignore[arg-type,return-value]

        return orders[0]



    def order_attributes(self, order: TrackedOrder) -> dict[str, Any]:

        attrs = dict(order.raw)

        attrs["service"] = order.service.value

        attrs["courier_nearby"] = order.courier_nearby

        if order.tracking_info:
            attrs["tracking_info"] = order.tracking_info.raw

        if order.delivery_eta_minutes is not None:
            attrs["delivery_eta_minutes"] = order.delivery_eta_minutes

        if order.courier_eta_minutes is not None:
            attrs["courier_eta_minutes"] = order.courier_eta_minutes

        attrs["poll_interval_seconds"] = int(self.update_interval.total_seconds())

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


