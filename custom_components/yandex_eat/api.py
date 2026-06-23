from __future__ import annotations

import logging
from typing import Any

from .const import (
    EMPTY_HTTP_STATUSES,
    ORDERS_INFO_BASE_URLS,
    ORDERS_INFO_PATH,
    ORDERS_INFO_PAGE_LIMIT,
    ORDERS_INFO_MAX_PAGES,
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


def _extract_orders_payload(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    orders = data.get("orders")
    if isinstance(orders, list):
        return [item for item in orders if isinstance(item, dict)]
    return []


def _pagination_settings(data: dict[str, Any]) -> dict[str, Any]:
    ps = data.get("pagination_settings")
    return ps if isinstance(ps, dict) else {}


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

    async def _async_get_orders_info_page(
        self,
        base: str,
        *,
        cursor: str | None,
    ) -> dict[str, Any] | None:
        pagination_settings: dict[str, Any] = {"limit": ORDERS_INFO_PAGE_LIMIT}
        if cursor:
            pagination_settings["cursor"] = cursor
        body = {"pagination_settings": pagination_settings}
        url = f"{base}{ORDERS_INFO_PATH}"
        headers = {**_service_headers(base), "Content-Type": "application/json"}
        try:
            data = await self._session.post_json(url, body, headers=headers)
        except Exception as err:
            _LOGGER.debug("orders-info failed for %s: %s", base, err)
            return None
        return data if isinstance(data, dict) else None

    async def _async_get_orders_from_base(
        self,
        base: str,
        *,
        default_service: Service,
    ) -> list[OrderHistoryEntry]:
        merged: dict[str, OrderHistoryEntry] = {}
        ordered: list[str] = []
        cursor: str | None = None

        for page in range(ORDERS_INFO_MAX_PAGES):
            data = await self._async_get_orders_info_page(base, cursor=cursor)
            if not data:
                break

            items = _extract_orders_payload(data)
            if not items and cursor is None:
                break

            for item in items:
                entry = OrderHistoryEntry.from_api(item, default_service)
                if not entry.order_nr:
                    continue
                if entry.order_nr not in merged:
                    ordered.append(entry.order_nr)
                merged[entry.order_nr] = entry

            ps = _pagination_settings(data)
            has_more = ps.get("has_more")
            if has_more is None:
                has_more = ps.get("hasMore")
            next_cursor = ps.get("cursor")
            if not has_more:
                break
            if not next_cursor or next_cursor == cursor:
                break
            cursor = str(next_cursor)

        return [merged[order_nr] for order_nr in ordered if order_nr in merged]

    async def async_get_recent_orders(self) -> list[OrderHistoryEntry]:
        merged: dict[str, OrderHistoryEntry] = {}
        ordered: list[str] = []
        for base in ORDERS_INFO_BASE_URLS:
            default_service = (
                Service.MARKET if base == SERVICE_BASE_URLS[SERVICE_MARKET] else Service.EDA
            )
            try:
                page_orders = await self._async_get_orders_from_base(
                    base,
                    default_service=default_service,
                )
            except Exception as err:
                _LOGGER.debug("order history failed for %s: %s", base, err)
                continue

            for entry in page_orders:
                if entry.order_nr not in merged:
                    ordered.append(entry.order_nr)
                merged[entry.order_nr] = entry

        return [merged[order_nr] for order_nr in ordered if order_nr in merged]
