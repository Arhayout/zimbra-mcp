from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Any

from imap_tools import AND, MailBox, MailBoxUnencrypted

from .config import Settings


class FallbackMail:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._search_sync, query, limit)

    def _search_sync(self, query: str, limit: int) -> list[dict[str, Any]]:
        self._settings.validate_imap()
        with self._mailbox().login(self._settings.username, self._settings.password) as mailbox:
            messages = mailbox.fetch(AND(text=query), limit=limit, reverse=True)
            return [_message_summary(message) for message in messages]

    async def read(self, message_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._read_sync, message_id)

    def _read_sync(self, message_id: str) -> dict[str, Any]:
        self._settings.validate_imap()
        with self._mailbox().login(self._settings.username, self._settings.password) as mailbox:
            messages = mailbox.fetch(AND(uid=message_id), mark_seen=False)
            for message in messages:
                return _message_detail(message)
        raise LookupError(f"Message not found: {message_id}")

    async def send(self, to: list[str], subject: str, body: str, message_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._send_sync, to, subject, body, message_id)

    def _send_sync(self, to: list[str], subject: str, body: str, message_id: str) -> dict[str, Any]:
        self._settings.validate_smtp()
        message = EmailMessage()
        message["From"] = self._settings.username
        message["To"] = ", ".join(to)
        message["Subject"] = subject
        message["Message-ID"] = f"<{message_id}@zimba-mcp>"
        message.set_content(body)
        if self._settings.smtp_ssl:
            with smtplib.SMTP_SSL(self._settings.smtp_host, self._settings.smtp_port) as smtp:
                smtp.login(self._settings.username, self._settings.password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port) as smtp:
                smtp.starttls()
                smtp.login(self._settings.username, self._settings.password)
                smtp.send_message(message)
        return {"status": "sent", "message_id": message_id, "backend": "smtp"}

    def _mailbox(self) -> MailBox | MailBoxUnencrypted:
        mailbox_type = MailBox if self._settings.imap_ssl else MailBoxUnencrypted
        return mailbox_type(self._settings.imap_host, self._settings.imap_port)


def _message_summary(message: Any) -> dict[str, Any]:
    return {
        "id": str(message.uid),
        "subject": message.subject,
        "from": str(message.from_),
        "to": [str(item) for item in message.to],
        "date": message.date.isoformat() if message.date else None,
        "text": message.text,
    }


def _message_detail(message: Any) -> dict[str, Any]:
    result = _message_summary(message)
    flags = message.flags if message.flags else set()
    result.update({"html": message.html, "flags": list(flags)})
    return result
