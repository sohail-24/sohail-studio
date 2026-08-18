"""Blueprint Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base_agent import AgentResult, BaseAgent
from sohail_agent_cli.blueprint.loader import BlueprintLoader
from sohail_agent_cli.blueprint.writer import BlueprintWriter
from sohail_agent_cli.generators.blueprint_generator import BlueprintGenerator


class BlueprintAgent(BaseAgent):
    """Generate structured blueprint files from planning and specification packages."""

    def __init__(
        self,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        super().__init__(
            name="BlueprintAgent",
            description=(
                "Generate V1 system, architecture, database, API, and implementation blueprints."
            ),
            dry_run=dry_run,
            verbose=verbose,
        )
        self.loader = BlueprintLoader()
        self.generator = BlueprintGenerator(verbose=verbose)
        self.writer = BlueprintWriter()

    async def execute(
        self,
        plan_dir: Path,
        spec_dir: Path,
        output_dir: Path,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute the BlueprintAgent V1 pipeline."""
        try:
            output_dir = Path(output_dir)
            if output_dir.exists() and not output_dir.is_dir():
                return AgentResult.failure(f"Output path is not a directory: {output_dir}")

            blueprint_input = self.loader.load(plan_dir, spec_dir)
            output = await self.generator.generate(blueprint_input)
            targets = self.writer.prepare(output_dir, output)
            conflicts = self.writer.conflicts(targets, overwrite=overwrite)
            if conflicts:
                return AgentResult.failure(
                    "Blueprint files were not written because output conflicts were found",
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
                        message="Blueprint generation is incomplete because a file write failed",
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
                f"Blueprint files created at {output_dir.resolve()}",
                files_created=created + overwritten,
                data={
                    "created_files": [str(path) for path in created],
                    "overwritten_files": [str(path) for path in overwritten],
                    "output_dir": str(output_dir.resolve()),
                },
            )
        except Exception as exc:
            if self.verbose:
                self.error(f"Blueprint generation failed: {exc}")
            return AgentResult.failure("Blueprint generation failed", error=str(exc))
