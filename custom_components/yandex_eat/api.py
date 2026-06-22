from __future__ import annotations

import logging
from typing import Any

from .const import (
    EMPTY_HTTP_STATUSES,
    ORDER_HISTORY_MAX_PAGES,
    ORDER_HISTORY_PAGE_SIZE,
    ORDER_HISTORY_PATHS,
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


def _extract_orders_payload(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    orders = data.get("orders")
    if isinstance(orders, list):
        return [item for item in orders if isinstance(item, dict)]
    payload = data.get("payload")
    if isinstance(payload, dict):
        for key in ("orders", "order_list", "orderList"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def _pagination_has_more(data: dict[str, Any], *, page_size: int, items_count: int) -> bool:
    for container in (data, data.get("payload"), data.get("meta")):
        if not isinstance(container, dict):
            continue
        pagination = container.get("pagination")
        if not isinstance(pagination, dict):
            continue
        has_more = pagination.get("has_more")
        if has_more is None:
            has_more = pagination.get("hasMore")
        if has_more is not None:
            return bool(has_more)
        for key in ("cursor", "next_cursor", "nextCursor", "next"):
            if pagination.get(key):
                return True
    for key in ("cursor", "next_cursor", "nextCursor", "next"):
        if data.get(key):
            return True
    return items_count >= page_size


def _pagination_cursor(
    data: dict[str, Any],
    *,
    items: list[dict[str, Any]] | None = None,
    allow_order_offset: bool = False,
) -> str | None:
    for container in (data, data.get("payload"), data.get("meta")):
        if not isinstance(container, dict):
            continue
        pagination = container.get("pagination")
        if isinstance(pagination, dict):
            for key in ("cursor", "next_cursor", "nextCursor", "next"):
                value = pagination.get(key)
                if value:
                    return str(value)
    for key in ("cursor", "next_cursor", "nextCursor", "next"):
        value = data.get(key)
        if value:
            return str(value)
    if allow_order_offset and items:
        last_order_nr = items[-1].get("order_nr")
        if last_order_nr:
            return f"offset:{last_order_nr}"
    return None


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

    async def _async_fetch_order_history_page(
        self,
        base: str,
        path: str,
        *,
        cursor: str | None,
        page_size: int,
    ) -> dict[str, Any] | None:
        pagination: dict[str, Any] = {"limit": page_size}
        if cursor:
            pagination["cursor"] = cursor
        bodies = (
            {"pagination": pagination},
            {"limit": page_size, "cursor": cursor} if cursor else {"limit": page_size},
            {} if cursor is None else None,
        )
        url = f"{base}{path}"
        headers = {**_service_headers(base), "Content-Type": "application/json"}
        for body in bodies:
            if body is None:
                continue
            try:
                data = await self._session.post_json(url, body, headers=headers)
            except Exception as err:
                _LOGGER.debug("order history page failed for %s%s: %s", base, path, err)
                continue
            if isinstance(data, dict):
                return data
        return None

    async def _async_get_orders_from_endpoint(
        self,
        base: str,
        path: str,
        *,
        default_service: Service,
    ) -> list[OrderHistoryEntry]:
        merged: dict[str, OrderHistoryEntry] = {}
        ordered: list[str] = []
        cursor: str | None = None
        allow_order_offset = "eats-order-history" in path

        for _ in range(ORDER_HISTORY_MAX_PAGES):
            data = await self._async_fetch_order_history_page(
                base,
                path,
                cursor=cursor,
                page_size=ORDER_HISTORY_PAGE_SIZE,
            )
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

            next_cursor = _pagination_cursor(
                data,
                items=items,
                allow_order_offset=allow_order_offset,
            )
            if not _pagination_has_more(
                data,
                page_size=ORDER_HISTORY_PAGE_SIZE,
                items_count=len(items),
            ):
                break
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

        return [merged[order_nr] for order_nr in ordered if order_nr in merged]

    async def async_get_recent_orders(self) -> list[OrderHistoryEntry]:
        merged: dict[str, OrderHistoryEntry] = {}
        ordered: list[str] = []
        for base in ORDERS_INFO_BASE_URLS:
            default_service = (
                Service.MARKET if base == SERVICE_BASE_URLS[SERVICE_MARKET] else Service.EDA
            )
            page_orders: list[OrderHistoryEntry] = []
            for path in (*ORDER_HISTORY_PATHS, ORDERS_INFO_PATH):
                try:
                    page_orders = await self._async_get_orders_from_endpoint(
                        base,
                        path,
                        default_service=default_service,
                    )
                except Exception as err:
                    _LOGGER.debug("order history failed for %s%s: %s", base, path, err)
                    continue
                if page_orders:
                    break

            for entry in page_orders:
                if entry.order_nr not in merged:
                    ordered.append(entry.order_nr)
                merged[entry.order_nr] = entry

        return [merged[order_nr] for order_nr in ordered if order_nr in merged]
