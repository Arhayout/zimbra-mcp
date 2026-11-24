"""Read-only account information (user endpoint only; no preference or admin access)."""

from __future__ import annotations

from typing import Any

from zimbra_mcp import server as core
from zimbra_mcp import soap
from zimbra_mcp.server import Settings
from zimbra_mcp.tools import _common as c


@core.mcp.tool()
@core._tool("get_account_info")
def get_account_info() -> dict[str, Any]:
    """Return non-sensitive account facts: display name, quota use and server version."""
    settings = Settings.from_env()
    c.require_soap(settings)
    reply = soap.soap_call(
        settings, "GetInfoRequest", {"sections": "mbox"}, namespace=soap.ACCOUNT_NS
    )
    return {
        "name": core._clean(reply.get("name", ""), 200),
        "display_name": core._clean(
            reply.get("attrs", {}).get("_attrs", {}).get("displayName", ""), 200
        ),
        "quota_used_bytes": reply.get("used"),
        "version": core._clean(reply.get("version", ""), 100),
        "lifetime_seconds": int(reply.get("lifetime", 0)) // 1000
        if reply.get("lifetime")
        else None,
    }
