from __future__ import annotations

import httpx
import pytest

from zimbra_mcp.admin import ZimbraAdminClient
from zimbra_mcp.config import Settings


def settings() -> Settings:
    return Settings(
        zimbra_url="https://mail.test",
        username="admin@example.com",
        password="test-only",  # noqa: S106
        request_timeout=5,
        verify_tls=True,
        imap_host="imap.test",
        imap_port=993,
        imap_ssl=True,
        smtp_host="smtp.test",
        smtp_port=465,
        smtp_ssl=True,
        enable_send=False,
        enable_admin=True,
    )


@pytest.mark.asyncio
async def test_admin_client_uses_admin_endpoint_and_token() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        payload = request.read()
        if b"AuthRequest" in payload:
            return httpx.Response(
                200,
                json={"Body": {"AuthResponse": {"authToken": {"_content": "admin-token"}}}},
            )
        if b"GetAccountInfoRequest" in payload:
            return httpx.Response(
                200, json={"Body": {"GetAccountInfoResponse": {"name": "u@example.com"}}}
            )
        return httpx.Response(
            200, json={"Body": {"SearchDirectoryResponse": {"account": {"name": "u@example.com"}}}}
        )

    client = ZimbraAdminClient(
        settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    try:
        assert (await client.account_info("u@example.com"))["name"] == "u@example.com"
        assert (await client.list_accounts("example.com", 10))[0]["name"] == "u@example.com"
        assert all(url.endswith("/service/admin/soap") for url in calls)
        assert len(calls) == 3
    finally:
        await client.aclose()
