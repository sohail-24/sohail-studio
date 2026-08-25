import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from core.cli_bridge import CONTROLLED_NEEDS_CLARIFICATION_EXIT_CODE
from core.evidence import (
    ClarificationRequest,
    ClarificationRequestError,
    EvidenceOrigin,
    UserProvidedEvidence,
)
from core.storage.database import Storage, StorageConfig
from core.storage.project_intelligence import ProjectIntelligenceRepository, metadata
from sohail_agent_cli.agents.docker_agent import DockerAgent
from sohail_agent_cli.dockerize import DockerClarificationPolicy
from sohail_agent_cli.inspection import DeepInspector
from sohail_agent_cli.providers import GenerationResult, MockProvider


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def repository_for(root: Path) -> ProjectIntelligenceRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repository = ProjectIntelligenceRepository(
        Storage(StorageConfig("postgresql://masked@localhost/studio"), engine=engine)
    )
    repository.persist(DeepInspector().inspect(root))
    return repository


def request() -> ClarificationRequest:
    return ClarificationRequest(
        request_id="request-1",
        workflow="Dockerize",
        gap_id="gap-1",
        root_path="/tmp/project",
        component="service",
        requirement="production start command",
        question="What exact production start command should be used for service?",
        expected_answer_type="text",
        proposition="The production start command for service is exactly the value supplied in this clarification.",
    )


def test_clarification_contract_requires_a_bound_proposition_and_preserves_yes_no_meaning():
    with pytest.raises(ClarificationRequestError, match="proposition"):
        ClarificationRequest(
            request_id="1", workflow="Dockerize", gap_id="1", root_path="/tmp/project",
            component="service", requirement="fact", question="Should I continue?",
            expected_answer_type="yes_no", allowed_answers=("Yes", "No"), proposition="",
        )
    yes_no = ClarificationRequest(
        request_id="2", workflow="Dockerize", gap_id="2", root_path="/tmp/project",
        component="service", requirement="fact", question="Do you confirm proposition P?",
        expected_answer_type="yes_no", allowed_answers=("Yes", "No"),
        proposition="Proposition P is true for service.",
    )
    evidence = DockerClarificationPolicy.validate_answer(yes_no, "Yes")
    assert evidence.answer == "Yes"
    assert evidence.proposition == yes_no.proposition
    assert evidence.origin is EvidenceOrigin.USER_PROVIDED_EVIDENCE


def test_user_evidence_is_separate_and_ai_analysis_cannot_become_user_evidence():
    evidence = DockerClarificationPolicy.validate_answer(request(), "python app.py")
    assert evidence.origin is EvidenceOrigin.USER_PROVIDED_EVIDENCE
    assert evidence.to_dict()["origin"] != EvidenceOrigin.REPOSITORY_EVIDENCE.value
    with pytest.raises(ClarificationRequestError):
        UserProvidedEvidence.from_dict({**evidence.to_dict(), "origin": "AI_ANALYSIS"})


@pytest.mark.asyncio
async def test_no_new_repository_evidence_issues_typed_clarification(tmp_path: Path):
    write(tmp_path / "backend/package.json", '{"scripts":{"dev":"python app.py"}}')
    write(tmp_path / "backend/app.py", "print('service')\n")
    repository = repository_for(tmp_path)
    analysis_response = json.dumps({
        "status": "inspect_more",
        "inspection_targets": [{"relative_path": "backend/app.py"}],
    })

    class AnalysisOnlyProvider(MockProvider):
        async def generate(self, generation_request):
            self.call_history.append(generation_request)
            return GenerationResult(text=analysis_response, model="mock")

    result = await DockerAgent(
        dry_run=True, repository=repository, provider=AnalysisOnlyProvider(), model="mock",
    ).execute(tmp_path, components=["backend"])

    assert result.status == "NEEDS_CLARIFICATION"
    clarification = result.data["clarification_request"]
    assert clarification["expected_answer_type"] == "text"
    assert "production start command" in clarification["question"]
    assert clarification["proposition"]
    assert repository.load_latest(str(tmp_path)).user_evidence == []
    repository.storage.close()


def test_policy_rejects_unsupported_or_shell_shaped_user_answers():
    with pytest.raises(ClarificationRequestError):
        DockerClarificationPolicy.validate_answer(request(), "")
    with pytest.raises(ClarificationRequestError, match="Shell operators"):
        DockerClarificationPolicy.validate_answer(request(), "python app.py; rm -rf /")
    with pytest.raises(ClarificationRequestError, match="exact command"):
        DockerClarificationPolicy.validate_answer(request(), "No")


def test_cli_bridge_has_a_distinct_bounded_clarification_exit_code():
    assert CONTROLLED_NEEDS_CLARIFICATION_EXIT_CODE != 2
    assert CONTROLLED_NEEDS_CLARIFICATION_EXIT_CODE == 3


