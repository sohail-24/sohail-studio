"""Planning and specification package loader for BlueprintAgent V1."""

from __future__ import annotations

import re
from pathlib import Path

from sohail_agent_cli.bootstrap.validator import PlanningValidator

from .models import BlueprintDecision, BlueprintInput


class BlueprintLoader:
    """Read and validate PlanningAgent and SpecificationAgent output."""

    REQUIRED_SPECIFICATION_FILES = (
        "PRODUCT_SPEC.md",
        "FEATURES.md",
        "DATA_MODEL.md",
        "API_SPEC.md",
        "NON_FUNCTIONAL.md",
    )

    def __init__(self, validator: PlanningValidator | None = None) -> None:
        self.validator = validator or PlanningValidator()

    def load(self, plan_directory: Path, specification_directory: Path) -> BlueprintInput:
        """Load planning and specification packages into a typed input dataclass."""
        plan_directory = plan_directory.resolve()
        specification_directory = specification_directory.resolve()
        self.validator.validate(plan_directory)
        self._validate_specification_directory(specification_directory)

        requirements = self._read(plan_directory / "REQUIREMENTS.md")
        architecture = self._read(plan_directory / "ARCHITECTURE.md")
        tasks = self._read(plan_directory / "TASK.md")
        decisions = self._load_decisions(plan_directory / "decisions")

        return BlueprintInput(
            plan_directory=plan_directory,
            specification_directory=specification_directory,
            tasks_markdown=tasks,
            requirements_markdown=requirements,
            architecture_markdown=architecture,
            product_spec_markdown=self._read(specification_directory / "PRODUCT_SPEC.md"),
            features_markdown=self._read(specification_directory / "FEATURES.md"),
            data_model_markdown=self._read(specification_directory / "DATA_MODEL.md"),
            api_spec_markdown=self._read(specification_directory / "API_SPEC.md"),
            non_functional_markdown=self._read(specification_directory / "NON_FUNCTIONAL.md"),
            decisions=decisions,
            project_goal=self._extract_project_goal(requirements),
        )

    def _load_decisions(self, decision_directory: Path) -> tuple[BlueprintDecision, ...]:
        decisions: list[BlueprintDecision] = []
        for path in sorted(decision_directory.glob("*.md")):
            topic = re.sub(r"^\d+_", "", path.stem)
            decisions.append(
                BlueprintDecision(
                    filename=path.name,
                    topic=topic,
                    content=self._read(path),
                )
            )
        return tuple(decisions)

    def _validate_specification_directory(self, specification_directory: Path) -> None:
        if not specification_directory.exists():
            raise ValueError(f"Specification package not found: {specification_directory}")

        if not specification_directory.is_dir():
            raise ValueError(f"Expected a directory: {specification_directory}")

        for filename in self.REQUIRED_SPECIFICATION_FILES:
            file_path = specification_directory / filename
            if not file_path.exists():
                raise ValueError(f"Missing required specification file: {filename}")
            if not file_path.is_file():
                raise ValueError(f"Expected specification file: {filename}")

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
