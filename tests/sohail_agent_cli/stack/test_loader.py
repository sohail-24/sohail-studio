from pathlib import Path

import pytest

from sohail_agent_cli.stack.loader import StackPlanError, StackPlanLoader


def write_plan(root: Path, frontend: str = "React", backend: str = "FastAPI", database: str = "PostgreSQL") -> Path:
    plan = root / "project-plan"
    decisions = plan / "decisions"
    decisions.mkdir(parents=True)
    for filename in ("REQUIREMENTS.md", "ARCHITECTURE.md", "TASK.md"):
        (plan / filename).write_text(f"# {filename}\n", encoding="utf-8")
    (decisions / "001_frontend.md").write_text(
        f"# DEC-001\n\n## Decision\n\n{frontend}\n\n## Rationale\n\n- Selected.\n",
        encoding="utf-8",
    )
    (decisions / "002_backend.md").write_text(
        f"# DEC-002\n\n## Decision\n\n{backend}\n\n## Rationale\n\n- Selected.\n",
        encoding="utf-8",
    )
    (decisions / "003_database.md").write_text(
        f"# DEC-003\n\n## Decision\n\n{database}\n\n## Rationale\n\n- Selected.\n",
        encoding="utf-8",
    )
    return plan


def test_loader_reads_stack_decisions(tmp_path):
    plan = StackPlanLoader().load(write_plan(tmp_path))
    assert plan.frontend == "React"
    assert plan.backend == "FastAPI"
    assert plan.database == "PostgreSQL"


def test_loader_rejects_missing_plan(tmp_path):
    with pytest.raises(StackPlanError):
        StackPlanLoader().load(tmp_path / "missing")


def test_loader_ignores_unresolved_choices(tmp_path):
    plan_dir = write_plan(tmp_path, frontend="undecided", backend="none", database="PostgreSQL")
    plan = StackPlanLoader().load(plan_dir)
    assert plan.frontend is None
    assert plan.backend is None
    assert plan.database == "PostgreSQL"
