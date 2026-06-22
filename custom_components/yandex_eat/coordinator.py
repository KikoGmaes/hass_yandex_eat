from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import YandexEatApi
from .const import CONF_SCAN_INTERVAL, CONF_X_TOKEN, DEFAULT_SCAN_INTERVAL, DOMAIN, STATE_NO_ORDER
from .models import TrackedOrder
from .yandex_session import YandexSession

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    YandexEatConfigEntry = ConfigEntry[YandexEatCoordinator]
else:
    YandexEatConfigEntry = ConfigEntry


class YandexEatCoordinator(DataUpdateCoordinator[dict[str, TrackedOrder]]):
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

    async def _async_setup_api(self) -> None:
        session = async_create_clientsession(self.hass)
        yandex = YandexSession(session, x_token=self.entry.data[CONF_X_TOKEN])
        if not await yandex.refresh_cookies():
            raise ConfigEntryAuthFailed("Invalid or expired Yandex token")
        self.api = YandexEatApi(yandex)

    async def _async_update_data(self) -> dict[str, TrackedOrder]:
        if self.api is None:
            await self._async_setup_api()
        assert self.api is not None
        try:
            orders = await self.api.async_get_all_tracked_orders()
        except ConfigEntryAuthFailed:
            self.entry.async_start_reauth(self.hass)
            raise
        except Exception as err:
            raise UpdateFailed(str(err)) from err
        return {order.id: order for order in orders if order.id}

    @property
    def active_orders(self) -> list[TrackedOrder]:
        return [o for o in self.data.values() if o.is_active]

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
