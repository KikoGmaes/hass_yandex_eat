from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from yandex_eat.client import YandexEatClient
from yandex_eat.models import Service


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _resolve_token(explicit: str | None) -> str:
    token = explicit or os.environ.get("YANDEX_X_TOKEN") or os.environ.get("X_TOKEN")
    if not token:
        raise SystemExit(
            "No token. Pass --token or set YANDEX_X_TOKEN in .env / environment."
        )
    return token


def _order_to_dict(order) -> dict:
    data = order.model_dump(mode="json", by_alias=True)
    data["courier_nearby"] = order.courier_nearby
    data["raw"] = order.raw
    return data


def cmd_login(args: argparse.Namespace) -> int:
    token = _resolve_token(args.token)
    with YandexEatClient(token) as client:
        client.login()
    print("OK: x-token accepted, session cookies obtained.")
    return 0


def cmd_track(args: argparse.Namespace) -> int:
    token = _resolve_token(args.token)
    service = Service(args.service) if args.service else None

    with YandexEatClient(token) as client:
        client.login()
        if not args.json:
            try:
                profile = client.user_profile(Service.EDA)
                print(
                    f"Account: {profile.get('email')} "
                    f"(has_delivered_orders={profile.get('has_delivered_orders')})"
                )
            except Exception:
                pass
        if service:
            orders = client.tracked_orders(service)
        else:
            orders = client.all_tracked_orders()

    if args.nearby:
        orders = [o for o in orders if o.courier_nearby]

    payload = [_order_to_dict(o) for o in orders]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif not payload:
        print("No active orders.")
    else:
        for o in orders:
            eta = o.tracking_info.remaining_time if o.tracking_info else None
            print(
                f"[{o.service.value}] #{o.short_order_id or o.id} "
                f"status={o.status} nearby={o.courier_nearby} eta={eta}"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    parser = argparse.ArgumentParser(description="Yandex Eda/Lavka consumer order tracker")
    parser.add_argument("--token", help="Yandex x-token (or YANDEX_X_TOKEN env)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Verify x-token and obtain session")
    p_login.set_defaults(func=cmd_login)

    p_track = sub.add_parser("track", help="Fetch tracked-orders")
    p_track.add_argument("--service", choices=["eda", "lavka"], help="Single service (default: both)")
    p_track.add_argument("--nearby", action="store_true", help="Only orders with courier nearby / ETA<=5")
    p_track.add_argument("--json", action="store_true", help="Print raw JSON")
    p_track.set_defaults(func=cmd_track)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
