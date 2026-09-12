"""Append-only audit log of every tool call (JSON Lines).

The strategy report requires real-time audit logging at the gateway so CIOs
and CFOs can see exactly what an AI agent did on whose behalf.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

_lock = threading.Lock()


def audit_path() -> Path:
    default = Path(__file__).resolve().parents[2] / "logs" / "audit.jsonl"
    return Path(os.environ.get("BIZPLAY_AUDIT_LOG", default))


def record(user_id: str, tool: str, arguments: dict, outcome: str, detail: str = "", *,
           via: str = "env") -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user_id": user_id,
        "via": via,  # bearer | env (how the caller was identified)
        "tool": tool,
        "arguments": arguments,
        "outcome": outcome,  # ok | denied | error
        "detail": detail,
    }
    path = audit_path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def tail(limit: int = 100) -> list[dict]:
    """Most recent audit entries, newest first."""
    path = audit_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(entries) >= limit:
            break
    return entries
