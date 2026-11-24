"""Importing this package registers the SOAP-backed tools on the shared FastMCP instance."""

from zimbra_mcp.tools import account, contacts, events, mail, tasks

__all__ = ["account", "contacts", "events", "mail", "tasks"]
