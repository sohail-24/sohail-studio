"""Validation helpers for AI responses."""

from __future__ import annotations

import json
import re
from typing import Any

from .exceptions import AIValidationError


class AIResponseValidator:
    """Validate AI JSON responses before parsing."""

    def validate_json_object(
        self,
        text: str,
        required_fields: tuple[str, ...],
        allowed_kinds: tuple[str, ...],
        allowed_keys: tuple[str, ...] = ("kind", "title", "summary", "items", "metadata"),
    ) -> dict[str, Any]:
        """Validate response text and return a JSON object."""
        if not text.strip():
            raise AIValidationError("AI response is empty")

        json_text = self.extract_json_object_text(text)
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise AIValidationError(f"AI response is not valid JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise AIValidationError("AI response must be a JSON object")

        unknown = sorted(set(data) - set(allowed_keys))
        if unknown:
            raise AIValidationError(f"AI response contains unknown keys: {unknown}")

        missing = [field for field in required_fields if field not in data]
        if missing:
            raise AIValidationError(f"AI response missing required fields: {missing}")

        if "kind" in data and data["kind"] not in allowed_kinds:
            raise AIValidationError(f"AI response has invalid kind: {data['kind']}")

        if "items" in data and not isinstance(data["items"], list):
            raise AIValidationError("AI response field 'items' must be a list")

        for field in ("kind", "title", "summary"):
            if field in data and not str(data[field]).strip():
                raise AIValidationError(f"AI response field '{field}' cannot be empty")

        return data

    def extract_json_object_text(self, text: str) -> str:
        """
        Extract a JSON object from provider text without inventing content.

        Models may return fenced JSON, prefaces, or trailing explanations.
        This method returns the first parseable JSON object string it can
        recover, or the stripped input so the existing JSON validation error is
        preserved.
        """
        stripped = text.strip()
        if self._is_json_object(stripped):
            return stripped

        for fenced in self._fenced_json_candidates(stripped):
            if self._is_json_object(fenced):
                return fenced

        balanced = self._first_balanced_object(stripped)
        if balanced and self._is_json_object(balanced):
            return balanced

        return stripped

    @staticmethod
    def _fenced_json_candidates(text: str) -> list[str]:
        return [
            match.group(1).strip()
            for match in re.finditer(
                r"```(?:json|JSON)?\s*(.*?)```",
                text,
                flags=re.DOTALL,
            )
        ]

    @staticmethod
    def _is_json_object(text: str) -> bool:
        try:
            return isinstance(json.loads(text), dict)
        except json.JSONDecodeError:
            return False

    @staticmethod
    def _first_balanced_object(text: str) -> str | None:
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]

        return None
