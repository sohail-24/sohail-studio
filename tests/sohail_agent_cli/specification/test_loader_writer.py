from pathlib import Path

import pytest

from sohail_agent_cli.bootstrap.validator import PlanningValidationError
from sohail_agent_cli.specification import SpecificationLoader, SpecificationOutput, SpecificationWriter
from sohail_agent_cli.specification.models import Specification


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

Build ecommerce platform.
""",
        encoding="utf-8",
    )
    (plan / "ARCHITECTURE.md").write_text("# Architecture\n", encoding="utf-8")
    (plan / "TASK.md").write_text("# Task Plan\n", encoding="utf-8")
    (decisions / "001_frontend.md").write_text(
        "# DEC-001\n\n## Decision\n\nReact\n", encoding="utf-8"
    )
    return plan


def specification() -> Specification:
    return Specification(
        title="Shopfront",
        summary="Commerce platform.",
        product_spec="Product scope.",
        features=("Browse products", "Manage cart"),
        data_model="Product, Cart, Order.",
        api_spec="GET /products",
        non_functional=("No secrets in source control",),
    )


def test_specification_loader_reads_complete_plan(tmp_path):
    loaded = SpecificationLoader().load(write_plan(tmp_path))

    assert loaded.plan_directory == (tmp_path / "project-plan").resolve()
    assert "Build ecommerce platform" in loaded.requirements_markdown
    assert loaded.project_goal == "Build ecommerce platform."
    assert loaded.decisions[0].topic == "frontend"
    assert loaded.decisions[0].filename == "001_frontend.md"


def test_specification_loader_rejects_invalid_plan(tmp_path):
    with pytest.raises(PlanningValidationError):
        SpecificationLoader().load(tmp_path / "missing-plan")


def test_specification_writer_prepares_all_required_files(tmp_path):
    output = SpecificationOutput(specification=specification())

    targets = SpecificationWriter().prepare(tmp_path, output)
    names = [target.path.name for target in targets]

    assert names == [
        "PRODUCT_SPEC.md",
        "FEATURES.md",
        "DATA_MODEL.md",
        "API_SPEC.md",
        "NON_FUNCTIONAL.md",
    ]
    assert all(target.content.endswith("\n") for target in targets)
    assert "# Product Specification" in targets[0].content


def test_specification_writer_detects_conflicts(tmp_path):
    target = tmp_path / "PRODUCT_SPEC.md"
    target.write_text("existing", encoding="utf-8")
    targets = SpecificationWriter().prepare(
        tmp_path,
        SpecificationOutput(specification=specification()),
    )

    conflicts = SpecificationWriter().conflicts(targets, overwrite=False)

    assert conflicts == [target.resolve()]
