"""Bootstrap planning package loader."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class BootstrapPlan:
    """
    Represents a loaded PlanningAgent package.

    This object is passed through the Bootstrap pipeline.
    """

    plan_directory: Path
    requirements: str
    architecture: str
    tasks: str
    decisions: dict[str, str] = field(default_factory=dict)


class PlanningLoader:
    """
    Loads a PlanningAgent package from disk.

    Expected structure:

    project-plan/
        REQUIREMENTS.md
        ARCHITECTURE.md
        TASK.md
        decisions/
    """

    REQUIRED_FILES = (
        "REQUIREMENTS.md",
        "ARCHITECTURE.md",
        "TASK.md",
    )

    def load(self, plan_directory: Path) -> BootstrapPlan:
        """
        Load a planning package into memory.
        """

        plan_directory = plan_directory.resolve()

        requirements = self._read_file(
            plan_directory / "REQUIREMENTS.md"
        )

        architecture = self._read_file(
            plan_directory / "ARCHITECTURE.md"
        )

        tasks = self._read_file(
            plan_directory / "TASK.md"
        )

        decisions = self._load_decisions(
            plan_directory / "decisions"
        )

        return BootstrapPlan(
            plan_directory=plan_directory,
            requirements=requirements,
            architecture=architecture,
            tasks=tasks,
            decisions=decisions,
        )

    def _load_decisions(
        self,
        decision_directory: Path,
    ) -> dict[str, str]:
        """
        Load every ADR / decision document.
        """

        if not decision_directory.exists():
            return {}

        decisions: dict[str, str] = {}

        for file in sorted(decision_directory.glob("*.md")):
            decisions[file.stem] = self._read_file(file)

        return decisions

    @staticmethod
    def _read_file(path: Path) -> str:
        """
        Read a UTF-8 text file.
        """

        return path.read_text(
            encoding="utf-8"
        ).strip()