from sohail_agent_cli.planning.decision_engine.models import Question, QuestionOption
from sohail_agent_cli.planning.decision_engine.renderer import TerminalRenderer


def prompt_from(values):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def test_renderer_accepts_single_choice_number():
    renderer = TerminalRenderer(prompt=prompt_from(["2"]), write=lambda _text: None)
    question = Question(
        "Q-1",
        "frontend.framework",
        "Frontend framework",
        "single_choice",
        options=(
            QuestionOption("React", "React"),
            QuestionOption("Next.js", "Next.js"),
        ),
    )

    answer = renderer.ask(question)

    assert answer.value == "Next.js"


def test_renderer_accepts_multi_choice_numbers():
    renderer = TerminalRenderer(prompt=prompt_from(["1, 3"]), write=lambda _text: None)
    question = Question(
        "Q-1",
        "testing.strategy",
        "Testing strategy",
        "multi_choice",
        options=(
            QuestionOption("unit", "Unit"),
            QuestionOption("integration", "Integration"),
            QuestionOption("e2e", "End-to-end"),
        ),
    )

    answer = renderer.ask(question)

    assert answer.value == ("unit", "e2e")


def test_renderer_retries_invalid_boolean():
    messages = []
    renderer = TerminalRenderer(
        prompt=prompt_from(["maybe", "yes"]),
        write=messages.append,
    )
    question = Question(
        "Q-1",
        "container.docker_required",
        "Is Docker required?",
        "boolean",
        required=True,
    )

    answer = renderer.ask(question)

    assert answer.value is True
    assert "Choose yes or no." in messages


def test_renderer_parses_number_defaults():
    renderer = TerminalRenderer(prompt=prompt_from([""]), write=lambda _text: None)
    question = Question(
        "Q-1",
        "project.expected_users",
        "Expected users",
        "number",
        default=250,
    )

    answer = renderer.ask(question)

    assert answer.value == 250
