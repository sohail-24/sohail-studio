from datetime import date

import pytest

from sohail_agent_cli.planning.questions import (
    QUESTION_CATALOG,
    build_planning_context,
    infer_project_category,
    normalize_project_name,
    questions_for_category,
)


def test_question_catalog_has_stable_unique_ids():
    ids = [question.question_id for question in QUESTION_CATALOG]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))


def test_web_application_gets_frontend_and_backend_questions():
    destinations = [
        question.destination for question in questions_for_category("web_application")
    ]
    assert "frontend" in destinations
    assert "backend" in destinations


def test_cli_tool_does_not_get_frontend_or_backend_questions():
    destinations = [question.destination for question in questions_for_category("cli_tool")]
    assert "frontend" not in destinations
    assert "backend" not in destinations


def test_kubernetes_question_requires_docker_yes_or_undecided():
    no_docker = [
        question.destination
        for question in questions_for_category("web_application", {"docker": "no"})
    ]
    yes_docker = [
        question.destination
        for question in questions_for_category("web_application", {"docker": "yes"})
    ]
    assert "kubernetes" not in no_docker
    assert "kubernetes" in yes_docker


def test_choice_validation_rejects_unknown_value():
    frontend = next(
        question for question in QUESTION_CATALOG if question.destination == "frontend"
    )
    with pytest.raises(ValueError, match="Choose one of"):
        frontend.validate_answer("Svelte")


def test_undecided_choices_become_open_questions_and_not_decisions():
    context = build_planning_context(
        goal="Build ecommerce platform",
        project_name="Shopfront",
        category="web_application",
        answers={
            "target_users": "shoppers, administrators",
            "first_release_scope": "browse products, place orders",
            "out_of_scope": "marketplace sellers",
            "frontend": "undecided",
            "backend": "FastAPI",
            "database": "undecided",
            "authentication": "session",
            "docker": "yes",
            "kubernetes": "later",
            "deployment_target": "",
            "quality_requirements": "security",
        },
        planning_date=date(2026, 6, 24),
    )
    decision_topics = {decision.topic for decision in context.decisions}
    question_text = " ".join(question.text for question in context.open_questions)
    assert "frontend" not in decision_topics
    assert "database" not in decision_topics
    assert "frontend" in question_text.lower()
    assert "database" in question_text.lower()


def test_project_helpers_are_conservative():
    assert infer_project_category("Build ecommerce platform") == "web_application"
    assert infer_project_category("Create a CLI log parser") == "cli_tool"
    assert normalize_project_name("  My   Project  ") == "My Project"
