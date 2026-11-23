from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from zimbra_mcp import server

ENV = {
    "ZIMBRA_IMAP_HOST": "imap.example.test",
    "ZIMBRA_SMTP_HOST": "smtp.example.test",
    "ZIMBRA_USERNAME": "alice@example.test",
    "ZIMBRA_PASSWORD": "S3cretPassw0rd",
    "ZIMBRA_CALDAV_URL": "https://dav.example.test/dav/alice/Calendar",
}


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    for key in list(__import__("os").environ):
        if key.startswith("ZIMBRA_"):
            monkeypatch.delenv(key)
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("ZIMBRA_STATE_DIR", str(tmp_path / "state"))
    server._METRICS.clear()
    yield


def make_settings(**overrides: Any) -> server.Settings:
    values: dict[str, Any] = {
        "imap_host": "imap.example.test",
        "imap_port": 993,
        "smtp_host": "smtp.example.test",
        "smtp_port": 587,
        "username": "alice@example.test",
        "password": "S3cretPassw0rd",
        "caldav_url": "https://dav.example.test/dav/alice/Calendar",
        "timeout": 10.0,
    }
    values.update(overrides)
    return server.Settings(**values)


class FakeFolder:
    def __init__(self) -> None:
        self.selected: list[str] = []
        self.fail = False

    def set(self, name: str) -> None:
        if self.fail:
            raise RuntimeError("no such folder")
        self.selected.append(name)


class FakeMailBox:
    """Stands in for imap_tools.MailBox; records every call."""

    def __init__(self, messages: list[Any] | None = None) -> None:
        self.messages = messages or []
        self.folder = FakeFolder()
        self.fetch_calls: list[tuple[Any, dict[str, Any]]] = []
        self.logins: list[tuple[str, str]] = []

    def login(self, username: str, password: str) -> FakeMailBox:
        self.logins.append((username, password))
        return self

    def __enter__(self) -> FakeMailBox:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def fetch(self, criteria: Any, **kwargs: Any) -> Iterator[Any]:
        if "folder" in kwargs:  # the real imap_tools.fetch has no such parameter
            raise TypeError("fetch() got an unexpected keyword argument 'folder'")
        self.fetch_calls.append((criteria, kwargs))
        limit = kwargs.get("limit")
        yield from self.messages[:limit]


def make_message(uid: int = 1, **overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "uid": str(uid),
        "subject": f"Subject {uid}",
        "from_": "bob@example.test",
        "date": None,
        "text": "hello",
        "html": "",
        "attachments": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def mailbox(monkeypatch: pytest.MonkeyPatch) -> FakeMailBox:
    box = FakeMailBox()
    monkeypatch.setattr(server, "_imap", lambda settings: box)
    return box
