DOMAIN = "yandex_eat"

CONF_X_TOKEN = "x_token"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 30
NEARBY_ETA_MINUTES = 5

STATE_NO_ORDER = "none"

TRACKED_ORDERS_PATH = "/api/v1/providers/orders/v1/tracked-orders"
TRACKING_V2_PATH = "/api/v2/orders/tracking"
ORDERS_INFO_PATH = "/eats/v1/orders-info/v1/orders"

SERVICE_EDA = "eda"
SERVICE_LAVKA = "lavka"
SERVICE_MARKET = "market"

SERVICE_BASE_URLS = {
    SERVICE_EDA: "https://eda.yandex.ru",
    SERVICE_LAVKA: "https://lavka.yandex.ru",
    SERVICE_MARKET: "https://market-delivery.yandex.ru",
}

# Hosts that share the same eats orders-info / v2 tracking API surface.
ORDERS_INFO_BASE_URLS = (
    SERVICE_BASE_URLS[SERVICE_EDA],
    SERVICE_BASE_URLS[SERVICE_MARKET],
)

TRACKING_V2_BASE_URLS = (
    SERVICE_BASE_URLS[SERVICE_EDA],
    SERVICE_BASE_URLS[SERVICE_MARKET],
)

YANDEX_LOGIN_RETPATH = "https://eda.yandex.ru"

EMPTY_HTTP_STATUSES = frozenset({424})
