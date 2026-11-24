from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

from .config import Settings


class ZimbraAdminClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        settings.validate_primary()
        self._settings = settings
        self._http = http_client or httpx.AsyncClient(
            timeout=settings.request_timeout,
            verify=settings.verify_tls,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            http2=True,
        )
        self._owns_http = http_client is None
        self._token: str | None = None
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _authenticate(self) -> str:
        async with self._lock:
            if self._token:
                return self._token
            body = {
                "Header": {"context": {"_jsns": "urn:zimbra"}},
                "Body": {
                    "AuthRequest": {
                        "_jsns": "urn:zimbraAdmin",
                        "account": {"_content": self._settings.username},
                        "password": {"_content": self._settings.password},
                    }
                },
            }
            response = await self._http.post(self._endpoint, json=body)
            response.raise_for_status()
            token = _path(response.json(), "Body", "AuthResponse", "authToken", "_content")
            if not isinstance(token, str) or not token:
                raise RuntimeError("Zimbra admin authentication did not return a token")
            self._token = token
            return token

    @property
    def _endpoint(self) -> str:
        return f"{self._settings.zimbra_url}/service/admin/soap"

    async def _request(self, operation: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        token = await self._authenticate()
        body = {
            "Header": {
                "context": {
                    "_jsns": "urn:zimbra",
                    "authToken": {"_content": token},
                }
            },
            "Body": {operation: {"_jsns": "urn:zimbraAdmin", **payload}},
        }
        response = await self._http.post(self._endpoint, json=body)
        if response.status_code in {401, 403}:
            self._token = None
            token = await self._authenticate()
            body["Header"]["context"]["authToken"] = {"_content": token}
            response = await self._http.post(self._endpoint, json=body)
        response.raise_for_status()
        result = _path(response.json(), "Body", operation.replace("Request", "Response"))
        if not isinstance(result, Mapping):
            raise RuntimeError("Zimbra admin returned an unexpected response")
        return result

    async def account_info(self, email: str) -> dict[str, Any]:
        result = await self._request("GetAccountInfoRequest", {"name": {"_content": email}})
        return dict(result)

    async def server_stats(self) -> dict[str, Any]:
        result = await self._request("GetServerStatsRequest", {})
        return dict(result)

    async def list_accounts(self, domain: str, limit: int) -> list[dict[str, Any]]:
        result = await self._request(
            "SearchDirectoryRequest", {"query": domain, "limit": limit, "types": "accounts"}
        )
        accounts = result.get("account", [])
        if isinstance(accounts, Mapping):
            accounts = [accounts]
        return [dict(item) for item in accounts if isinstance(item, Mapping)][:limit]

    async def create_account(
        self, email: str, password: str, attributes: Mapping[str, str]
    ) -> dict[str, Any]:
        result = await self._request(
            "CreateAccountRequest",
            {"name": {"_content": email}, "password": {"_content": password}, **dict(attributes)},
        )
        return dict(result)

    async def modify_account(self, email: str, attributes: Mapping[str, str]) -> dict[str, Any]:
        result = await self._request(
            "ModifyAccountRequest",
            {"name": {"_content": email}, **dict(attributes)},
        )
        return dict(result)

    async def delete_account(self, email: str) -> dict[str, Any]:
        result = await self._request("DeleteAccountRequest", {"name": {"_content": email}})
        return dict(result)


def _path(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current
