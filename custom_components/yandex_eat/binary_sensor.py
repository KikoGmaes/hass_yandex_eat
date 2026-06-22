from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import YandexEatCoordinator
from .entity import YandexEatAccountEntity, primary_order_attributes


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: YandexEatCoordinator = entry.runtime_data
    async_add_entities([YandexEatCourierNearbySensor(coordinator)])


class YandexEatCourierNearbySensor(YandexEatAccountEntity, BinarySensorEntity):
    _attr_translation_key = "courier_nearby"
    _attr_icon = "mdi:bike-fast"

    def __init__(self, coordinator: YandexEatCoordinator) -> None:
        super().__init__(coordinator, "courier_nearby")

    @property
    def is_on(self) -> bool:
        order = self.primary_order
        return bool(order and order.courier_nearby)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return primary_order_attributes(self.coordinator)
