"""Parse validated AI responses into dataclasses."""

from __future__ import annotations

from typing import Any

from .exceptions import AIParseError
from .models import AIStructuredOutput


class AIResponseParser:
    """Convert validated response dictionaries into dataclasses."""

    def parse_structured_output(self, data: dict[str, Any]) -> AIStructuredOutput:
        """Parse a validated JSON object into AIStructuredOutput."""
        try:
            return AIStructuredOutput(
                kind=str(data["kind"]),
                title=str(data["title"]),
                summary=str(data["summary"]),
                items=tuple(str(item) for item in data.get("items", [])),
                metadata=dict(data.get("metadata", {})),
            )
        except Exception as exc:
            raise AIParseError(str(exc)) from exc
