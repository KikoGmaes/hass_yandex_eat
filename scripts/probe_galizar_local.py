#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys

import httpx

HA_URL = os.environ.get("HOMEASSISTANT_URL", "https://ha.badkiko.ru").rstrip("/")
HA_TOKEN = os.environ.get("HOMEASSISTANT_TOKEN", "")
ENTRY_ID = "01KVR72CGPB1DDP3EPWSBB2Q2V"

URLS = {
    "eda_tracked": "https://eda.yandex.ru/api/v1/providers/orders/v1/tracked-orders",
    "lavka_tracked": "https://lavka.yandex.ru/api/v1/providers/orders/v1/tracked-orders",
    "market_tracked": "https://market-delivery.yandex.ru/api/v1/providers/orders/v1/tracked-orders",
    "eda_profile": "https://eda.yandex.ru/api/v1/user/profile",
    "market_profile": "https://market-delivery.yandex.ru/api/v1/user/profile",
}


def ws_get_entry() -> dict:
    import websocket

    ws_url = HA_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/websocket"
    ws = websocket.create_connection(ws_url, timeout=30)
    try:
        hello = json.loads(ws.recv())
        ws.send(json.dumps({"type": "auth", "access_token": HA_TOKEN}))
        auth = json.loads(ws.recv())
        if auth.get("type") != "auth_ok":
            raise RuntimeError(f"auth failed: {auth}")

        ws.send(json.dumps({"id": 1, "type": "config_entries/get", "entry_id": ENTRY_ID}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                if not msg.get("success"):
                    raise RuntimeError(msg)
                return msg["result"]
    finally:
        ws.close()


def fetch_galizar_token() -> tuple[str, str]:
    entry = ws_get_entry()
    data = entry.get("data") or {}
    token = data.get("x_token")
    if not token:
        raise RuntimeError(f"no x_token in ws entry, keys={list(data)}")
    return entry.get("title", "Galizar"), token


def probe_yandex(token: str) -> None:
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
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        auth_headers = {"Ya-Consumer-Authorization": f"OAuth {token}"}
        r = client.post(
            "https://mobileproxy.passport.yandex.net/1/bundle/auth/x_token/",
            data={"type": "x-token", "retpath": "https://www.yandex.ru"},
            headers=auth_headers,
        )
        data = r.json()
        print("login_status:", data.get("status"))
        if data.get("status") != "ok":
            print("login_error:", json.dumps(data, ensure_ascii=False)[:500])
            return

        host = data["passport_host"]
        track = {"track_id": data["track_id"]}
        r = client.get(f"{host}/auth/session/", params=track, follow_redirects=False)
        print("session_redirect:", r.status_code, (r.headers.get("Location") or "")[:120])

        r = client.get("https://yandex.ru/quasar?storage=1")
        user = r.json().get("storage", {}).get("user", {})
        print("yandex_uid:", user.get("uid"), "yandex_login:", user.get("login"))

        for name, url in URLS.items():
            r = client.get(url)
            print(f"\n=== {name} ===")
            print("status:", r.status_code, "len:", len(r.text))
            print(r.text[:2500])


def main() -> None:
    if not HA_TOKEN:
        print("Set HOMEASSISTANT_TOKEN", file=sys.stderr)
        sys.exit(1)
    title, token = fetch_galizar_token()
    print("account:", title, "token_prefix:", token[:12])
    probe_yandex(token)


if __name__ == "__main__":
    main()
