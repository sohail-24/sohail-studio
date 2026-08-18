from pathlib import Path

import pytest

from sohail_agent_cli.ai.models import AIExecutionMetadata, AIResult, AIStructuredOutput
from sohail_agent_cli.blueprint.loader import BlueprintLoader
from sohail_agent_cli.generators import BlueprintGenerator


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


class FakeOrchestrator:
    def __init__(self) -> None:
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        return AIResult(
            output=AIStructuredOutput(
                kind="blueprint",
                title="Shopfront Blueprint",
                summary="A commerce implementation blueprint.",
                items=("Layered system",),
                metadata={
                    "system_design": "Layered service design.",
                    "backend_architecture": "FastAPI service.",
                    "frontend_architecture": "React application.",
                    "database_design": "PostgreSQL schema.",
                    "api_flow": "GET /products",
                    "implementation_plan": "Build vertical slices.",
                    "folder_structure": "src/, tests/",
                    "dependencies": "fastapi, react",
                },
            ),
            metadata=AIExecutionMetadata(
                provider="fake",
                prompt_name="blueprint",
                prompt_version="v1",
                attempts=1,
                model="fake",
            ),
        )


@pytest.mark.asyncio
async def test_blueprint_generator_uses_ai_foundation_once(tmp_path):
    orchestrator = FakeOrchestrator()
    blueprint_input = BlueprintLoader().load(write_plan(tmp_path), write_specs(tmp_path))

    result = await BlueprintGenerator(orchestrator=orchestrator).generate(blueprint_input)

    assert not result.is_empty
    assert result.blueprint is not None
    assert result.blueprint.title == "Shopfront Blueprint"
    assert result.blueprint.backend_architecture == "FastAPI service."
    assert len(orchestrator.requests) == 1
    assert orchestrator.requests[0].task == "write_blueprint"
    assert orchestrator.requests[0].prompt_name == "blueprint"
    assert orchestrator.requests[0].allowed_kinds == ("blueprint",)
    assert orchestrator.requests[0].max_retries == 1
    assert "<PRODUCT_SPEC_MD>" in orchestrator.requests[0].instruction
    assert "<NON_FUNCTIONAL_MD>" in orchestrator.requests[0].instruction
