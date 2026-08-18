"""Data models for BlueprintAgent V1."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sohail_agent_cli.ai.models import AIStructuredOutput


@dataclass(slots=True, frozen=True)
class BlueprintDecision:
    """One PlanningAgent decision document loaded for blueprint generation."""

    filename: str
    topic: str
    content: str


@dataclass(slots=True, frozen=True)
class BlueprintInput:
    """Planning and specification package content required by BlueprintGenerator."""

    plan_directory: Path
    specification_directory: Path
    tasks_markdown: str
    requirements_markdown: str
    architecture_markdown: str
    product_spec_markdown: str
    features_markdown: str
    data_model_markdown: str
    api_spec_markdown: str
    non_functional_markdown: str
    decisions: tuple[BlueprintDecision, ...] = ()
    project_goal: str | None = None

    @property
    def source_path(self) -> Path:
        """Backward-compatible source path alias."""
        return self.plan_directory


@dataclass(slots=True, frozen=True)
class Blueprint:
    """Structured blueprint produced from AI Foundation output."""

    title: str
    summary: str
    system_design: str
    backend_architecture: str
    frontend_architecture: str
    database_design: str
    api_flow: str
    implementation_plan: str
    folder_structure: str
    dependencies: str
    source_items: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_ai_output(cls, output: AIStructuredOutput) -> Blueprint:
        """Convert validated AI output into the Blueprint dataclass."""
        metadata = output.metadata
        return cls(
            title=output.title,
            summary=output.summary,
            system_design=_as_text(
                metadata.get("system_design"),
                fallback=output.summary,
            ),
            backend_architecture=_as_text(
                metadata.get("backend_architecture"),
                fallback="No backend architecture details were provided by the AI response.",
            ),
            frontend_architecture=_as_text(
                metadata.get("frontend_architecture"),
                fallback="No frontend architecture details were provided by the AI response.",
            ),
            database_design=_as_text(
                metadata.get("database_design"),
                fallback="No database design details were provided by the AI response.",
            ),
            api_flow=_as_text(
                metadata.get("api_flow"),
                fallback="No API flow details were provided by the AI response.",
            ),
            implementation_plan=_as_text(
                metadata.get("implementation_plan"),
                fallback="No implementation plan was provided by the AI response.",
            ),
            folder_structure=_as_text(
                metadata.get("folder_structure"),
                fallback="No folder structure was provided by the AI response.",
            ),
            dependencies=_as_text(
                metadata.get("dependencies"),
                fallback="No dependencies were provided by the AI response.",
            ),
            source_items=output.items,
            metadata=metadata,
        )


@dataclass(slots=True, frozen=True)
class BlueprintOutput:
    """Output returned by BlueprintGenerator."""

    blueprint: Blueprint | None = None
    warnings: tuple[str, ...] = ()

    @property
    def document(self) -> Blueprint | None:
        """Backward-compatible document alias."""
        return self.blueprint

    @property
    def is_empty(self) -> bool:
        """Return True when no blueprint was produced."""
        return self.blueprint is None


@dataclass(slots=True, frozen=True)
class BlueprintWriteTarget:
    """Resolved blueprint file target."""

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
