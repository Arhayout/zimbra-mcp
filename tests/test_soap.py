from __future__ import annotations

import json
from typing import Any

import pytest

from conftest import make_settings
from zimbra_mcp import soap

URL = "https://mail.example.test/service/soap"


class Resp:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self.raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status_code = status

    def __enter__(self) -> Resp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def iter_content(self, size: int) -> Any:
        for i in range(0, len(self.raw), size):
            yield self.raw[i : i + size]


def auth_reply(token: str = "tok-1", lifetime_ms: int = 3_600_000) -> dict[str, Any]:
    return {"Body": {"AuthResponse": {"authToken": [{"_content": token}], "lifetime": lifetime_ms}}}


def fault(code: str) -> dict[str, Any]:
    return {"Body": {"Fault": {"Reason": {"Text": "boom"}, "Detail": {"Error": {"Code": code}}}}}


@pytest.fixture(autouse=True)
def reset() -> None:
    soap.clear_token_cache()


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Queue of replies; records every posted payload."""
    state: dict[str, Any] = {"queue": [], "posts": []}

    def post(url: str, **kwargs: Any) -> Resp:
        state["posts"].append((url, kwargs))
        item = state["queue"].pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(soap.requests, "post", post)
    return state  # type: ignore[return-value]


def settings() -> Any:
    return make_settings(soap_url=URL)


def test_requires_configured_url() -> None:
    with pytest.raises(ValueError, match="ZIMBRA_SOAP_URL"):
        soap.soap_call(make_settings(), "GetFolderRequest")


def test_authenticates_once_and_caches_token(wire: Any) -> None:
    wire["queue"] += [
        Resp(auth_reply()),
        Resp({"Body": {"GetFolderResponse": {"folder": []}}}),
        Resp({"Body": {"GetFolderResponse": {"folder": []}}}),
    ]
    soap.soap_call(settings(), "GetFolderRequest")
    soap.soap_call(settings(), "GetFolderRequest")
    assert len(wire["posts"]) == 3  # one auth + two calls
    first_call = wire["posts"][1][1]["json"]
    assert first_call["Header"]["context"]["authToken"] == "tok-1"
    assert wire["posts"][0][1]["allow_redirects"] is False


def test_expired_token_is_refreshed_once(wire: Any) -> None:
    wire["queue"] += [
        Resp(auth_reply("OLD")),
        Resp(fault("service.AUTH_EXPIRED")),
        Resp(auth_reply("NEW")),
        Resp({"Body": {"GetFolderResponse": {"folder": [{"id": "1"}]}}}),
    ]
    result = soap.soap_call(settings(), "GetFolderRequest")
    assert result["folder"] == [{"id": "1"}]
    assert wire["posts"][3][1]["json"]["Header"]["context"]["authToken"] == "NEW"


def test_persistent_auth_failure_is_not_retried_forever(wire: Any) -> None:
    wire["queue"] += [
        Resp(auth_reply()),
        Resp(fault("service.AUTH_EXPIRED")),
        Resp(auth_reply()),
        Resp(fault("service.AUTH_EXPIRED")),
    ]
    with pytest.raises(soap.SoapError) as info:
        soap.soap_call(settings(), "GetFolderRequest")
    assert info.value.code == "service.AUTH_EXPIRED"


def test_short_lifetime_token_is_not_reused(wire: Any) -> None:
    wire["queue"] += [
        Resp(auth_reply("A", lifetime_ms=30_000)),
        Resp({"Body": {"GetFolderResponse": {}}}),
        Resp(auth_reply("B", lifetime_ms=3_600_000)),
        Resp({"Body": {"GetFolderResponse": {}}}),
    ]
    soap.soap_call(settings(), "GetFolderRequest")
    soap.soap_call(settings(), "GetFolderRequest")
    assert wire["posts"][3][1]["json"]["Header"]["context"]["authToken"] == "B"


def test_fault_maps_to_soap_error_with_code(wire: Any) -> None:
    wire["queue"] += [Resp(auth_reply()), Resp(fault("mail.NO_SUCH_FOLDER"))]
    with pytest.raises(soap.SoapError) as info:
        soap.soap_call(settings(), "GetFolderRequest")
    assert info.value.code == "mail.NO_SUCH_FOLDER"


def test_login_failure_never_echoes_password(wire: Any) -> None:
    wire["queue"] += [Resp(fault("account.AUTH_FAILED"))]
    with pytest.raises(soap.SoapError) as info:
        soap.soap_call(settings(), "GetFolderRequest")
    assert "S3cretPassw0rd" not in str(info.value)


def test_network_error_is_unavailable_and_redacted(wire: Any) -> None:
    import requests

    wire["queue"] += [requests.ConnectionError("https://u:S3cretPassw0rd@host")]
    with pytest.raises(soap.SoapUnavailable) as info:
        soap.soap_call(settings(), "GetFolderRequest")
    assert "S3cretPassw0rd" not in str(info.value)


def test_http_500_without_soap_body_is_unavailable(wire: Any) -> None:
    wire["queue"] += [Resp(b"<html>oops</html>", 502)]
    with pytest.raises(soap.SoapUnavailable):
        soap.soap_call(settings(), "GetFolderRequest")


def test_redirect_is_refused(wire: Any) -> None:
    wire["queue"] += [Resp(b"", 302)]
    with pytest.raises(soap.SoapError, match="redirect"):
        soap.soap_call(settings(), "GetFolderRequest")


def test_oversized_response_is_refused(wire: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(soap, "MAX_SOAP_BYTES", 100)
    wire["queue"] += [Resp(b"x" * 1000)]
    with pytest.raises(soap.SoapError, match="size limit"):
        soap.soap_call(settings(), "GetFolderRequest")


def test_request_name_must_end_with_request() -> None:
    with pytest.raises(ValueError, match="Request"):
        soap.soap_call(settings(), "GetFolder")


def test_admin_endpoints_are_rejected_in_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from zimbra_mcp.server import Settings

    for bad in (
        "https://mail.example.test:7071/service/admin/soap",
        "https://mail.example.test/service/admin/soap",
        "http://mail.example.test/service/soap",
    ):
        monkeypatch.setenv("ZIMBRA_SOAP_URL", bad)
        with pytest.raises(ValueError, match="ZIMBRA_SOAP_URL"):
            Settings.from_env()
    monkeypatch.setenv("ZIMBRA_SOAP_URL", URL)
    assert Settings.from_env().soap_url == URL
