from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .const import INACTIVE_TRACKED_STATUSES, NEARBY_ETA_MINUTES, RETAIL_CHAIN_SUBSTRINGS

EDA_ORDER_NR_RE = re.compile(r"^\d{6}-\d+$")


class Service(StrEnum):
    EDA = "eda"
    LAVKA = "lavka"
    MARKET = "market"


class OrderStatus(StrEnum):
    ASSEMBLING = "assembling"
    PERFORMER_FOUND = "performer_found"
    DELIVERY_ARRIVED = "delivery_arrived"
    CLOSED = "closed"
    UNKNOWN = "unknown"


def _is_retail_chain(name: str) -> bool:
    low = name.lower().strip()
    return any(chain in low for chain in RETAIL_CHAIN_SUBSTRINGS)


@dataclass
class TrackingInfo:
    grocery_image: str | None = None
    remaining_time: int | None = None
    courier_position: list[float] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | None) -> TrackingInfo | None:
        if not isinstance(raw, dict):
            return None
        remaining_time = None
        for key in (
            "remainingTime",
            "remaining_time",
            "remaining_time_sec",
            "eta",
            "etaMinutes",
            "minutes",
            "eta_minutes",
        ):
            if key not in raw:
                continue
            val = raw[key]
            if isinstance(val, (int, float)):
                remaining_time = int(val if key != "remaining_time_sec" else val / 60)
                break
            if isinstance(val, str) and val.isdigit():
                remaining_time = int(val)
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

        return cls(
            grocery_image=raw.get("groceryImage"),
            remaining_time=remaining_time,
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
    def detect_service(
        item: dict[str, Any],
        default: Service = Service.EDA,
        *,
        place_business: str | None = None,
        restaurant_as: Service = Service.EDA,
    ) -> Service:
        order_nr = str(item.get("order_nr", ""))
        general = item.get("widgets", {}).get("general", {})
        if not isinstance(general, dict):
            general = {}

        name = str(general.get("name", ""))
        name_low = name.lower()
        business_type = str(
            general.get("business_type", item.get("business_type", ""))
        ).lower()
        raw_blob = str(item).lower()
        place_business_low = (place_business or "").lower()

        if order_nr.endswith("-grocery"):
            return Service.LAVKA
        if "лавка" in name_low or "lavka" in name_low:
            return Service.LAVKA
        if business_type in {"shop", "store", "grocery", "lavka"}:
            return Service.LAVKA if business_type == "lavka" else Service.MARKET
        if "lavka.yandex" in raw_blob or "/lavka/" in raw_blob:
            return Service.LAVKA

        if place_business_low in {"shop", "store", "retail"}:
            return Service.MARKET
        if _is_retail_chain(name):
            return Service.MARKET

        if "деливери" in name_low or "delivery club" in name_low:
            return Service.MARKET
        if business_type in {"delivery", "dc", "market"}:
            return Service.MARKET
        if "market-delivery" in raw_blob or "/dc/" in raw_blob:
            return Service.MARKET

        if place_business_low in {"restaurant", "cafe", "fastfood"}:
            return restaurant_as
        if EDA_ORDER_NR_RE.match(order_nr):
            return restaurant_as

        return default

    @classmethod
    def from_detail(
        cls,
        detail: dict[str, Any],
        *,
        default_service: Service = Service.EDA,
        restaurant_as: Service = Service.EDA,
    ) -> OrderHistoryEntry:
        place = detail.get("place") if isinstance(detail.get("place"), dict) else {}
        created_at = str(detail.get("created_at") or "")
        status = detail.get("status_for_customer", "")
        if isinstance(status, dict):
            status = status.get("title") or status.get("text") or ""
        cost = detail.get("total_cost_for_customer") or detail.get("final_cost_for_customer")
        date_display = created_at[:10] if created_at else ""
        item = {
            "order_nr": detail.get("order_nr"),
            "widgets": {
                "general": {
                    "name": place.get("name", ""),
                    "date": date_display,
                    "cost_value": str(cost) if cost is not None else None,
                    "status": {"text": str(status)},
                }
            },
        }
        business = place.get("business")
        return cls(
            order_nr=str(detail.get("order_nr", "")),
            name=str(place.get("name", "")),
            date=date_display,
            status=str(status),
            cost=str(cost) if cost is not None else None,
            service=cls.detect_service(
                item,
                default_service,
                place_business=str(business) if business else None,
                restaurant_as=restaurant_as,
            ),
            raw={**item, "created_at": created_at, "detail": detail},
        )

    @classmethod
    def from_api(
        cls,
        item: dict[str, Any],
        service: Service = Service.EDA,
        *,
        place_business: str | None = None,
        restaurant_as: Service = Service.EDA,
    ) -> OrderHistoryEntry:
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
            service=cls.detect_service(
                item,
                service,
                place_business=place_business,
                restaurant_as=restaurant_as,
            ),
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
    def courier_nearby(self) -> bool:
        if self.order_status == OrderStatus.DELIVERY_ARRIVED:
            return True
        if self.tracking_info and self.tracking_info.remaining_time is not None:
            return self.tracking_info.remaining_time <= NEARBY_ETA_MINUTES
        return False

    @property
    def is_active(self) -> bool:
        if self.status.lower() in INACTIVE_TRACKED_STATUSES:
            return False
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
