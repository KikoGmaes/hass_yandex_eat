from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Service(StrEnum):
    EDA = "eda"
    LAVKA = "lavka"


class OrderStatus(StrEnum):
    ASSEMBLING = "assembling"
    PERFORMER_FOUND = "performer_found"
    DELIVERY_ARRIVED = "delivery_arrived"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class TrackingInfo(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    grocery_image: str | None = Field(None, alias="groceryImage")
    remaining_time: int | None = None
    eta_minutes: int | None = None
    courier_position: list[float] | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> TrackingInfo:
        data = dict(raw)
        # Normalize common field names seen across grocery API versions
        for key in ("remainingTime", "remaining_time_sec", "eta", "etaMinutes", "minutes"):
            if key in raw and data.get("remaining_time") is None:
                val = raw[key]
                if isinstance(val, (int, float)):
                    data["remaining_time"] = int(val if key != "remaining_time_sec" else val / 60)
                elif isinstance(val, str) and val.isdigit():
                    data["remaining_time"] = int(val)

        for key in ("courierPosition", "courier_location", "position", "performerPosition"):
            if key in raw and data.get("courier_position") is None:
                pos = raw[key]
                if isinstance(pos, dict):
                    lat = pos.get("lat") or pos.get("latitude")
                    lon = pos.get("lon") or pos.get("longitude")
                    if lat is not None and lon is not None:
                        data["courier_position"] = [float(lon), float(lat)]
                elif isinstance(pos, (list, tuple)) and len(pos) >= 2:
                    data["courier_position"] = [float(pos[0]), float(pos[1])]

        return cls.model_validate(data)


class TrackedOrder(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    status: str
    short_order_id: str | None = Field(None, alias="shortOrderId")
    tracking_info: TrackingInfo | None = None
    service: Service
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

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

    @classmethod
    def from_api(cls, item: dict[str, Any], service: Service) -> TrackedOrder:
        tracking_raw = item.get("trackingInfo") or item.get("tracking_info")
        tracking = TrackingInfo.from_raw(tracking_raw) if isinstance(tracking_raw, dict) else None
        return cls(
            id=str(item.get("id", "")),
            status=str(item.get("status", "unknown")),
            shortOrderId=item.get("shortOrderId"),
            tracking_info=tracking,
            service=service,
            raw=item,
        )
