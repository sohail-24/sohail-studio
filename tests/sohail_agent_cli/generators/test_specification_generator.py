from pathlib import Path

import pytest

from sohail_agent_cli.ai.models import AIExecutionMetadata, AIResult, AIStructuredOutput
from sohail_agent_cli.generators import SpecificationGenerator
from sohail_agent_cli.specification.loader import SpecificationLoader


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


class FakeOrchestrator:
    def __init__(self) -> None:
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        return AIResult(
            output=AIStructuredOutput(
                kind="specification",
                title="Shopfront Specification",
                summary="A commerce platform.",
                items=("Browse products",),
                metadata={
                    "product_spec": "Product scope.",
                    "features": ["Browse products"],
                    "data_model": "Product table.",
                    "api_spec": "GET /products",
                    "non_functional": ["No secrets in source control"],
                },
            ),
            metadata=AIExecutionMetadata(
                provider="fake",
                prompt_name="specification",
                prompt_version="v1",
                attempts=1,
                model="fake",
            ),
        )


@pytest.mark.asyncio
async def test_specification_generator_uses_ai_foundation_once(tmp_path):
    orchestrator = FakeOrchestrator()
    specification_input = SpecificationLoader().load(write_plan(tmp_path))

    result = await SpecificationGenerator(orchestrator=orchestrator).generate(
        specification_input
    )

    assert not result.is_empty
    assert result.specification is not None
    assert result.specification.title == "Shopfront Specification"
    assert len(orchestrator.requests) == 1
    assert orchestrator.requests[0].task == "write_specification"
    assert orchestrator.requests[0].allowed_kinds == ("specification",)
    assert orchestrator.requests[0].max_retries == 1
