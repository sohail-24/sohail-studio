"""PlanningAgent package loader for StackGenerator V1."""

from __future__ import annotations

import re
from pathlib import Path

from .models import StackPlan


class StackPlanError(Exception):
    """Raised when a planning package cannot be loaded for stack generation."""


class StackPlanLoader:
    """
    Load frontend, backend, and database decisions from PlanningAgent output.

    The loader intentionally reads accepted decision documents instead of scraping
    arbitrary architecture prose. This keeps StackGenerator coupled to the
    PlanningAgent memory format, not to wording inside summary files.
    """

    REQUIRED_FILES = (
        "REQUIREMENTS.md",
        "ARCHITECTURE.md",
        "TASK.md",
    )

    TOPICS = {
        "frontend": "frontend",
        "backend": "backend",
        "database": "database",
    }

    def load(self, plan_directory: Path) -> StackPlan:
        """Load stack choices from a planning package."""
        plan_directory = plan_directory.resolve()
        self._validate_plan_directory(plan_directory)

        choices: dict[str, str] = {}
        for decision_file in sorted((plan_directory / "decisions").glob("*.md")):
            topic = self._topic_from_file(decision_file)
            if topic not in self.TOPICS:
                continue

            decision = self._read_decision(decision_file)
            if decision and decision.lower() not in {"none", "undecided"}:
                choices[self.TOPICS[topic]] = decision

        plan = StackPlan(
            plan_directory=plan_directory,
            frontend=choices.get("frontend"),
            backend=choices.get("backend"),
            database=choices.get("database"),
        )
        if not plan.has_any_stack():
            raise StackPlanError("No supported stack decisions were found in the planning package")
        return plan

    def _validate_plan_directory(self, plan_directory: Path) -> None:
        if not plan_directory.exists():
            raise StackPlanError(f"Planning package not found: {plan_directory}")
        if not plan_directory.is_dir():
            raise StackPlanError(f"Expected planning package directory: {plan_directory}")

        for filename in self.REQUIRED_FILES:
            if not (plan_directory / filename).is_file():
                raise StackPlanError(f"Missing required planning file: {filename}")

        decisions = plan_directory / "decisions"
        if not decisions.is_dir():
            raise StackPlanError("Missing decisions directory")

    @staticmethod
    def _topic_from_file(path: Path) -> str:
        """Infer the decision topic from a PlanningAgent decision filename."""
        stem = path.stem.lower()
        return re.sub(r"^\d+_", "", stem)

    @staticmethod
    def _read_decision(path: Path) -> str:
        """Read the body of the `## Decision` section from a decision file."""
        content = path.read_text(encoding="utf-8")
        match = re.search(
            r"^## Decision\s*\n+(.*?)(?=\n## |\Z)",
            content,
            flags=re.MULTILINE | re.DOTALL,
        )
        if not match:
            return ""
        return match.group(1).strip()
