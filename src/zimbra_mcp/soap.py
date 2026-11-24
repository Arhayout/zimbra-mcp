"""Minimal Zimbra JSON-SOAP client for the *user* endpoint (never the admin endpoint).

Payload shapes follow Zimbra's documented JSON-SOAP conventions but have NOT been verified
against a live server in this repository's CI; run ``scripts/smoke.py`` (read-only) against a
test account first.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import requests

from zimbra_mcp.server import Settings

MAIL_NS = "urn:zimbraMail"
ACCOUNT_NS = "urn:zimbraAccount"
MAX_SOAP_BYTES = 5 * 1024 * 1024
TOKEN_SKEW_SECONDS = 60
DEFAULT_LIFETIME_SECONDS = 3600
MAX_LIFETIME_SECONDS = 86_400
AUTH_FAULTS = {"service.AUTH_EXPIRED", "service.AUTH_REQUIRED"}


class SoapError(RuntimeError):
    """A Zimbra fault or malformed reply. ``code`` is the Zimbra error code."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


class SoapUnavailable(SoapError):
    """Network failure or HTTP 5xx without a fault body; callers may fall back to IMAP."""


_TOKENS: dict[tuple[str, str], tuple[str, float]] = {}
_LOCK = threading.Lock()


def clear_token_cache() -> None:
    with _LOCK:
        _TOKENS.clear()


def _post(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = requests.post(
            settings.soap_url,
            json=payload,
            headers={"Accept": "application/json"},
            timeout=settings.timeout,
            allow_redirects=False,
            stream=True,
        )
    except requests.RequestException as error:
        raise SoapUnavailable("network", type(error).__name__) from None

    with response:
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_SOAP_BYTES:
                raise SoapError("too_large", "SOAP response exceeds the size limit")
            chunks.append(chunk)
        status = response.status_code

    if 300 <= status < 400:
        raise SoapError("redirect", f"HTTP {status}; redirects are not followed")
    try:
        data = json.loads(b"".join(chunks))
        body = data["Body"]
    except (ValueError, KeyError, TypeError):
        if status >= 500:
            raise SoapUnavailable(f"HTTP {status}") from None
        raise SoapError("bad_response", f"HTTP {status}, not a SOAP JSON reply") from None

    fault = body.get("Fault") if isinstance(body, dict) else None
    if fault:
        code = (fault.get("Detail") or {}).get("Error", {}).get("Code", "unknown")
        reason = (fault.get("Reason") or {}).get("Text", "")
        raise SoapError(str(code), str(reason))
    if not isinstance(body, dict):
        raise SoapError("bad_response", "unexpected SOAP body")
    return body


def _token_value(raw: Any) -> str:
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, dict):
        raw = raw.get("_content")
    if not isinstance(raw, str) or not raw:
        raise SoapError("bad_response", "AuthResponse had no authToken")
    return raw


def _authenticate(settings: Settings) -> tuple[str, float]:
    body = _post(
        settings,
        {
            "Header": {"context": {"_jsns": "urn:zimbra"}},
            "Body": {
                "AuthRequest": {
                    "_jsns": ACCOUNT_NS,
                    "account": {"by": "name", "_content": settings.username},
                    "password": {"_content": settings.password},
                }
            },
        },
    )
    response = body.get("AuthResponse") or {}
    token = _token_value(response.get("authToken"))
    try:
        lifetime = int(response.get("lifetime", 0)) / 1000
    except (TypeError, ValueError):
        lifetime = 0
    if lifetime <= 0:
        lifetime = DEFAULT_LIFETIME_SECONDS
    lifetime = min(lifetime, MAX_LIFETIME_SECONDS)
    return token, time.monotonic() + lifetime


def _get_token(settings: Settings, *, force: bool = False) -> str:
    key = (settings.soap_url, settings.username)
    with _LOCK:
        cached = _TOKENS.get(key)
        if cached and not force and cached[1] - time.monotonic() > TOKEN_SKEW_SECONDS:
            return cached[0]
        token, expires = _authenticate(settings)
        _TOKENS[key] = (token, expires)
        return token


def soap_call(
    settings: Settings,
    request_name: str,
    body: dict[str, Any] | None = None,
    namespace: str = MAIL_NS,
) -> dict[str, Any]:
    """Send one authenticated request and return its ``<Name>Response`` dict.

    The token is cached per (endpoint, user), refreshed before expiry, and re-obtained once
    if the server reports it expired. Tokens are never logged or returned to the client.
    """
    if not settings.soap_url:
        raise ValueError("ZIMBRA_SOAP_URL is not configured (expected https://host/service/soap)")
    if not request_name.endswith("Request"):
        raise ValueError("request_name must end with 'Request'")

    for attempt in (0, 1):
        token = _get_token(settings, force=attempt == 1)
        payload = {
            "Header": {"context": {"_jsns": "urn:zimbra", "authToken": token}},
            "Body": {request_name: {"_jsns": namespace, **(body or {})}},
        }
        try:
            reply = _post(settings, payload)
        except SoapError as error:
            if error.code in AUTH_FAULTS and attempt == 0:
                with _LOCK:
                    _TOKENS.pop((settings.soap_url, settings.username), None)
                continue
            raise
        result = reply.get(request_name.removesuffix("Request") + "Response", {})
        return result if isinstance(result, dict) else {}
    raise SoapError("service.AUTH_REQUIRED", "authentication failed")  # pragma: no cover
