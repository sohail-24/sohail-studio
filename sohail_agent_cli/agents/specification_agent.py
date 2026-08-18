"""Specification Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base_agent import AgentResult, BaseAgent
from sohail_agent_cli.generators.specification_generator import SpecificationGenerator
from sohail_agent_cli.specification.loader import SpecificationLoader
from sohail_agent_cli.specification.writer import SpecificationWriter


class SpecificationAgent(BaseAgent):
    """Generate structured specification files from a PlanningAgent package."""

    def __init__(
        self,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        super().__init__(
            name="SpecificationAgent",
            description="Generate V1 product, feature, data, API, and NFR specs.",
            dry_run=dry_run,
            verbose=verbose,
        )
        self.loader = SpecificationLoader()
        self.generator = SpecificationGenerator(verbose=verbose)
        self.writer = SpecificationWriter()

    async def execute(
        self,
        plan_dir: Path,
        output_dir: Path,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute the SpecificationAgent V1 pipeline."""
        try:
            output_dir = Path(output_dir)
            if output_dir.exists() and not output_dir.is_dir():
                return AgentResult.failure(f"Output path is not a directory: {output_dir}")

            specification_input = self.loader.load(plan_dir)
            output = await self.generator.generate(specification_input)
            targets = self.writer.prepare(output_dir, output)
            conflicts = self.writer.conflicts(targets, overwrite=overwrite)
            if conflicts:
                return AgentResult.failure(
                    "Specification files were not written because output conflicts were found",
                    error="; ".join(str(path) for path in conflicts),
                )

            if self.dry_run:
                for target in targets:
                    action = "overwrite" if target.path.exists() else "create"
                    self.info(f"[DRY RUN] Would {action} {target.path}")
                return AgentResult.success(
                    "Dry run complete; no files were modified",
                    data={
                        "dry_run": True,
                        "dry_run_files": [str(target.path) for target in targets],
                        "output_dir": str(output_dir.resolve()),
                    },
                )

            created: list[Path] = []
            overwritten: list[Path] = []
            for target in targets:
                existed = target.path.exists()
                success, message, is_dry_run = await self.write_file(
                    target.path,
                    target.content,
                    overwrite=overwrite,
                )
                if not success or is_dry_run:
                    return AgentResult(
                        success=False,
                        message="Specification generation is incomplete because a file write failed",
                        error=message,
                        files_created=created + overwritten,
                        files_skipped=[target.path],
                        data={
                            "created_files": [str(path) for path in created],
                            "overwritten_files": [str(path) for path in overwritten],
                            "failed_file": str(target.path),
                        },
                    )
                if existed:
                    overwritten.append(target.path)
                else:
                    created.append(target.path)
                self.success(message)

            return AgentResult.success(
                f"Specification files created at {output_dir.resolve()}",
                files_created=created + overwritten,
                data={
                    "created_files": [str(path) for path in created],
                    "overwritten_files": [str(path) for path in overwritten],
                    "output_dir": str(output_dir.resolve()),
                },
            )
        except Exception as exc:
            if self.verbose:
                self.error(f"Specification generation failed: {exc}")
            return AgentResult.failure("Specification generation failed", error=str(exc))
