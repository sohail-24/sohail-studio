"""Dataclasses used by the AI orchestration foundation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True, frozen=True)
class ProjectContext:
    """Normalized project context built from persistent planning files."""

    goal: str
    project_name: str
    frontend: str | None = None
    backend: str | None = None
    database: str | None = None
    deployment: str | None = None
    decisions: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    source: str = "project-plan"

    def to_prompt_data(self) -> dict[str, Any]:
        """Return prompt-safe serializable context."""
        return {
            "goal": self.goal,
            "project_name": self.project_name,
            "frontend": self.frontend,
            "backend": self.backend,
            "database": self.database,
            "deployment": self.deployment,
            "decisions": list(self.decisions),
            "assumptions": list(self.assumptions),
            "source": self.source,
        }


@dataclass(slots=True, frozen=True)
class PromptTemplate:
    """Versioned reusable prompt template."""

    name: str
    version: str
    system: str
    user: str
    required_fields: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class AIRequest:
    """Validated request passed to the AI orchestrator."""

    task: str
    prompt_name: str | None = None
    context: ProjectContext | None = None
    instruction: str = ""
    required_fields: tuple[str, ...] = ("kind", "title", "summary", "items")
    allowed_kinds: tuple[str, ...] = (
        "planning",
        "specification",
        "blueprint",
        "feature",
        "documentation",
        "entities",
    )
    model: str | None = None
    max_retries: int = 1


@dataclass(slots=True, frozen=True)
class AIStructuredOutput:
    """Structured output returned by the AI layer."""

    kind: str
    title: str
    summary: str
    items: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class AIExecutionMetadata:
    """Execution metadata captured for memory and diagnostics."""

    provider: str
    prompt_name: str
    prompt_version: str
    attempts: int
    model: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(slots=True, frozen=True)
class AIResult:
    """Final dataclass result returned by the orchestrator."""

    output: AIStructuredOutput
    metadata: AIExecutionMetadata
