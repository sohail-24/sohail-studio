"""Mock provider for testing without actual AI calls."""

from __future__ import annotations

from typing import AsyncIterator

from .base_provider import BaseProvider, GenerationRequest, GenerationResult, ProviderConfig


class MockProvider(BaseProvider):
    """
    Mock provider for testing.
    
    This provider returns predefined responses without making
    actual API calls. Useful for testing and development.
    """
    
    def __init__(
        self, 
        config: ProviderConfig | None = None,
        responses: dict[str, str] | None = None,
    ) -> None:
        """
        Initialize the mock provider.
        
        Args:
            config: Provider configuration
            responses: Dictionary mapping prompt patterns to responses
        """
        super().__init__(config)
        self.responses = responses or {}
        self.call_history: list[GenerationRequest] = []
    
    @property
    def name(self) -> str:
        """Get the provider name."""
        return "mock"
    
    @property
    def is_local(self) -> bool:
        """Check if this is a local provider."""
        return True
    
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """
        Generate a mock response.
        
        Args:
            request: The generation request
        
        Returns:
            A mock generation result
        """
        self.call_history.append(request)
        
        # Check for predefined response
        for pattern, response in self.responses.items():
            if pattern in request.prompt:
                return GenerationResult(
                    text=response,
                    model=request.model or self.config.default_model,
                    done=True,
                )
        
        # Default mock response
        return GenerationResult(
            text=f"[Mock response for: {request.prompt[:50]}...]",
            model=request.model or self.config.default_model,
            done=True,
        )
    
    async def generate_stream(
        self, 
        request: GenerationRequest,
    ) -> AsyncIterator[GenerationResult]:
        """
        Generate a mock streaming response.
        
        Args:
            request: The generation request
        
        Yields:
            Mock generation results
        """
        self.call_history.append(request)
        
        # Get the full response
        result = await self.generate(request)
        
        # Split into words for streaming effect
        words = result.text.split()
        
        for i, word in enumerate(words):
            chunk = word + (" " if i < len(words) - 1 else "")
            yield GenerationResult(
                text=chunk,
                model=result.model,
                done=i == len(words) - 1,
            )
    
    async def list_models(self) -> list[str]:
        """
        List mock available models.
        
        Returns:
            List of mock model names
        """
        return [
            "mock-llama3.2",
            "mock-codellama",
            "mock-mistral",
        ]
    
    async def health_check(self) -> bool:
        """
        Mock health check.
        
        Returns:
            Always True for mock
        """
        return True
    
    def add_response(self, pattern: str, response: str) -> None:
        """
        Add a predefined response.
        
        Args:
            pattern: The prompt pattern to match
            response: The response to return
        """
        self.responses[pattern] = response
    
    def clear_history(self) -> None:
        """Clear the call history."""
        self.call_history.clear()
