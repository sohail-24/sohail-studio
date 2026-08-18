"""Data models for SpecificationAgent V1."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sohail_agent_cli.ai.models import AIStructuredOutput


@dataclass(slots=True, frozen=True)
class SpecificationDecision:
    """One PlanningAgent decision document loaded for specification generation."""

    filename: str
    topic: str
    content: str


@dataclass(slots=True, frozen=True)
class SpecificationInput:
    """Planning package content required by SpecificationGenerator."""

    plan_directory: Path
    tasks_markdown: str
    requirements_markdown: str
    architecture_markdown: str
    decisions: tuple[SpecificationDecision, ...] = ()
    project_goal: str | None = None

    @property
    def source_path(self) -> Path:
        """Backward-compatible source path alias."""
        return self.plan_directory


@dataclass(slots=True, frozen=True)
class Specification:
    """Structured product specification produced from AI Foundation output."""

    title: str
    summary: str
    product_spec: str
    features: tuple[str, ...]
    data_model: str
    api_spec: str
    non_functional: tuple[str, ...]
    source_items: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_ai_output(cls, output: AIStructuredOutput) -> Specification:
        """Convert validated AI output into the Specification dataclass."""
        metadata = output.metadata
        return cls(
            title=output.title,
            summary=output.summary,
            product_spec=_as_text(
                metadata.get("product_spec"),
                fallback=output.summary,
            ),
            features=_as_tuple(
                metadata.get("features"),
                fallback=output.items,
            ),
            data_model=_as_text(
                metadata.get("data_model"),
                fallback="No data model details were provided by the AI response.",
            ),
            api_spec=_as_text(
                metadata.get("api_spec"),
                fallback="No API details were provided by the AI response.",
            ),
            non_functional=_as_tuple(
                metadata.get("non_functional"),
                fallback=("No non-functional requirements were provided by the AI response.",),
            ),
            source_items=output.items,
            metadata=metadata,
        )


@dataclass(slots=True, frozen=True)
class SpecificationOutput:
    """Output returned by SpecificationGenerator."""

    specification: Specification | None = None
    warnings: tuple[str, ...] = ()

    @property
    def document(self) -> Specification | None:
        """Backward-compatible document alias."""
        return self.specification

    @property
    def is_empty(self) -> bool:
        """Return True when no specification was produced."""
        return self.specification is None


@dataclass(slots=True, frozen=True)
class SpecificationWriteTarget:
    """Resolved specification file target."""

    path: Path
    content: str


def _as_text(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, list | tuple):
        items = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(f"- {item}" for item in items) if items else fallback
    if isinstance(value, dict):
        lines = [
            f"- **{key}:** {item}"
            for key, item in value.items()
            if str(item).strip()
        ]
        return "\n".join(lines) if lines else fallback
    return str(value).strip() or fallback


def _as_tuple(value: Any, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return fallback
    if isinstance(value, str):
        items = [item.strip(" -") for item in value.splitlines() if item.strip(" -")]
        return tuple(items) or fallback
    if isinstance(value, list | tuple):
        items = tuple(str(item).strip() for item in value if str(item).strip())
        return items or fallback
    return (str(value).strip(),) if str(value).strip() else fallback
