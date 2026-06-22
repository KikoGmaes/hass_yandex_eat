#!/usr/bin/env python3
"""Probe Yandex orders-info / order-history APIs for pagination."""
from __future__ import annotations

import json
import os
import sys

import httpx

TOKEN = os.environ.get("YANDEX_X_TOKEN", "").strip()
if not TOKEN:
    print("Set YANDEX_X_TOKEN", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


def login(client: httpx.Client, token: str) -> dict:
    r = client.post(
        "https://mobileproxy.passport.yandex.net/1/bundle/auth/x_token/",
        data={"type": "x-token", "retpath": "https://eda.yandex.ru"},
        headers={
            "Ya-Consumer-Authorization": f"OAuth {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    data = r.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"login failed: {data}")
    client.get(
        f"{data['passport_host']}/auth/session/",
        params={"track_id": data["track_id"]},
        follow_redirects=False,
    )
    user = client.get("https://yandex.ru/quasar?storage=1").json().get("storage", {}).get("user", {})
    return user


def probe_post(client: httpx.Client, base: str, path: str, body: dict) -> None:
    h = {**HEADERS, "Origin": base, "Referer": f"{base}/", "Content-Type": "application/json"}
    r = client.post(base + path, headers=h, json=body)
    text = r.text
    print(f"\nPOST {r.status_code} {base}{path}")
    print("body:", json.dumps(body, ensure_ascii=False))
    if r.status_code != 200:
        print(text[:500])
        return
    try:
        data = r.json()
    except Exception:
        print(text[:2000])
        return
    if isinstance(data, dict):
        keys = list(data.keys())
        print("top keys:", keys)
        orders = data.get("orders")
        if isinstance(orders, list):
            print("orders count:", len(orders))
        payload = data.get("payload")
        if isinstance(payload, dict):
            print("payload keys:", list(payload.keys()))
            porders = payload.get("orders")
            if isinstance(porders, list):
                print("payload.orders count:", len(porders))
        pagination = data.get("pagination") or (payload.get("pagination") if isinstance(payload, dict) else None)
        if pagination:
            print("pagination:", json.dumps(pagination, ensure_ascii=False))
        cursor = data.get("cursor") or data.get("next_cursor") or data.get("next")
        if cursor:
            print("cursor/next:", cursor)
        if isinstance(orders, list) and orders:
            print("first order_nr:", orders[0].get("order_nr"))
            print("last order_nr:", orders[-1].get("order_nr"))
    else:
        print(type(data), str(data)[:500])


def main() -> None:
    bases = [
        "https://eda.yandex.ru",
        "https://market-delivery.yandex.ru",
    ]
    bodies = [
        {},
        {"limit": 50},
        {"limit": 100},
        {"pagination": {"limit": 50}},
        {"pagination": {"limit": 50, "offset": 0}},
        {"pagination": {"limit": 50, "cursor": ""}},
        {"offset": 0, "limit": 50},
    ]
    history_bodies = [
        {},
        {"pagination": {"limit": 50}},
        {"pagination": {"limit": 50, "offset": 0}},
        {"limit": 50},
    ]
    paths = [
        "/eats/v1/orders-info/v1/orders",
        "/eats/v1/eats-order-history/v1/orders/list",
        "/eats/v1/eats-order-history/v1/orders/history",
    ]

    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        user = login(client, TOKEN)
        print("login:", user.get("login"), "uid:", user.get("uid"))

        for base in bases:
            for path in paths:
                for body in (bodies if "orders-info" in path else history_bodies):
                    probe_post(client, base, path, body)


if __name__ == "__main__":
    main()
