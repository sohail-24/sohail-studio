"""Structured data models for PlanningAgent V1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

PLANNING_SCHEMA_VERSION = 1

REQUIREMENT_CATEGORIES = {"functional", "non_functional", "constraint"}
REQUIREMENT_PRIORITIES = {"must", "should", "could", "will_not"}
REQUIREMENT_STATUSES = {"proposed", "accepted", "deferred", "rejected", "superseded"}
TASK_STATUSES = {"proposed", "ready", "blocked"}
TASK_PRIORITIES = {"P0", "P1", "P2", "P3"}
DECISION_STATUSES = {"proposed", "accepted", "rejected", "superseded", "deprecated"}


@dataclass(frozen=True)
class ProjectBrief:
    """Top-level project identity and scope."""

    name: str
    goal: str
    category: str
    target_users: list[str]
    first_release_scope: list[str]
    out_of_scope: list[str] = field(default_factory=list)
    planning_date: date = field(default_factory=date.today)

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("Project name cannot be empty")
        if not self.goal.strip():
            raise ValueError("Project goal cannot be empty")
        if not self.target_users:
            raise ValueError("At least one target user is required")
        if not self.first_release_scope:
            raise ValueError("First-release scope cannot be empty")


@dataclass(frozen=True)
class Requirement:
    """A functional, non-functional, or constraint requirement."""

    requirement_id: str
    title: str
    category: str
    priority: str
    status: str
    source: str
    statement: str
    acceptance: str
    decision_ids: list[str] = field(default_factory=list)

    def validate(self) -> None:
        prefixes = {
            "functional": "FR-",
            "non_functional": "NFR-",
            "constraint": "CON-",
        }
        if self.category not in REQUIREMENT_CATEGORIES:
            raise ValueError(f"Invalid requirement category: {self.category}")
        if not self.requirement_id.startswith(prefixes[self.category]):
            raise ValueError(
                f"Requirement {self.requirement_id} does not match category {self.category}"
            )
        if self.priority not in REQUIREMENT_PRIORITIES:
            raise ValueError(f"Invalid requirement priority: {self.priority}")
        if self.status not in REQUIREMENT_STATUSES:
            raise ValueError(f"Invalid requirement status: {self.status}")
        if not all((self.title.strip(), self.statement.strip(), self.acceptance.strip())):
            raise ValueError(f"Requirement {self.requirement_id} has empty required fields")


@dataclass(frozen=True)
class OpenQuestion:
    """A decision or requirement that remains unresolved."""

    question_id: str
    text: str

    def validate(self) -> None:
        if not self.question_id.startswith("OQ-"):
            raise ValueError(f"Invalid open-question ID: {self.question_id}")
        if not self.text.strip():
            raise ValueError(f"Open question {self.question_id} cannot be empty")


@dataclass(frozen=True)
class DecisionRecord:
    """A confirmed consequential project choice."""

    decision_id: str
    slug: str
    title: str
    topic: str
    choice: str
    context: str
    rationale: list[str]
    alternatives: list[str]
    positive_consequences: list[str]
    negative_consequences: list[str]
    related_requirement_ids: list[str] = field(default_factory=list)
    related_task_ids: list[str] = field(default_factory=list)
    open_question_ids: list[str] = field(default_factory=list)
    status: str = "accepted"

    @property
    def sequence(self) -> int:
        return int(self.decision_id.split("-")[1])

    @property
    def filename(self) -> Path:
        return Path("decisions") / f"{self.sequence:03d}_{self.slug}.md"

    def validate(self) -> None:
        if not self.decision_id.startswith("DEC-"):
            raise ValueError(f"Invalid decision ID: {self.decision_id}")
        if self.status not in DECISION_STATUSES:
            raise ValueError(f"Invalid decision status: {self.status}")
        if not self.slug or not self.slug.replace("_", "").isalnum():
            raise ValueError(f"Invalid decision slug: {self.slug}")
        if not all((self.title.strip(), self.topic.strip(), self.choice.strip())):
            raise ValueError(f"Decision {self.decision_id} has empty required fields")


@dataclass(frozen=True)
class ArchitectureComponent:
    """A high-level system component."""

    name: str
    responsibilities: list[str]
    decision_ids: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.name.strip() or not self.responsibilities:
            raise ValueError("Architecture components need a name and responsibilities")


@dataclass(frozen=True)
class TaskItem:
    """A project backlog task, distinct from core runtime PlanStep."""

    task_id: str
    title: str
    status: str
    priority: str
    owner: str
    dependencies: list[str]
    requirement_ids: list[str]
    decision_ids: list[str]
    objective: str
    acceptance_criteria: list[str]
    notes: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.task_id.startswith("T-"):
            raise ValueError(f"Invalid task ID: {self.task_id}")
        if self.status not in TASK_STATUSES:
            raise ValueError(f"Invalid task status: {self.status}")
        if self.priority not in TASK_PRIORITIES:
            raise ValueError(f"Invalid task priority: {self.priority}")
        if self.task_id in self.dependencies:
            raise ValueError(f"Task {self.task_id} cannot depend on itself")
        if not all((self.title.strip(), self.owner.strip(), self.objective.strip())):
            raise ValueError(f"Task {self.task_id} has empty required fields")
        if not self.acceptance_criteria:
            raise ValueError(f"Task {self.task_id} needs acceptance criteria")


@dataclass
class PlanningContext:
    """Complete validated input for PlanningGenerator."""

    brief: ProjectBrief
    requirements: list[Requirement]
    architecture_components: list[ArchitectureComponent]
    tasks: list[TaskItem]
    decisions: list[DecisionRecord]
    assumptions: list[str]
    open_questions: list[OpenQuestion]
    quality_goals: list[str] = field(default_factory=list)
    deployment_summary: str = "Deployment approach is not yet decided."
    authentication_summary: str = "Authentication approach is not yet decided."
    schema_version: int = PLANNING_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != PLANNING_SCHEMA_VERSION:
            raise ValueError(f"Unsupported planning schema: {self.schema_version}")
        self.brief.validate()
        for collection in (
            self.requirements,
            self.architecture_components,
            self.tasks,
            self.decisions,
            self.open_questions,
        ):
            for item in collection:
                item.validate()

        requirement_ids = self._unique_ids(
            (item.requirement_id for item in self.requirements), "requirement"
        )
        task_ids = self._unique_ids((item.task_id for item in self.tasks), "task")
        decision_ids = self._unique_ids(
            (item.decision_id for item in self.decisions), "decision"
        )
        open_question_ids = self._unique_ids(
            (item.question_id for item in self.open_questions), "open question"
        )

        for task in self.tasks:
            self._require_known(task.dependencies, task_ids, f"{task.task_id} dependency")
            self._require_known(
                task.requirement_ids, requirement_ids, f"{task.task_id} requirement"
            )
            self._require_known(task.decision_ids, decision_ids, f"{task.task_id} decision")

        for decision in self.decisions:
            self._require_known(
                decision.related_requirement_ids,
                requirement_ids,
                f"{decision.decision_id} requirement",
            )
            self._require_known(
                decision.related_task_ids, task_ids, f"{decision.decision_id} task"
            )
            self._require_known(
                decision.open_question_ids,
                open_question_ids,
                f"{decision.decision_id} open question",
            )

        for component in self.architecture_components:
            self._require_known(
                component.decision_ids, decision_ids, f"{component.name} decision"
            )

        self._validate_task_graph()

    @staticmethod
    def _unique_ids(values: Iterable[str], label: str) -> set[str]:
        values_list = list(values)
        if len(values_list) != len(set(values_list)):
            raise ValueError(f"Duplicate {label} IDs are not allowed")
        return set(values_list)

    @staticmethod
    def _require_known(values: Iterable[str], known: set[str], label: str) -> None:
        missing = sorted(set(values) - known)
        if missing:
            raise ValueError(f"Unknown {label} references: {', '.join(missing)}")

    def _validate_task_graph(self) -> None:
        dependency_map = {task.task_id: task.dependencies for task in self.tasks}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError("Circular task dependency detected")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in dependency_map[task_id]:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in dependency_map:
            visit(task_id)
