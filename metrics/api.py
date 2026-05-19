from __future__ import annotations

from typing import Any

import requests

from .config import Config


def auth_headers(api_token: str) -> dict[str, str]:
    token = api_token.strip()
    if token and not token.startswith("Bearer "):
        token = f"Bearer {token}"

    return {
        "Accept": "application/json",
        "Authorization": token,
    }


def unwrap_response(payload: Any) -> Any:
    if isinstance(payload, dict):
        for wrapper_key in ("response", "data"):
            if wrapper_key in payload:
                return payload[wrapper_key]

    return payload


class RemnawaveClient:
    def __init__(
        self,
        config: Config,
        session: requests.Session | None = None,
    ) -> None:
        self._config = config
        self._session = session or requests.Session()
        self._session.headers.update(auth_headers(config.api_token))

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self._session.get(
            f"{self._config.api_base_url}/{path.lstrip('/')}",
            params=params,
            timeout=self._config.request_timeout,
        )

        if not response.ok:
            body = response.text[:300].replace("\n", " ")
            raise RuntimeError(
                f"Remnawave API GET {path} returned HTTP "
                f"{response.status_code}: {body}"
            )

        return unwrap_response(response.json())

    def fetch_users_page(
        self,
        start: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], int | None]:
        data = self._get(
            "users",
            params={"start": start, "size": size},
        )

        if not isinstance(data, dict):
            raise ValueError("Remnawave users response is not a JSON object")

        users = data.get("users")
        total = data.get("total")

        if not isinstance(users, list):
            raise ValueError("Remnawave response does not contain a users list")

        if total is not None:
            total = int(total)

        return users, total

    def fetch_all_users(self) -> list[dict[str, Any]]:
        users: list[dict[str, Any]] = []
        start = 0
        total: int | None = None

        while True:
            page, total = self.fetch_users_page(
                start=start,
                size=self._config.page_size,
            )
            users.extend(page)

            if not page:
                break
            if total is not None and len(users) >= total:
                break
            if len(page) < self._config.page_size and total is None:
                break

            start += len(page)

        return users

    def fetch_servers(self) -> list[dict[str, Any]]:
        data = self._get("nodes")

        if isinstance(data, dict):
            servers = data.get("nodes") or data.get("servers")
        else:
            servers = data

        if not isinstance(servers, list):
            raise ValueError("Remnawave response does not contain a nodes list")

        return servers
