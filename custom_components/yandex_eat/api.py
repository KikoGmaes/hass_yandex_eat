from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .const import (
    EMPTY_HTTP_STATUSES,
    ORDER_DETAIL_PATH,
    ORDER_DETAIL_SUPPLEMENT_LIMIT,
    ORDERS_INFO_BASE_URLS,
    ORDERS_INFO_PATH,
    ORDERS_INFO_PAGE_LIMIT,
    ORDERS_INFO_MAX_PAGES,
    SERVICE_BASE_URLS,
    SERVICE_EDA,
    SERVICE_MARKET,
    TRACKED_ORDERS_PATH,
    TRACKING_V2_BASE_URLS,
    TRACKING_V2_PATH,
)
from .models import EDA_ORDER_NR_RE, OrderHistoryEntry, Service, TrackedOrder, _is_retail_chain
from .yandex_session import YandexSession

_LOGGER = logging.getLogger(__name__)

_ORDERS_HISTORY_STREAMS = ("ordershistory_cursor", "grocery_cursor")


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


def _history_sort_key(entry: OrderHistoryEntry) -> str:
    created = entry.raw.get("created_at")
    if isinstance(created, str) and created:
        return created
    order_nr = entry.order_nr
    if EDA_ORDER_NR_RE.match(order_nr):
        return f"20{order_nr[:2]}-{order_nr[2:4]}-{order_nr[4:6]}T00:00:00"
    return entry.date or ""


