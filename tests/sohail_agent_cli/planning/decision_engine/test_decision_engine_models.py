import json

from sohail_agent_cli.planning.decision_engine.models import PlanningSelections, QuestionAnswer


def test_planning_selections_group_answers_by_section():
    selections = PlanningSelections.from_answers(
        (
            QuestionAnswer("Q-1", "project.name", "Shopfront"),
            QuestionAnswer("Q-2", "frontend.framework", "Next.js"),
            QuestionAnswer("Q-3", "testing.strategy", ("unit", "integration")),
            QuestionAnswer(
                "Q-4",
                "custom_requirements.items",
                "Generate PDF reports, Offline mode",
            ),
        )
    )

    assert selections.project["name"] == "Shopfront"
    assert selections.frontend["framework"] == "Next.js"
    assert selections.testing["strategy"] == ["unit", "integration"]
    assert selections.custom_requirements == ("Generate PDF reports", "Offline mode")


def test_planning_selections_json_is_stable_and_serializable():
    selections = PlanningSelections.from_answers(
        (
            QuestionAnswer("Q-1", "project.name", "Shopfront"),
            QuestionAnswer("Q-2", "custom_requirements.items", ("AI inspection",)),
        )
    )

    data = json.loads(selections.to_json())

    assert data["schema_version"] == 1
    assert data["project"]["name"] == "Shopfront"
    assert data["custom_requirements"] == ["AI inspection"]
    assert data["answers"][0]["key"] == "project.name"
