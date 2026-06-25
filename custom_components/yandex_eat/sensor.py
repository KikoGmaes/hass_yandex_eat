from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime

from .const import CURRENCY_RUB
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import STATE_NO_ORDER
from .coordinator import YandexEatCoordinator
from .entity import YandexEatAccountEntity, primary_order_attributes
from .models import OrderStatus, Service, parse_order_year


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: YandexEatCoordinator = entry.runtime_data
    async_add_entities(
        [
            YandexEatActiveOrdersSensor(coordinator),
            YandexEatOrderStatusSensor(coordinator),
            YandexEatCourierEtaSensor(coordinator),
            YandexEatPastOrdersSensor(coordinator, Service.EDA, "past_orders_eda", "mdi:food"),
            YandexEatPastOrdersSensor(
                coordinator, Service.MARKET, "past_orders_delivery", "mdi:moped"
            ),
            YandexEatPastOrdersSensor(coordinator, Service.LAVKA, "past_orders_lavka", "mdi:cart"),
            YandexEatTotalSpentSensor(coordinator),
            YandexEatTotalSpentYearSensor(coordinator),
        ]
    )


class YandexEatActiveOrdersSensor(YandexEatAccountEntity, SensorEntity):
    _attr_translation_key = "active_orders"
    _attr_icon = "mdi:food"

    def __init__(self, coordinator: YandexEatCoordinator) -> None:
        super().__init__(coordinator, "active_orders")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.active_orders)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
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
            ],
            "recent_orders": [
                self.coordinator.recent_order_dict(order)
                for order in self.coordinator.recent_orders
            ],
        }
        last_order = self.coordinator.last_order
        if last_order is not None:
            attrs["last_order"] = self.coordinator.recent_order_dict(last_order)
        return attrs


class YandexEatOrderStatusSensor(YandexEatAccountEntity, SensorEntity):
    _attr_translation_key = "order_status"
    _attr_icon = "mdi:truck-delivery"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [status.value for status in OrderStatus] + [STATE_NO_ORDER]

    def __init__(self, coordinator: YandexEatCoordinator) -> None:
        super().__init__(coordinator, "order_status")

    @property
    def native_value(self) -> str:
        order = self.primary_order
        if order is None:
            return STATE_NO_ORDER
        return order.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return primary_order_attributes(self.coordinator)


class YandexEatCourierEtaSensor(YandexEatAccountEntity, SensorEntity):
    _attr_translation_key = "courier_eta"
    _attr_icon = "mdi:timer-sand"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: YandexEatCoordinator) -> None:
        super().__init__(coordinator, "courier_eta")

    @property
    def native_value(self) -> int | None:
        order = self.primary_order
        if order is None or not order.tracking_info:
            return None
        return order.tracking_info.remaining_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = primary_order_attributes(self.coordinator)
        order = self.primary_order
        if (
            order
            and order.tracking_info
            and order.tracking_info.remaining_time is not None
        ):
            eta = order.tracking_info.remaining_time
            attrs["arrival_time"] = (
                dt_util.now() + timedelta(minutes=eta)
            ).isoformat()
        return attrs


class YandexEatPastOrdersSensor(YandexEatAccountEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: YandexEatCoordinator,
        service: Service,
        suffix: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator, suffix)
        self._service = service
        self._attr_translation_key = suffix
        self._attr_icon = icon

    @property
    def native_value(self) -> int:
        return sum(
            1 for order in self.coordinator.recent_orders if order.service == self._service
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "orders": [
                self.coordinator.recent_order_dict(order)
                for order in self.coordinator.recent_orders
                if order.service == self._service
            ],
            "total_recent_orders": len(self.coordinator.recent_orders),
        }


class YandexEatTotalSpentSensor(YandexEatAccountEntity, SensorEntity):
    _attr_translation_key = "total_spent"
    _attr_icon = "mdi:cash-multiple"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_RUB
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: YandexEatCoordinator) -> None:
        super().__init__(coordinator, "total_spent")

    @property
    def native_value(self) -> float:
        return round(self.coordinator.total_spent, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "order_count": len(self.coordinator.spent_orders()),
        }


class YandexEatTotalSpentYearSensor(YandexEatAccountEntity, SensorEntity):
    _attr_translation_key = "total_spent_year"
    _attr_icon = "mdi:cash"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_RUB
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: YandexEatCoordinator) -> None:
        super().__init__(coordinator, "total_spent_year")

    @property
    def native_value(self) -> float:
        return round(self.coordinator.total_spent_this_year, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        year = dt_util.now().year
        orders = [
            order
            for order in self.coordinator.spent_orders()
            if parse_order_year(order.order_nr, order.date, fallback_year=year) == year
        ]
        return {
            "year": year,
            "order_count": len(orders),
        }
