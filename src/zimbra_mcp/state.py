from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class StateStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path).expanduser()
        self._lock = asyncio.Lock()

    async def get_idempotency(self, key: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_idempotency_sync, key)

    async def put_idempotency(self, key: str, response: Mapping[str, Any]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._put_idempotency_sync, key, dict(response))

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS idempotency "
            "(key TEXT PRIMARY KEY, response_json TEXT NOT NULL, "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        connection.commit()
        return connection

    def _get_idempotency_sync(self, key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM idempotency WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        return dict(value) if isinstance(value, Mapping) else None

    def _put_idempotency_sync(self, key: str, response: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO idempotency(key, response_json) VALUES (?, ?)",
                (key, json.dumps(response, separators=(",", ":"))),
            )
            connection.commit()
