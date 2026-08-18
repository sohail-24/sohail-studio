from datetime import date

import pytest

from sohail_agent_cli.planning.models import (
    ArchitectureComponent,
    DecisionRecord,
    OpenQuestion,
    PlanningContext,
    ProjectBrief,
    Requirement,
    TaskItem,
)


def make_context() -> PlanningContext:
    return PlanningContext(
        brief=ProjectBrief(
            name="Shopfront",
            goal="Build an ecommerce platform",
            category="web_application",
            target_users=["shoppers"],
            first_release_scope=["browse products"],
            planning_date=date(2026, 6, 24),
        ),
        requirements=[
            Requirement(
                "FR-001",
                "Browse Products",
                "functional",
                "must",
                "accepted",
                "user",
                "Visitors can browse products.",
                "Products are visible.",
            )
        ],
        architecture_components=[
            ArchitectureComponent("Application", ["Deliver the catalog"], ["DEC-001"])
        ],
        tasks=[
            TaskItem(
                "T-001",
                "Build catalog",
                "ready",
                "P0",
                "unassigned",
                [],
                ["FR-001"],
                ["DEC-001"],
                "Deliver the catalog.",
                ["Products are visible."],
            )
        ],
        decisions=[
            DecisionRecord(
                "DEC-001",
                "frontend",
                "Select frontend",
                "frontend",
                "Next.js",
                "A frontend is needed.",
                ["Supports the confirmed UI."],
                ["React"],
                ["Clear direction."],
                ["Must be validated."],
                related_requirement_ids=["FR-001"],
                related_task_ids=["T-001"],
            )
        ],
        assumptions=["Human review is required."],
        open_questions=[OpenQuestion("OQ-001", "Which hosting platform?")],
    )


def test_valid_context_passes_validation():
    make_context().validate()


def test_duplicate_requirement_ids_are_rejected():
    context = make_context()
    context.requirements.append(context.requirements[0])
    with pytest.raises(ValueError, match="Duplicate requirement"):
        context.validate()


def test_unknown_task_reference_is_rejected():
    context = make_context()
    context.tasks[0] = TaskItem(
        "T-001",
        "Build catalog",
        "ready",
        "P0",
        "unassigned",
        ["T-999"],
        ["FR-001"],
        ["DEC-001"],
        "Deliver the catalog.",
        ["Products are visible."],
    )
    with pytest.raises(ValueError, match="Unknown T-001 dependency"):
        context.validate()


def test_circular_task_dependencies_are_rejected():
    context = make_context()
    context.tasks = [
        TaskItem(
            "T-001",
            "First",
            "proposed",
            "P0",
            "unassigned",
            ["T-002"],
            ["FR-001"],
            [],
            "First task.",
            ["First done."],
        ),
        TaskItem(
            "T-002",
            "Second",
            "proposed",
            "P0",
            "unassigned",
            ["T-001"],
            ["FR-001"],
            [],
            "Second task.",
            ["Second done."],
        ),
    ]
    context.decisions = []
    context.architecture_components = [ArchitectureComponent("Application", ["Deliver scope"])]
    with pytest.raises(ValueError, match="Circular"):
        context.validate()


def test_decision_filename_matches_identifier():
    decision = make_context().decisions[0]
    assert str(decision.filename) == "decisions/001_frontend.md"
