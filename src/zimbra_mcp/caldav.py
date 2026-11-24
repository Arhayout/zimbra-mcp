from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import quote, urljoin

import httpx
from defusedxml import ElementTree

from .config import Settings


class CalDAVError(RuntimeError):
    """Raised when a CalDAV request fails or returns invalid data."""


class CalDAVClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        settings.validate_primary()
        if not settings.caldav_url:
            raise RuntimeError("CALDAV_URL or ZIMBRA_URL is required for CalDAV")
        self._settings = settings
        self._http = http_client or httpx.AsyncClient(
            timeout=settings.request_timeout,
            verify=settings.verify_tls,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            http2=True,
        )
        self._owns_http = http_client is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def list_events(self, start: datetime, end: datetime, limit: int) -> list[dict[str, Any]]:
        start_value = start.strftime("%Y%m%dT%H%M%SZ")
        end_value = end.strftime("%Y%m%dT%H%M%SZ")
        query = f"""<?xml version="1.0" encoding="utf-8" ?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop><D:getetag/><C:calendar-data/></D:prop>
  <C:filter><C:comp-filter name="VCALENDAR">
  <C:comp-filter name="VEVENT">
    <C:time-range start="{start_value}" end="{end_value}"/>
  </C:comp-filter>
  </C:comp-filter></C:filter>
</C:calendar-query>"""
        response = await self._http.request(
            "REPORT",
            self._settings.caldav_url,
            content=query.encode(),
            headers={"Content-Type": "application/xml; charset=utf-8", "Depth": "1"},
            auth=(self._settings.username, self._settings.password),
        )
        response.raise_for_status()
        events: list[dict[str, Any]] = []
        for href, calendar_data in _multistatus_events(response.text):
            event = _parse_icalendar(calendar_data)
            event["href"] = href
            events.append(event)
            if len(events) >= limit:
                break
        return events

    async def read_event(self, event_id: str) -> dict[str, Any]:
        url = (
            event_id
            if event_id.startswith("http")
            else urljoin(f"{self._settings.caldav_url}/", quote(event_id))
        )
        response = await self._http.get(
            url,
            auth=(self._settings.username, self._settings.password),
            headers={"Accept": "text/calendar"},
        )
        response.raise_for_status()
        return _parse_icalendar(response.text) | {"href": url}


def _multistatus_events(xml_text: str) -> list[tuple[str, str]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise CalDAVError("CalDAV returned invalid XML") from exc
    results: list[tuple[str, str]] = []
    for response in root.iter("{DAV:}response"):
        href = response.findtext("{DAV:}href") or ""
        data = next(
            (
                element.text
                for element in response.iter("{urn:ietf:params:xml:ns:caldav}calendar-data")
                if element.text
            ),
            None,
        )
        if data:
            results.append((href, data))
    return results


def _parse_icalendar(data: str) -> dict[str, Any]:
    unfolded = re.sub(r"\r?\n[ \t]", "", data)
    values: dict[str, Any] = {}
    attendees: list[str] = []
    for line in unfolded.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        name = key.split(";", 1)[0].upper()
        if name == "ATTENDEE":
            attendees.append(value.removeprefix("mailto:"))
        elif name in {
            "UID",
            "SUMMARY",
            "DESCRIPTION",
            "LOCATION",
            "STATUS",
            "DTSTART",
            "DTEND",
            "DTSTAMP",
        }:
            values[name.lower()] = value
    if attendees:
        values["attendees"] = attendees
    return values
