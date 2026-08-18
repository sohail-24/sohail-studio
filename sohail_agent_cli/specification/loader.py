"""Planning-package loader for SpecificationAgent V1."""

from __future__ import annotations

import re
from pathlib import Path

from sohail_agent_cli.bootstrap.validator import PlanningValidator

from .models import SpecificationDecision, SpecificationInput


class SpecificationLoader:
    """Read and validate PlanningAgent output for specification generation."""

    def __init__(self, validator: PlanningValidator | None = None) -> None:
        self.validator = validator or PlanningValidator()

    def load(self, plan_directory: Path) -> SpecificationInput:
        """Load a planning package into a strongly typed input dataclass."""
        plan_directory = plan_directory.resolve()
        self.validator.validate(plan_directory)

        requirements = self._read(plan_directory / "REQUIREMENTS.md")
        architecture = self._read(plan_directory / "ARCHITECTURE.md")
        tasks = self._read(plan_directory / "TASK.md")
        decisions = self._load_decisions(plan_directory / "decisions")

        return SpecificationInput(
            plan_directory=plan_directory,
            tasks_markdown=tasks,
            requirements_markdown=requirements,
            architecture_markdown=architecture,
            decisions=decisions,
            project_goal=self._extract_project_goal(requirements),
        )

    def _load_decisions(self, decision_directory: Path) -> tuple[SpecificationDecision, ...]:
        decisions: list[SpecificationDecision] = []
        for path in sorted(decision_directory.glob("*.md")):
            topic = re.sub(r"^\d+_", "", path.stem)
            decisions.append(
                SpecificationDecision(
                    filename=path.name,
                    topic=topic,
                    content=self._read(path),
                )
            )
        return tuple(decisions)

    @staticmethod
    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8").strip()

    @staticmethod
    def _extract_project_goal(requirements_markdown: str) -> str | None:
        match = re.search(
            r"^## Project Goal\s*\n+(.*?)(?=\n## |\Z)",
            requirements_markdown,
            flags=re.MULTILINE | re.DOTALL,
        )
        return match.group(1).strip() if match else None
