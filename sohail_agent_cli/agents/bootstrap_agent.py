"""Bootstrap Agent."""

from __future__ import annotations

from pathlib import Path

from .base_agent import BaseAgent, AgentResult
from sohail_agent_cli.generators.bootstrap_generator import BootstrapGenerator


class BootstrapAgent(BaseAgent):
    """Bootstrap a project from a PlanningAgent package."""

    def __init__(
        self,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        super().__init__(
            name="BootstrapAgent",
            description="Generate a project scaffold from a planning package.",
            dry_run=dry_run,
            verbose=verbose,
        )
        self.generator = BootstrapGenerator()

    async def execute(
        self,
        plan_dir: Path,
        output_dir: Path,
        overwrite: bool = False,
    ) -> AgentResult:
        """
        Execute the BootstrapAgent pipeline.
        """

        if self.dry_run:
            return AgentResult.success(
                success=True,
                message="Dry run completed.",
                files_created=[],
                warnings=[],
            )

        result = self.generator.generate(
            plan_directory=plan_dir,
            output_directory=output_dir,
            overwrite=overwrite,
        )

        return AgentResult.success(
            message="Bootstrap completed successfully.",
            files_created=result.created_paths,
            data={
                "project_directory": str(result.project_directory),
                "loaded_decisions": result.loaded_decisions,
            },
        )