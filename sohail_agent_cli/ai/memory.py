"""Serializable lightweight engineering memory."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .exceptions import AIMemoryError


@dataclass(slots=True, frozen=True)
class MemoryEntry:
    """One durable memory entry."""

    category: str
    key: str
    value: Any
    source: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(slots=True)
class ProjectMemory:
    """Serializable project memory reused by future AI subsystems."""

    entries: list[MemoryEntry] = field(default_factory=list)

    def add(self, category: str, key: str, value: Any, source: str) -> None:
        """Add a memory entry."""
        self.entries.append(
            MemoryEntry(category=category, key=key, value=value, source=source)
        )

    def by_category(self, category: str) -> tuple[MemoryEntry, ...]:
        """Return entries matching a category."""
        return tuple(entry for entry in self.entries if entry.category == category)

    def to_dict(self) -> dict[str, Any]:
        """Serialize memory to a plain dictionary."""
        return {"entries": [asdict(entry) for entry in self.entries]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectMemory:
        """Load memory from a plain dictionary."""
        entries = [
            MemoryEntry(
                category=item["category"],
                key=item["key"],
                value=item["value"],
                source=item["source"],
                timestamp=item.get("timestamp")
                or datetime.now(timezone.utc).isoformat(),
            )
            for item in data.get("entries", [])
        ]
        return cls(entries=entries)

    def save(self, path: Path) -> None:
        """Persist memory as JSON."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            raise AIMemoryError(str(exc)) from exc

    @classmethod
    def load(cls, path: Path) -> ProjectMemory:
        """Load memory from JSON."""
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            raise AIMemoryError(str(exc)) from exc
