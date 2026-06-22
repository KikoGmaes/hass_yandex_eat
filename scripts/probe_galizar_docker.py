#!/usr/bin/env python3
import json
import httpx

entry = [
    x
    for x in json.load(open("/config/.storage/core.config_entries"))["data"]["entries"]
    if x.get("domain") == "yandex_eat" and x.get("title") == "Galizar"
][0]
token = entry["data"]["x_token"]

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Accept-Language": "ru-RU",
}
with httpx.Client(headers=headers, timeout=25.0, follow_redirects=True) as c:
    r = c.post(
        "https://mobileproxy.passport.yandex.net/1/bundle/auth/x_token/",
        data={"type": "x-token", "retpath": "https://eda.yandex.ru"},
        headers={
            "Ya-Consumer-Authorization": f"OAuth {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    d = r.json()
    c.get(
        f"{d['passport_host']}/auth/session/",
        params={"track_id": d["track_id"]},
        follow_redirects=False,
    )
    user = c.get("https://yandex.ru/quasar?storage=1").json().get("storage", {}).get("user", {})
    print("login", user.get("login"), "uid", user.get("uid"))

    print("\n--- tracking ---")
    for base in ("https://eda.yandex.ru", "https://market-delivery.yandex.ru"):
        for path in (
            "/api/v2/orders/tracking",
            "/api/v1/providers/orders/v1/tracked-orders",
        ):
            r = c.get(base + path, headers={"Origin": base, "Referer": f"{base}/"})
            print(base, path, r.status_code, r.text[:400])

    posts = [
        ("/eats/v1/eats-order-history/v1/orders/list", {}),
        ("/eats/v1/eats-order-history/v1/orders/list", {"limit": 10}),
        ("/eats/v1/eats-order-history/v1/orders/list", {"pagination": {"limit": 10}}),
        ("/eats/v1/eats-order-history/v1/order/list", {}),
        ("/eats/v1/eats-order-history/v1/get-orders", {}),
        ("/eats/v1/eats-order-history/v1/get-orders-list", {}),
        ("/eats/v1/eats-orders/v1/orders/list", {}),
        ("/eats/v1/eats-orders/v1/orders/history", {}),
        ("/eats/v1/layout-constructor/v1/layout", {
            "location": {"latitude": 59.93, "longitude": 30.31},
            "view": {"type": "order_history", "slug": "order_history"},
        }),
        ("/eats/v1/layout-constructor/v1/layout", {
            "location": {"latitude": 59.93, "longitude": 30.31},
            "view": {"slug": "orders_history", "type": "orders_history"},
        }),
    ]
    print("\n--- post probes ---")
    for base in ("https://eda.yandex.ru", "https://market-delivery.yandex.ru"):
        for path, body in posts:
            h = {
                **headers,
                "Origin": base,
                "Referer": f"{base}/",
                "Content-Type": "application/json",
            }
            r = c.post(base + path, headers=h, json=body)
            if r.status_code == 200 and r.text.strip() not in ("[]", "{}"):
                if "trackedOrders\":[]" not in r.text:
                    print("HIT", r.status_code, base + path, body)
                    print(r.text[:5000])
                    print("---")
            elif r.status_code not in (404, 405):
                print(r.status_code, base + path, r.text[:300])
