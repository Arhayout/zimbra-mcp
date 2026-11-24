from __future__ import annotations

import pytest

from zimbra_mcp.state import StateStore


@pytest.mark.asyncio
async def test_idempotency_survives_store_instances(tmp_path) -> None:
    path = str(tmp_path / "state.sqlite3")
    first = StateStore(path)
    await first.put_idempotency("request-1", {"status": "sent", "backend": "zimbra"})
    second = StateStore(path)
    assert await second.get_idempotency("request-1") == {"status": "sent", "backend": "zimbra"}
