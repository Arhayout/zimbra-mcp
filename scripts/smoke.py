"""Read-only smoke test against a real Zimbra account. Run with the same ZIMBRA_* env vars.

    uv run python scripts/smoke.py

Only read tools are called. No write tool is invoked, so ZIMBRA_ALLOW_WRITE / ZIMBRA_ALLOW_SEND
are irrelevant (and are cleared here as a safeguard). Output shows counts and ids, never
message bodies, subjects, addresses or credentials.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any

os.environ.pop("ZIMBRA_ALLOW_WRITE", None)
os.environ.pop("ZIMBRA_ALLOW_SEND", None)

from zimbra_mcp import server  # noqa: E402
from zimbra_mcp.tools import account, contacts, events, mail, tasks  # noqa: E402

failures: list[str] = []


def step(name: str, call: Callable[[], Any], show: Callable[[Any], str]) -> Any:
    try:
        result = call()
    except Exception as error:  # report every failure instead of stopping at the first
        failures.append(name)
        print(f"FAIL {name}: {type(error).__name__}: {str(error)[:160]}")
        return None
    print(f"ok   {name}: {show(result)}")
    return result


def main() -> int:
    step("health_check(deep)", lambda: server.health_check(deep=True), lambda r: str(r["checks"]))
    step(
        "get_account_info",
        account.get_account_info,
        lambda r: f"quota_used={r['quota_used_bytes']}",
    )
    folders = step(
        "list_mail_folders",
        mail.list_mail_folders,
        lambda r: f"{r['backend']} backend, {len(r['folders'])} folders",
    )
    step("list_mail_tags", mail.list_mail_tags, lambda r: f"{len(r['tags'])} tags")
    found = step(
        "search_mail(limit=1)",
        lambda: server.search_mail("a", limit=1),
        lambda r: f"{len(r['results'])} result(s), has_more={r['has_more']}",
    )
    if found and found["results"]:
        uid = int(found["results"][0]["uid"])
        step("read_message", lambda: server.read_message(uid), lambda r: f"uid={r['uid']}")
    else:
        print("skip read_message: search returned nothing")
    step("list_calendars", events.list_calendars, lambda r: f"{len(r['calendars'])} calendars")
    step("list_address_books", contacts.list_address_books, lambda r: f"{len(r['address_books'])}")
    step("list_tasks", lambda: tasks.list_tasks(limit=1), lambda r: f"{len(r['tasks'])} task(s)")
    step(
        "list_calendar_events",
        lambda: server.list_calendar_events("2026-01-01", "2026-01-07"),
        lambda r: f"{len(r['events'])} events, skipped={r['skipped_unparseable']}",
    )
    if folders is None:
        print("note: list_attachments needs a SOAP message id; run search via SOAP to try it")
    print(f"\n{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
