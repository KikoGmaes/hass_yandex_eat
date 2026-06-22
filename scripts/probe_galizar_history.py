#!/usr/bin/env python3
"""Probe Galizar account for active/recent orders across Yandex Eda / Market Delivery APIs."""
from __future__ import annotations

import json
import sys

import httpx
import paramiko

HA_SSH = ("192.168.0.32", "kiko", "kiko123")
ENTRY_TITLE = "Galizar"


def get_token() -> str:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HA_SSH[0], username=HA_SSH[1], password=HA_SSH[2], timeout=20)
    cmd = (
        "docker exec homeassistant python3 -c \"import json; "
        "e=[x for x in json.load(open('/config/.storage/core.config_entries'))['data']['entries'] "
        f"if x.get('domain')=='yandex_eat' and x.get('title')=='{ENTRY_TITLE}'][0]; "
        "print(e['data']['x_token'])\""
    )
    _, stdout, _ = client.exec_command(cmd)
    token = stdout.read().decode().strip()
    client.close()
    if not token:
        raise RuntimeError("Galizar token not found")
    return token


def login(client: httpx.Client, token: str, retpath: str) -> dict:
    r = client.post(
        "https://mobileproxy.passport.yandex.net/1/bundle/auth/x_token/",
        data={"type": "x-token", "retpath": retpath},
        headers={
            "Ya-Consumer-Authorization": f"OAuth {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    data = r.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"login failed for {retpath}: {data}")
    client.get(
        f"{data['passport_host']}/auth/session/",
        params={"track_id": data["track_id"]},
        follow_redirects=False,
    )
    user = client.get("https://yandex.ru/quasar?storage=1").json().get("storage", {}).get("user", {})
    return user


def interesting(status: int, text: str) -> bool:
    if status in (401, 403, 500, 502, 503):
        return True
    if status == 405:
        return True
    if status == 404 and len(text) > 80 and "notFound" in text:
        return True
    if status == 200 and text.strip() not in (
        "[]",
        "{}",
        '{"payload":{"trackedOrders":[]},"meta":{"count":0,"checkAfter":15}}',
    ):
        return True
    if status == 424 and text.strip():
        return True
    if status == 400 and "required" in text.lower():
        return True
    return False


def main() -> None:
    token = get_token()
    print("token_prefix:", token[:12])

    bases = [
        "https://eda.yandex.ru",
        "https://market-delivery.yandex.ru",
        "https://lavka.yandex.ru",
    ]
    get_paths = [
        "/api/v2/orders/tracking",
        "/api/v1/providers/orders/v1/tracked-orders",
        "/api/v1/orders/history",
        "/api/v1/orders/list",
        "/api/v1/orders/current",
        "/api/v1/orders/last",
        "/api/v1/user/orders",
        "/api/v1/user/orders/history",
        "/api/v1/user/orders/list",
        "/api/v1/orders/archive",
        "/api/v1/orders/completed",
        "/api/v1/orders/recent",
        "/api/v1/feedback/orders",
        "/api/v1/user/profile",
        "/eats/v1/eats-orders/v1/orders/list",
        "/eats/v1/eats-orders/v1/orders/history",
        "/eats/v1/eats-order-history/v1/orders/list",
        "/eats/v1/eats-order-history/v1/orders/history",
        "/eats/v1/eats-order-history/v1/order/list",
        "/eats/v1/eats-order-history/v1/order/history",
        "/eats/v1/orders/list",
        "/eats/v1/orders/history",
    ]
    post_paths = [
        "/api/v1/orders",
        "/api/v1/orders/list",
        "/api/v1/orders/history",
        "/api/v2/orders/history",
        "/api/v2/orders/list",
        "/eats/v1/eats-orders/v1/orders/list",
        "/eats/v1/eats-orders/v1/orders/history",
        "/eats/v1/eats-order-history/v1/orders/list",
        "/eats/v1/eats-order-history/v1/orders/history",
        "/eats/v1/eats-order-history/v1/order/list",
        "/eats/v1/eats-order-history/v1/order/history",
        "/api/v1/user/orders/history",
        "/api/v2/user/orders/history",
    ]
    bodies = [{}, {"limit": 10}, {"offset": 0, "limit": 10}]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9",
    }

    for retpath in ("https://eda.yandex.ru", "https://market-delivery.yandex.ru"):
        with httpx.Client(headers=headers, timeout=25.0, follow_redirects=True) as client:
            user = login(client, token, retpath)
            print(f"\n=== retpath={retpath} login={user.get('login')} uid={user.get('uid')} ===\n")

            for base in bases:
                h = {**headers, "Origin": base, "Referer": f"{base}/"}
                for path in get_paths:
                    url = base + path
                    try:
                        r = client.get(url, headers=h)
                    except Exception as exc:
                        print("ERR GET", url, exc)
                        continue
                    if interesting(r.status_code, r.text):
                        print(f"GET {r.status_code} {url}")
                        print(r.text[:3000])
                        print("---")

                for path in post_paths:
                    for body in bodies:
                        url = base + path
                        try:
                            r = client.post(
                                url,
                                headers={**h, "Content-Type": "application/json"},
                                json=body,
                            )
                        except Exception:
                            continue
                        if interesting(r.status_code, r.text):
                            print(f"POST {r.status_code} {url} body={body}")
                            print(r.text[:3000])
                            print("---")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FATAL:", exc, file=sys.stderr)
        sys.exit(1)
