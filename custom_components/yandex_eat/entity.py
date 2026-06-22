from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import YandexEatCoordinator
from .models import TrackedOrder


class YandexEatEntity(CoordinatorEntity[YandexEatCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: YandexEatCoordinator, order: TrackedOrder, suffix: str) -> None:
        super().__init__(coordinator)
        self._order_id = order.id
        self._attr_unique_id = f"{coordinator.entry.unique_id}_{order.id}_{suffix}"
        service_label = "Lavka" if order.service.value == "lavka" else "Eda"
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
        return self.coordinator.data.get(self._order_id)

    @property
    def available(self) -> bool:
        order = self.order
        return order is not None and order.is_active
