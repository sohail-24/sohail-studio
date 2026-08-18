"""AI task registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class AIRoute:
    """Route from an AI task to a prompt template."""

    task: str
    prompt_name: str
    description: str


class AITaskRegistry:
    """Small deterministic registry for AI task routing."""

    def __init__(self) -> None:
        self._routes: dict[str, AIRoute] = {
            "extract_entities": AIRoute(
                "extract_entities", "blueprint", "Extract entities from context"
            ),
            "generate_documentation": AIRoute(
                "generate_documentation", "documentation", "Generate documentation guidance"
            ),
            "generate_architecture": AIRoute(
                "generate_architecture", "planning", "Generate architecture guidance"
            ),
            "generate_features": AIRoute(
                "generate_features", "feature", "Generate feature suggestions"
            ),
            "write_specification": AIRoute(
                "write_specification", "specification", "Generate specification guidance"
            ),
        }

    def resolve(self, task: str) -> AIRoute:
        """Resolve a task name to an AI route."""
        normalized = task.strip().lower()
        if normalized not in self._routes:
            raise KeyError(f"Unknown AI task: {task}")
        return self._routes[normalized]

    def routes(self) -> tuple[AIRoute, ...]:
        """Return all routes."""
        return tuple(self._routes[key] for key in sorted(self._routes))
