from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from zimbra_mcp.caldav import CalDAVClient
from zimbra_mcp.config import Settings


@pytest.mark.asyncio
async def test_caldav_list_and_read_event() -> None:
    calendar = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:event-1\nSUMMARY:Planning\n"
        "DTSTART:20261123T100000Z\nDTEND:20261123T110000Z\n"
        "ATTENDEE:mailto:user@example.com\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    xml = f"""<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:response><D:href>/dav/user/Calendar/event-1.ics</D:href>
    <D:propstat><D:prop><C:calendar-data>{calendar}</C:calendar-data></D:prop></D:propstat>
  </D:response>
</D:multistatus>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "REPORT":
            return httpx.Response(207, text=xml)
        return httpx.Response(200, text=calendar, headers={"Content-Type": "text/calendar"})

    settings = Settings(
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
        caldav_url="https://mail.test/dav/user/Calendar",
    )
    client = CalDAVClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        events = await client.list_events(
            datetime(2026, 11, 23, 0, tzinfo=UTC), datetime(2026, 11, 24, tzinfo=UTC), 10
        )
        assert events[0]["uid"] == "event-1"
        assert events[0]["summary"] == "Planning"
        assert (await client.read_event("event-1.ics"))["uid"] == "event-1"
    finally:
        await client.aclose()
