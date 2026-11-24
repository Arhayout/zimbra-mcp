from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


@dataclass(frozen=True, slots=True)
class Settings:
    zimbra_url: str
    username: str
    password: str
    request_timeout: float
    verify_tls: bool
    imap_host: str
    imap_port: int
    imap_ssl: bool
    smtp_host: str
    smtp_port: int
    smtp_ssl: bool
    enable_send: bool
    caldav_url: str = ""
    enable_write: bool = False
    enable_admin: bool = False
    state_db: str = "~/.local/share/zimba-mcp/state.sqlite3"

    @classmethod
    def from_env(cls) -> Settings:
        zimbra_url = os.getenv("ZIMBRA_URL", "").rstrip("/")
        username = os.getenv("ZIMBRA_USERNAME", "")
        return cls(
            zimbra_url=zimbra_url,
            username=username,
            password=os.getenv("ZIMBRA_PASSWORD", ""),
            request_timeout=float(os.getenv("ZIMBRA_REQUEST_TIMEOUT", "20")),
            verify_tls=_env_bool("ZIMBRA_VERIFY_TLS", True),
            imap_host=os.getenv("IMAP_HOST", ""),
            imap_port=_env_int("IMAP_PORT", 993),
            imap_ssl=_env_bool("IMAP_SSL", True),
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=_env_int("SMTP_PORT", 465),
            smtp_ssl=_env_bool("SMTP_SSL", True),
            enable_send=_env_bool("ZIMBRA_ENABLE_SEND", False),
            caldav_url=os.getenv("CALDAV_URL", f"{zimbra_url}/dav/{username}/Calendar").rstrip("/"),
            enable_write=_env_bool("ZIMBRA_ENABLE_WRITE", False),
            enable_admin=_env_bool("ZIMBRA_ENABLE_ADMIN", False),
            state_db=os.getenv("ZIMBA_STATE_DB", "~/.local/share/zimba-mcp/state.sqlite3"),
        )

    def validate_primary(self) -> None:
        missing = [
            name
            for name, value in {
                "ZIMBRA_URL": self.zimbra_url,
                "ZIMBRA_USERNAME": self.username,
                "ZIMBRA_PASSWORD": self.password,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required Zimbra configuration: {', '.join(missing)}")

    def validate_imap(self) -> None:
        missing = [
            name
            for name, value in {
                "IMAP_HOST": self.imap_host,
                "ZIMBRA_USERNAME": self.username,
                "ZIMBRA_PASSWORD": self.password,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required IMAP configuration: {', '.join(missing)}")

    def validate_smtp(self) -> None:
        missing = [
            name
            for name, value in {
                "SMTP_HOST": self.smtp_host,
                "ZIMBRA_USERNAME": self.username,
                "ZIMBRA_PASSWORD": self.password,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required SMTP configuration: {', '.join(missing)}")
