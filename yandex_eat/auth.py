from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import httpx


class YandexAuthError(Exception):
    """Failed to authenticate with x-token."""


@dataclass
class YandexSession:
    """Minimal session: x-token -> cookies, then authenticated GET requests."""

    x_token: str
    timeout: float = 30.0
    _client: httpx.Client | None = None
    csrf_token: str | None = None

    def __post_init__(self) -> None:
        self._client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ru-RU,ru;q=0.9",
            },
        )

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> YandexSession:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def login(self, *, retries: int = 3) -> None:
        """Exchange x-token for session cookies (AlexxIT/YandexStation flow)."""
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                self._login_once()
                return
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError) as exc:
                last_error = exc
                if attempt + 1 < retries:
                    time.sleep(1.5 * (attempt + 1))
        raise YandexAuthError(f"x-token login failed after {retries} attempts: {last_error}")

    def _login_once(self) -> None:
        assert self._client is not None
        payload = {"type": "x-token", "retpath": "https://www.yandex.ru"}
        headers = {"Ya-Consumer-Authorization": f"OAuth {self.x_token}"}
        r = self._client.post(
            "https://mobileproxy.passport.yandex.net/1/bundle/auth/x_token/",
            data=payload,
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "ok":
            raise YandexAuthError(f"x-token login failed: {data}")

        host = data["passport_host"]
        track = {"track_id": data["track_id"]}
        r = self._client.get(f"{host}/auth/session/", params=track, follow_redirects=False)
        if r.status_code not in (302, 303, 307):
            raise YandexAuthError(f"session redirect expected, got {r.status_code}: {r.text[:200]}")

        location = r.headers.get("Location", "")
        if "/auth/finish" not in location:
            raise YandexAuthError(f"unexpected redirect: {location[:200]}")

        # Verify cookies
        r = self._client.get("https://yandex.ru/quasar?storage=1")
        r.raise_for_status()
        storage = r.json()
        uid = storage.get("storage", {}).get("user", {}).get("uid")
        if not uid:
            raise YandexAuthError("cookies ok but no yandex uid in quasar storage")

    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        empty_statuses: frozenset[int] = frozenset({424}),
    ) -> Any:
        assert self._client is not None
        r = self._client.get(url, params=params)
        if r.status_code == 401:
            self.login()
            r = self._client.get(url, params=params)
        if r.status_code in empty_statuses and not r.content:
            return []
        if r.status_code != 200:
            raise httpx.HTTPStatusError(
                f"{url} -> {r.status_code}",
                request=r.request,
                response=r,
            )
        if not r.content:
            return []
        return r.json()

    def fetch_csrf(self) -> str:
        if self.csrf_token:
            return self.csrf_token
        assert self._client is not None
        r = self._client.get("https://yandex.ru/quasar")
        r.raise_for_status()
        m = re.search(r'"csrfToken2":"(.+?)"', r.text)
        if not m:
            raise YandexAuthError("csrf token not found on yandex.ru/quasar")
        self.csrf_token = m.group(1)
        return self.csrf_token
