"""Exceptions for the reusable AI orchestration layer."""

from __future__ import annotations


class AIError(Exception):
    """Base exception for AI infrastructure failures."""


class AIProviderError(AIError):
    """Raised when provider selection or execution fails."""


class AIValidationError(AIError):
    """Raised when an AI response fails validation."""


class AIParseError(AIError):
    """Raised when an AI response cannot be parsed into a model."""


class AIContextError(AIError):
    """Raised when project context cannot be built."""


class AIMemoryError(AIError):
    """Raised when project memory cannot be loaded or serialized."""
