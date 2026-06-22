#!/usr/bin/env python3
import asyncio
import json
import sys

import aiohttp

ENTRY_ID = "01KVR72CGPB1DDP3EPWSBB2Q2V"
CONFIG = "/config/.storage/core.config_entries"

URLS = {
    "eda_tracked": "https://eda.yandex.ru/api/v1/providers/orders/v1/tracked-orders",
    "lavka_tracked": "https://lavka.yandex.ru/api/v1/providers/orders/v1/tracked-orders",
    "market_tracked": "https://market-delivery.yandex.ru/api/v1/providers/orders/v1/tracked-orders",
    "eda_profile": "https://eda.yandex.ru/api/v1/user/profile",
    "market_profile": "https://market-delivery.yandex.ru/api/v1/user/profile",
    "eda_orders": "https://eda.yandex.ru/api/v2/orders/active",
    "eda_tracking": "https://eda.yandex.ru/eats/v1/orders/tracking",
}


async def main() -> None:
    entries = json.load(open(CONFIG))["data"]["entries"]
    entry = next(e for e in entries if e.get("entry_id") == ENTRY_ID)
    token = entry["data"]["x_token"]
    print("account:", entry.get("title"))
    print("token_prefix:", token[:12])

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Origin": "https://eda.yandex.ru",
        "Referer": "https://eda.yandex.ru/",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        payload = {"type": "x-token", "retpath": "https://www.yandex.ru"}
        auth_headers = {"Ya-Consumer-Authorization": f"OAuth {token}"}
        async with session.post(
            "https://mobileproxy.passport.yandex.net/1/bundle/auth/x_token/",
            data=payload,
            headers=auth_headers,
        ) as resp:
            data = await resp.json()
            print("login_status:", data.get("status"))
            if data.get("status") != "ok":
                print("login_error:", data)
                return
            host = data["passport_host"]
            track = {"track_id": data["track_id"]}

        async with session.get(f"{host}/auth/session/", params=track, allow_redirects=False) as resp:
            print("session_redirect:", resp.status, (resp.headers.get("Location") or "")[:100])

        async with session.get("https://yandex.ru/quasar?storage=1") as resp:
            storage = await resp.json()
            user = storage.get("storage", {}).get("user", {})
            print("yandex_uid:", user.get("uid"), "yandex_login:", user.get("login"))

        for name, url in URLS.items():
            try:
                async with session.get(url) as resp:
                    text = await resp.text()
                    print(f"\n=== {name} ===")
                    print("status:", resp.status, "len:", len(text))
                    print(text[:2000])
            except Exception as err:
                print(f"\n=== {name} === ERROR: {err}")


if __name__ == "__main__":
    asyncio.run(main())
