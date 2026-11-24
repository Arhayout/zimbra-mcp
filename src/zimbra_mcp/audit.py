from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Mapping
from typing import Any

_logger = logging.getLogger("zimbra_mcp.audit")
_counts: Counter[str] = Counter()


def record(tool: str, status: str, **metadata: str | int | bool) -> None:
    _counts[f"{tool}.{status}"] += 1
    safe = {
        key: value for key, value in metadata.items() if key not in {"body", "password", "token"}
    }
    _logger.info(json.dumps({"tool": tool, "status": status, **safe}, sort_keys=True))


def snapshot() -> Mapping[str, int]:
    return dict(_counts)


def reset() -> None:
    _counts.clear()


def redact_result(result: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key not in {"password", "authToken"}}
