from pathlib import Path

import pytest

from sohail_agent_cli.ai.context import AIContextBuilder
from sohail_agent_cli.ai.exceptions import AIContextError


def write_plan(root: Path) -> Path:
    plan = root / "project-plan"
    decisions = plan / "decisions"
    decisions.mkdir(parents=True)
    (plan / "REQUIREMENTS.md").write_text(
        """---
project: Shopfront
---

# Requirements

## Project Goal

Build an ecommerce platform.

## Assumptions

- Human review is required.
- Planning files describe the first release.
""",
        encoding="utf-8",
    )
    (plan / "ARCHITECTURE.md").write_text("# Architecture\n", encoding="utf-8")
    (plan / "TASK.md").write_text("# Task Plan\n", encoding="utf-8")
    for index, (topic, choice) in enumerate(
        (
            ("frontend", "React"),
            ("backend", "Node.js"),
            ("database", "PostgreSQL"),
            ("deployment", "Docker for V1; Kubernetes deferred"),
        ),
        start=1,
    ):
        (decisions / f"{index:03d}_{topic}.md").write_text(
            f"# DEC-{index:03d}\n\n## Decision\n\n{choice}\n\n## Rationale\n\n- Selected.\n",
            encoding="utf-8",
        )
    return plan


def test_context_builder_loads_project_plan(tmp_path):
    context = AIContextBuilder().build(write_plan(tmp_path))
    assert context.project_name == "Shopfront"
    assert context.goal == "Build an ecommerce platform."
    assert context.frontend == "React"
    assert context.backend == "Node.js"
    assert context.database == "PostgreSQL"
    assert context.deployment.startswith("Docker")
    assert "frontend: React" in context.decisions
    assert "Human review is required." in context.assumptions


def test_context_builder_creates_memory(tmp_path):
    builder = AIContextBuilder()
    memory = builder.build_memory(builder.build(write_plan(tmp_path)))
    assert len(memory.by_category("decision")) == 4
    assert len(memory.by_category("technology_stack")) == 3


def test_context_builder_rejects_invalid_plan(tmp_path):
    with pytest.raises(AIContextError):
        AIContextBuilder().build(tmp_path / "missing")
