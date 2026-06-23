from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import aiohttp
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import YANDEX_LOGIN_RETPATH

_LOGGER = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "android (3.80.0)",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "X-Platform": "android_app",
    "X-App-Version": "18.9.1",
}


def _device_id(x_token: str | None) -> str:
    if not x_token:
        return "yandex-eat-ha"
    digest = hashlib.sha256(x_token.encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


class LoginResponse:
    def __init__(self, resp: dict[str, Any]):
        self.raw = resp

    @property
    def ok(self) -> bool:
        return self.raw.get("status") == "ok"

    @property
    def errors(self) -> list[Any]:
        return self.raw.get("errors", [])

    @property
    def error(self) -> str:
        return self.errors[0] if self.errors else "unknown"

    @property
    def display_login(self) -> str:
        return self.raw.get("display_login") or self.raw.get("login") or "yandex"

    @property
    def x_token(self) -> str:
        return self.raw["x_token"]


class YandexSession:
    """Async Yandex auth session (QR / token). Based on AlexxIT/YandexStation."""

    def __init__(self, session: aiohttp.ClientSession, x_token: str | None = None) -> None:
        self._session = session
        self.x_token = x_token
        self.auth_headers: dict[str, str] | None = None
        self.auth_json: dict[str, Any] | None = None
        self._request_headers = {
            **DEFAULT_HEADERS,
            "X-Device-Id": _device_id(x_token),
        }

    async def get_qr(self) -> str:
        async with self._session.get("https://passport.yandex.ru/pwl-yandex") as r:
            r.raise_for_status()
            text = await r.text()
        match = re.search(r'__CSRF__ = "([^"]+)', text)
        if not match:
            raise RuntimeError("CSRF token not found on passport page")
        self.auth_headers = {"X-CSRF-Token": match.group(1)}

        async with self._session.post(
            "https://passport.yandex.ru/pwl-yandex/api/passport/auth/password/submit",
            json={"retpath": "https://passport.yandex.ru/"},
            headers=self.auth_headers,
        ) as r:
            r.raise_for_status()
            self.auth_json = await r.json()

        async with self._session.post(
            "https://passport.yandex.ru/pwl-yandex/api/passport/auth/magic/code",
            data={
                "location_id": "0",
                "magic_track_id": self.auth_json["track_id"],
                "track_id": "",
            },
            headers=self.auth_headers,
        ) as r:
            r.raise_for_status()
            resp = await r.json()
        return resp["link"]

    async def login_qr(self) -> LoginResponse | None:
        if not self.auth_json or not self.auth_headers:
            return None
        async with self._session.post(
            "https://passport.yandex.ru/pwl-yandex/api/passport/auth/magic/code/status",
            json=self.auth_json,
            headers=self.auth_headers,
        ) as r:
            r.raise_for_status()
            resp = await r.json()
        if resp.get("state") != "otp_auth_finished":
            return None

        async with self._session.post(
            "https://passport.yandex.ru/pwl-yandex/api/passport/sessions/get_session",
            data={"track_id": resp["trackId"]},
            headers=self.auth_headers,
        ) as r:
            r.raise_for_status()
        return await self.login_cookies()

    async def login_cookies(self) -> LoginResponse:
        cookies = "; ".join(
            f"{cookie.key}={cookie.value}"
            for cookie in self._session.cookie_jar
            if "yandex" in (cookie["domain"] or "")
        )
        async with self._session.post(
            "https://mobileproxy.passport.yandex.net/1/bundle/oauth/token_by_sessionid",
            data={
                "client_id": "c0ebe342af7d48fbbbfcf2d2eedb8f9e",
                "client_secret": "ad0a908f0aa341a182a37ecd75bc319e",
            },
            headers={"Ya-Client-Host": "passport.yandex.ru", "Ya-Client-Cookie": cookies},
        ) as r:
            resp = await r.json()
        return await self.validate_token(resp["access_token"])

    async def validate_token(self, x_token: str) -> LoginResponse:
        async with self._session.get(
            "https://mobileproxy.passport.yandex.net/1/bundle/account/short_info/?avatar_size=islands-300",
            headers={"Authorization": f"OAuth {x_token}"},
        ) as r:
            resp = await r.json()
        if resp.get("status") != "ok":
            return LoginResponse(resp)
        resp["x_token"] = x_token
        resp["display_login"] = resp.get("display_name") or resp.get("login") or resp.get("default_email")
        return LoginResponse(resp)

    async def refresh_cookies(self) -> bool:
        if not self.x_token:
            return False
        expected_uid = await self._token_uid()
        if expected_uid is None:
            return False

        if not await self._login_token(self.x_token):
            return False

        async with self._session.get(
            "https://yandex.ru/quasar?storage=1",
            headers=self._request_headers,
        ) as r:
            resp = await r.json()
        actual_uid = str(resp.get("storage", {}).get("user", {}).get("uid") or "")
        return actual_uid == expected_uid

    async def _token_uid(self) -> str | None:
        if not self.x_token:
            return None
        async with self._session.get(
            "https://mobileproxy.passport.yandex.net/1/bundle/account/short_info/?avatar_size=islands-300",
            headers={"Authorization": f"OAuth {self.x_token}"},
        ) as r:
            resp = await r.json()
        if resp.get("status") != "ok":
            _LOGGER.error("short_info failed: %s", resp)
            return None
        uid = resp.get("uid")
        return str(uid) if uid is not None else None

    async def _login_token(self, x_token: str) -> bool:
        payload = {"type": "x-token", "retpath": YANDEX_LOGIN_RETPATH}
        headers = {
            **self._request_headers,
            "Ya-Consumer-Authorization": f"OAuth {x_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        async with self._session.post(
            "https://mobileproxy.passport.yandex.net/1/bundle/auth/x_token/",
            data=payload,
            headers=headers,
        ) as r:
            resp = await r.json()
        if resp.get("status") != "ok":
            _LOGGER.error("x-token login failed: %s", resp)
            return False

        host = resp["passport_host"]
        track = {"track_id": resp["track_id"]}
        async with self._session.get(
            f"{host}/auth/session/",
            params=track,
            allow_redirects=False,
        ) as r:
            location = r.headers.get("Location", "")
            if r.status not in (302, 303, 307) or "/auth/finish" not in location:
                return False
        self.x_token = x_token
        return True

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        empty_statuses: frozenset[int] | None = None,
    ) -> Any:
        return await self._request_json(
            "GET",
            url,
            params=params,
            headers=headers,
            empty_statuses=empty_statuses,
        )

    async def post_json(
        self,
        url: str,
        body: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        empty_statuses: frozenset[int] | None = None,
    ) -> Any:
        return await self._request_json(
            "POST",
            url,
            json_body=body or {},
            headers=headers,
            empty_statuses=empty_statuses,
        )

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        empty_statuses: frozenset[int] | None = None,
    ) -> Any:
        empty_statuses = empty_statuses or frozenset()
        request_headers = {**self._request_headers, **(headers or {})}
        for attempt in range(2):
            async with self._session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=request_headers,
            ) as r:
                if r.status == 401 and attempt == 0 and self.x_token:
                    if await self.refresh_cookies():
                        continue
                    raise ConfigEntryAuthFailed("Yandex token expired")
                if r.status in empty_statuses and r.content_length in (0, None):
                    text = await r.text()
                    if not text:
                        return [] if method == "GET" else {}
                if r.status != 200:
                    raise aiohttp.ClientResponseError(
                        r.request_info,
                        r.history,
                        status=r.status,
                        message=f"{url} -> {r.status}",
                        headers=r.headers,
                    )
                if r.content_length in (0, None):
                    text = await r.text()
                    if not text:
                        return [] if method == "GET" else {}
                return await r.json()
        raise RuntimeError(f"failed to fetch {url}")
