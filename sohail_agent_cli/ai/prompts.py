"""Versioned reusable prompt catalog and prompt builder."""

from __future__ import annotations

import json

from .models import ProjectContext, PromptTemplate


class PromptCatalog:
    """Catalog of reusable versioned AI prompts."""

    _TEMPLATES: dict[str, PromptTemplate] = {
        "planning": PromptTemplate(
            name="planning",
            version="v1",
            system="You are an engineering planning assistant. Return JSON only.",
            user=(
                "Use the project context to produce planning output with keys: "
                "kind, title, summary, items, metadata."
            ),
        ),
        "specification": PromptTemplate(
            name="specification",
            version="v1",
            system="You extract precise software specifications. Return JSON only.",
            user="Extract requirements and constraints from the provided context.",
        ),
        "blueprint": PromptTemplate(
            name="blueprint",
            version="v1",
            system="You suggest software blueprints. Return JSON only.",
            user="Create a concise architecture blueprint from the context.",
        ),
        "feature": PromptTemplate(
            name="feature",
            version="v1",
            system="You suggest implementation-neutral feature slices. Return JSON only.",
            user="Suggest feature slices without writing project files.",
        ),
        "documentation": PromptTemplate(
            name="documentation",
            version="v1",
            system="You summarize engineering documentation. Return JSON only.",
            user="Generate documentation guidance from the context.",
        ),
    }

    def get(self, name: str) -> PromptTemplate:
        """Return a prompt template by name."""
        if name not in self._TEMPLATES:
            raise KeyError(f"Unknown prompt template: {name}")
        return self._TEMPLATES[name]

    def names(self) -> tuple[str, ...]:
        """Return available prompt names."""
        return tuple(sorted(self._TEMPLATES))


class PromptBuilder:
    """Build provider-ready prompt text from templates and context."""

    def __init__(self, catalog: PromptCatalog | None = None) -> None:
        self.catalog = catalog or PromptCatalog()

    def build(
        self,
        prompt_name: str,
        context: ProjectContext | None = None,
        instruction: str = "",
    ) -> tuple[PromptTemplate, str]:
        """Return the selected template and user prompt."""
        template = self.catalog.get(prompt_name)
        payload = {
            "instruction": instruction,
            "context": context.to_prompt_data() if context else {},
            "response_contract": {
                "kind": "string enum",
                "title": "short string",
                "summary": "string",
                "items": "array of strings",
                "metadata": "object",
            },
        }
        return template, f"{template.user}\n\n{json.dumps(payload, indent=2, sort_keys=True)}"
