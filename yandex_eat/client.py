from __future__ import annotations

from typing import Any

from yandex_eat.auth import YandexSession
from yandex_eat.models import Service, TrackedOrder

TRACKED_ORDERS_PATH = "/api/v1/providers/orders/v1/tracked-orders"

SERVICE_BASE_URLS: dict[Service, str] = {
    Service.EDA: "https://eda.yandex.ru",
    Service.LAVKA: "https://lavka.yandex.ru",
}


class YandexEatClient:
    """Poll active orders from Yandex Eda / Lavka consumer web API."""

    def __init__(self, x_token: str, *, timeout: float = 30.0) -> None:
        self._session = YandexSession(x_token=x_token.strip(), timeout=timeout)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> YandexEatClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def login(self) -> None:
        self._session.login()

    def user_profile(self, service: Service = Service.EDA) -> dict[str, Any]:
        base = SERVICE_BASE_URLS[service]
        data = self._session.get_json(f"{base}/api/v1/user/profile")
        if not isinstance(data, dict):
            raise TypeError(f"expected profile dict, got {type(data).__name__}")
        return data

    def tracked_orders(self, service: Service = Service.EDA) -> list[TrackedOrder]:
        base = SERVICE_BASE_URLS[service]
        url = f"{base}{TRACKED_ORDERS_PATH}"
        data = self._session.get_json(url)
        if not isinstance(data, list):
            raise TypeError(f"expected list from {url}, got {type(data).__name__}")
        return [TrackedOrder.from_api(item, service) for item in data if isinstance(item, dict)]

    def all_tracked_orders(self) -> list[TrackedOrder]:
        orders: list[TrackedOrder] = []
        for service in Service:
            try:
                orders.extend(self.tracked_orders(service))
            except Exception:
                # Lavka may 404 in some regions; Eda may be empty — keep going
                continue
        return orders

    def nearby_orders(self, *, eta_minutes: int = 5) -> list[TrackedOrder]:
        result: list[TrackedOrder] = []
        for order in self.all_tracked_orders():
            if order.order_status.value == "delivery_arrived":
                result.append(order)
                continue
            eta = order.tracking_info.remaining_time if order.tracking_info else None
            if eta is not None and eta <= eta_minutes:
                result.append(order)
        return result
