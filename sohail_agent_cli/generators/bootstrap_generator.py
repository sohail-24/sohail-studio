"""Bootstrap project generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sohail_agent_cli.bootstrap.loader import BootstrapPlan, PlanningLoader
from sohail_agent_cli.bootstrap.scaffold import ProjectScaffold
from sohail_agent_cli.bootstrap.templates import ProjectTemplates
from sohail_agent_cli.bootstrap.validator import PlanningValidator


@dataclass(slots=True)
class BootstrapResult:
    """
    Result returned after bootstrapping a project.
    """

    success: bool
    project_directory: Path
    created_paths: list[Path] = field(default_factory=list)
    loaded_decisions: int = 0
    warnings: list[str] = field(default_factory=list)


class BootstrapGenerator:
    """
    Coordinates the complete Bootstrap pipeline.

    Pipeline:

        Validate
            ↓
        Load Plan
            ↓
        Create Scaffold
            ↓
        Populate Templates
            ↓
        Return Result
    """

    def __init__(self) -> None:
        self.validator = PlanningValidator()
        self.loader = PlanningLoader()
        self.scaffold = ProjectScaffold()

    def generate(
        self,
        plan_directory: Path,
        output_directory: Path,
        overwrite: bool = False,
    ) -> BootstrapResult:
        """
        Generate a project scaffold from a planning package.
        """

        self.validator.validate(plan_directory)

        plan = self.loader.load(plan_directory)

        created_paths = self.scaffold.create(
            output_directory,
            overwrite=overwrite,
        )

        self._write_templates(
            output_directory,
            overwrite=overwrite,
        )

        return BootstrapResult(
            success=True,
            project_directory=output_directory.resolve(),
            created_paths=created_paths,
            loaded_decisions=len(plan.decisions),
        )

    def _write_templates(
        self,
        output_directory: Path,
        overwrite: bool,
    ) -> None:
        """
        Populate scaffold files with template content.
        """

        templates = ProjectTemplates.as_dict()

        for filename, content in templates.items():

            file_path = output_directory / filename

            if file_path.exists() and not overwrite:
                continue

            file_path.write_text(
                content,
                encoding="utf-8",
            )