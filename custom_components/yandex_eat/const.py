DOMAIN = "yandex_eat"

CONF_X_TOKEN = "x_token"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 30
NEARBY_ETA_MINUTES = 5

STATE_NO_ORDER = "none"
CURRENCY_RUB = "RUB"

TRACKED_ORDERS_PATH = "/api/v1/providers/orders/v1/tracked-orders"
TRACKING_V2_PATH = "/api/v2/orders/tracking"
TRACKING_DESKTOP_PATH = "/eats/v1/eats-orders-tracking/v1/tracking-for-desktop"
ORDERS_INFO_PATH = "/eats/v1/orders-info/v1/orders"
ORDERS_INFO_BASE_URL = "https://eda.yandex.ru"
ORDERS_INFO_PAGE_LIMIT = 50
ORDERS_INFO_MAX_PAGES = 20

# orders-info restaurant streams are selected via X-Platform (grocery stream is shared).
ORDER_HISTORY_PLATFORM_EDA = "android_app"
ORDER_HISTORY_PLATFORM_DC = "dc_app"
ORDER_TRACKING_PLATFORM_DC = "dc_desktop_web"

SERVICE_EDA = "eda"
SERVICE_LAVKA = "lavka"
SERVICE_MARKET = "market"

SERVICE_BASE_URLS = {
    SERVICE_EDA: ORDERS_INFO_BASE_URL,
    SERVICE_LAVKA: "https://lavka.yandex.ru",
    SERVICE_MARKET: "https://market-delivery.yandex.ru",
}

TRACKING_V2_BASE_URLS = (
    SERVICE_BASE_URLS[SERVICE_EDA],
    SERVICE_BASE_URLS[SERVICE_MARKET],
)

YANDEX_LOGIN_RETPATH = "https://market-delivery.yandex.ru"

EMPTY_HTTP_STATUSES = frozenset({424})
