import pytest

from sohail_agent_cli.planning.decision_engine.models import (
    PlanningSelections,
    Question,
    QuestionAnswer,
    QuestionGroup,
    QuestionOption,
)
from sohail_agent_cli.planning.decision_engine.validator import (
    DecisionValidationError,
    PlanningSelectionValidator,
)


def required_choice_question() -> Question:
    return Question(
        "Q-1",
        "frontend.framework",
        "Frontend framework",
        "single_choice",
        required=True,
        options=(
            QuestionOption("React", "React"),
            QuestionOption("Next.js", "Next.js"),
        ),
    )


def test_validator_rejects_missing_required_answer():
    question = required_choice_question()

    with pytest.raises(DecisionValidationError, match="Missing required"):
        PlanningSelectionValidator().validate_answer(
            question,
            QuestionAnswer("Q-1", "frontend.framework", ""),
        )


def test_validator_rejects_invalid_choice():
    question = required_choice_question()

    with pytest.raises(DecisionValidationError, match="Invalid choice"):
        PlanningSelectionValidator().validate_answer(
            question,
            QuestionAnswer("Q-1", "frontend.framework", "Svelte"),
        )


def test_validator_rejects_duplicate_multi_choice_selections():
    question = Question(
        "Q-1",
        "testing.strategy",
        "Testing strategy",
        "multi_choice",
        options=(
            QuestionOption("unit", "Unit"),
            QuestionOption("integration", "Integration"),
        ),
    )

    with pytest.raises(DecisionValidationError, match="Duplicate selections"):
        PlanningSelectionValidator().validate_answer(
            question,
            QuestionAnswer("Q-1", "testing.strategy", ("unit", "unit")),
        )


def test_validator_rejects_duplicate_selection_keys():
    groups = (
        QuestionGroup(
            "frontend",
            "Frontend",
            "Frontend questions",
            (required_choice_question(),),
        ),
    )
    selections = PlanningSelections.from_answers(
        (
            QuestionAnswer("Q-1", "frontend.framework", "React"),
            QuestionAnswer("Q-1", "frontend.framework", "Next.js"),
        )
    )

    with pytest.raises(DecisionValidationError, match="Duplicate selections"):
        PlanningSelectionValidator().validate_selections(selections, groups)


def test_validator_rejects_simple_dependency_conflict():
    groups = (
        QuestionGroup(
            "container",
            "Container",
            "Container questions",
            (
                Question(
                    "Q-1",
                    "container.docker_required",
                    "Docker?",
                    "boolean",
                    required=True,
                ),
                Question(
                    "Q-2",
                    "container.kubernetes",
                    "Kubernetes?",
                    "single_choice",
                    required=True,
                    options=(
                        QuestionOption("yes", "Yes"),
                        QuestionOption("no", "No"),
                    ),
                ),
            ),
        ),
    )
    selections = PlanningSelections.from_answers(
        (
            QuestionAnswer("Q-1", "container.docker_required", False),
            QuestionAnswer("Q-2", "container.kubernetes", "yes"),
        )
    )

    with pytest.raises(DecisionValidationError, match="Kubernetes requires Docker"):
        PlanningSelectionValidator().validate_selections(selections, groups)