@pytest.mark.asyncio
async def test_accepted_user_evidence_persists_separately_and_allows_one_retry(tmp_path: Path):
    write(tmp_path / ".nvmrc", "20\n")
    write(tmp_path / "backend/package.json", '{"scripts":{"dev":"node src/server.js"}}')
    write(tmp_path / "backend/src/server.js", "app.listen(5001);\n")
    repository = repository_for(tmp_path)
    analysis_response = json.dumps({
        "status": "inspect_more",
        "inspection_targets": [{"relative_path": "backend/src/server.js"}],
    })

    class SequencedProvider(MockProvider):
        async def generate(self, generation_request):
            self.call_history.append(generation_request)
            if "evidence analysis assistant" in (generation_request.system or ""):
                return GenerationResult(text=analysis_response, model="mock")
            return GenerationResult(text=json.dumps({
                "status": "ready", "reason": "Evidence is sufficient",
                "components": [{
                    "name": "backend", "base_image": "node:20-alpine", "working_directory": "/app",
                    "package_manager": "npm", "install_command": "npm ci",
                    "start_command": ["node", "src/server.js"], "port": 5001,
                }],
                "compose": {"services": [{
                    "name": "backend", "component": "backend", "build_context": "./backend",
                    "port": 5001, "target_port": 5001,
                }]},
            }), model="mock")

    provider = SequencedProvider()
    first = await DockerAgent(
        dry_run=True, repository=repository, provider=provider, model="mock",
    ).execute(tmp_path, components=["backend"], compose=False)
    clarification = ClarificationRequest.from_dict(first.data["clarification_request"])
    evidence = DockerClarificationPolicy.validate_answer(clarification, "node src/server.js")

    second = await DockerAgent(
        dry_run=True, repository=repository, provider=provider, model="mock",
    ).execute(tmp_path, components=["backend"], compose=False, user_evidence=json.dumps(evidence.to_dict()))

    assert first.status == "NEEDS_CLARIFICATION"
    assert second.success is True, second.message
    persisted = repository.load_latest(str(tmp_path))
    assert persisted.user_evidence[0]["origin"] == "USER_PROVIDED_EVIDENCE"
    assert persisted.evidence == repository.load_latest(str(tmp_path)).evidence
    assert len([call for call in provider.call_history if "evidence analysis assistant" in (call.system or "")]) == 1
    repository.storage.close()


def test_dashboard_exposes_dynamic_clarification_request_controls():
    source = Path("dashboard/app.js").read_text(encoding="utf-8")
    assert "clarification_required" in source
    assert "/api/agent/runs/" in source and "/clarification" in source
    assert "agent-clarification-form" in source
    assert "expected_answer_type" in source
    assert "allowed_answers" in source


@pytest.mark.asyncio
async def test_backend_keeps_run_open_then_accepts_one_clarification_retry(monkeypatch):
    import backend.main as api

    clarification = request()
    manager = api.RunManager()
    state = api.RunState(
        "clarification-run", "dockerize", clarification.root_path,
        agent_request=api.AgentRunRequest(operation="dockerize", target=clarification.root_path),
    )
    manager.runs[state.run_id] = state

    async def fake_stream(_command, _provider="", _model=""):
        yield "output", "Clarification required\n"
        yield "output", "SOHAIL_CLARIFICATION_REQUEST:" + json.dumps(clarification.to_dict()) + "\n"
        yield "exit", str(CONTROLLED_NEEDS_CLARIFICATION_EXIT_CODE)

    monkeypatch.setattr(api.cli, "stream", fake_stream)
    await manager._stream_command(state, SimpleNamespace(provider="", model=""), SimpleNamespace(display="dockerize", purpose="test"))
    assert state.complete is False
    assert state.awaiting_clarification is True
    assert any(event["type"] == "clarification_required" for event in state.events)

    retry_requests = []

    async def fake_retry(_state, retry_request):
        retry_requests.append(retry_request)

    monkeypatch.setattr(manager, "_execute_agent", fake_retry)
    result = await manager.submit_clarification(
        state.run_id,
        api.ClarificationAnswerRequest(request_id=clarification.request_id, answer="python app.py"),
    )
    await asyncio.sleep(0)
    assert result == {"status": "accepted", "retry": True}
    assert state.clarification_attempts == 1
    assert retry_requests[0].clarification_response
    assert any(event["type"] == "user_evidence_accepted" for event in state.events)
    with pytest.raises(api.HTTPException) as exc_info:
        await manager.submit_clarification(
            state.run_id,
            api.ClarificationAnswerRequest(request_id=clarification.request_id, answer="python app.py"),
        )
    assert exc_info.value.status_code == 409
