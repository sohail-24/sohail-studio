import pytest

from sohail_agent_cli.providers import GenerationRequest, MockProvider


@pytest.mark.asyncio
async def test_mock_provider_returns_configured_response():
    provider = MockProvider(responses={"hello": "world"})
    result = await provider.generate(GenerationRequest(prompt="say hello"))
    assert result.success
    assert result.text == "world"
    assert provider.call_history[0].prompt == "say hello"


@pytest.mark.asyncio
async def test_mock_provider_health_check_is_true():
    assert await MockProvider().health_check() is True
