import pytest

from sohail_agent_cli.ai.exceptions import AIValidationError
from sohail_agent_cli.ai.models import AIRequest, AIStructuredOutput
from sohail_agent_cli.ai.orchestrator import AIOrchestrator
from sohail_agent_cli.providers import GenerationRequest, GenerationResult, MockProvider


@pytest.mark.asyncio
async def test_orchestrator_returns_dataclass_output():
    provider = MockProvider(
        responses={
            "response_contract": (
                '{"kind":"documentation","title":"Docs","summary":"Write docs.",'
                '"items":["README"],"metadata":{"source":"test"}}'
            )
        }
    )
    result = await AIOrchestrator(provider=provider).execute(
        AIRequest(task="generate_documentation")
    )
    assert isinstance(result.output, AIStructuredOutput)
    assert result.output.kind == "documentation"
    assert result.output.items == ("README",)
    assert result.metadata.provider == "mock"
    assert result.metadata.attempts == 1


@pytest.mark.asyncio
async def test_orchestrator_retries_invalid_outputs():
    class FlakyProvider(MockProvider):
        async def generate(self, request: GenerationRequest) -> GenerationResult:
            self.call_history.append(request)
            if len(self.call_history) == 1:
                return GenerationResult(text="not json", model="mock")
            return GenerationResult(
                text='{"kind":"planning","title":"Plan","summary":"Ok","items":[]}',
                model="mock",
            )

    result = await AIOrchestrator(provider=FlakyProvider()).execute(
        AIRequest(task="generate_architecture", max_retries=1)
    )
    assert result.output.kind == "planning"
    assert result.metadata.attempts == 2


@pytest.mark.asyncio
async def test_orchestrator_retry_uses_stricter_json_instruction():
    class FlakyProvider(MockProvider):
        async def generate(self, request: GenerationRequest) -> GenerationResult:
            self.call_history.append(request)
            if len(self.call_history) == 1:
                return GenerationResult(text="not json", model="mock")
            return GenerationResult(
                text='{"kind":"planning","title":"Plan","summary":"Ok","items":[]}',
                model="mock",
            )

    provider = FlakyProvider()
    await AIOrchestrator(provider=provider).execute(
        AIRequest(task="generate_architecture", max_retries=1)
    )
    assert "Return ONLY valid JSON" in provider.call_history[1].prompt


@pytest.mark.asyncio
async def test_orchestrator_fails_after_retries():
    provider = MockProvider(responses={"response_contract": "not json"})
    with pytest.raises(AIValidationError):
        await AIOrchestrator(provider=provider).execute(
            AIRequest(task="generate_documentation", max_retries=1)
        )
