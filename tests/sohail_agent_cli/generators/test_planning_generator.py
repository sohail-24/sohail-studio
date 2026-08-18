from datetime import date
from pathlib import Path

from sohail_agent_cli.generators import PlanningGenerator
from sohail_agent_cli.planning.questions import build_planning_context


def ecommerce_context():
    return build_planning_context(
        goal="Build ecommerce platform",
        project_name="Shopfront",
        category="web_application",
        answers={
            "target_users": "shoppers, store administrators",
            "first_release_scope": "browse products, manage a cart, place an order",
            "out_of_scope": "marketplace sellers, native mobile apps",
            "frontend": "Next.js",
            "backend": "FastAPI",
            "database": "PostgreSQL",
            "authentication": "session",
            "docker": "yes",
            "kubernetes": "later",
            "deployment_target": "a managed container platform",
            "quality_requirements": "security, transactional consistency",
        },
        planning_date=date(2026, 6, 24),
    )


def test_generator_returns_expected_file_set():
    files = PlanningGenerator().generate(ecommerce_context())
    fixture = Path("tests/fixtures/planning/expected_file_list.txt")
    expected = fixture.read_text(encoding="utf-8").splitlines()
    assert [path.as_posix() for path in files] == expected


def test_generation_is_deterministic():
    generator = PlanningGenerator()
    first = generator.generate(ecommerce_context())
    second = generator.generate(ecommerce_context())
    assert first == second


def test_documents_have_required_sections_and_links():
    files = PlanningGenerator().generate(ecommerce_context())
    requirements = files[Path("REQUIREMENTS.md")]
    architecture = files[Path("ARCHITECTURE.md")]
    tasks = files[Path("TASK.md")]
    assert "# Requirements" in requirements
    assert "## Functional Requirements" in requirements
    assert "## Non-Functional Requirements" in requirements
    assert "## Constraints" in requirements
    assert "## Open Questions" in requirements
    assert "# Architecture" in architecture
    assert "## Major Components" in architecture
    assert "## Deployment View" in architecture
    assert "(decisions/001_frontend.md)" in architecture
    assert "# Task Plan" in tasks
    assert "## T-001" in tasks
    assert "**Status:** ready" in tasks


def test_decision_records_use_matching_ids_and_filenames():
    files = PlanningGenerator().generate(ecommerce_context())
    decision_paths = [path for path in files if path.parts[0] == "decisions"]
    for path in decision_paths:
        sequence = int(path.name[:3])
        assert f"id: DEC-{sequence:03d}" in files[path]
        assert f"# DEC-{sequence:03d}" in files[path]


def test_decision_records_include_reverse_task_and_requirement_links():
    files = PlanningGenerator().generate(ecommerce_context())
    deployment = files[Path("decisions/005_deployment.md")]
    assert "- CON-001" in deployment
    assert "- T-001" in deployment
    assert "- T-006" in deployment


def test_generator_preserves_unresolved_choices_as_open_questions():
    context = build_planning_context(
        goal="Build ecommerce platform",
        project_name="Shopfront",
        category="web_application",
        answers={
            "target_users": "shoppers",
            "first_release_scope": "browse products",
            "out_of_scope": "",
            "frontend": "undecided",
            "backend": "undecided",
            "database": "undecided",
            "authentication": "undecided",
            "docker": "undecided",
            "kubernetes": "undecided",
            "deployment_target": "",
            "quality_requirements": "",
        },
        planning_date=date(2026, 6, 24),
    )
    files = PlanningGenerator().generate(context)
    architecture = files[Path("ARCHITECTURE.md")]
    requirements = files[Path("REQUIREMENTS.md")]
    assert "not yet decided" in architecture
    assert "Which frontend approach" in requirements
    assert not any(path.name.endswith("frontend.md") for path in files)


def test_generator_never_returns_absolute_or_parent_paths():
    files = PlanningGenerator().generate(ecommerce_context())
    assert all(not path.is_absolute() for path in files)
    assert all(".." not in path.parts for path in files)
