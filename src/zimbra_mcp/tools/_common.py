"""Validation, output mapping and the write gate shared by all SOAP-backed tools."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from zimbra_mcp import server as core
from zimbra_mcp.server import Settings

MAX_LIST = 100
MAX_OFFSET = 1000
MAX_FOLDERS = 1000
SYSTEM_FOLDER_LIMIT = 256  # Zimbra system folders have numeric ids below 256

_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}(:[A-Za-z0-9_-]{1,64})?$")
_BAD_NAME = re.compile(r'[/:",\x00-\x1f\x7f]')


def require_soap(settings: Settings) -> None:
    if not settings.soap_url:
        raise ValueError("This tool needs ZIMBRA_SOAP_URL (https://host/service/soap)")


def valid_id(value: str, label: str = "id") -> str:
    value = value.strip()
    if not _ID.match(value):
        raise ValueError(f"{label} must be a single Zimbra item id")
    return value


def valid_name(value: str, label: str, max_len: int = 128) -> str:
    value = value.strip()
    if not value or len(value) > max_len or _BAD_NAME.search(value):
        raise ValueError(f'{label} must be 1-{max_len} characters without / : " , or controls')
    return value


def user_folder_id(value: str) -> str:
    value = valid_id(value, "folder_id")
    if value.isdigit() and int(value) < SYSTEM_FOLDER_LIMIT:
        raise ValueError("System folders cannot be renamed or deleted")
    return value


def check_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= MAX_LIST:
        raise ValueError(f"limit must be between 1 and {MAX_LIST}")
    if not 0 <= offset <= MAX_OFFSET:
        raise ValueError(f"offset must be between 0 and {MAX_OFFSET}")


def check_message(subject: str, body: str) -> str:
    subject = subject.strip()
    if not subject or len(subject) > 255 or core._CONTROL_CHARS.search(subject) or "\n" in subject:
        raise ValueError("subject must be 1-255 characters on a single line")
    if not body.strip() or len(body) > core.MAX_SEND_BODY_CHARS:
        raise ValueError(f"body must be 1-{core.MAX_SEND_BODY_CHARS} characters")
    return subject


def draft_recipients(to: str, settings: Settings) -> list[str]:
    """Validate address format and count only; allowlists apply to sending, not drafting."""
    return core._parse_recipients(to, replace(settings, send_allowlist=()))


def iso_from_ms(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def address(entry: dict[str, Any]) -> str:
    name = core._clean(entry.get("p", ""), 100)
    email = core._clean(entry.get("a", ""), 200)
    return f"{name} <{email}>" if name and email else email or name


def message_summary(item: dict[str, Any]) -> dict[str, Any]:
    flags = str(item.get("f", ""))
    senders = [e for e in item.get("e", []) if e.get("t") == "f"]
    return {
        "id": str(item.get("id", "")),
        "conversation_id": str(item.get("cid", "")),
        "subject": core._clean(item.get("su", "")),
        "from": address(senders[0]) if senders else "",
        "date": iso_from_ms(item.get("d")),
        "fragment": core._clean(item.get("fr", ""), 200),
        "folder_id": str(item.get("l", "")),
        "unread": "u" in flags,
        "flagged": "f" in flags,
        "has_attachment": "a" in flags,
    }


def as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    return [item for item in value or [] if isinstance(item, dict)]


def flatten_folders(
    nodes: list[dict[str, Any]], out: list[dict[str, Any]] | None = None, depth: int = 0
) -> list[dict[str, Any]]:
    out = [] if out is None else out
    for node in nodes:
        if len(out) >= MAX_FOLDERS or depth > 20:
            break
        out.append(
            {
                "id": str(node.get("id", "")),
                "name": core._clean(node.get("name", ""), 128),
                "path": core._clean(node.get("absFolderPath", ""), 400),
                "view": str(node.get("view", "")),
                "parent_id": str(node.get("l", "")),
                "items": node.get("n", 0),
                "unread": node.get("u", 0),
            }
        )
        flatten_folders(as_list(node.get("folder")), out, depth + 1)
    return out


def gate(settings: Settings, *, sends_mail: bool = False) -> None:
    """Fail fast when the operator has not enabled writes (or sending)."""
    if not settings.allow_write:
        raise ValueError("Write tools are disabled; the operator must set ZIMBRA_ALLOW_WRITE=true")
    if sends_mail and not settings.allow_send:
        raise ValueError("Sending is disabled; the operator must set ZIMBRA_ALLOW_SEND=true")


def mutate(
    name: str,
    settings: Settings,
    *,
    preview: dict[str, Any],
    execute: Callable[[], dict[str, Any]],
    confirm: bool = False,
    needs_confirm: bool = False,
    needs_key: bool = False,
    idempotency_key: str = "",
    sends_mail: bool = False,
    content: Any = None,
) -> dict[str, Any]:
    """Run a mutation behind the write gate, confirmation and durable idempotency.

    ``content`` is the full payload (bodies, notes, field values). It is hashed into the
    idempotency fingerprint so a reused key with different content is rejected, but it is
    never stored or shown; ``preview`` is what the user sees.
    """
    gate(settings, sends_mail=sends_mail)
    if (needs_confirm or sends_mail) and not confirm:
        return {
            "status": "confirmation_required",
            "action": name,
            "preview": preview,
            "next_step": "Show this to the user; once they approve, call again with confirm=true"
            + (" and a unique idempotency_key." if needs_key else "."),
        }
    if not needs_key:
        return {"status": "done", **execute()}

    if not core.MIN_IDEMPOTENCY_KEY <= len(idempotency_key) <= core.MAX_IDEMPOTENCY_KEY:
        raise ValueError(
            f"idempotency_key must be {core.MIN_IDEMPOTENCY_KEY}-{core.MAX_IDEMPOTENCY_KEY} "
            "characters"
        )
    fingerprint = hashlib.sha256(
        json.dumps([name, preview, content], sort_keys=True, default=str).encode()
    ).hexdigest()
    if not core._claim_send(settings, idempotency_key, fingerprint):
        return {"status": "duplicate", "detail": "Already done for this idempotency_key."}
    try:
        result = execute()
    except Exception:
        core._finish_send(settings, idempotency_key, sent=False)
        raise
    core._finish_send(settings, idempotency_key, sent=True)
    return {"status": "done", **result}
