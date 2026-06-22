from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import YandexEatCoordinator
from .entity import YandexEatEntity
from .models import TrackedOrder


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: YandexEatCoordinator = entry.runtime_data
    manager = YandexEatBinarySensorManager(coordinator, async_add_entities)
    manager.setup()
    entry.async_on_unload(coordinator.async_add_listener(manager.update))


class YandexEatBinarySensorManager:
    def __init__(
        self,
        coordinator: YandexEatCoordinator,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        self.coordinator = coordinator
        self.async_add_entities = async_add_entities
        self._entities: dict[str, YandexEatCourierNearbySensor] = {}

    def setup(self) -> None:
        self.update()

    @callback
    def update(self) -> None:
        current_orders = {
            order.id: order
            for order in self.coordinator.data.values()
            if order.is_active
        }
        new_entities: list[YandexEatCourierNearbySensor] = []
        for order_id, order in current_orders.items():
            if order_id not in self._entities:
                entity = YandexEatCourierNearbySensor(self.coordinator, order)
                self._entities[order_id] = entity
                new_entities.append(entity)
            else:
                self._entities[order_id].async_write_ha_state()
        if new_entities:
            self.async_add_entities(new_entities)

        for order_id in list(self._entities):
            if order_id not in current_orders:
                del self._entities[order_id]


class YandexEatCourierNearbySensor(YandexEatEntity, BinarySensorEntity):
    _attr_translation_key = "courier_nearby"
    _attr_icon = "mdi:bike-fast"

    def __init__(self, coordinator: YandexEatCoordinator, order: TrackedOrder) -> None:
        super().__init__(coordinator, order, "courier_nearby")
        self._attr_name = "Courier nearby"

    @property
    def is_on(self) -> bool | None:
        order = self.order
        return order.courier_nearby if order else None

    @property
    def extra_state_attributes(self) -> dict:
        order = self.order
        if not order:
            return {}
        attrs = self.coordinator.order_attributes(order)
        if order.tracking_info and order.tracking_info.remaining_time is not None:
            attrs["eta_minutes"] = order.tracking_info.remaining_time
        return attrs
