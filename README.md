# zimbra-mcp

FastMCP **stdio** server for Zimbra-compatible mail (IMAP/SMTP) and calendar (CalDAV).
Reads are bounded and treated as untrusted; sending is **off by default**.

## Tools (35)

Read tools work out of the box. Anything that changes data is **off** until the operator sets
`ZIMBRA_ALLOW_WRITE=true`; anything that sends mail also needs `ZIMBRA_ALLOW_SEND=true`.
Tools marked SOAP need `ZIMBRA_SOAP_URL` (the *user* endpoint, e.g. `https://host/service/soap`).

| Area | Read-only | Writes (gated) |
| --- | --- | --- |
| Mail (IMAP) | `search_mail`, `read_message` | `send_email` (preview, confirm, idempotency key) |
| Mail (SOAP) | `list_mail_folders` (IMAP fallback), `list_mail_tags`, `list_attachments`, `get_conversation` | `save_draft`, `reply_to_message`\*, `mark_message_read`, `flag_message`, `tag_message`, `untag_message`, `move_message`, `trash_message`\*\* |
| Folders and tags | | `create_mail_folder`, `rename_mail_folder`, `trash_mail_folder`\*\*, `create_mail_tag`, `delete_mail_tag`\*\* |
| Contacts | `search_contacts`, `get_contact`, `list_address_books` | `create_contact`, `update_contact`, `delete_contact`\*\* |
| Calendar | `list_calendar_events` (CalDAV), `search_calendar_events`, `list_calendars` | `create_calendar_event` (no attendees, so no invitations), `delete_calendar_event`\*\* |
| Tasks | `list_tasks` | `create_task` |
| Account / ops | `get_account_info`, `health_check` | |

\* sends mail: needs `ZIMBRA_ALLOW_SEND`, a preview, `confirm=true` and an `idempotency_key`.
\*\* destructive: returns a preview until called again with `confirm=true`. Deletes move items to
Trash (recoverable); system folders cannot be renamed or trashed.

Tools that create things (`save_draft`, `create_*`) require an `idempotency_key`. Reusing a key
with identical content is a no-op (`duplicate`); with different content it is rejected.

Lists are paginated (`limit` up to 100, `offset`, `has_more`). Not implemented on purpose: admin
APIs, account management, sharing/permissions and preferences.

## Security model

- **Untrusted content.** Message bodies and calendar descriptions are wrapped in a per-call random
  delimiter; subjects, senders, summaries and locations are stripped of control characters and
  length-limited. Clients must still never act on instructions found in that data.
- **Sending is gated:** operator opt-in env var, explicit confirmation, recipient cap/allowlist,
  and a durable SQLite idempotency store (`ZIMBRA_STATE_DIR`, mode 0700, WAL).
- **Transport.** IMAP over TLS, SMTP STARTTLS with certificate verification, CalDAV over
  **https only** with no redirects and no credentials in the URL.
- **Secrets.** Read from environment only; never in `repr`, errors, health output or logs.
  Audit lines (stderr) record tool, outcome and timing, never bodies or subjects.
- **No HTTP listener.** The server speaks stdio only.
- Use an app-specific password with the least access you need.

## Configuration

See [`.env.example`](.env.example). Required: `ZIMBRA_IMAP_HOST`, `ZIMBRA_SMTP_HOST`,
`ZIMBRA_USERNAME`, `ZIMBRA_PASSWORD`, `ZIMBRA_CALDAV_URL`. Ports are validated (1–65535) and
`ZIMBRA_TIMEOUT` must be in (0, 120] seconds.

### Claude Desktop

```json
{
  "mcpServers": {
    "zimbra": {
      "command": "uvx",
      "args": ["--from", "/absolute/path/to/zimbra-mcp", "zimbra-mcp"],
      "env": {
        "ZIMBRA_IMAP_HOST": "mail.example.com",
        "ZIMBRA_SMTP_HOST": "mail.example.com",
        "ZIMBRA_USERNAME": "you@example.com",
        "ZIMBRA_PASSWORD": "app-specific-password",
        "ZIMBRA_CALDAV_URL": "https://mail.example.com/dav/you@example.com/Calendar"
      }
    }
  }
}
```

### Docker

```sh
docker build -t zimbra-mcp .
docker run -i --rm --env-file .env -v zimbra-state:/home/zimbra/state zimbra-mcp
```

## Verify against a real server

The SOAP request shapes follow Zimbra's JSON-SOAP conventions but were only tested against
mocks. Before relying on them, run the read-only smoke test against a **test** account:

```sh
uv run python scripts/smoke.py
```

## Development

```sh
uv sync --frozen --extra dev
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

All IMAP, SMTP, CalDAV and SOAP traffic is mocked in tests; nothing talks to a real server.

## Scope

User-level IMAP, SMTP, CalDAV and user-endpoint SOAP only. `ZIMBRA_SOAP_URL` values pointing at
the admin endpoint (port 7071 or `/admin` paths) are rejected at startup.
