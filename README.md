# zimbra-mcp

Minimal FastMCP stdio server for Zimbra-compatible mail and calendar services.

## Features

- Search mail and read messages through IMAP over TLS.
- Send plain-text email through authenticated SMTP STARTTLS.
- List events from a CalDAV calendar (read-only).
- Email bodies are returned as untrusted data with explicit delimiters.

## Setup

Requires Python 3.11+ and a Zimbra CalDAV collection URL.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

Set these environment variables in the MCP client's server configuration; secrets are never read from files:

| Variable | Required | Default |
| --- | --- | --- |
| `ZIMBRA_IMAP_HOST` | Yes | — |
| `ZIMBRA_IMAP_PORT` | No | `993` |
| `ZIMBRA_SMTP_HOST` | Yes | — |
| `ZIMBRA_SMTP_PORT` | No | `587` |
| `ZIMBRA_USERNAME` | Yes | — |
| `ZIMBRA_PASSWORD` | Yes | — |
| `ZIMBRA_CALDAV_URL` | Yes | — |
| `ZIMBRA_TIMEOUT` | No | `30` seconds |

## Tools

- `search_mail(query, folder="INBOX", limit=20)` — search message text, capped at 100 results.
- `read_message(uid, folder="INBOX")` — read without changing the seen flag.
- `send_email(to, subject, body)` — send plain text via STARTTLS.
- `list_calendar_events(start_date, end_date)` — read a date range up to 366 days.

Configure the server command as `zimbra-mcp`; MCP uses stdio. Grant the account only the access it needs.

## Checks

```sh
pytest
ruff check .
mypy
```
