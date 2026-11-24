# Zimba MCP

Zimba MCP is a Python 3.12 MCP server for Zimbra mail. It uses Zimbra `/service/soap` as the primary backend and falls back to IMAP/SMTP when SOAP is unavailable.

## Verified baseline

- FastMCP: **4.2.0**, the current stable PyPI release at project creation.
- MCP: **2026-07-28**, the current stateless specification.
- Transports: stdio and Streamable HTTP. HTTP runs in FastMCP stateless mode.

MCP is the Model Context Protocol: a standard JSON-RPC interface that lets clients discover and call tools exposed by a server. Stdio is used by local clients such as Claude Desktop. Streamable HTTP is used by network clients and sends requests to one MCP endpoint.

## Setup

```bash
uv sync
cp .env.example .env
# edit .env with your Zimbra and IMAP/SMTP values
uv run zimbra-mcp --transport stdio
```

Secrets are read only from environment variables. They are not logged. Do not commit `.env`.

## Configuration

`ZIMBRA_URL`, `ZIMBRA_USERNAME`, and `ZIMBRA_PASSWORD` configure SOAP. `IMAP_HOST`, `IMAP_PORT`, `IMAP_SSL`, `SMTP_HOST`, `SMTP_PORT`, and `SMTP_SSL` configure the fallback. SOAP uses a pooled async `httpx` client and caches its auth token. A 401/403 response clears the token and retries authentication once.

Sending is disabled by default. Set `ZIMBRA_ENABLE_SEND=true` to enable `send_mail`. Every send requires an idempotency key. Results are persisted in the SQLite database at `ZIMBA_STATE_DB` and also become the SMTP `Message-ID` / Zimbra message identifier. The database stores result metadata only, never credentials or message bodies.

## Tools

- `search_mail(query, limit=20)` searches Zimbra and falls back to IMAP.
- `read_message(message_id)` reads from Zimbra and falls back to IMAP.
- `send_mail(to, subject, body, idempotency_key)` is guarded by `ZIMBRA_ENABLE_SEND`.
- `list_mail_folders()` and `create_mail_folder(name, parent_id)` manage folders.
- `list_mail_tags()` and `create_mail_tag(name, color)` manage tags.
- `save_draft(to, subject, body, draft_id)` saves a draft without sending it.
- `list_attachments(message_id)` returns attachment metadata without file bytes.
- `bulk_mail_action(...)` supports bounded read, flag, delete, move, and tag actions.
- `list_calendar_events(start, end, limit=50)` lists events using Zimbra, then CalDAV.
- `read_calendar_event(event_id)` reads an event using Zimbra, then CalDAV.
- `get_free_busy(start, end, emails)` reads Zimbra free/busy intervals.
- `search_contacts(query, limit=50)` searches contacts.
- `save_contact(fields, folder_id="7", contact_id)` creates or updates a contact when writes are enabled.
- `delete_contact(contact_id, confirm)` deletes a contact with explicit confirmation.
- `list_tasks(query="in:Tasks", limit=50)` lists tasks.
- `save_task(fields, folder_id="15", task_id)` creates or updates a task when writes are enabled.
- `delete_task(task_id, confirm)` deletes a task with explicit confirmation.
- `list_briefcase(limit=100)` lists Briefcase metadata without file bytes.
- `get_preferences()` reads account preferences.
- `update_preferences(preferences)` updates preferences with write access.
- `get_quota()` reads mailbox quota usage.
- `list_shares()` reads visible share information.
- `change_share(folder_id, grantee, rights, revoke, confirm)` changes sharing with confirmation.
- `save_briefcase_document(...)` and `delete_briefcase_document(...)` manage text documents with write access.
- `audit_metrics()` returns secret-free process-local counters.
- `health_check()` reports enabled capabilities without revealing secrets.
- `admin_status()` is disabled unless `ZIMBRA_ENABLE_ADMIN=true`.
- `admin_account_info(email)` and `admin_list_accounts(domain, limit=100)` use a separate admin SOAP token and are disabled by default.
- `admin_create_account`, `admin_modify_account`, and `admin_delete_account` require admin access and confirmation.

Bulk actions are limited to 50 message IDs. Delete and move require `confirm=true`.
Folder creation, tag creation, draft saving, and all bulk actions also require
`ZIMBRA_ENABLE_WRITE=true`.
Advanced Stage 1 operations use the Zimbra SOAP backend and fail closed if it is unavailable.
Calendar tools are read-only in Stage 2. Set `CALDAV_URL` when the server's CalDAV path
differs from the default `/dav/{username}/Calendar` path.

Contacts, tasks, Briefcase, preferences, quota, and shares are read-only in this release.
`ZIMBRA_ENABLE_WRITE` is reserved for future guarded write tools. Administrator access is
separately gated by `ZIMBRA_ENABLE_ADMIN`, authenticates against `/service/admin/soap`, and
should only be enabled with an administrator credential and network controls. Audit metrics are process-local and never contain passwords,
auth tokens, or message bodies.

## Claude Desktop

Build the environment once with `uv sync`, then add this entry to Claude Desktop's MCP configuration. Replace the working directory if the project is elsewhere.

```json
{
  "mcpServers": {
    "zimba": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/home/ubuntu/zimbra-mcp",
        "zimbra-mcp",
        "--transport",
        "stdio"
      ],
      "env": {
        "ZIMBRA_URL": "https://mail.example.com",
        "ZIMBRA_USERNAME": "user@example.com",
        "ZIMBRA_PASSWORD": "replace-me",
        "IMAP_HOST": "mail.example.com",
        "SMTP_HOST": "mail.example.com",
        "ZIMBRA_ENABLE_SEND": "false"
      }
    }
  }
}
```

For Streamable HTTP:

```bash
uv run zimbra-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

The MCP endpoint is served by FastMCP at `/mcp`. Protect remote deployments with network access controls and TLS termination.

For deployment, `Dockerfile` runs the stateless HTTP transport on port 8000. Keep the
container behind TLS and an authenticated reverse proxy. The default local CLI bind is
`127.0.0.1`; do not expose it directly to an untrusted network.

## Development

```bash
uv run ruff check .
uv run mypy
uv run pytest
```

`make check` runs the same quality gate. CI is defined in `.github/workflows/ci.yml`.

Tests mock SOAP and IMAP/SMTP boundaries; they never require a live mailbox.
