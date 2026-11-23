from __future__ import annotations

import pytest

from zimbra_mcp.server import Settings, _redact


def test_password_is_not_in_repr_or_str() -> None:
    settings = Settings.from_env()
    assert "S3cretPassw0rd" not in repr(settings)
    assert "S3cretPassw0rd" not in str(settings)


def test_missing_variables_are_listed_without_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZIMBRA_PASSWORD")
    with pytest.raises(ValueError, match="ZIMBRA_PASSWORD") as info:
        Settings.from_env()
    assert "S3cretPassw0rd" not in str(info.value)


@pytest.mark.parametrize(
    "url", ["http://dav.example.test/cal", "ftp://dav.example.test/cal", "https:///nohost"]
)
def test_caldav_requires_https(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("ZIMBRA_CALDAV_URL", url)
    with pytest.raises(ValueError, match="https"):
        Settings.from_env()


def test_caldav_url_must_not_embed_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZIMBRA_CALDAV_URL", "https://alice:pw@dav.example.test/cal")
    with pytest.raises(ValueError, match="credentials"):
        Settings.from_env()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ZIMBRA_TIMEOUT", "0"),
        ("ZIMBRA_TIMEOUT", "-5"),
        ("ZIMBRA_TIMEOUT", "nan"),
        ("ZIMBRA_TIMEOUT", "inf"),
        ("ZIMBRA_TIMEOUT", "9999"),
        ("ZIMBRA_TIMEOUT", "soon"),
        ("ZIMBRA_IMAP_PORT", "0"),
        ("ZIMBRA_IMAP_PORT", "99999"),
        ("ZIMBRA_SMTP_PORT", "abc"),
    ],
)
def test_numeric_settings_are_validated(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        Settings.from_env()


def test_safe_defaults() -> None:
    settings = Settings.from_env()
    assert settings.allow_send is False
    assert settings.imap_port == 993
    assert settings.smtp_port == 587
    assert settings.send_allowlist == ()


def test_allowlist_is_parsed_and_lowercased(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZIMBRA_SEND_ALLOWLIST", " Bob@Example.test , @corp.test ,")
    assert Settings.from_env().send_allowlist == ("bob@example.test", "@corp.test")


def test_redact_removes_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "login failed for alice@example.test with S3cretPassw0rd"
    cleaned = _redact(text)
    assert "S3cretPassw0rd" not in cleaned
    assert "alice@example.test" not in cleaned
