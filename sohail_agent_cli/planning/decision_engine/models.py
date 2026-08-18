"""Data models for the Engineering Decision Engine V1."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

DECISION_ENGINE_SCHEMA_VERSION = 1

QuestionType = Literal[
    "text",
    "single_choice",
    "multi_choice",
    "boolean",
    "number",
    "path",
]

QUESTION_TYPES = {
    "text",
    "single_choice",
    "multi_choice",
    "boolean",
    "number",
    "path",
}

SELECTION_SECTIONS = (
    "project",
    "architecture",
    "frontend",
    "backend",
    "database",
    "authentication",
    "infrastructure",
    "cloud",
    "container",
    "ci_cd",
    "monitoring",
    "security",
    "features",
    "notifications",
    "testing",
    "documentation",
)


@dataclass(slots=True, frozen=True)
class QuestionOption:
    """One allowed option for a choice question."""

    value: str
    label: str
    description: str = ""

    def validate(self) -> None:
        if not self.value.strip():
            raise ValueError("Question option value cannot be empty")
        if not self.label.strip():
            raise ValueError("Question option label cannot be empty")

    def to_dict(self) -> dict[str, str]:
        return {
            "value": self.value,
            "label": self.label,
            "description": self.description,
        }


@dataclass(slots=True, frozen=True)
class Question:
    """Renderer-neutral engineering decision question."""

    question_id: str
    key: str
    prompt: str
    question_type: QuestionType
    required: bool = False
    help_text: str = ""
    options: tuple[QuestionOption, ...] = ()
    default: Any = None

    @property
    def section(self) -> str:
        return self.key.partition(".")[0]

    @property
    def field(self) -> str:
        return self.key.partition(".")[2]

    def option_values(self) -> tuple[str, ...]:
        return tuple(option.value for option in self.options)

    def validate(self) -> None:
        if not self.question_id.strip():
            raise ValueError("Question ID cannot be empty")
        if not self.key.strip() or "." not in self.key:
            raise ValueError(f"Question {self.question_id} needs a section.field key")
        if not self.prompt.strip():
            raise ValueError(f"Question {self.question_id} prompt cannot be empty")
        if self.question_type not in QUESTION_TYPES:
            raise ValueError(f"Invalid question type: {self.question_type}")
        if self.question_type in {"single_choice", "multi_choice"} and not self.options:
            raise ValueError(f"Question {self.question_id} needs options")
        for option in self.options:
            option.validate()


@dataclass(slots=True, frozen=True)
class QuestionGroup:
    """Reusable group of related engineering decision questions."""

    group_id: str
    title: str
    description: str
    questions: tuple[Question, ...]

    def validate(self) -> None:
        if not self.group_id.strip():
            raise ValueError("Question group ID cannot be empty")
        if not self.title.strip():
            raise ValueError(f"Question group {self.group_id} title cannot be empty")
        question_ids = [question.question_id for question in self.questions]
        question_keys = [question.key for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError(f"Duplicate question IDs in group {self.group_id}")
        if len(question_keys) != len(set(question_keys)):
            raise ValueError(f"Duplicate question keys in group {self.group_id}")
        for question in self.questions:
            question.validate()


@dataclass(slots=True, frozen=True)
class QuestionAnswer:
    """One collected answer for a question."""

    question_id: str
    key: str
    value: Any

    def to_dict(self) -> dict[str, Any]:
        value = list(self.value) if isinstance(self.value, tuple) else self.value
        return {
            "question_id": self.question_id,
            "key": self.key,
            "value": value,
        }


@dataclass(slots=True, frozen=True)
class PlanningSelections:
    """Canonical V1 engineering decision record."""

    project: dict[str, Any] = field(default_factory=dict)
    architecture: dict[str, Any] = field(default_factory=dict)
    frontend: dict[str, Any] = field(default_factory=dict)
    backend: dict[str, Any] = field(default_factory=dict)
    database: dict[str, Any] = field(default_factory=dict)
    authentication: dict[str, Any] = field(default_factory=dict)
    infrastructure: dict[str, Any] = field(default_factory=dict)
    cloud: dict[str, Any] = field(default_factory=dict)
    container: dict[str, Any] = field(default_factory=dict)
    ci_cd: dict[str, Any] = field(default_factory=dict)
    monitoring: dict[str, Any] = field(default_factory=dict)
    security: dict[str, Any] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)
    notifications: dict[str, Any] = field(default_factory=dict)
    testing: dict[str, Any] = field(default_factory=dict)
    documentation: dict[str, Any] = field(default_factory=dict)
    custom_requirements: tuple[str, ...] = ()
    answers: tuple[QuestionAnswer, ...] = ()
    schema_version: int = DECISION_ENGINE_SCHEMA_VERSION

    @classmethod
    def from_answers(cls, answers: tuple[QuestionAnswer, ...]) -> PlanningSelections:
        """Build a sectioned PlanningSelections record from flat question answers."""
        section_data: dict[str, dict[str, Any]] = {
            section: {} for section in SELECTION_SECTIONS
        }
        custom_requirements: tuple[str, ...] = ()

        for answer in answers:
            section, _, field_name = answer.key.partition(".")
            if section == "custom_requirements":
                custom_requirements = _split_custom_requirements(answer.value)
                continue
            if section in section_data and field_name:
                section_data[section][field_name] = _json_safe_value(answer.value)

        return cls(
            project=section_data["project"],
            architecture=section_data["architecture"],
            frontend=section_data["frontend"],
            backend=section_data["backend"],
            database=section_data["database"],
            authentication=section_data["authentication"],
            infrastructure=section_data["infrastructure"],
            cloud=section_data["cloud"],
            container=section_data["container"],
            ci_cd=section_data["ci_cd"],
            monitoring=section_data["monitoring"],
            security=section_data["security"],
            features=section_data["features"],
            notifications=section_data["notifications"],
            testing=section_data["testing"],
            documentation=section_data["documentation"],
            custom_requirements=custom_requirements,
            answers=answers,
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Return a selected value by section.field key."""
        section, _, field_name = key.partition(".")
        if section == "custom_requirements":
            return self.custom_requirements
        data = getattr(self, section, None)
        if isinstance(data, dict):
            return data.get(field_name, default)
        return default

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "architecture": self.architecture,
            "frontend": self.frontend,
            "backend": self.backend,
            "database": self.database,
            "authentication": self.authentication,
            "infrastructure": self.infrastructure,
            "cloud": self.cloud,
            "container": self.container,
            "ci_cd": self.ci_cd,
            "monitoring": self.monitoring,
            "security": self.security,
            "features": self.features,
            "notifications": self.notifications,
            "testing": self.testing,
            "documentation": self.documentation,
            "custom_requirements": list(self.custom_requirements),
            "answers": [answer.to_dict() for answer in self.answers],
        }

    def to_json(self) -> str:
        """Render the selections as stable JSON."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    return value


def _split_custom_requirements(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list | tuple):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip()
    if not text:
        return ()
    return tuple(
        item.strip(" -")
        for item in text.replace("\r", "\n").replace(",", "\n").splitlines()
        if item.strip(" -")
    )
