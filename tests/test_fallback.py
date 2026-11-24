from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from zimbra_mcp.config import Settings
from zimbra_mcp.fallback import FallbackMail


class FakeMailbox:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.message = SimpleNamespace(
            uid="42",
            subject="Test subject",
            from_="sender@example.com",
            to=["user@example.com"],
            date=datetime(2026, 1, 1, tzinfo=UTC),
            text="hello",
            html="<p>hello</p>",
            flags={"\\Seen"},
        )

    def login(self, *_args: object, **_kwargs: object) -> FakeMailbox:
        return self

    def __enter__(self) -> FakeMailbox:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def fetch(self, *_args: object, **_kwargs: object) -> list[object]:
        return [self.message]


class FakeSMTP:
    last_message: Any = None

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.logged_in = False

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def login(self, *_args: object, **_kwargs: object) -> None:
        self.logged_in = True

    def send_message(self, message: Any) -> None:
        assert self.logged_in
        FakeSMTP.last_message = message


def test_imap_search_uses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zimbra_mcp.fallback.MailBox", FakeMailbox)
    config = Settings(
        zimbra_url="",
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
    result = FallbackMail(config)._search_sync("hello", 5)
    assert result[0]["id"] == "42"
    assert result[0]["subject"] == "Test subject"


def test_imap_read_uses_uid_without_marking_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zimbra_mcp.fallback.MailBox", FakeMailbox)
    result = FallbackMail(_settings())._read_sync("42")
    assert result["id"] == "42"
    assert result["html"] == "<p>hello</p>"


def test_smtp_send_sets_idempotent_message_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zimbra_mcp.fallback.smtplib.SMTP_SSL", FakeSMTP)
    result = FallbackMail(_settings())._send_sync(
        ["recipient@example.com"], "Subject", "Body", "request-123"
    )
    assert result == {"status": "sent", "message_id": "request-123", "backend": "smtp"}
    assert FakeSMTP.last_message["Message-ID"] == "<request-123@zimba-mcp>"


def _settings() -> Settings:
    return Settings(
        zimbra_url="",
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
        enable_send=True,
    )
