DOMAIN = "yandex_eat"

CONF_X_TOKEN = "x_token"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 30
NEARBY_ETA_MINUTES = 5

TRACKED_ORDERS_PATH = "/api/v1/providers/orders/v1/tracked-orders"

SERVICE_EDA = "eda"
SERVICE_LAVKA = "lavka"

SERVICE_BASE_URLS = {
    SERVICE_EDA: "https://eda.yandex.ru",
    SERVICE_LAVKA: "https://lavka.yandex.ru",
}

EMPTY_HTTP_STATUSES = frozenset({424})
