from pathlib import Path

from fastapi.testclient import TestClient

import backend.main as api
from core.cli_bridge import CliBridge
from sohail_agent_cli.agents.cicd_agent import CicdAgent
from sohail_agent_cli.agents.k8s_agent import K8sAgent
from sohail_agent_cli.inspection import ProjectIntelligence
from sohail_agent_cli.inspection import DeepInspector
from sohail_agent_cli.inspection import repo_analysis_from_intelligence
import pytest


def test_terminal_project_selection_validates_without_running_inspection(tmp_path: Path):
    client = TestClient(api.app)

    response = client.get("/api/agent/project", params={"target": str(tmp_path)})

    assert response.status_code == 200
    assert response.json() == {"target": str(tmp_path.resolve()), "valid": True}


def test_complete_inspection_exposes_real_phase_callbacks(tmp_path: Path):
    (tmp_path / "README.md").write_text("local project\n", encoding="utf-8")
    phases = []

    DeepInspector().inspect(tmp_path, progress=phases.append)

    assert phases == [
        "Discovering repository structure",
        "Extracting repository evidence",
        "Recognizing verified engineering patterns",
    ]


def test_terminal_stored_intelligence_endpoint_returns_persisted_snapshot(monkeypatch, tmp_path: Path):
    intelligence = ProjectIntelligence(
        name="sample",
        root_path=str(tmp_path.resolve()),
        inspection_run_id="inspection-123",
        components=[{"name": "frontend", "kind": "frontend"}],
        verified_patterns=[{
            "pattern_id": "static-frontend",
            "category": "static_frontend",
            "component": "frontend",
            "origin": "VERIFIED_INFERENCE",
        }],
    )

    class FakeStorage:
        def close(self):
            return None

    class FakeRepository:
        storage = FakeStorage()

        def load_latest(self, root_path):
            assert root_path == str(tmp_path.resolve())
            return intelligence

    def unexpected_execution(*_args, **_kwargs):
        raise AssertionError("loading intelligence must not create an agent run")

    monkeypatch.setattr(api.ProjectIntelligenceRepository, "from_env", lambda: FakeRepository())
    monkeypatch.setattr(api.runs, "create_agent", unexpected_execution)
    client = TestClient(api.app)

    response = client.get("/api/agent/intelligence", params={"target": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["components"] == [{"name": "frontend", "kind": "frontend"}]
    assert payload["verified_patterns"][0]["origin"] == "VERIFIED_INFERENCE"
    assert payload["inspection_run_id"] == "inspection-123"


def test_dashboard_treats_completed_runs_as_terminal_and_removes_inspect_from_next_actions():
    source = Path("dashboard/app.js").read_text(encoding="utf-8")

    assert 'state.agentRunId && !state.agentRunTerminal' in source
    assert 'if (state.agentRunTerminal) return;' in source
    assert 'if (state.agentRunStarting) return;' in source
    assert 'state.agentInspectionReady ? ["dockerize", "kubernetes", "cicd"]' in source
    assert 'data-agent-reinspect' in source
    assert 'state.agentInspectionReady = true' in source
    assert 'const operationWorkspace = inspectionRunMode ? ""' in source
    assert 'inspection_run_id: operation === "inspect" ? "" : state.agentInspectionRunId' in source
    assert "dry_run: state.agentDryRun" in source
    assert '(!state.agentInspectionReady || !state.agentContext || !state.agentInspectionRunId)' in source


def test_dashboard_opens_a_persisted_intelligence_docker_planner_without_auto_running():
    source = Path("dashboard/app.js").read_text(encoding="utf-8")

    assert "function dockerizePlanningWorkspace()" in source
    assert "data-docker-plan-component" in source
    assert "data-docker-plan-compose" in source
    assert 'docker_plan: dockerPlan || {}' in source
    assert 'operation?.id === "dockerize" ? "Continue"' in source
    assert 'state.selectedAgentOperation === "inspect" && state.agentCategory === "inspect"' in source
    assert "Preview without writing files" in source


def test_dashboard_intelligence_summary_uses_persisted_evidence_sections():
    source = Path("dashboard/app.js").read_text(encoding="utf-8")

    for label in (
        "Project path",
        "Persistence",
        "Architecture / components",
        "Technology stack",
        "Database",
        "Deployment intelligence",
        "Network / ports",
        "Inspection quality",
        "files.length",
        "evidence.length",
        "context.evidence_counts",
    ):
        assert label in source


def test_downstream_cli_carries_the_existing_inspection_run_id(tmp_path: Path):
    command = CliBridge().build_agent_command(
        "kubernetes",
        target=str(tmp_path),
        inspection_run_id="inspection-123",
    )

    assert "--inspection-run-id" in command.argv
    assert "inspection-123" in command.argv


def test_downstream_analysis_adapter_uses_persisted_facts_without_scanning(tmp_path: Path):
    intelligence = ProjectIntelligence(
        name="sample",
        root_path=str(tmp_path.resolve()),
        inspection_run_id="inspection-123",
        components=[{
            "name": "backend",
            "path": "backend",
            "kind": "backend",
            "role": "backend/application",
            "framework": "Express",
            "package_manager": "npm",
        }],
        runtimes=[{"runtime": "Node.js", "version": "20", "source_file": "backend/package.json", "confidence": "high"}],
        ports=[{"component": "backend", "port": 5001, "port_type": "application"}],
    )

    analysis = repo_analysis_from_intelligence(intelligence)

    assert analysis.components[0].name == "backend"
    assert analysis.components[0].framework == "Express"
    assert analysis.components[0].runtime == "Node.js 20"
    assert analysis.components[0].ports == [5001]


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_class", [K8sAgent, CicdAgent])
async def test_downstream_agents_require_persisted_intelligence(tmp_path: Path, agent_class):
    result = await agent_class(dry_run=True).execute(tmp_path)

    assert result.success is False
    assert "Project Intelligence is required" in result.message


def test_dashboard_uses_folder_first_categories_and_persisted_intelligence():
    source = Path("dashboard/app.js").read_text(encoding="utf-8")

    assert "Select Project Folder" in source
    assert 'data-agent-category="inspect"' in source
    assert 'data-agent-category="build"' in source
    assert "/api/agent/intelligence" in source
    assert "inspection_persisted" in source
    assert 'void startAgentOperation("inspect")' in source
    assert "agentInspectionActive" in source
    assert 'const operationWorkspace = inspectionRunMode ? ""' in source
    assert 'data-agent-choice="component"' not in source
