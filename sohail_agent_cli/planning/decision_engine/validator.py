"""Validation for Engineering Decision Engine V1."""

from __future__ import annotations

from typing import Any

from .models import (
    DECISION_ENGINE_SCHEMA_VERSION,
    QUESTION_TYPES,
    PlanningSelections,
    Question,
    QuestionAnswer,
    QuestionGroup,
)


class DecisionValidationError(ValueError):
    """Raised when engineering decision validation fails."""


class PlanningSelectionValidator:
    """Validate question catalogs, answers, and final selections."""

    def validate_question_groups(self, groups: tuple[QuestionGroup, ...]) -> None:
        """Validate group definitions and cross-group uniqueness."""
        errors: list[str] = []
        group_ids = [group.group_id for group in groups]
        if len(group_ids) != len(set(group_ids)):
            errors.append("Duplicate question group IDs are not allowed")

        question_ids: list[str] = []
        question_keys: list[str] = []
        for group in groups:
            try:
                group.validate()
            except ValueError as exc:
                errors.append(str(exc))
            question_ids.extend(question.question_id for question in group.questions)
            question_keys.extend(question.key for question in group.questions)

        if len(question_ids) != len(set(question_ids)):
            errors.append("Duplicate question IDs are not allowed")
        if len(question_keys) != len(set(question_keys)):
            errors.append("Duplicate question keys are not allowed")

        self._raise_if_errors(errors)

    def validate_answer(self, question: Question, answer: QuestionAnswer) -> None:
        """Validate one answer against its question definition."""
        errors: list[str] = []
        if answer.question_id != question.question_id:
            errors.append(f"Answer question ID does not match {question.question_id}")
        if answer.key != question.key:
            errors.append(f"Answer key does not match {question.key}")

        value = answer.value
        if self._is_empty(value):
            if question.required:
                errors.append(f"Missing required selection: {question.key}")
            self._raise_if_errors(errors)
            return

        if question.question_type not in QUESTION_TYPES:
            errors.append(f"Invalid question type: {question.question_type}")
        elif question.question_type == "single_choice":
            self._validate_single_choice(question, value, errors)
        elif question.question_type == "multi_choice":
            self._validate_multi_choice(question, value, errors)
        elif question.question_type == "boolean" and not isinstance(value, bool):
            errors.append(f"Selection {question.key} must be true or false")
        elif question.question_type == "number" and not isinstance(value, int | float):
            errors.append(f"Selection {question.key} must be a number")
        elif question.question_type in {"text", "path"} and not isinstance(value, str):
            errors.append(f"Selection {question.key} must be text")

        self._raise_if_errors(errors)

    def validate_selections(
        self,
        selections: PlanningSelections,
        groups: tuple[QuestionGroup, ...],
    ) -> None:
        """Validate a completed PlanningSelections record."""
        errors: list[str] = []
        if selections.schema_version != DECISION_ENGINE_SCHEMA_VERSION:
            errors.append(f"Unsupported PlanningSelections schema: {selections.schema_version}")

        answer_keys = [answer.key for answer in selections.answers]
        if len(answer_keys) != len(set(answer_keys)):
            errors.append("Duplicate selections are not allowed")

        question_by_key = {
            question.key: question
            for group in groups
            for question in group.questions
        }
        answer_by_key = {answer.key: answer for answer in selections.answers}
        for question in question_by_key.values():
            answer = answer_by_key.get(question.key)
            if answer is None:
                if question.required:
                    errors.append(f"Missing required selection: {question.key}")
                continue
            try:
                self.validate_answer(question, answer)
            except DecisionValidationError as exc:
                errors.append(str(exc))

        self._validate_simple_dependencies(selections, errors)
        self._raise_if_errors(errors)

    def _validate_single_choice(
        self,
        question: Question,
        value: Any,
        errors: list[str],
    ) -> None:
        if not isinstance(value, str):
            errors.append(f"Selection {question.key} must be one choice")
            return
        allowed = set(question.option_values())
        if value not in allowed:
            errors.append(f"Invalid choice for {question.key}: {value}")

    def _validate_multi_choice(
        self,
        question: Question,
        value: Any,
        errors: list[str],
    ) -> None:
        if not isinstance(value, tuple | list):
            errors.append(f"Selection {question.key} must be a list of choices")
            return
        values = [str(item) for item in value if str(item).strip()]
        if len(values) != len(set(values)):
            errors.append(f"Duplicate selections for {question.key} are not allowed")
        allowed = set(question.option_values())
        invalid = sorted(set(values) - allowed)
        if invalid:
            errors.append(f"Invalid choices for {question.key}: {', '.join(invalid)}")

    def _validate_simple_dependencies(
        self,
        selections: PlanningSelections,
        errors: list[str],
    ) -> None:
        docker_required = selections.get("container.docker_required")
        kubernetes = selections.get("container.kubernetes")
        if docker_required is False and kubernetes == "yes":
            errors.append("Kubernetes requires Docker to be enabled")

    @staticmethod
    def _is_empty(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, tuple | list):
            return not value
        return False

    @staticmethod
    def _raise_if_errors(errors: list[str]) -> None:
        if errors:
            raise DecisionValidationError("; ".join(errors))
