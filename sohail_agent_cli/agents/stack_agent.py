"""Stack Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base_agent import AgentResult, BaseAgent
from sohail_agent_cli.generators.stack_generator import StackGenerator
from sohail_agent_cli.stack.project_writer import StackProjectWriter


class StackAgent(BaseAgent):
    """Generate technology stack skeletons from a PlanningAgent package."""

    def __init__(
        self,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        super().__init__(
            name="StackAgent",
            description="Generate frontend, backend, and database stack skeletons.",
            dry_run=dry_run,
            verbose=verbose,
        )
        self.generator = StackGenerator()
        self.writer = StackProjectWriter()

    async def execute(
        self,
        plan_dir: Path,
        output_dir: Path,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute the StackAgent generation pipeline."""
        try:
            output_dir = Path(output_dir)
            if output_dir.exists() and not output_dir.is_dir():
                return AgentResult.failure(f"Output path is not a directory: {output_dir}")

            result = self.generator.generate(plan_dir)
            targets = self.writer.prepare(output_dir, result.files)
            conflicts = self.writer.conflicts(targets, overwrite=overwrite)
            if conflicts:
                return AgentResult.failure(
                    "Stack skeleton was not written because output conflicts were found",
                    error="; ".join(str(path) for path in conflicts),
                )

            if self.dry_run:
                for target in targets:
                    action = "overwrite" if target.target_path.exists() else "create"
                    self.info(f"[DRY RUN] Would {action} {target.target_path}")
                return AgentResult.success(
                    "Dry run complete; no files were modified",
                    data={
                        "dry_run": True,
                        "dry_run_files": [str(target.target_path) for target in targets],
                        "frontend": result.selection.frontend,
                        "backend": result.selection.backend,
                        "database": result.selection.database,
                    },
                )

            created: list[Path] = []
            overwritten: list[Path] = []
            for target in targets:
                existed = target.target_path.exists()
                success, message, is_dry_run = await self.write_file(
                    target.target_path,
                    target.content,
                    overwrite=overwrite,
                )
                if not success or is_dry_run:
                    return AgentResult(
                        success=False,
                        message="Stack skeleton is incomplete because a file write failed",
                        error=message,
                        files_created=created + overwritten,
                        files_skipped=[target.target_path],
                        data={
                            "created_files": [str(path) for path in created],
                            "overwritten_files": [str(path) for path in overwritten],
                            "failed_file": str(target.target_path),
                        },
                    )
                if existed:
                    overwritten.append(target.target_path)
                else:
                    created.append(target.target_path)
                self.success(message)

            return AgentResult.success(
                f"Stack skeleton created at {output_dir.resolve()}",
                files_created=created + overwritten,
                data={
                    "created_files": [str(path) for path in created],
                    "overwritten_files": [str(path) for path in overwritten],
                    "frontend": result.selection.frontend,
                    "backend": result.selection.backend,
                    "database": result.selection.database,
                },
            )
        except Exception as exc:
            if self.verbose:
                self.error(f"Stack generation failed: {exc}")
            return AgentResult.failure("Stack generation failed", error=str(exc))
