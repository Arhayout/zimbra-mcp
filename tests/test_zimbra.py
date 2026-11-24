from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from zimbra_mcp.config import Settings
from zimbra_mcp.zimbra import ZimbraClient


def settings() -> Settings:
    return Settings(
        zimbra_url="https://mail.test",
        username="user@example.com",
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
    )


@pytest.mark.asyncio
async def test_auth_token_is_cached() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.read())
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={"Body": {"AuthResponse": {"authToken": {"_content": "token-1"}}}},
            )
        return httpx.Response(200, json={"Body": {"SearchResponse": {"c": []}}})

    client = ZimbraClient(settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        assert await client.search("from:test", 10) == []
        assert await client.search("subject:test", 10) == []
        assert len(calls) == 3
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unauthorized_response_reauthenticates() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={"Body": {"AuthResponse": {"authToken": {"_content": "token-1"}}}},
            )
        if calls == 2:
            return httpx.Response(401)
        if calls == 3:
            return httpx.Response(
                200,
                json={"Body": {"AuthResponse": {"authToken": {"_content": "token-2"}}}},
            )
        return httpx.Response(200, json={"Body": {"SearchResponse": {"c": []}}})

    client = ZimbraClient(settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        assert await client.search("from:test", 10) == []
        assert calls == 4
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_mail_management_operations_parse_soap_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read()
        if b"AuthRequest" in payload:
            return httpx.Response(
                200,
                json={"Body": {"AuthResponse": {"authToken": {"_content": "token-1"}}}},
            )
        if b"GetFolderRequest" in payload:
            return httpx.Response(
                200,
                json={
                    "Body": {
                        "GetFolderResponse": {
                            "folder": {
                                "id": "1",
                                "name": "Inbox",
                                "folder": {"id": "2", "name": "Work"},
                            }
                        }
                    }
                },
            )
        if b"GetTagRequest" in payload:
            return httpx.Response(
                200,
                json={"Body": {"GetTagResponse": {"tag": {"id": "t1", "name": "Important"}}}},
            )
        if b"GetMsgRequest" in payload:
            return httpx.Response(
                200,
                json={
                    "Body": {
                        "GetMsgResponse": {
                            "m": {"id": "m1", "mp": {"filename": "report.pdf", "aid": "a1"}}
                        }
                    }
                },
            )
        if b"SaveDraftRequest" in payload:
            return httpx.Response(200, json={"Body": {"SaveDraftResponse": {"m": {"id": "d1"}}}})
        if b"CreateFolderRequest" in payload:
            return httpx.Response(
                200, json={"Body": {"CreateFolderResponse": {"folder": {"id": "3"}}}}
            )
        if b"CreateTagRequest" in payload:
            return httpx.Response(200, json={"Body": {"CreateTagResponse": {"tag": {"id": "t2"}}}})
        return httpx.Response(200, json={"Body": {"MsgActionResponse": {"m": []}}})

    client = ZimbraClient(settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        assert len(await client.list_folders()) == 2
        assert (await client.create_folder("Work"))["id"] == "3"
        assert (await client.list_tags())[0]["name"] == "Important"
        assert (await client.create_tag("Urgent"))["id"] == "t2"
        assert (await client.save_draft(["user@example.com"], "Draft", "Body"))["id"] == "d1"
        assert (await client.list_attachments("m1"))[0]["filename"] == "report.pdf"
        assert await client.message_action("read", ["m1"]) == {"m": []}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_calendar_operations_parse_soap_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read()
        if b"AuthRequest" in payload:
            return httpx.Response(
                200,
                json={"Body": {"AuthResponse": {"authToken": {"_content": "token-1"}}}},
            )
        if b"GetApptSummariesRequest" in payload:
            return httpx.Response(
                200,
                json={"Body": {"GetApptSummariesResponse": {"appt": {"id": "a1"}}}},
            )
        if b"GetAppointmentRequest" in payload:
            return httpx.Response(
                200,
                json={
                    "Body": {"GetAppointmentResponse": {"appt": {"id": "a1", "name": "Planning"}}}
                },
            )
        return httpx.Response(
            200,
            json={"Body": {"FreeBusyResponse": {"usr": {"id": "user@example.com"}}}},
        )

    client = ZimbraClient(settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        start = datetime(2026, 11, 23, tzinfo=UTC)
        end = datetime(2026, 11, 24, tzinfo=UTC)
        assert (await client.list_calendar_events(start, end, 10))[0]["id"] == "a1"
        assert (await client.read_calendar_event("a1"))["name"] == "Planning"
        assert (await client.free_busy(start, end, ["user@example.com"]))[0][
            "id"
        ] == "user@example.com"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_extended_read_operations_parse_soap_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read()
        if b"AuthRequest" in payload:
            return httpx.Response(
                200,
                json={"Body": {"AuthResponse": {"authToken": {"_content": "token-1"}}}},
            )
        if b'"types":"contact"' in payload:
            return httpx.Response(200, json={"Body": {"SearchResponse": {"cn": {"id": "c1"}}}})
        if b'"types":"task"' in payload:
            return httpx.Response(200, json={"Body": {"SearchResponse": {"task": {"id": "t1"}}}})
        if b"GetPrefsRequest" in payload:
            return httpx.Response(
                200, json={"Body": {"GetPrefsResponse": {"zimbraPrefLocale": "en_US"}}}
            )
        if b"GetQuotaUsageRequest" in payload:
            return httpx.Response(200, json={"Body": {"GetQuotaUsageResponse": {"used": 10}}})
        if b"GetShareInfoRequest" in payload:
            return httpx.Response(
                200, json={"Body": {"GetShareInfoResponse": {"share": {"id": "s1"}}}}
            )
        if b"CreateContactRequest" in payload:
            return httpx.Response(
                200, json={"Body": {"CreateContactResponse": {"cn": {"id": "c2"}}}}
            )
        if b"CreateTaskRequest" in payload:
            return httpx.Response(200, json={"Body": {"CreateTaskResponse": {"m": {"id": "t2"}}}})
        if b"ContactActionRequest" in payload:
            return httpx.Response(200, json={"Body": {"ContactActionResponse": {}}})
        if b"TaskActionRequest" in payload:
            return httpx.Response(200, json={"Body": {"TaskActionResponse": {}}})
        return httpx.Response(200, json={"Body": {"GetFolderResponse": {"folder": {"id": "b1"}}}})

    client = ZimbraClient(settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        assert (await client.search_contacts("Ada", 10))[0]["id"] == "c1"
        assert (await client.list_tasks("in:Tasks", 10))[0]["id"] == "t1"
        assert (await client.list_briefcase(10))[0]["id"] == "b1"
        assert (await client.get_preferences())["zimbraPrefLocale"] == "en_US"
        assert (await client.get_quota())["used"] == 10
        assert (await client.get_share_info())[0]["id"] == "s1"
        assert (await client.save_contact({"email": "u@example.com"}))["id"] == "c2"
        assert (await client.save_task({"name": "Review"}))["id"] == "t2"
        assert await client.delete_contact("c2") == {}
        assert await client.delete_task("t2") == {}
    finally:
        await client.aclose()
