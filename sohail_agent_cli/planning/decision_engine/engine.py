"""Engineering Decision Engine V1 orchestration."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import PlanningSelections, QuestionAnswer, QuestionGroup
from .questions import DEFAULT_QUESTION_GROUPS
from .renderer import TerminalRenderer
from .validator import PlanningSelectionValidator


class EngineeringDecisionEngine:
    """Collect validated engineering decisions from reusable question groups."""

    def __init__(
        self,
        question_groups: tuple[QuestionGroup, ...] | None = None,
        renderer: TerminalRenderer | None = None,
        validator: PlanningSelectionValidator | None = None,
    ) -> None:
        self.question_groups = question_groups or DEFAULT_QUESTION_GROUPS
        self.renderer = renderer or TerminalRenderer()
        self.validator = validator or PlanningSelectionValidator()

    def run(self, initial_answers: dict[str, Any] | None = None) -> PlanningSelections:
        """Run the decision session and return PlanningSelections."""
        initial_answers = initial_answers or {}
        self.validator.validate_question_groups(self.question_groups)

        answers: list[QuestionAnswer] = []
        for group in self.question_groups:
            self.renderer.render_group(group)
            for question in group.questions:
                question_to_ask = question
                if question.key in initial_answers:
                    question_to_ask = replace(question, default=initial_answers[question.key])
                answer = self.renderer.ask(question_to_ask)
                self.validator.validate_answer(question, answer)
                answers.append(answer)

        selections = PlanningSelections.from_answers(tuple(answers))
        self.validator.validate_selections(selections, self.question_groups)
        return selections
