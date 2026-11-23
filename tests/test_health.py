from __future__ import annotations

from typing import Any

import pytest

from conftest import FakeMailBox
from zimbra_mcp import server


def test_health_check_does_not_touch_the_network_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("network used")

    monkeypatch.setattr(server.requests, "request", forbidden)
    monkeypatch.setattr(server, "_imap", forbidden)
    result = server.health_check()
    assert result["status"] == "ok"
    assert result["config"]["send_enabled"] is False
    assert "checks" not in result


def test_health_check_never_reveals_secrets() -> None:
    dump = str(server.health_check())
    assert "S3cretPassw0rd" not in dump
    assert "alice@example.test" not in dump


def test_deep_health_check_reports_degraded(
    monkeypatch: pytest.MonkeyPatch, mailbox: FakeMailBox
) -> None:
    class Response:
        status_code = 503

    monkeypatch.setattr(server.requests, "request", lambda *a, **k: Response())
    result = server.health_check(deep=True)
    assert result["checks"] == {"imap": "ok", "caldav": "HTTP 503"}
    assert result["status"] == "degraded"


def test_metrics_count_calls(mailbox: FakeMailBox) -> None:
    server.health_check()
    server.health_check()
    assert server.health_check()["metrics"]["health_check.calls"] == 3


def test_all_expected_tools_are_registered() -> None:
    import asyncio

    tools: Any = asyncio.run(server.mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "search_mail",
        "read_message",
        "send_email",
        "list_calendar_events",
        "health_check",
    }
