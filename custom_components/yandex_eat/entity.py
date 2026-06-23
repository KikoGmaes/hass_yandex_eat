from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import YandexEatCoordinator
from .models import TrackedOrder


class YandexEatAccountEntity(CoordinatorEntity[YandexEatCoordinator], Entity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: YandexEatCoordinator, suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.unique_id}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title,
            manufacturer="Yandex",
            model="Yandex Eat",
        )

    @property
    def primary_order(self) -> TrackedOrder | None:
        return self.coordinator.primary_order


class YandexEatEntity(YandexEatAccountEntity):
    def __init__(self, coordinator: YandexEatCoordinator, order: TrackedOrder, suffix: str) -> None:
        super().__init__(coordinator, suffix)
        self._order_id = order.id
        self._attr_unique_id = f"{coordinator.entry.unique_id}_{order.id}_{suffix}"
        service_label = {
            "lavka": "Lavka",
            "market": "Delivery",
        }.get(order.service.value, "Eda")
        order_label = order.short_order_id or order.id[:8]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id, order.id)},
            name=f"{service_label} {order_label}",
            manufacturer="Yandex",
            model=service_label,
            via_device=(DOMAIN, coordinator.entry.entry_id),
        )

    @property
    def order(self) -> TrackedOrder | None:
        return self.coordinator.data.orders.get(self._order_id)

    @property
    def available(self) -> bool:
        order = self.order
        return order is not None and order.is_active


def primary_order_attributes(
    coordinator: YandexEatCoordinator,
) -> dict:
    order = coordinator.primary_order
    attrs: dict = {
        "recent_orders": [
            coordinator.recent_order_dict(item) for item in coordinator.recent_orders
        ],
    }
    last_order = coordinator.last_order
    if last_order is not None:
        attrs["last_order"] = coordinator.recent_order_dict(last_order)
    if order is None:
        attrs["has_active_order"] = False
        return attrs
    attrs.update(coordinator.order_attributes(order))
    attrs["has_active_order"] = True
    attrs["order_id"] = order.id
    attrs["short_order_id"] = order.short_order_id
    return attrs
