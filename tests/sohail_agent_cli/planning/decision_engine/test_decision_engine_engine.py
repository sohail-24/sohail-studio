from sohail_agent_cli.planning.decision_engine.engine import EngineeringDecisionEngine
from sohail_agent_cli.planning.decision_engine.models import Question, QuestionGroup, QuestionOption
from sohail_agent_cli.planning.decision_engine.renderer import TerminalRenderer


def prompt_from(values):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def test_engine_collects_and_validates_planning_selections():
    groups = (
        QuestionGroup(
            "project",
            "Project",
            "Project questions",
            (
                Question("Q-1", "project.name", "Project name", "text", required=True),
                Question("Q-2", "project.goal", "Project goal", "text", required=True),
                Question(
                    "Q-3",
                    "frontend.framework",
                    "Frontend framework",
                    "single_choice",
                    required=True,
                    options=(
                        QuestionOption("React", "React"),
                        QuestionOption("Next.js", "Next.js"),
                    ),
                ),
                Question(
                    "Q-4",
                    "container.docker_required",
                    "Docker?",
                    "boolean",
                    required=True,
                ),
            ),
        ),
    )
    renderer = TerminalRenderer(
        prompt=prompt_from(["Shopfront", "Build ecommerce", "2", "yes"]),
        write=lambda _text: None,
    )

    selections = EngineeringDecisionEngine(groups, renderer=renderer).run()

    assert selections.project["name"] == "Shopfront"
    assert selections.project["goal"] == "Build ecommerce"
    assert selections.frontend["framework"] == "Next.js"
    assert selections.container["docker_required"] is True


def test_engine_uses_initial_answers_as_defaults():
    groups = (
        QuestionGroup(
            "project",
            "Project",
            "Project questions",
            (
                Question("Q-1", "project.name", "Project name", "text", required=True),
                Question("Q-2", "project.goal", "Project goal", "text", required=True),
            ),
        ),
    )
    renderer = TerminalRenderer(prompt=prompt_from(["", ""]), write=lambda _text: None)

    selections = EngineeringDecisionEngine(groups, renderer=renderer).run(
        initial_answers={
            "project.name": "Shopfront",
            "project.goal": "Build ecommerce",
        }
    )

    assert selections.project["name"] == "Shopfront"
    assert selections.project["goal"] == "Build ecommerce"
