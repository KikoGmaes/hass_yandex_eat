from __future__ import annotations

import logging
from typing import Any

from .const import EMPTY_HTTP_STATUSES, SERVICE_BASE_URLS, TRACKED_ORDERS_PATH
from .models import Service, TrackedOrder
from .yandex_session import YandexSession

_LOGGER = logging.getLogger(__name__)


class YandexEatApi:
    def __init__(self, session: YandexSession) -> None:
        self._session = session

    async def async_get_profile(self, service: Service = Service.EDA) -> dict[str, Any]:
        base = SERVICE_BASE_URLS[service.value]
        data = await self._session.get_json(f"{base}/api/v1/user/profile")
        if not isinstance(data, dict):
            raise TypeError(f"expected profile dict, got {type(data).__name__}")
        return data

    async def async_get_tracked_orders(self, service: Service) -> list[TrackedOrder]:
        base = SERVICE_BASE_URLS[service.value]
        url = f"{base}{TRACKED_ORDERS_PATH}"
        try:
            data = await self._session.get_json(url, empty_statuses=EMPTY_HTTP_STATUSES)
        except Exception as err:
            _LOGGER.debug("tracked-orders failed for %s: %s", service.value, err)
            return []
        if not isinstance(data, list):
            _LOGGER.warning("unexpected tracked-orders payload for %s: %s", service.value, type(data))
            return []
        return [TrackedOrder.from_api(item, service) for item in data if isinstance(item, dict)]

    async def async_get_all_tracked_orders(self) -> list[TrackedOrder]:
        orders: list[TrackedOrder] = []
        for service in Service:
            orders.extend(await self.async_get_tracked_orders(service))
        return orders
