"""Ollama provider for local AI model integration."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from .base_provider import BaseProvider, GenerationRequest, GenerationResult, ProviderConfig


class OllamaProvider(BaseProvider):
    """
    Provider for Ollama local AI models.

    The public provider interface remains prompt/result based, while this
    implementation uses Ollama's modern Chat API internally.
    """

    def __init__(self, config: ProviderConfig | None = None) -> None:
        """
        Initialize the Ollama provider.

        Args:
            config: Provider configuration with Ollama-specific settings
        """
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        """Get the provider name."""
        return "ollama"

    @property
    def is_local(self) -> bool:
        """Check if this is a local provider."""
        return True

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
            )
        return self._client

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """
        Generate text using Ollama Chat API.

        Args:
            request: The generation request

        Returns:
            The generation result
        """
        client = self._get_client()
        model = request.model or self.config.default_model
        payload = self._build_chat_payload(request, model=model, stream=False)

        try:
            response = await client.post("/api/chat", json=payload)
            response.raise_for_status()

            data = response.json()
            message = data.get("message") or {}

            return GenerationResult(
                text=message.get("content", ""),
                model=data.get("model") or model,
                done=data.get("done", True),
                total_duration_ms=data.get("total_duration", 0) / 1_000_000,
                load_duration_ms=data.get("load_duration", 0) / 1_000_000,
                prompt_eval_count=data.get("prompt_eval_count"),
                eval_count=data.get("eval_count"),
            )

        except httpx.HTTPStatusError as exc:
            return GenerationResult.error_result(
                self._http_error_message(exc, model),
                model=model,
            )
        except httpx.ConnectError:
            return GenerationResult.error_result(
                f"Cannot connect to Ollama at {self.config.base_url}. "
                f"Is Ollama running? Model requested: {model}",
                model=model,
            )
        except Exception as exc:
            return GenerationResult.error_result(
                f"Ollama chat generation failed for model '{model}' "
                f"at {self.config.base_url}: {exc}",
                model=model,
            )

    async def generate_stream(
        self,
        request: GenerationRequest,
    ) -> AsyncIterator[GenerationResult]:
        """
        Generate text with streaming from Ollama Chat API.

        Args:
            request: The generation request

        Yields:
            Generation results as they become available
        """
        client = self._get_client()
        model = request.model or self.config.default_model
        payload = self._build_chat_payload(request, model=model, stream=True)

        try:
            async with client.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError as exc:
                        yield GenerationResult.error_result(
                            f"Ollama returned malformed streaming JSON: {exc}",
                            model=model,
                        )
                        return

                    message = data.get("message") or {}
                    yield GenerationResult(
                        text=message.get("content", ""),
                        model=data.get("model") or model,
                        done=data.get("done", False),
                        total_duration_ms=data.get("total_duration", 0) / 1_000_000,
                        load_duration_ms=data.get("load_duration", 0) / 1_000_000,
                        prompt_eval_count=data.get("prompt_eval_count"),
                        eval_count=data.get("eval_count"),
                    )

        except httpx.HTTPStatusError as exc:
            yield GenerationResult.error_result(
                self._http_error_message(exc, model),
                model=model,
            )
        except httpx.ConnectError:
            yield GenerationResult.error_result(
                f"Cannot connect to Ollama at {self.config.base_url}. "
                f"Is Ollama running? Model requested: {model}",
                model=model,
            )
        except Exception as exc:
            yield GenerationResult.error_result(
                f"Ollama chat streaming failed for model '{model}' "
                f"at {self.config.base_url}: {exc}",
                model=model,
            )

    def _build_chat_payload(
        self,
        request: GenerationRequest,
        model: str,
        stream: bool,
    ) -> dict[str, Any]:
        """Translate GenerationRequest into an Ollama Chat API payload."""
        options = dict(request.options)
        response_format = options.pop("format", None)
        if request.max_tokens is not None:
            options.setdefault("num_predict", request.max_tokens)

        messages: list[dict[str, str]] = [
            {"role": message["role"], "content": message["content"]}
            for message in (request.messages or [])
        ]
        if request.system and (
            not messages
            or messages[0].get("role") != "system"
            or messages[0].get("content") != request.system
        ):
            messages.insert(0, {"role": "system", "content": request.system})
        if request.prompt and not any(
            message.get("role") == "user" and message.get("content") == request.prompt
            for message in messages
        ):
            messages.append({"role": "user", "content": request.prompt})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": request.temperature,
                **options,
            },
        }
        if response_format:
            payload["format"] = response_format
        if request.think is not None:
            payload["think"] = request.think
        return payload

    def _http_error_message(self, exc: httpx.HTTPStatusError, model: str) -> str:
        return (
            f"Ollama HTTP error {exc.response.status_code} for model '{model}' "
            f"at {self.config.base_url}: {exc.response.text}"
        )

    async def list_models(self) -> list[str]:
        """
        List available Ollama models.

        Returns:
            List of model names
        """
        client = self._get_client()

        try:
            response = await client.get("/api/tags")
            response.raise_for_status()

            data = response.json()
            models = data.get("models", [])

            return [model.get("name", "") for model in models if model.get("name")]

        except Exception:
            return []

    async def health_check(self) -> bool:
        """
        Check if Ollama is running.

        Returns:
            True if Ollama is available
        """
        client = self._get_client()

        try:
            response = await client.get("/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    async def pull_model(self, model: str) -> bool:
        """
        Pull a model from Ollama.

        Args:
            model: The model name to pull

        Returns:
            True if successful
        """
        client = self._get_client()

        try:
            response = await client.post(
                "/api/pull",
                json={"name": model, "stream": False},
            )
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
