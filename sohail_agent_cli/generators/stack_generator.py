"""Technology stack skeleton generator."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from sohail_agent_cli.stack.backend import BackendSkeletons
from sohail_agent_cli.stack.database import DatabaseSkeletons
from sohail_agent_cli.stack.frontend import FrontendSkeletons
from sohail_agent_cli.stack.loader import StackPlanLoader
from sohail_agent_cli.stack.models import StackPlan, StackSelection, StackSkeleton
from sohail_agent_cli.stack.selector import StackSelector


@dataclass(slots=True)
class StackGenerationResult:
    """Result returned after generating stack skeleton content."""

    success: bool
    plan: StackPlan
    selection: StackSelection
    files: OrderedDict[Path, str] = field(default_factory=OrderedDict)
    warnings: list[str] = field(default_factory=list)


class StackGenerator:
    """
    Generate technology-specific skeleton files from a PlanningAgent package.

    Pipeline:

        Load Plan
            ↓
        Select Supported Stack
            ↓
        Generate Skeleton Files
            ↓
        Validate File Map
    """

    def __init__(self) -> None:
        self.loader = StackPlanLoader()
        self.selector = StackSelector()
        self.frontend = FrontendSkeletons()
        self.backend = BackendSkeletons()
        self.database = DatabaseSkeletons()

    def generate(self, plan_directory: Path) -> StackGenerationResult:
        """Generate a deterministic file map from a planning package."""
        plan = self.loader.load(plan_directory)
        selection = self.selector.select(plan)
        files: OrderedDict[Path, str] = OrderedDict()

        files.update(self.frontend.generate(selection.frontend))
        files.update(self.backend.generate(selection.backend))
        files.update(self.database.generate(selection.database))

        skeleton = StackSkeleton(files=files)
        skeleton.validate()

        return StackGenerationResult(
            success=True,
            plan=plan,
            selection=selection,
            files=skeleton.files,
        )
