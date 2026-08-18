"""Specification generator."""

from __future__ import annotations

from typing import Any

from sohail_agent_cli.ai.context import AIContextBuilder
from sohail_agent_cli.ai.models import AIRequest
from sohail_agent_cli.ai.orchestrator import AIOrchestrator
from sohail_agent_cli.ai.provider import ProviderSpec
from sohail_agent_cli.specification.models import Specification, SpecificationInput, SpecificationOutput


class SpecificationGenerator:
    """
    Generate structured specifications through the AI Foundation.

    The generator does not write files and does not call providers directly.
    """

    def __init__(
        self,
        context_builder: AIContextBuilder | None = None,
        orchestrator: Any | None = None,
        verbose: bool = False,
    ) -> None:
        self.context_builder = context_builder or AIContextBuilder()
        self.orchestrator = orchestrator or AIOrchestrator(
            provider_spec=ProviderSpec(name="ollama"),
            verbose=verbose,
        )

    async def generate(self, specification_input: SpecificationInput) -> SpecificationOutput:
        """Generate a specification using exactly one AI Foundation call."""
        context = self.context_builder.build(specification_input.plan_directory)
        ai_result = await self.orchestrator.execute(
            AIRequest(
                task="write_specification",
                context=context,
                instruction=self._build_instruction(specification_input),
                required_fields=("kind", "title", "summary", "items"),
                allowed_kinds=("specification",),
                max_retries=1,
            )
          
        )
        

        return SpecificationOutput(
            specification=Specification.from_ai_output(ai_result.output)
        )
        

    def _build_instruction(self, specification_input: SpecificationInput) -> str:
        return "\n\n".join(
            [
                """
    You are generating a software specification.

    Return ONLY valid JSON.

    Do NOT return Markdown.
    Do NOT wrap the JSON in ``` blocks.
    Do NOT include explanations.

    The JSON MUST exactly match this schema:

    {
    "kind": "specification",
    "title": "<project title>",
    "summary": "<short summary>",
    "items": [
        "<major requirement>",
        "<major requirement>"
    ],
    "metadata": {
        "product_spec": "<product specification>",
        "features": [
        "<feature>",
        "<feature>"
        ],
        "data_model": "<data model>",
        "api_spec": "<api specification>",
        "non_functional": [
        "<requirement>",
        "<requirement>"
        ]
    }
    }

    Do not add any extra top-level keys.
    """,
                self._section("PROJECT_GOAL", specification_input.project_goal or ""),
                self._section("REQUIREMENTS_MD", specification_input.requirements_markdown),
                self._section("ARCHITECTURE_MD", specification_input.architecture_markdown),
                self._section("TASK_MD", specification_input.tasks_markdown),
                self._section(
                    "DECISIONS_MD",
                    "\n\n".join(
                        f"## {decision.filename}\n{decision.content}"
                        for decision in specification_input.decisions
                    ),
                ),
            ]
        )

    @staticmethod
    def _section(name: str, content: str) -> str:
        return f"<{name}>\n{content.strip()}\n</{name}>"
