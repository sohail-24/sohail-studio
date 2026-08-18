"""Data models for StackGenerator V1."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True, frozen=True)
class StackPlan:
    """Technology choices loaded from a PlanningAgent package."""

    plan_directory: Path
    frontend: str | None = None
    backend: str | None = None
    database: str | None = None

    def has_any_stack(self) -> bool:
        """Return True when at least one stack component is selected."""
        return any((self.frontend, self.backend, self.database))


@dataclass(slots=True, frozen=True)
class StackSelection:
    """Normalized stack choices selected for skeleton generation."""

    frontend: str | None = None
    backend: str | None = None
    database: str | None = None


@dataclass(slots=True, frozen=True)
class StackSkeleton:
    """Generated technology-stack file map."""

    files: OrderedDict[Path, str] = field(default_factory=OrderedDict)

    def validate(self) -> None:
        """Validate generated paths and content before writing."""
        if not self.files:
            raise ValueError("Stack skeleton contains no files")

        for path, content in self.files.items():
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Stack output path must be relative: {path}")
            if content and not content.endswith("\n"):
                raise ValueError(f"Stack output needs a trailing newline: {path}")


@dataclass(slots=True, frozen=True)
class StackWriteTarget:
    """Resolved write target for one generated file."""

    relative_path: Path
    target_path: Path
    content: str
