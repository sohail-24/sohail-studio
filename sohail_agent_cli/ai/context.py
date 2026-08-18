"""Build structured AI context from PlanningAgent packages."""

from __future__ import annotations

import re
from pathlib import Path

from .exceptions import AIContextError
from .memory import ProjectMemory
from .models import ProjectContext


class AIContextBuilder:
    """Build normalized AI context from `project-plan/`."""

    REQUIRED_FILES = ("REQUIREMENTS.md", "ARCHITECTURE.md", "TASK.md")

    def build(self, plan_directory: Path) -> ProjectContext:
        """Load a PlanningAgent package into ProjectContext."""
        plan_directory = plan_directory.resolve()
        self._validate(plan_directory)

        requirements = (plan_directory / "REQUIREMENTS.md").read_text(encoding="utf-8")
        decisions = self._load_decisions(plan_directory / "decisions")
        goal = self._extract_section(requirements, "Project Goal") or "Unknown project goal"
        project_name = self._extract_front_matter(requirements, "project") or "Unknown Project"

        return ProjectContext(
            goal=goal,
            project_name=project_name,
            frontend=decisions.get("frontend"),
            backend=decisions.get("backend"),
            database=decisions.get("database"),
            deployment=decisions.get("deployment"),
            decisions=tuple(f"{topic}: {choice}" for topic, choice in decisions.items()),
            assumptions=tuple(self._extract_bullets(requirements, "Assumptions")),
            source=str(plan_directory),
        )

    def build_memory(self, context: ProjectContext) -> ProjectMemory:
        """Create lightweight memory from context."""
        memory = ProjectMemory()
        for decision in context.decisions:
            topic, _, value = decision.partition(":")
            memory.add("decision", topic.strip(), value.strip(), context.source)
        for assumption in context.assumptions:
            memory.add("assumption", assumption, True, context.source)
        for key in ("frontend", "backend", "database"):
            value = getattr(context, key)
            if value:
                memory.add("technology_stack", key, value, context.source)
        return memory

    def _validate(self, plan_directory: Path) -> None:
        if not plan_directory.exists():
            raise AIContextError(f"Planning package not found: {plan_directory}")
        if not plan_directory.is_dir():
            raise AIContextError(f"Expected planning directory: {plan_directory}")
        for filename in self.REQUIRED_FILES:
            if not (plan_directory / filename).is_file():
                raise AIContextError(f"Missing planning file: {filename}")
        if not (plan_directory / "decisions").is_dir():
            raise AIContextError("Missing decisions directory")

    def _load_decisions(self, decision_directory: Path) -> dict[str, str]:
        decisions: dict[str, str] = {}
        for path in sorted(decision_directory.glob("*.md")):
            topic = re.sub(r"^\d+_", "", path.stem).lower()
            value = self._extract_section(path.read_text(encoding="utf-8"), "Decision")
            if value:
                decisions[topic] = value
        return decisions

    @staticmethod
    def _extract_front_matter(content: str, key: str) -> str | None:
        match = re.search(rf"^{re.escape(key)}:\s*(.+)$", content, flags=re.MULTILINE)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_section(content: str, heading: str) -> str | None:
        match = re.search(
            rf"^## {re.escape(heading)}\s*\n+(.*?)(?=\n## |\Z)",
            content,
            flags=re.MULTILINE | re.DOTALL,
        )
        return match.group(1).strip() if match else None

    @classmethod
    def _extract_bullets(cls, content: str, heading: str) -> list[str]:
        section = cls._extract_section(content, heading) or ""
        return [
            line[2:].strip()
            for line in section.splitlines()
            if line.startswith("- ") and line[2:].strip()
        ]
