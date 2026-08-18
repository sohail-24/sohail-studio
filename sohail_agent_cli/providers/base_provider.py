"""Base provider for AI model backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import os
from typing import Any, AsyncIterator


@dataclass
class ProviderConfig:
    """Configuration for an AI provider."""
    base_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    api_key: str | None = None
    timeout: float = 60.0
    max_retries: int = 3
    default_model: str = field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.2")
    )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_model": self.default_model,
        }


@dataclass
class GenerationRequest:
    """Request for text generation."""
    prompt: str
    model: str | None = None
    system: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False
    context: list[int] | None = None
    options: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert request to dictionary."""
        data: dict[str, Any] = {
            "prompt": self.prompt,
            "temperature": self.temperature,
            "stream": self.stream,
        }
        if self.model:
            data["model"] = self.model
        if self.system:
            data["system"] = self.system
        if self.max_tokens:
            data["max_tokens"] = self.max_tokens
        if self.context:
            data["context"] = self.context
        if self.options:
            data["options"] = self.options
        return data


@dataclass
class GenerationResult:
    """Result of text generation."""
    text: str
    model: str
    done: bool = True
    context: list[int] | None = None
    total_duration_ms: float | None = None
    load_duration_ms: float | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    error: str | None = None
    
    @property
    def success(self) -> bool:
        """Check if generation was successful."""
        return self.error is None
    
    @classmethod
    def error_result(cls, error: str, model: str = "") -> GenerationResult:
        """Create an error result."""
        return cls(
            text="",
            model=model,
            error=error,
            done=True,
        )


class BaseProvider(ABC):
    """
    Abstract base class for AI model providers.
    
    Providers implement the interface for interacting with
    different AI model backends (Ollama, OpenAI, etc.).
    """
    
    def __init__(self, config: ProviderConfig | None = None) -> None:
        """
        Initialize the provider.
        
        Args:
            config: Provider configuration
        """
        self.config = config or ProviderConfig()
    
    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """
        Generate text from a prompt.
        
        Args:
            request: The generation request
        
        Returns:
            The generation result
        """
        pass
    
    @abstractmethod
    async def generate_stream(
        self, 
        request: GenerationRequest,
    ) -> AsyncIterator[GenerationResult]:
        """
        Generate text with streaming.
        
        Args:
            request: The generation request
        
        Yields:
            Generation results as they become available
        """
        pass
    
    @abstractmethod
    async def list_models(self) -> list[str]:
        """
        List available models.
        
        Returns:
            List of model names
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the provider is healthy.
        
        Returns:
            True if the provider is available
        """
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Get the provider name."""
        pass
    
    @property
    @abstractmethod
    def is_local(self) -> bool:
        """Check if this is a local provider."""
        pass
