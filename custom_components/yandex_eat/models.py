from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Service(StrEnum):
    EDA = "eda"
    LAVKA = "lavka"


class OrderStatus(StrEnum):
    ASSEMBLING = "assembling"
    PERFORMER_FOUND = "performer_found"
    DELIVERY_ARRIVED = "delivery_arrived"
    CLOSED = "closed"
    UNKNOWN = "unknown"


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
        for key in ("remainingTime", "remaining_time", "remaining_time_sec", "eta", "etaMinutes", "minutes"):
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
            return self.tracking_info.remaining_time <= 5
        return False

    @property
    def is_active(self) -> bool:
        return self.order_status != OrderStatus.CLOSED

    @classmethod
    def from_api(cls, item: dict[str, Any], service: Service) -> TrackedOrder:
        return cls(
            id=str(item.get("id", "")),
            status=str(item.get("status", "unknown")),
            short_order_id=item.get("shortOrderId"),
            tracking_info=TrackingInfo.from_raw(item.get("trackingInfo") or item.get("tracking_info")),
            service=service,
            raw=item,
        )
