# zimbra-mcp

FastMCP **stdio** server for Zimbra-compatible mail (IMAP/SMTP) and calendar (CalDAV).
Reads are bounded and treated as untrusted; sending is **off by default**.

## Tools

| Tool | Purpose |
| --- | --- |
| `search_mail(query, folder="INBOX", limit=20, offset=0)` | One page of metadata, newest first; returns `has_more` / `next_offset`. Max 100 per page, offset ≤ 500. |
| `read_message(uid, folder="INBOX")` | Does not mark as seen. Body capped at 20 000 chars (`body_truncated`), attachment *metadata only*. |
| `send_email(to, subject, body, confirm=False, idempotency_key="")` | Needs `ZIMBRA_ALLOW_SEND=true`. First call returns a preview; resend with `confirm=true` and a unique key. Max 5 recipients, optional allowlist, duplicate keys never resend. |
| `list_calendar_events(start_date, end_date, time_zone="UTC", max_events=100)` | Read-only CalDAV `REPORT` with recurrence expansion. Local-date range ≤ 366 days, max 500 events, 5 MB response cap. |
| `health_check(deep=False)` | Config summary and call metrics; `deep=true` also tests IMAP login and CalDAV `OPTIONS`. |

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

## Development

```sh
uv sync --frozen --extra dev
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

All IMAP, SMTP and CalDAV traffic is mocked in tests; nothing talks to a real server.

## Scope

This server implements IMAP/SMTP/CalDAV only. It does **not** use the Zimbra SOAP or admin APIs,
so there are no admin or mutation tools beyond gated `send_email`.
