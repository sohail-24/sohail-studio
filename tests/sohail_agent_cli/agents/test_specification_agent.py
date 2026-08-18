from pathlib import Path

import pytest

from sohail_agent_cli.agents import SpecificationAgent
from sohail_agent_cli.specification.models import Specification, SpecificationOutput


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


def output() -> SpecificationOutput:
    return SpecificationOutput(
        specification=Specification(
            title="Shopfront",
            summary="Commerce platform.",
            product_spec="Product scope.",
            features=("Browse products",),
            data_model="Product table.",
            api_spec="GET /products",
            non_functional=("No secrets in source control",),
        )
    )


class FakeGenerator:
    async def generate(self, specification_input):
        return output()


@pytest.mark.asyncio
async def test_specification_agent_writes_required_files(tmp_path):
    agent = SpecificationAgent()
    agent.generator = FakeGenerator()
    target = tmp_path / "specifications"

    result = await agent.execute(write_plan(tmp_path), output_dir=target)

    assert result.success
    assert (target / "PRODUCT_SPEC.md").exists()
    assert (target / "FEATURES.md").exists()
    assert (target / "DATA_MODEL.md").exists()
    assert (target / "API_SPEC.md").exists()
    assert (target / "NON_FUNCTIONAL.md").exists()


@pytest.mark.asyncio
async def test_specification_agent_dry_run_writes_nothing(tmp_path):
    agent = SpecificationAgent(dry_run=True)
    agent.generator = FakeGenerator()
    target = tmp_path / "specifications"

    result = await agent.execute(write_plan(tmp_path), output_dir=target)

    assert result.success
    assert result.data["dry_run"] is True
    assert not target.exists()


@pytest.mark.asyncio
async def test_specification_agent_blocks_existing_files_without_overwrite(tmp_path):
    agent = SpecificationAgent()
    agent.generator = FakeGenerator()
    target = tmp_path / "specifications"
    target.mkdir()
    existing = target / "PRODUCT_SPEC.md"
    existing.write_text("human content", encoding="utf-8")

    result = await agent.execute(write_plan(tmp_path), output_dir=target)

    assert not result.success
    assert existing.read_text(encoding="utf-8") == "human content"


@pytest.mark.asyncio
async def test_specification_agent_overwrites_when_requested(tmp_path):
    agent = SpecificationAgent()
    agent.generator = FakeGenerator()
    target = tmp_path / "specifications"
    target.mkdir()
    existing = target / "PRODUCT_SPEC.md"
    existing.write_text("human content", encoding="utf-8")

    result = await agent.execute(
        write_plan(tmp_path),
        output_dir=target,
        overwrite=True,
    )

    assert result.success
    assert "human content" not in existing.read_text(encoding="utf-8")
