"""AI request router."""

from __future__ import annotations

from dataclasses import replace

from .models import AIRequest
from .registry import AITaskRegistry


class AIRouter:
    """Route AI requests to the correct prompt template."""

    def __init__(self, registry: AITaskRegistry | None = None) -> None:
        self.registry = registry or AITaskRegistry()

    def route(self, request: AIRequest) -> AIRequest:
        """Return a request with a prompt selected from the task registry."""
        if request.prompt_name:
            return request
        route = self.registry.resolve(request.task)
        return replace(request, prompt_name=route.prompt_name)
