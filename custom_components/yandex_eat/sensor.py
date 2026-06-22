from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import YandexEatCoordinator
from .entity import YandexEatEntity
from .models import TrackedOrder


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: YandexEatCoordinator = entry.runtime_data
    manager = YandexEatSensorManager(coordinator, async_add_entities)
    manager.setup()
    entry.async_on_unload(coordinator.async_add_listener(manager.update))


class YandexEatSensorManager:
    def __init__(
        self,
        coordinator: YandexEatCoordinator,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        self.coordinator = coordinator
        self.async_add_entities = async_add_entities
        self._status_entities: dict[str, YandexEatOrderStatusSensor] = {}
        self._eta_entities: dict[str, YandexEatOrderEtaSensor] = {}
        self._summary: YandexEatActiveOrdersSensor | None = None

    def setup(self) -> None:
        if self._summary is None:
            self._summary = YandexEatActiveOrdersSensor(self.coordinator)
            self.async_add_entities([self._summary])
        self.update()

    @callback
    def update(self) -> None:
        current_orders = {
            order.id: order
            for order in self.coordinator.data.values()
            if order.is_active
        }
        new_entities: list[SensorEntity] = []
        for order_id, order in current_orders.items():
            if order_id not in self._status_entities:
                status_entity = YandexEatOrderStatusSensor(self.coordinator, order)
                eta_entity = YandexEatOrderEtaSensor(self.coordinator, order)
                self._status_entities[order_id] = status_entity
                self._eta_entities[order_id] = eta_entity
                new_entities.extend((status_entity, eta_entity))
            else:
                self._status_entities[order_id].async_write_ha_state()
                self._eta_entities[order_id].async_write_ha_state()
        if new_entities:
            self.async_add_entities(new_entities)

        for order_id in list(self._status_entities):
            if order_id not in current_orders:
                del self._status_entities[order_id]
                del self._eta_entities[order_id]

        if self._summary:
            self._summary.async_write_ha_state()


class YandexEatActiveOrdersSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "active_orders"
    _attr_icon = "mdi:food"

    def __init__(self, coordinator: YandexEatCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.unique_id}_active_orders"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title,
            manufacturer="Yandex",
            model="Yandex Eat",
        )

    @property
    def native_value(self) -> int:
        return len(self.coordinator.active_orders)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "orders": [
                {
                    "id": order.id,
                    "short_order_id": order.short_order_id,
                    "status": order.status,
                    "service": order.service.value,
                    "courier_nearby": order.courier_nearby,
                    "eta_minutes": (
                        order.tracking_info.remaining_time
                        if order.tracking_info and order.tracking_info.remaining_time is not None
                        else None
                    ),
                }
                for order in self.coordinator.active_orders
            ]
        }


class YandexEatOrderEtaSensor(YandexEatEntity, SensorEntity):
    _attr_translation_key = "courier_eta"
    _attr_icon = "mdi:timer-sand"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: YandexEatCoordinator, order: TrackedOrder) -> None:
        super().__init__(coordinator, order, "eta")

    @property
    def native_value(self) -> int | None:
        order = self.order
        if not order or not order.tracking_info:
            return None
        return order.tracking_info.remaining_time

    @property
    def available(self) -> bool:
        order = self.order
        if not order or not order.is_active:
            return False
        return (
            order.tracking_info is not None
            and order.tracking_info.remaining_time is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        order = self.order
        if not order:
            return {}
        attrs: dict[str, Any] = {
            "status": order.status,
            "service": order.service.value,
            "short_order_id": order.short_order_id,
        }
        if order.tracking_info and order.tracking_info.remaining_time is not None:
            eta = order.tracking_info.remaining_time
            attrs["arrival_time"] = (
                dt_util.now() + timedelta(minutes=eta)
            ).isoformat()
        return attrs


class YandexEatOrderStatusSensor(YandexEatEntity, SensorEntity):
    _attr_translation_key = "order_status"
    _attr_icon = "mdi:truck-delivery"

    def __init__(self, coordinator: YandexEatCoordinator, order: TrackedOrder) -> None:
        super().__init__(coordinator, order, "status")
        self._attr_name = "Status"

    @property
    def native_value(self) -> str | None:
        order = self.order
        return order.status if order else None

    @property
    def extra_state_attributes(self) -> dict:
        order = self.order
        if not order:
            return {}
        return self.coordinator.order_attributes(order)
