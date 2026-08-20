from fastapi.testclient import TestClient

import backend.main as main
from sohail_agent_cli.providers import GenerationResult


class FakeProvider:
    def __init__(self):
        self.requests = []

    async def generate_stream(self, request):
        self.requests.append(request)
        yield GenerationResult("The date came from the local read-only tool.", request.model or "", done=False)
        yield GenerationResult("", request.model or "", done=True, total_duration_ms=1)


def test_chat_passes_read_only_context_to_ollama_without_exposing_protocol(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(main, "chat_provider", provider)

    with TestClient(main.app) as client:
        with client.websocket_connect("/ws/chat") as websocket:
            assert websocket.receive_json()["transport"] == "ollama-api"
            websocket.send_json({"action": "input", "data": "What is today's date?\n"})
            output = websocket.receive_json()
            complete = websocket.receive_json()

    request = provider.requests[0]
    assert output["type"] == "output"
    assert output["message"] == "The date came from the local read-only tool."
    assert complete["status"] == "completed"
    assert complete["timing"]["tool_names"] == ["local_time"]
    assert complete["timing"]["tool_ms"] >= 0
    assert request.system.startswith("You are the Sohail Studio assistant.")
    assert request.messages[1]["role"] == "system"
    assert "local_time" in request.messages[1]["content"]
