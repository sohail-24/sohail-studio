import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.cli_bridge import CONTROLLED_NEEDS_EVIDENCE_EXIT_CODE
from sohail_agent_cli import main as cli_main
from sohail_agent_cli.agents.base_agent import AgentResult


def test_dashboard_recognizes_all_controlled_needs_evidence_signals():
    source = Path("dashboard/app.js").read_text(encoding="utf-8")
    assert 'event.result_status === "NEEDS_EVIDENCE"' in source
    assert 'event.status === "needs_evidence"' in source
    assert 'state.selectedAgentOperation === "dockerize" && event.exit_code === 2' in source
    assert "[NEEDS_EVIDENCE · controlled outcome]" in source


@pytest.mark.asyncio
async def test_dockerize_cli_returns_controlled_needs_evidence_code(monkeypatch, tmp_path: Path):
    class FakeDockerAgent:
        def __init__(self, **_kwargs):
            pass

        async def execute(self, *_args, **_kwargs):
            return AgentResult.controlled("NEEDS_EVIDENCE", "frontend lacks production evidence")

    monkeypatch.setattr(cli_main, "DockerAgent", FakeDockerAgent)
    args = argparse.Namespace(
        path=str(tmp_path),
        port=None,
        dry_run=True,
        verbose=False,
        overwrite=False,
        component=None,
        compose_action="keep",
        compose=True,
    )

    assert await cli_main.cmd_dockerize(args) == CONTROLLED_NEEDS_EVIDENCE_EXIT_CODE


@pytest.mark.asyncio
async def test_backend_agent_run_preserves_needs_evidence_status(monkeypatch, tmp_path: Path):
    import backend.main as api

    async def fake_stream(_command, _provider="", _model=""):
        yield "output", "Dockerize needs evidence: frontend lacks production evidence\n"
        yield "exit", str(CONTROLLED_NEEDS_EVIDENCE_EXIT_CODE)

    monkeypatch.setattr(api.cli, "stream", fake_stream)
    monkeypatch.setattr(api.store, "write", lambda *_args, **_kwargs: None)
    state = api.RunState("controlled-status-test", "dockerize", str(tmp_path))

    await api.runs._stream_command(
        state,
        SimpleNamespace(provider="", model=""),
        SimpleNamespace(display="dockerize", purpose="test"),
    )

    complete = next(event for event in state.events if event["type"] == "complete")
    output = "".join(event["message"] for event in state.events if event["type"] == "output")
    assert complete["status"] == "needs_evidence"
    assert complete["result_status"] == "NEEDS_EVIDENCE"
    assert complete["exit_code"] == CONTROLLED_NEEDS_EVIDENCE_EXIT_CODE
    assert "frontend lacks production evidence" in output


@pytest.mark.asyncio
async def test_backend_agent_run_keeps_unexpected_exit_as_failed(monkeypatch, tmp_path: Path):
    import backend.main as api

    async def fake_stream(_command, _provider="", _model=""):
        yield "output", "unexpected failure\n"
        yield "exit", "1"

    monkeypatch.setattr(api.cli, "stream", fake_stream)
    monkeypatch.setattr(api.store, "write", lambda *_args, **_kwargs: None)
    state = api.RunState("failed-status-test", "dockerize", str(tmp_path))

    await api.runs._stream_command(
        state,
        SimpleNamespace(provider="", model=""),
        SimpleNamespace(display="dockerize", purpose="test"),
    )

    complete = next(event for event in state.events if event["type"] == "complete")
    assert complete["status"] == "failed"
    assert complete["result_status"] == "FAILED"
    assert complete["exit_code"] == 1
