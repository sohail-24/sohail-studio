import json

import httpx
import pytest

from sohail_agent_cli.providers import GenerationRequest, OllamaProvider, ProviderConfig


class FakeResponse:
    status_code = 200
    text = "ok"

    def __init__(self, data=None):
        self._data = data or {
            "model": "qwen3.5:latest",
            "message": {
                "role": "assistant",
                "content": '{"kind":"planning"}',
                "thinking": "internal reasoning",
            },
            "done": True,
        }

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class ErrorResponse:
    status_code = 500
    text = "server exploded"

    def raise_for_status(self):
        request = httpx.Request("POST", "http://localhost:11434/api/chat")
        response = httpx.Response(self.status_code, request=request, text=self.text)
        raise httpx.HTTPStatusError("bad", request=request, response=response)


class FakeClient:
    def __init__(self, response=None):
        self.posts = []
        self.response = response or FakeResponse()

    async def post(self, path, json):
        self.posts.append((path, json))
        return self.response


class FakeStreamResponse:
    def __init__(self, lines):
        self.lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class FakeStreamClient:
    def __init__(self):
        self.streams = []

    def stream(self, method, path, json):
        self.streams.append((method, path, json))
        return FakeStreamResponse(
            [
                json_module_dumps(
                    {
                        "model": "qwen3.5:latest",
                        "message": {"role": "assistant", "content": "hello "},
                        "done": False,
                    }
                ),
                json_module_dumps(
                    {
                        "model": "qwen3.5:latest",
                        "message": {"role": "assistant", "content": "world"},
                        "done": True,
                    }
                ),
            ]
        )


def json_module_dumps(data):
    return json.dumps(data)


@pytest.mark.asyncio
async def test_ollama_provider_uses_chat_api_and_extracts_message_content():
    client = FakeClient()
    provider = OllamaProvider(
        ProviderConfig(base_url="http://localhost:11434", default_model="qwen3.5:latest")
    )
    provider._client = client

    result = await provider.generate(GenerationRequest(prompt="Return JSON"))

    assert result.success
    assert result.text == '{"kind":"planning"}'
    assert result.model == "qwen3.5:latest"
    assert client.posts[0][0] == "/api/chat"
    assert client.posts[0][1]["messages"] == [
        {"role": "user", "content": "Return JSON"}
    ]


@pytest.mark.asyncio
async def test_ollama_provider_preserves_conversation_messages():
    client = FakeClient()
    provider = OllamaProvider(
        ProviderConfig(base_url="http://localhost:11434", default_model="qwen3.5:latest")
    )

    provider._client = client
    request = GenerationRequest(
        prompt="What did I ask?",
        messages=[
            {"role": "user", "content": "Remember this."},
            {"role": "assistant", "content": "I will."},
            {"role": "user", "content": "What did I ask?"},
        ],
    )
    await provider.generate(request)

    assert client.posts[0][1]["messages"] == request.messages


@pytest.mark.asyncio
async def test_ollama_provider_preserves_json_mode_and_options():
    client = FakeClient()
    provider = OllamaProvider(
        ProviderConfig(base_url="http://localhost:11434", default_model="llama3.2")
    )
    provider._client = client

    result = await provider.generate(
        GenerationRequest(
            prompt="Return JSON",
            system="Return structured data.",
            max_tokens=128,
            options={"format": "json", "num_ctx": 2048},
        )
    )

    assert result.success
    payload = client.posts[0][1]
    assert payload["format"] == "json"
    assert payload["options"]["num_ctx"] == 2048
    assert payload["options"]["num_predict"] == 128
    assert "format" not in payload["options"]
    assert payload["messages"][0] == {
        "role": "system",
        "content": "Return structured data.",
    }


@pytest.mark.asyncio
async def test_ollama_provider_streams_chat_message_content():
    client = FakeStreamClient()
    provider = OllamaProvider(
        ProviderConfig(base_url="http://localhost:11434", default_model="qwen3.5:latest")
    )
    provider._client = client

    chunks = [
        chunk
        async for chunk in provider.generate_stream(
            GenerationRequest(prompt="Stream", options={"format": "json"})
        )
    ]

    assert [chunk.text for chunk in chunks] == ["hello ", "world"]
    assert chunks[-1].done is True
    assert client.streams[0][0] == "POST"
    assert client.streams[0][1] == "/api/chat"
    assert client.streams[0][2]["format"] == "json"


@pytest.mark.asyncio
async def test_ollama_provider_reports_http_errors_with_diagnostics():
    client = FakeClient(response=ErrorResponse())
    provider = OllamaProvider(
        ProviderConfig(base_url="http://localhost:11434", default_model="qwen3.5:latest")
    )
    provider._client = client

    result = await provider.generate(GenerationRequest(prompt="fail"))

    assert not result.success
    assert result.model == "qwen3.5:latest"
    assert "HTTP error 500" in result.error
    assert "qwen3.5:latest" in result.error
    assert "http://localhost:11434" in result.error
