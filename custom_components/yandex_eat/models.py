from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

EDA_ORDER_NR_RE = re.compile(r"^\d{6}-\d+$")
ORDER_YEAR_RE = re.compile(r",\s*(20\d{2})\s*$")
ETA_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
ETA_MINUTES_RANGE_RE = re.compile(r"(\d{1,3})\s*[–\-—−]\s*(\d{1,3})\s*мин", re.IGNORECASE)
ETA_MINUTES_SINGLE_RE = re.compile(r"(\d{1,3})\s*мин", re.IGNORECASE)
try:
    YANDEX_LOCAL_TZ = ZoneInfo("Europe/Moscow")
except ZoneInfoNotFoundError:
    YANDEX_LOCAL_TZ = timezone(timedelta(hours=3))
ACTIVE_STATUS_MARKERS = (
    "в работе",
    "in progress",
    "готов",
    "приготов",
    "курьер",
    "дороге",
    "ожида",
    "собира",
    "assembling",
    "performer",
)


def parse_order_cost(cost: str | None) -> float:
    if not cost:
        return 0.0
    normalized = str(cost).replace("\u202f", "").replace(" ", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return 0.0


def parse_order_year(order_nr: str, date: str, *, fallback_year: int) -> int:
    if match := EDA_ORDER_NR_RE.match(order_nr):
        return 2000 + int(match.group(0)[:2])
    if year_match := ORDER_YEAR_RE.search(date):
        return int(year_match.group(1))
    return fallback_year


def is_cancelled_order(status: str) -> bool:
    lowered = status.lower()
    return "отмен" in lowered or "cancel" in lowered


def is_delivered_order(status: str) -> bool:
    lowered = status.lower()
    return "доставлен" in lowered or "delivered" in lowered


def parse_courier_minutes_from_text(text: str | None) -> int | None:
    if not text:
        return None
    if match := ETA_MINUTES_RANGE_RE.search(text):
        return max(int(match.group(1)), int(match.group(2)))
    if match := ETA_MINUTES_SINGLE_RE.search(text):
        return int(match.group(1))
    return None


def parse_eta_minutes_from_title(title: str | None) -> int | None:
    if not title:
        return None
    match = ETA_TIME_RE.search(title)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    now = datetime.now(YANDEX_LOCAL_TZ)
    eta = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if eta <= now:
        return 0
    return int((eta - now).total_seconds() // 60)


def _delivery_eta_from_tracking_titles(data: dict[str, Any]) -> int | None:
    for key in ("title", "eta_text", "etaText"):
        delivery_eta = parse_eta_minutes_from_title(str(data.get(key) or ""))
        if delivery_eta is not None:
            return delivery_eta
    return None


def _courier_eta_from_tracking_titles(data: dict[str, Any]) -> int | None:
    for key in ("title", "eta_text", "etaText", "subtitle"):
        courier_eta = parse_courier_minutes_from_text(str(data.get(key) or ""))
        if courier_eta is not None:
            return courier_eta
    return None


def order_status_text(item: dict[str, Any]) -> str:
    general = item.get("widgets", {}).get("general", {})
    if not isinstance(general, dict):
        general = {}
    status = general.get("status", {})
    if isinstance(status, dict):
        return str(status.get("text") or "")
    return str(status or "")


def is_active_orders_info_item(item: dict[str, Any], order_nrs_to_update: set[str]) -> bool:
    order_nr = str(item.get("order_nr", ""))
    if not order_nr:
        return False
    if order_nr in order_nrs_to_update:
        return True
    widgets = item.get("widgets", {})
    if not isinstance(widgets, dict):
        return False
    if widgets.get("progress_bar_tracking"):
        return True
    status_text = order_status_text(item)
    if is_cancelled_order(status_text) or is_delivered_order(status_text):
        return False
    if not status_text.strip():
        return True
    lowered = status_text.lower()
    return any(marker in lowered for marker in ACTIVE_STATUS_MARKERS)


class Service(StrEnum):
    EDA = "eda"
    LAVKA = "lavka"
    MARKET = "market"


class OrderStatus(StrEnum):
    CONFIRMED = "confirmed"
    ASSEMBLING = "assembling"
    PERFORMER_FOUND = "performer_found"
    DELIVERY_ARRIVED = "delivery_arrived"
    CLOSED = "closed"
    UNKNOWN = "unknown"


COURIER_TRACKING_STATUSES = frozenset(
    {OrderStatus.PERFORMER_FOUND, OrderStatus.DELIVERY_ARRIVED}
)


@dataclass
class TrackingInfo:
    grocery_image: str | None = None
    delivery_eta_minutes: int | None = None
    courier_eta_minutes: int | None = None
    courier_position: list[float] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | None) -> TrackingInfo | None:
        if not isinstance(raw, dict):
            return None
        courier_eta_minutes = None
        for key in ("remainingTime", "remaining_time", "remaining_time_sec", "eta", "etaMinutes", "minutes"):
            if key not in raw:
                continue
            val = raw[key]
            if isinstance(val, (int, float)):
                courier_eta_minutes = int(val if key != "remaining_time_sec" else val / 60)
                break
            if isinstance(val, str) and val.isdigit():
                courier_eta_minutes = int(val)
                break

        courier_position = None
        for key in ("courierPosition", "courier_location", "position", "performerPosition"):
            if key not in raw:
                continue
            pos = raw[key]
            if isinstance(pos, dict):
                lat = pos.get("lat") or pos.get("latitude")
                lon = pos.get("lon") or pos.get("longitude")
                if lat is not None and lon is not None:
                    courier_position = [float(lon), float(lat)]
                    break
            if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                courier_position = [float(pos[0]), float(pos[1])]
                break

        if courier_eta_minutes is None and courier_position is None and not raw.get("groceryImage"):
            return None

        return cls(
            grocery_image=raw.get("groceryImage"),
            courier_eta_minutes=courier_eta_minutes,
            courier_position=courier_position,
            raw=raw,
        )

    @classmethod
    def from_progress_bar(cls, progress: dict[str, Any] | None) -> TrackingInfo | None:
        if not isinstance(progress, dict):
            return None
        delivery_eta_minutes = parse_eta_minutes_from_title(progress.get("title"))
        if delivery_eta_minutes is None:
            return None
        return cls(
            delivery_eta_minutes=delivery_eta_minutes,
            raw=progress,
        )

    @classmethod
    def from_desktop_tracking(cls, raw: dict[str, Any] | None) -> TrackingInfo | None:
        if not isinstance(raw, dict):
            return None
        delivery_eta_minutes = None
        courier_eta_minutes = None
        courier_position = None
        grocery_image = None

        tracked_order = raw.get("tracked_order")
        if isinstance(tracked_order, dict):
            delivery_eta_minutes = _delivery_eta_from_tracking_titles(tracked_order)
            if courier_eta_minutes is None:
                courier_eta_minutes = _courier_eta_from_tracking_titles(tracked_order)

        for key in ("tracking_info", "trackingInfo", "payload", "order"):
            nested = raw.get(key)
            if isinstance(nested, dict):
                info = cls.from_raw(nested)
                if info:
                    courier_eta_minutes = info.courier_eta_minutes
                    courier_position = info.courier_position
                    grocery_image = info.grocery_image
                    if courier_eta_minutes is not None:
                        break

        if courier_eta_minutes is None:
            info = cls.from_raw(raw)
            if info:
                courier_eta_minutes = info.courier_eta_minutes
                courier_position = courier_position or info.courier_position
                grocery_image = grocery_image or info.grocery_image

        if delivery_eta_minutes is None:
            delivery_eta_minutes = _delivery_eta_from_tracking_titles(raw)

        if courier_eta_minutes is None:
            courier_eta_minutes = _courier_eta_from_tracking_titles(raw)

        if (
            delivery_eta_minutes is None
            and courier_eta_minutes is None
            and courier_position is None
        ):
            return None

        return cls(
            grocery_image=grocery_image,
            delivery_eta_minutes=delivery_eta_minutes,
            courier_eta_minutes=courier_eta_minutes,
            courier_position=courier_position,
            raw=raw,
        )


@dataclass
class OrderHistoryEntry:
    order_nr: str
    name: str
    date: str
    status: str
    cost: str | None
    service: Service
    raw: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def detect_service(item: dict[str, Any], default: Service = Service.EDA) -> Service:
        order_nr = str(item.get("order_nr", ""))
        if order_nr.endswith("-grocery"):
            return Service.LAVKA

        general = item.get("widgets", {}).get("general", {})
        if not isinstance(general, dict):
            general = {}

        name = str(general.get("name", "")).lower()
        business_type = str(
            general.get("business_type", item.get("business_type", ""))
        ).lower()
        if "лавка" in name or "lavka" in name:
            return Service.LAVKA
        if business_type in {"shop", "store", "grocery", "lavka"}:
            return Service.LAVKA
        if "lavka.yandex" in str(item).lower():
            return Service.LAVKA

        return default

    @classmethod
    def from_api(cls, item: dict[str, Any], service: Service = Service.EDA) -> OrderHistoryEntry:
        general = item.get("widgets", {}).get("general", {})
        if not isinstance(general, dict):
            general = {}
        status = general.get("status", {})
        status_text = status.get("text") if isinstance(status, dict) else str(status or "")
        return cls(
            order_nr=str(item.get("order_nr", "")),
            name=str(general.get("name", "")),
            date=str(general.get("date", "")),
            status=str(status_text),
            cost=general.get("cost_value"),
            service=cls.detect_service(item, service),
            raw=item,
        )


@dataclass
class TrackedOrder:
    id: str
    status: str
    service: Service
    short_order_id: str | None = None
    tracking_info: TrackingInfo | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def order_status(self) -> OrderStatus:
        try:
            return OrderStatus(self.status)
        except ValueError:
            return OrderStatus.UNKNOWN

    @property
    def delivery_eta_minutes(self) -> int | None:
        if self.order_status in COURIER_TRACKING_STATUSES:
            return None
        if self.tracking_info and self.tracking_info.delivery_eta_minutes is not None:
            return self.tracking_info.delivery_eta_minutes
        return None

    @property
    def courier_eta_minutes(self) -> int | None:
        if self.order_status not in COURIER_TRACKING_STATUSES:
            return None
        if not self.tracking_info:
            return None
        if self.tracking_info.courier_eta_minutes is not None:
            return self.tracking_info.courier_eta_minutes
        tracked_order = self.tracking_info.raw.get("tracked_order")
        if isinstance(tracked_order, dict):
            if courier_eta := _courier_eta_from_tracking_titles(tracked_order):
                return courier_eta
        return _courier_eta_from_tracking_titles(self.tracking_info.raw)

    @property
    def courier_nearby(self) -> bool:
        if self.order_status == OrderStatus.DELIVERY_ARRIVED:
            return True
        eta = self.courier_eta_minutes
        return eta is not None and eta <= 5

    @property
    def is_active(self) -> bool:
        return self.order_status != OrderStatus.CLOSED

    @classmethod
    def from_api(cls, item: dict[str, Any], service: Service) -> TrackedOrder:
        return cls(
            id=str(item.get("id", "")),
            status=str(item.get("status", "unknown")),
            short_order_id=item.get("shortOrderId") or item.get("short_order_id"),
            tracking_info=TrackingInfo.from_raw(item.get("trackingInfo") or item.get("tracking_info")),
            service=service,
            raw=item,
        )

    @classmethod
    def from_orders_info(
        cls,
        item: dict[str, Any],
        service: Service,
        *,
        desktop_tracking: dict[str, Any] | None = None,
    ) -> TrackedOrder | None:
        order_nr = str(item.get("order_nr", ""))
        if not order_nr:
            return None
        widgets = item.get("widgets", {})
        if not isinstance(widgets, dict):
            widgets = {}
        progress = widgets.get("progress_bar_tracking")
        tracking_info = TrackingInfo.from_desktop_tracking(desktop_tracking)
        if tracking_info is None and isinstance(progress, dict):
            tracking_info = TrackingInfo.from_progress_bar(progress)
        status = cls._status_from_orders_info(item, progress if isinstance(progress, dict) else None)
        short_id = order_nr.split("-", 1)[-1]
        return cls(
            id=order_nr,
            status=status,
            short_order_id=short_id[:12],
            tracking_info=tracking_info,
            service=service,
            raw={"orders_info": item, "desktop_tracking": desktop_tracking or {}},
        )

    @staticmethod
    def _status_from_orders_info(
        item: dict[str, Any],
        progress: dict[str, Any] | None,
    ) -> str:
        if isinstance(progress, dict):
            bar = progress.get("progress_bar")
            if isinstance(bar, dict):
                steps = bar.get("steps")
                if not isinstance(steps, dict):
                    steps = bar
                active_steps = steps.get("active_steps_amount")
                total_steps = steps.get("steps_amount")
                if isinstance(active_steps, int) and isinstance(total_steps, int) and total_steps > 0:
                    if active_steps >= total_steps:
                        return OrderStatus.DELIVERY_ARRIVED
                    if active_steps >= max(1, total_steps - 1):
                        return OrderStatus.PERFORMER_FOUND
                    if active_steps == 1:
                        return OrderStatus.CONFIRMED
                    return OrderStatus.ASSEMBLING
        status_text = order_status_text(item).lower()
        if "курьер" in status_text or "дороге" in status_text or "performer" in status_text:
            return OrderStatus.PERFORMER_FOUND
        if "прибыл" in status_text or "arrived" in status_text:
            return OrderStatus.DELIVERY_ARRIVED
        return OrderStatus.ASSEMBLING

    @classmethod
    def from_api_v2(cls, item: dict[str, Any], service: Service) -> TrackedOrder:
        order = item.get("order") if isinstance(item.get("order"), dict) else item
        order_id = (
            order.get("id")
            or order.get("orderId")
            or order.get("order_id")
            or item.get("id")
            or item.get("orderId")
        )
        status = (
            order.get("status")
            or order.get("orderStatus")
            or item.get("status")
            or "unknown"
        )
        tracking = (
            order.get("trackingInfo")
            or order.get("tracking_info")
            or item.get("trackingInfo")
            or item.get("tracking_info")
        )
        return cls(
            id=str(order_id or ""),
            status=str(status),
            short_order_id=order.get("shortOrderId")
            or order.get("short_order_id")
            or item.get("shortOrderId"),
            tracking_info=TrackingInfo.from_raw(tracking if isinstance(tracking, dict) else None),
            service=service,
            raw=item,
        )