class YandexEatApi:
    def __init__(self, session: YandexSession) -> None:
        self._session = session
        self._place_business_cache: dict[str, str] = {}

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
        cursor: str | None = None,
        stream_key: str | None = None,
        stream_value: str | None = None,
    ) -> dict[str, Any] | None:
        pagination_settings: dict[str, Any] = {"limit": ORDERS_INFO_PAGE_LIMIT}
        if stream_key and stream_value:
            pagination_settings["cursor"] = json.dumps(
                {"version": "1.0", stream_key: stream_value},
                separators=(",", ":"),
            )
        elif cursor:
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
        restaurant_as: Service,
    ) -> list[OrderHistoryEntry]:
        raw_merged: dict[str, dict[str, Any]] = {}
        ordered: list[str] = []

        def absorb(items: list[dict[str, Any]]) -> None:
            for item in items:
                order_nr = str(item.get("order_nr", ""))
                if not order_nr:
                    continue
                if order_nr not in raw_merged:
                    ordered.append(order_nr)
                raw_merged[order_nr] = item

        data = await self._async_get_orders_info_page(base, cursor=None)
        if not data:
            return []

        absorb(_extract_orders_payload(data))
        cursor_json: dict[str, Any] = {}
        cursor_raw = _pagination_settings(data).get("cursor")
        if isinstance(cursor_raw, str) and cursor_raw:
            try:
                parsed = json.loads(cursor_raw)
                if isinstance(parsed, dict):
                    cursor_json = parsed
            except json.JSONDecodeError:
                _LOGGER.debug("orders-info cursor JSON parse failed: %s", cursor_raw[:120])

        for stream_key in _ORDERS_HISTORY_STREAMS:
            stream_value = cursor_json.get(stream_key)
            if not stream_value:
                continue
            seen_values: set[str] = set()
            for _ in range(ORDERS_INFO_MAX_PAGES):
                if stream_value in seen_values:
                    break
                seen_values.add(str(stream_value))
                page_data = await self._async_get_orders_info_page(
                    base,
                    stream_key=stream_key,
                    stream_value=str(stream_value),
                )
                if not page_data:
                    break
                page_items = _extract_orders_payload(page_data)
                if not page_items:
                    break
                absorb(page_items)
                page_ps = _pagination_settings(page_data)
                has_more = page_ps.get("has_more")
                if has_more is None:
                    has_more = page_ps.get("hasMore")
                if not has_more:
                    break
                try:
                    next_json = json.loads(page_ps.get("cursor", "{}"))
                except json.JSONDecodeError:
                    break
                if not isinstance(next_json, dict):
                    break
                next_value = next_json.get(stream_key)
                if not next_value or next_value == stream_value:
                    break
                stream_value = next_value

        return [
            OrderHistoryEntry.from_api(
                raw_merged[order_nr],
                default_service,
                restaurant_as=restaurant_as,
            )
            for order_nr in ordered
            if order_nr in raw_merged
        ]

    async def _async_get_order_detail(self, order_nr: str) -> dict[str, Any] | None:
        if not order_nr:
            return None
        base = SERVICE_BASE_URLS[SERVICE_EDA]
        url = f"{base}{ORDER_DETAIL_PATH}?order_nr={order_nr}"
        try:
            data = await self._session.get_json(url, headers=_service_headers(base))
        except Exception as err:
            _LOGGER.debug("order detail failed for %s: %s", order_nr, err)
            return None
        return data if isinstance(data, dict) else None

    async def _async_get_place_business(self, order_nr: str) -> str | None:
        if not order_nr or order_nr.endswith("-grocery"):
            return "lavka" if order_nr.endswith("-grocery") else None
        cached = self._place_business_cache.get(order_nr)
        if cached is not None:
            return cached or None

        data = await self._async_get_order_detail(order_nr)
        business = ""
        if isinstance(data, dict):
            place = data.get("place")
            if isinstance(place, dict):
                business = str(place.get("business") or "")
        self._place_business_cache[order_nr] = business
        return business or None

    async def _async_supplement_from_details(
        self,
        merged: dict[str, OrderHistoryEntry],
        ordered: list[str],
        extra_order_nrs: frozenset[str],
        *,
        restaurant_as: Service,
    ) -> None:
        missing = [
            order_nr
            for order_nr in sorted(extra_order_nrs)
            if order_nr and order_nr not in merged
        ][:ORDER_DETAIL_SUPPLEMENT_LIMIT]
        if not missing:
            return

        details = await asyncio.gather(
            *(self._async_get_order_detail(order_nr) for order_nr in missing)
        )
        for detail in details:
            if not isinstance(detail, dict) or not detail.get("order_nr"):
                continue
            entry = OrderHistoryEntry.from_detail(
                detail,
                restaurant_as=restaurant_as,
            )
            if entry.order_nr not in merged:
                ordered.append(entry.order_nr)
            merged[entry.order_nr] = entry

    async def _async_enrich_order_services(
        self,
        entries: list[OrderHistoryEntry],
        *,
        restaurant_as: Service,
    ) -> None:
        unknown = [
            entry
            for entry in entries
            if EDA_ORDER_NR_RE.match(entry.order_nr)
            and not entry.order_nr.endswith("-grocery")
            and not _is_retail_chain(entry.name)
        ]
        if not unknown:
            return

        batch_size = 10
        for offset in range(0, len(unknown), batch_size):
            batch = unknown[offset : offset + batch_size]
            businesses = await asyncio.gather(
                *(self._async_get_place_business(entry.order_nr) for entry in batch)
            )
            for entry, business in zip(batch, businesses, strict=True):
                entry.service = OrderHistoryEntry.detect_service(
                    entry.raw,
                    entry.service,
                    place_business=business,
                    restaurant_as=restaurant_as,
                )

    async def async_get_recent_orders(
        self,
        *,
        restaurant_as: Service = Service.EDA,
        extra_order_nrs: frozenset[str] | None = None,
    ) -> list[OrderHistoryEntry]:
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
                    restaurant_as=restaurant_as,
                )
            except Exception as err:
                _LOGGER.debug("order history failed for %s: %s", base, err)
                continue

            for entry in page_orders:
                if entry.order_nr not in merged:
                    ordered.append(entry.order_nr)
                merged[entry.order_nr] = entry

        if extra_order_nrs:
            await self._async_supplement_from_details(
                merged,
                ordered,
                extra_order_nrs,
                restaurant_as=restaurant_as,
            )

        result = [merged[order_nr] for order_nr in ordered if order_nr in merged]
        result.sort(key=_history_sort_key, reverse=True)
        await self._async_enrich_order_services(result, restaurant_as=restaurant_as)
        return result
