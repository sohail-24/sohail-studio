"""Provider selection for the AI orchestration layer."""

from __future__ import annotations

from dataclasses import dataclass

from sohail_agent_cli.providers import BaseProvider, MockProvider, OllamaProvider, ProviderConfig

from .exceptions import AIProviderError


@dataclass(slots=True, frozen=True)
class ProviderSpec:
    """Provider selection request."""

    name: str = "mock"
    model: str | None = None


class AIProviderFactory:
    """Create supported provider instances for orchestration."""

    SUPPORTED = ("mock", "ollama")
    PLACEHOLDERS = ("openai", "anthropic", "gemini")

    def create(
        self,
        spec: ProviderSpec | None = None,
        provider: BaseProvider | None = None,
    ) -> BaseProvider:
        """Return an explicit provider or construct one from a spec."""
        if provider is not None:
            return provider

        spec = spec or ProviderSpec()
        normalized = spec.name.strip().lower()
        config = ProviderConfig(default_model=spec.model or ProviderConfig().default_model)

        if normalized == "mock":
            return MockProvider(config=config)
        if normalized == "ollama":
            return OllamaProvider(config=config)
        if normalized in self.PLACEHOLDERS:
            raise AIProviderError(f"Provider placeholder is not implemented: {normalized}")
        raise AIProviderError(f"Unknown provider: {spec.name}")
