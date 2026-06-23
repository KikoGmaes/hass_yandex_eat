from __future__ import annotations

import logging
from typing import Any

from .const import (
    EMPTY_HTTP_STATUSES,
    ORDER_HISTORY_PLATFORM_DC,
    ORDER_HISTORY_PLATFORM_EDA,
    ORDER_TRACKING_PLATFORM_DC,
    ORDERS_INFO_BASE_URL,
    ORDERS_INFO_MAX_PAGES,
    ORDERS_INFO_PAGE_LIMIT,
    ORDERS_INFO_PATH,
    SERVICE_BASE_URLS,
    TRACKED_ORDERS_PATH,
    TRACKING_DESKTOP_PATH,
    TRACKING_V2_BASE_URLS,
    TRACKING_V2_PATH,
)
from .models import (
    EDA_ORDER_NR_RE,
    OrderHistoryEntry,
    Service,
    TrackedOrder,
    is_active_orders_info_item,
)
from .yandex_session import YandexSession

_LOGGER = logging.getLogger(__name__)

ORDER_HISTORY_STREAMS = (
    (ORDER_HISTORY_PLATFORM_EDA, Service.EDA),
    (ORDER_HISTORY_PLATFORM_DC, Service.MARKET),
)


def _service_headers(base: str) -> dict[str, str]:
    return {"Origin": base, "Referer": f"{base}/"}


def _desktop_tracking_headers(base: str) -> dict[str, str]:
    return {
        **_service_headers(base),
        "X-Platform": ORDER_TRACKING_PLATFORM_DC,
        "Content-Type": "application/json",
    }


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


def _order_nrs_to_update(data: dict[str, Any]) -> set[str]:
    update_settings = data.get("update_settings")
    if not isinstance(update_settings, dict):
        return set()
    raw = update_settings.get("order_nrs_to_update")
    if not isinstance(raw, list):
        return set()
    return {str(order_nr) for order_nr in raw if order_nr}


def _insert_order_nr(ordered: list[str], order_nr: str) -> None:
    if not EDA_ORDER_NR_RE.match(order_nr):
        ordered.append(order_nr)
        return
    new_date = int(order_nr[:6])
    for index, existing in enumerate(ordered):
        if EDA_ORDER_NR_RE.match(existing) and int(existing[:6]) < new_date:
            ordered.insert(index, order_nr)
            return
    ordered.append(order_nr)


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
        if service == Service.MARKET:
            await self._async_merge_orders_info_active(service, merged)
        return list(merged.values())

    async def async_get_desktop_tracking(
        self,
        service: Service,
        order_nr: str,
    ) -> dict[str, Any] | None:
        base = SERVICE_BASE_URLS[service.value]
        url = f"{base}{TRACKING_DESKTOP_PATH}"
        headers = _desktop_tracking_headers(base)
        try:
            data = await self._session.get_json(
                url,
                params={"order_nr": order_nr},
                headers=headers,
                empty_statuses=frozenset({404}),
            )
            if isinstance(data, dict) and data:
                return data
        except Exception as err:
            _LOGGER.debug("desktop tracking GET failed for %s: %s", order_nr, err)
        try:
            data = await self._session.post_json(
                url,
                {"order_nr": order_nr},
                headers=headers,
                empty_statuses=frozenset({404}),
            )
            if isinstance(data, dict) and data:
                return data
        except Exception as err:
            _LOGGER.debug("desktop tracking POST failed for %s: %s", order_nr, err)
        return None

    async def _async_merge_orders_info_active(
        self,
        service: Service,
        merged: dict[str, TrackedOrder],
    ) -> None:
        base = SERVICE_BASE_URLS[service.value]
        data = await self._async_get_orders_info_page(
            platform=ORDER_HISTORY_PLATFORM_DC,
            cursor=None,
            base_url=base,
        )
        if not data:
            return

        items = _extract_orders_payload(data)
        if not items:
            return

        order_nrs_to_update = _order_nrs_to_update(data)
        items_by_nr = {
            str(item.get("order_nr")): item
            for item in items
            if isinstance(item, dict) and item.get("order_nr")
        }
        active_nrs = {
            order_nr
            for order_nr, item in items_by_nr.items()
            if is_active_orders_info_item(item, order_nrs_to_update)
        }
        if not active_nrs:
            return

        for order_nr in active_nrs:
            existing = merged.get(order_nr)
            if existing is not None and existing.is_active:
                continue
            item = items_by_nr.get(order_nr)
            if not isinstance(item, dict):
                continue
            desktop_tracking = await self.async_get_desktop_tracking(service, order_nr)
            tracked = TrackedOrder.from_orders_info(
                item,
                service,
                desktop_tracking=desktop_tracking,
            )
            if tracked is not None:
                merged[order_nr] = tracked

    async def async_get_all_tracked_orders(self) -> list[TrackedOrder]:
        merged: dict[str, TrackedOrder] = {}
        for service in Service:
            for order in await self.async_get_tracked_orders(service):
                if order.id:
                    merged[order.id] = order
        return list(merged.values())

    async def _async_get_orders_info_page(
        self,
        *,
        platform: str,
        cursor: str | None,
        base_url: str = ORDERS_INFO_BASE_URL,
    ) -> dict[str, Any] | None:
        pagination_settings: dict[str, Any] = {"limit": ORDERS_INFO_PAGE_LIMIT}
        if cursor:
            pagination_settings["cursor"] = cursor
        body = {"pagination_settings": pagination_settings}
        url = f"{base_url}{ORDERS_INFO_PATH}"
        headers = {
            **_service_headers(base_url),
            "Content-Type": "application/json",
            "X-Platform": platform,
        }
        try:
            data = await self._session.post_json(url, body, headers=headers)
        except Exception as err:
            _LOGGER.debug("orders-info failed for platform %s: %s", platform, err)
            return None
        return data if isinstance(data, dict) else None

    async def _async_get_orders_from_stream(
        self,
        *,
        platform: str,
        default_service: Service,
    ) -> list[OrderHistoryEntry]:
        merged: dict[str, OrderHistoryEntry] = {}
        ordered: list[str] = []
        cursor: str | None = None

        for page in range(ORDERS_INFO_MAX_PAGES):
            data = await self._async_get_orders_info_page(platform=platform, cursor=cursor)
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

        for platform, default_service in ORDER_HISTORY_STREAMS:
            try:
                stream_orders = await self._async_get_orders_from_stream(
                    platform=platform,
                    default_service=default_service,
                )
            except Exception as err:
                _LOGGER.debug("order history failed for platform %s: %s", platform, err)
                continue

            for entry in stream_orders:
                if entry.order_nr in merged:
                    continue
                merged[entry.order_nr] = entry
                if platform == ORDER_HISTORY_PLATFORM_EDA:
                    ordered.append(entry.order_nr)
                else:
                    _insert_order_nr(ordered, entry.order_nr)

        return [merged[order_nr] for order_nr in ordered if order_nr in merged]
