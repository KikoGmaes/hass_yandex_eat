from __future__ import annotations

import logging
from typing import Any

from .const import (
    EMPTY_HTTP_STATUSES,
    ORDERS_INFO_BASE_URLS,
    ORDERS_INFO_PATH,
    SERVICE_BASE_URLS,
    SERVICE_MARKET,
    TRACKED_ORDERS_PATH,
    TRACKING_V2_BASE_URLS,
    TRACKING_V2_PATH,
)
from .models import OrderHistoryEntry, Service, TrackedOrder
from .yandex_session import YandexSession

_LOGGER = logging.getLogger(__name__)


def _service_headers(base: str) -> dict[str, str]:
    return {"Origin": base, "Referer": f"{base}/"}


class YandexEatApi:
    def __init__(self, session: YandexSession) -> None:
        self._session = session

    async def async_get_profile(self, service: Service = Service.EDA) -> dict[str, Any]:
        base = SERVICE_BASE_URLS[service.value]
        data = await self._session.get_json(
            f"{base}/api/v1/user/profile",
            headers=_service_headers(base),
        )
        if not isinstance(data, dict):
            raise TypeError(f"expected profile dict, got {type(data).__name__}")
        return data

    async def async_get_tracked_orders_v1(self, service: Service) -> list[TrackedOrder]:
        base = SERVICE_BASE_URLS[service.value]
        url = f"{base}{TRACKED_ORDERS_PATH}"
        try:
            data = await self._session.get_json(
                url,
                headers=_service_headers(base),
                empty_statuses=EMPTY_HTTP_STATUSES,
            )
        except Exception as err:
            _LOGGER.debug("tracked-orders v1 failed for %s: %s", service.value, err)
            return []
        if not isinstance(data, list):
            _LOGGER.debug("unexpected tracked-orders v1 payload for %s: %s", service.value, type(data))
            return []
        return [TrackedOrder.from_api(item, service) for item in data if isinstance(item, dict)]

    async def async_get_tracked_orders_v2(self, service: Service) -> list[TrackedOrder]:
        base = SERVICE_BASE_URLS[service.value]
        if base not in TRACKING_V2_BASE_URLS:
            return []
        url = f"{base}{TRACKING_V2_PATH}"
        try:
            data = await self._session.get_json(url, headers=_service_headers(base))
        except Exception as err:
            _LOGGER.debug("tracked-orders v2 failed for %s: %s", service.value, err)
            return []
        if not isinstance(data, dict):
            return []
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return []
        tracked = payload.get("trackedOrders")
        if not isinstance(tracked, list):
            return []
        orders = [
            TrackedOrder.from_api_v2(item, service)
            for item in tracked
            if isinstance(item, dict)
        ]
        return [order for order in orders if order.id]

    async def async_get_tracked_orders(self, service: Service) -> list[TrackedOrder]:
        merged: dict[str, TrackedOrder] = {}
        for order in await self.async_get_tracked_orders_v1(service):
            if order.id:
                merged[order.id] = order
        for order in await self.async_get_tracked_orders_v2(service):
            if order.id:
                merged[order.id] = order
        return list(merged.values())

    async def async_get_all_tracked_orders(self) -> list[TrackedOrder]:
        merged: dict[str, TrackedOrder] = {}
        for service in Service:
            for order in await self.async_get_tracked_orders(service):
                if order.id:
                    merged[order.id] = order
        return list(merged.values())

    async def async_get_recent_orders(self) -> list[OrderHistoryEntry]:
        merged: dict[str, OrderHistoryEntry] = {}
        ordered: list[str] = []
        for base in ORDERS_INFO_BASE_URLS:
            default_service = (
                Service.MARKET if base == SERVICE_BASE_URLS[SERVICE_MARKET] else Service.EDA
            )
            url = f"{base}{ORDERS_INFO_PATH}"
            try:
                data = await self._session.post_json(
                    url,
                    {},
                    headers={**_service_headers(base), "Content-Type": "application/json"},
                )
            except Exception as err:
                _LOGGER.debug("orders-info failed for %s: %s", base, err)
                continue
            if not isinstance(data, dict):
                continue
            orders = data.get("orders")
            if not isinstance(orders, list):
                continue
            for item in orders:
                if not isinstance(item, dict):
                    continue
                entry = OrderHistoryEntry.from_api(item, default_service)
                if not entry.order_nr:
                    continue
                if entry.order_nr not in merged:
                    ordered.append(entry.order_nr)
                merged[entry.order_nr] = entry
        return [merged[order_nr] for order_nr in ordered if order_nr in merged]
