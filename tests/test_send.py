from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from zimbra_mcp import server

KEY = "key-12345678"


@pytest.fixture
def sender(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Enable sending and replace the SMTP layer; returns the list of 'sent' messages."""
    monkeypatch.setenv("ZIMBRA_ALLOW_SEND", "true")
    sent: list[dict[str, Any]] = []

    def fake(settings: server.Settings, recipients: list[str], subject: str, body: str) -> None:
        sent.append({"to": recipients, "subject": subject, "body": body})

    monkeypatch.setattr(server, "_send_mail", fake)
    return sent


def test_sending_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[object] = []
    monkeypatch.setattr(server, "_send_mail", lambda *a: called.append(a))
    with pytest.raises(ValueError, match="disabled"):
        server.send_email("bob@example.test", "s", "b", confirm=True, idempotency_key=KEY)
    assert called == []


def test_unconfirmed_call_returns_preview_and_sends_nothing(sender: list[dict[str, Any]]) -> None:
    result = server.send_email("Bob <bob@example.test>", "Hi", "body text")
    assert result["status"] == "confirmation_required"
    assert result["preview"]["to"] == ["bob@example.test"]
    assert sender == []


def test_confirmed_send_requires_idempotency_key(sender: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError, match="idempotency_key"):
        server.send_email("bob@example.test", "Hi", "b", confirm=True)
    assert sender == []


def test_confirmed_send_goes_out_once(sender: list[dict[str, Any]]) -> None:
    first = server.send_email("bob@example.test", "Hi", "b", confirm=True, idempotency_key=KEY)
    again = server.send_email("bob@example.test", "Hi", "b", confirm=True, idempotency_key=KEY)
    assert first["status"] == "sent"
    assert again["status"] == "duplicate"
    assert len(sender) == 1


def test_key_reuse_with_different_content_is_rejected(sender: list[dict[str, Any]]) -> None:
    server.send_email("bob@example.test", "Hi", "b", confirm=True, idempotency_key=KEY)
    with pytest.raises(ValueError, match="different message"):
        server.send_email("bob@example.test", "Hi", "other", confirm=True, idempotency_key=KEY)
    assert len(sender) == 1


def test_failed_send_releases_key_for_retry(
    monkeypatch: pytest.MonkeyPatch, sender: list[dict[str, Any]]
) -> None:
    def fail(*args: object) -> None:
        raise OSError("connection reset")

    good = server._send_mail
    monkeypatch.setattr(server, "_send_mail", fail)
    with pytest.raises(RuntimeError, match="send_email failed"):
        server.send_email("bob@example.test", "Hi", "b", confirm=True, idempotency_key=KEY)
    monkeypatch.setattr(server, "_send_mail", good)
    result = server.send_email("bob@example.test", "Hi", "b", confirm=True, idempotency_key=KEY)
    assert result["status"] == "sent"


def test_pending_key_blocks_a_second_send(sender: list[dict[str, Any]]) -> None:
    settings = server.Settings.from_env()
    fingerprint = __import__("hashlib").sha256(b"bob@example.test\nHi\nb").hexdigest()
    assert server._claim_send(settings, KEY, fingerprint) is True
    with pytest.raises(ValueError, match="in progress"):
        server.send_email("bob@example.test", "Hi", "b", confirm=True, idempotency_key=KEY)
    assert sender == []


def test_idempotency_store_is_private_and_consistent(
    sender: list[dict[str, Any]], tmp_path: Path
) -> None:
    server.send_email("bob@example.test", "Hi", "b", confirm=True, idempotency_key=KEY)
    state = tmp_path / "state"
    assert (state.stat().st_mode & 0o777) == 0o700
    with sqlite3.connect(state / "idempotency.db") as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT status FROM sent").fetchall() == [("sent",)]
        assert "Hi" not in str(db.execute("SELECT * FROM sent").fetchall())


def test_recipient_limit(sender: list[dict[str, Any]]) -> None:
    many = ", ".join(f"u{i}@example.test" for i in range(server.MAX_RECIPIENTS + 1))
    with pytest.raises(ValueError, match="At most"):
        server.send_email(many, "Hi", "b")


@pytest.mark.parametrize("bad", ["not-an-address", "a@b", "x@y.test\nBcc: z@y.test", "   "])
def test_invalid_recipients_rejected(sender: list[dict[str, Any]], bad: str) -> None:
    with pytest.raises(ValueError):
        server.send_email(bad, "Hi", "b")


def test_allowlist_blocks_other_recipients(
    monkeypatch: pytest.MonkeyPatch, sender: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("ZIMBRA_SEND_ALLOWLIST", "ok@example.test,@corp.test")
    server.send_email("ok@example.test, anyone@corp.test", "Hi", "b")
    with pytest.raises(ValueError, match="ZIMBRA_SEND_ALLOWLIST"):
        server.send_email("evil@attacker.test", "Hi", "b")


@pytest.mark.parametrize(
    ("subject", "body"),
    [("", "b"), ("Hi\r\nBcc: x@y.test", "b"), ("s" * 300, "b"), ("Hi", ""), ("Hi", "b" * 100_001)],
)
def test_subject_and_body_validation(sender: list[dict[str, Any]], subject: str, body: str) -> None:
    with pytest.raises(ValueError):
        server.send_email("bob@example.test", subject, body)


def test_smtp_uses_starttls_with_default_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            events.append(f"connect {host}:{port}")

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def ehlo(self) -> None:
            events.append("ehlo")

        def starttls(self, context: Any) -> None:
            assert context.check_hostname is True
            events.append("starttls")

        def login(self, user: str, password: str) -> None:
            events.append("login")

        def send_message(self, message: Any) -> dict[str, Any]:
            assert message["To"] == "bob@example.test"
            events.append("send")
            return {}

    monkeypatch.setattr(server.smtplib, "SMTP", FakeSMTP)
    server._send_mail(server.Settings.from_env(), ["bob@example.test"], "s", "b")
    assert events == ["connect smtp.example.test:587", "ehlo", "starttls", "ehlo", "login", "send"]


def test_smtp_rejected_recipients_raise_without_leaking_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RejectingSMTP:
        def __init__(self, *a: object, **k: object) -> None: ...
        def __enter__(self) -> RejectingSMTP:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def ehlo(self) -> None: ...
        def starttls(self, context: Any) -> None: ...
        def login(self, user: str, password: str) -> None: ...
        def send_message(self, message: Any) -> dict[str, Any]:
            return {"bob@example.test": (550, b"no")}

    monkeypatch.setattr(server.smtplib, "SMTP", RejectingSMTP)
    with pytest.raises(RuntimeError, match=r"rejected 1 recipient") as info:
        server._send_mail(server.Settings.from_env(), ["bob@example.test"], "s", "b")
    assert "bob@example.test" not in str(info.value)
