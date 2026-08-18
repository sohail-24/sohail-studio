import pytest

from sohail_agent_cli.stack.models import StackPlan
from sohail_agent_cli.stack.selector import StackSelector


def test_selector_normalizes_supported_stack(tmp_path):
    plan = StackPlan(
        plan_directory=tmp_path,
        frontend="React",
        backend="Node.js",
        database="PostgreSQL",
    )
    selection = StackSelector().select(plan)
    assert selection.frontend == "react"
    assert selection.backend == "node"
    assert selection.database == "postgresql"


def test_selector_rejects_unsupported_stack(tmp_path):
    plan = StackPlan(plan_directory=tmp_path, frontend="Next.js")
    with pytest.raises(ValueError, match="Unsupported frontend"):
        StackSelector().select(plan)
