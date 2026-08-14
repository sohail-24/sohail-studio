"""Small local JSON session store."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, session_id: str, payload: dict[str, Any]) -> None:
        document = {"updated_at": datetime.now(timezone.utc).isoformat(), **payload}
        path = self.root / f"{session_id}.json"
        path.write_text(json.dumps(document, indent=2, default=str) + "\n")

    def list_recent(self, limit: int = 8) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
            try:
                sessions.append(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
        return sessions
