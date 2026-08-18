"""Blueprint generator."""

from __future__ import annotations

from typing import Any

from sohail_agent_cli.ai.context import AIContextBuilder
from sohail_agent_cli.ai.models import AIRequest
from sohail_agent_cli.ai.orchestrator import AIOrchestrator
from sohail_agent_cli.ai.provider import ProviderSpec
from sohail_agent_cli.blueprint.models import Blueprint, BlueprintInput, BlueprintOutput


class BlueprintGenerator:
    """
    Generate structured blueprints through the AI Foundation.

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

    async def generate(self, blueprint_input: BlueprintInput) -> BlueprintOutput:
        """Generate a blueprint using exactly one AI Foundation call."""
        context = self.context_builder.build(blueprint_input.plan_directory)
        ai_result = await self.orchestrator.execute(
            AIRequest(
                task="write_blueprint",
                prompt_name="blueprint",
                context=context,
                instruction=self._build_instruction(blueprint_input),
                required_fields=("kind", "title", "summary", "items"),
                allowed_kinds=("blueprint",),
                max_retries=1,
            )
        )

        return BlueprintOutput(blueprint=Blueprint.from_ai_output(ai_result.output))

    def _build_instruction(self, blueprint_input: BlueprintInput) -> str:
        return "\n\n".join(
            [
                """
    You are generating a software implementation blueprint.

    Return ONLY valid JSON.

    Do NOT return Markdown.
    Do NOT wrap the JSON in ``` blocks.
    Do NOT include explanations.
    Return exactly one JSON object.

    The JSON MUST exactly match this schema:

    {
    "kind": "blueprint",
    "title": "<blueprint title>",
    "summary": "<short summary>",
    "items": [
        "<major blueprint item>",
        "<major blueprint item>"
    ],
    "metadata": {
        "system_design": "<system design>",
        "backend_architecture": "<backend architecture>",
        "frontend_architecture": "<frontend architecture>",
        "database_design": "<database design>",
        "api_flow": "<API flow>",
        "implementation_plan": "<implementation plan>",
        "folder_structure": "<folder structure>",
        "dependencies": "<dependencies>"
    }
    }

    Do not add any extra top-level keys.
    """,
                self._section("PROJECT_GOAL", blueprint_input.project_goal or ""),
                self._section("REQUIREMENTS_MD", blueprint_input.requirements_markdown),
                self._section("ARCHITECTURE_MD", blueprint_input.architecture_markdown),
                self._section("TASK_MD", blueprint_input.tasks_markdown),
                self._section(
                    "DECISIONS_MD",
                    "\n\n".join(
                        f"## {decision.filename}\n{decision.content}"
                        for decision in blueprint_input.decisions
                    ),
                ),
                self._section("PRODUCT_SPEC_MD", blueprint_input.product_spec_markdown),
                self._section("FEATURES_MD", blueprint_input.features_markdown),
                self._section("DATA_MODEL_MD", blueprint_input.data_model_markdown),
                self._section("API_SPEC_MD", blueprint_input.api_spec_markdown),
                self._section("NON_FUNCTIONAL_MD", blueprint_input.non_functional_markdown),
            ]
        )

    @staticmethod
    def _section(name: str, content: str) -> str:
        return f"<{name}>\n{content.strip()}\n</{name}>"
