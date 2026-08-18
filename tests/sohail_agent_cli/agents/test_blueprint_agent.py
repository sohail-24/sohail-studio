from pathlib import Path

import pytest

from sohail_agent_cli.agents import BlueprintAgent
from sohail_agent_cli.blueprint.models import Blueprint, BlueprintOutput


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


def write_specs(root: Path) -> Path:
    specs = root / "specifications"
    specs.mkdir()
    (specs / "PRODUCT_SPEC.md").write_text("# Product Specification\n", encoding="utf-8")
    (specs / "FEATURES.md").write_text("# Features\n- Browse products\n", encoding="utf-8")
    (specs / "DATA_MODEL.md").write_text("# Data Model\nProduct\n", encoding="utf-8")
    (specs / "API_SPEC.md").write_text("# API Specification\nGET /products\n", encoding="utf-8")
    (specs / "NON_FUNCTIONAL.md").write_text("# NFR\nNo secrets\n", encoding="utf-8")
    return specs


def output() -> BlueprintOutput:
    return BlueprintOutput(
        blueprint=Blueprint(
            title="Shopfront",
            summary="Commerce platform blueprint.",
            system_design="Layered system.",
            backend_architecture="FastAPI service.",
            frontend_architecture="React application.",
            database_design="PostgreSQL schema.",
            api_flow="GET /products",
            implementation_plan="Build slices.",
            folder_structure="src/, tests/",
            dependencies="fastapi, react",
        )
    )


class FakeGenerator:
    async def generate(self, blueprint_input):
        return output()


@pytest.mark.asyncio
async def test_blueprint_agent_writes_required_files(tmp_path):
    agent = BlueprintAgent()
    agent.generator = FakeGenerator()
    target = tmp_path / "blueprints"

    result = await agent.execute(
        write_plan(tmp_path),
        spec_dir=write_specs(tmp_path),
        output_dir=target,
    )

    assert result.success
    assert (target / "SYSTEM_DESIGN.md").exists()
    assert (target / "BACKEND_ARCHITECTURE.md").exists()
    assert (target / "FRONTEND_ARCHITECTURE.md").exists()
    assert (target / "DATABASE_DESIGN.md").exists()
    assert (target / "API_FLOW.md").exists()
    assert (target / "IMPLEMENTATION_PLAN.md").exists()
    assert (target / "FOLDER_STRUCTURE.md").exists()
    assert (target / "DEPENDENCIES.md").exists()


@pytest.mark.asyncio
async def test_blueprint_agent_dry_run_writes_nothing(tmp_path):
    agent = BlueprintAgent(dry_run=True)
    agent.generator = FakeGenerator()
    target = tmp_path / "blueprints"

    result = await agent.execute(
        write_plan(tmp_path),
        spec_dir=write_specs(tmp_path),
        output_dir=target,
    )

    assert result.success
    assert result.data["dry_run"] is True
    assert not target.exists()


@pytest.mark.asyncio
async def test_blueprint_agent_blocks_existing_files_without_overwrite(tmp_path):
    agent = BlueprintAgent()
    agent.generator = FakeGenerator()
    target = tmp_path / "blueprints"
    target.mkdir()
    existing = target / "SYSTEM_DESIGN.md"
    existing.write_text("human content", encoding="utf-8")

    result = await agent.execute(
        write_plan(tmp_path),
        spec_dir=write_specs(tmp_path),
        output_dir=target,
    )

    assert not result.success
    assert existing.read_text(encoding="utf-8") == "human content"


@pytest.mark.asyncio
async def test_blueprint_agent_overwrites_when_requested(tmp_path):
    agent = BlueprintAgent()
    agent.generator = FakeGenerator()
    target = tmp_path / "blueprints"
    target.mkdir()
    existing = target / "SYSTEM_DESIGN.md"
    existing.write_text("human content", encoding="utf-8")

    result = await agent.execute(
        write_plan(tmp_path),
        spec_dir=write_specs(tmp_path),
        output_dir=target,
        overwrite=True,
    )

    assert result.success
    assert "human content" not in existing.read_text(encoding="utf-8")
