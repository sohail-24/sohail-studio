"""Stack selection logic."""

from __future__ import annotations

from .models import StackPlan, StackSelection
from .registry import StackRegistry


class StackSelector:
    """Convert PlanningAgent choices into supported StackGenerator selections."""

    def __init__(self, registry: StackRegistry | None = None) -> None:
        self.registry = registry or StackRegistry()

    def select(self, plan: StackPlan) -> StackSelection:
        """Return normalized supported stack choices."""
        selection = StackSelection(
            frontend=self.registry.normalize_frontend(plan.frontend),
            backend=self.registry.normalize_backend(plan.backend),
            database=self.registry.normalize_database(plan.database),
        )
        if not any((selection.frontend, selection.backend, selection.database)):
            raise ValueError("No supported stack components were selected")
        return selection
