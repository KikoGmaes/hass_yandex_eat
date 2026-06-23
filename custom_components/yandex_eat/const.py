DOMAIN = "yandex_eat"

CONF_X_TOKEN = "x_token"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_RESTAURANT_AS = "restaurant_as"
CONF_EXTRA_ORDER_NRS = "extra_order_nrs"

DEFAULT_SCAN_INTERVAL = 30
ORDER_DETAIL_SUPPLEMENT_LIMIT = 30
KNOWN_ORDERS_STORE_VERSION = 1
DEFAULT_RESTAURANT_AS = "eda"
RESTAURANT_AS_MARKET = "market"
NEARBY_ETA_MINUTES = 5

STATE_NO_ORDER = "none"

TRACKED_ORDERS_PATH = "/api/v1/providers/orders/v1/tracked-orders"
TRACKING_V2_PATH = "/api/v2/orders/tracking"
ORDERS_INFO_PATH = "/eats/v1/orders-info/v1/orders"
ORDER_DETAIL_PATH = "/eats/v1/orders-info/v1/order"
ORDERS_INFO_PAGE_LIMIT = 50
ORDERS_INFO_MAX_PAGES = 20

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
)

TRACKING_V2_BASE_URLS = (
    SERVICE_BASE_URLS[SERVICE_EDA],
    SERVICE_BASE_URLS[SERVICE_MARKET],
)

YANDEX_LOGIN_RETPATH = "https://market-delivery.yandex.ru"

EMPTY_HTTP_STATUSES = frozenset({424})

# Substrings matched against lowercased place names for grocery retail chains.
RETAIL_CHAIN_SUBSTRINGS = (
    "пятёрочка",
    "пятерочка",
    "магнит",
    "перекрёсток",
    "перекресток",
    "дикси",
    "лента",
    "ашан",
    "вкусвилл",
    "верный",
    "монетка",
    "fix price",
    "ozon fresh",
    "озон fresh",
    "metro",
)

INACTIVE_TRACKED_STATUSES = frozenset(
    {
        "closed",
        "delivered",
        "delivered_finish",
        "cancelled",
        "cancelled_with_payment",
        "failed",
    }
)
