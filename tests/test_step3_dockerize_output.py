"""Focused Step 3 coverage for Compose output, previews, and command guidance."""

import asyncio
import json
from pathlib import Path

from rich.console import Console
from sqlalchemy import create_engine

import sohail_agent_cli.main as cli
from sohail_agent_cli.agents.base_agent import AgentResult
from sohail_agent_cli.agents.docker_agent import DockerAgent
from core.storage.database import Storage, StorageConfig
from core.storage.project_intelligence import ProjectIntelligenceRepository, metadata
from sohail_agent_cli.dockerize.context_builder import DockerContext, DockerContextBuilder
from sohail_agent_cli.dockerize.decision import DockerDecision, DockerDecisionEngine
from sohail_agent_cli.inspection import DeepInspector
from sohail_agent_cli.providers import MockProvider


def recorded_console(monkeypatch) -> Console:
    output = Console(record=True, color_system=None, width=140)
    monkeypatch.setattr(cli, "console", output)
    return output


def test_dry_run_prints_separate_full_preview_for_each_selected_artifact(monkeypatch):
    output = recorded_console(monkeypatch)
    result = AgentResult(
        success=True,
        message="Docker artifacts validated successfully",
        data={
            "inspection_run_id": "run-step3",
            "context": {
                "project": {"name": "sample", "root_path": "/tmp/sample", "inspection_run_id": "run-step3"},
            },
            "decision": {"status": "ready"},
            "validation": {"status": "passed"},
            "model_called": True,
            "artifact_previews": [
                {"path": "/tmp/sample/Dockerfile", "action": "generate", "content": "FROM java:17\nCMD [\"java\"]\n"},
                {"path": "/tmp/sample/docker-compose.yml", "action": "generate", "content": "services:\n  application:\n"},
            ],
            "planned_actions": [
                {"action": "generate", "path": "/tmp/sample/Dockerfile"},
                {"action": "generate", "path": "/tmp/sample/docker-compose.yml"},
            ],
        },
    )

    cli._print_docker_result(result, dry_run=True)

    text = output.export_text()
    assert "ARTIFACT 1 OF 2 — Dockerfile" in text
    assert "ARTIFACT 2 OF 2 — docker-compose.yml" in text
    assert "FROM java:17" in text
    assert "services:" in text
    assert "application:" in text
    assert "Recommended Docker commands" in text
    assert "docker compose up --build" in text
    assert "Files written: NO" in text


def test_dry_run_does_not_display_unselected_artifacts(monkeypatch):
    output = recorded_console(monkeypatch)
    result = AgentResult(
        success=True,
        message="Docker artifacts validated successfully",
        data={
            "context": {"project": {"name": "sample", "root_path": "/tmp/sample"}},
            "validation": {"status": "passed"},
            "artifact_previews": [
                {"path": "/tmp/sample/Dockerfile", "action": "generate", "content": "FROM node:20\n"},
            ],
            "planned_actions": [{"action": "generate", "path": "/tmp/sample/Dockerfile"}],
        },
    )

    cli._print_docker_result(result, dry_run=True)

    text = output.export_text()
    assert "ARTIFACT 1 OF 1 — Dockerfile" in text
    assert "docker-compose.yml" not in text
    assert "docker compose up" not in text


def test_compose_renderer_canonicalizes_layout_from_selected_context():
    context = DockerContext(
        project={"name": "sample", "root_path": "/tmp/sample"},
        components=[{"name": "backend", "path": "backend"}],
        infrastructure={},
        evidence=[],
    )
    decision = DockerDecision(
        status="ready",
        components=[{"name": "backend", "working_directory": "/app"}],
        compose={
            "services": [{
                "name": "backend",
                "component": "backend",
                "build_context": "./wrong-place",
                "port": None,
                "target_port": None,
            }],
        },
        raw={},
    )

    rendered = DockerDecisionEngine.render_compose(decision, context)

    assert "build: ./backend" in rendered
    assert "working_dir: /app" in rendered
    assert "wrong-place" not in rendered
    assert "mysql:" not in rendered


def test_dockerfile_only_commands_are_derived_from_selected_artifact_and_context():
    commands = cli._recommended_docker_commands({
        "context": {
            "project": {"name": "Expenses Tracker", "root_path": "/tmp/expenses"},
            "components": [{
                "name": "application",
                "path": ".",
                "ports": [{"port_type": "application", "port": 9090, "conflict": False}],
                "dockerfiles": ["Dockerfile"],
            }],
        },
        "planned_actions": [{"action": "generate", "path": "/tmp/expenses/Dockerfile"}],
    })

    text = "\n".join(commands)
    assert "docker build -t application:local -f Dockerfile ." in text
    assert "docker run --rm --name application -p 9090:9090 application:local" in text
    assert "docker compose" not in text


def test_frontend_nginx_config_is_supporting_evidence_not_an_independent_component(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend/package.json").write_text(
        json.dumps({"scripts": {"start": "node server.js"}}), encoding="utf-8"
    )
    (tmp_path / "backend/package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "backend/server.js").write_text("app.listen(3000);\n", encoding="utf-8")
    (tmp_path / "frontend/package.json").write_text(
        json.dumps({"scripts": {"build": "vite build"}, "dependencies": {"react": "^18", "vite": "^5"}}),
        encoding="utf-8",
    )
    (tmp_path / "frontend/package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "frontend/index.html").write_text("<div id='root'></div>\n", encoding="utf-8")
    (tmp_path / "frontend/src/main.jsx").parent.mkdir()
    (tmp_path / "frontend/src/main.jsx").write_text("console.log('frontend');\n", encoding="utf-8")
    (tmp_path / "frontend/nginx.conf").write_text("server { listen 80; }\n", encoding="utf-8")

    intelligence = DeepInspector().inspect(tmp_path)

    names = {str(item["name"]) for item in intelligence.components}
    assert {"backend", "frontend"}.issubset(names)
    assert "nginx" not in names
    assert any(item.relative_path == "frontend/nginx.conf" for item in intelligence.files)


def test_full_stack_dockerize_uses_component_contexts_without_nginx_or_dockerignore(tmp_path, monkeypatch):
    (tmp_path / ".nvmrc").write_text("20\n", encoding="utf-8")
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend/src").mkdir(parents=True)
    (tmp_path / "backend/package.json").write_text(
        json.dumps({"scripts": {"start": "node server.js"}, "dependencies": {"express": "^4"}}),
        encoding="utf-8",
    )
    (tmp_path / "backend/package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "backend/server.js").write_text("app.listen(3000);\n", encoding="utf-8")
    (tmp_path / "frontend/package.json").write_text(
        json.dumps({"scripts": {"build": "vite build"}, "dependencies": {"react": "^18", "vite": "^5"}}),
        encoding="utf-8",
    )
    (tmp_path / "frontend/package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "frontend/index.html").write_text("<div id='root'></div>\n", encoding="utf-8")
    (tmp_path / "frontend/src/main.jsx").write_text("console.log('frontend');\n", encoding="utf-8")
    (tmp_path / "frontend/nginx.conf").write_text("server { listen 80; }\n", encoding="utf-8")

    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repository = ProjectIntelligenceRepository(
        Storage(StorageConfig("postgresql://masked@localhost/studio"), engine=engine)
    )
    run_id = repository.persist(DeepInspector().inspect(tmp_path)).run_id
    context = DockerContextBuilder(repository).build(tmp_path, expected_inspection_run_id=run_id)
    names = {item["name"] for item in context.components}
    assert names == {"backend", "frontend"}

    node = next(item for item in context.components if item["name"] == "backend")
    frontend = next(item for item in context.components if item["name"] == "frontend")
    response = json.dumps({
        "status": "ready", "reason": "component-scoped evidence is sufficient",
        "components": [
            {
                "name": "backend", "strategy_id": node["strategy_id"], "language": "JavaScript",
                "framework": "Express", "base_image": "node:20-alpine", "working_directory": "/app",
                "package_manager": "npm", "install_command": "npm ci", "build_command": "",
                "start_command": "node server.js", "port": 3000,
            },
            {
                "name": "frontend", "strategy_id": frontend["strategy_id"], "language": "JavaScript",
                "framework": "React", "base_image": "node:20-alpine", "working_directory": "/app",
                "package_manager": "npm", "install_command": "npm ci", "build_command": "vite build",
                "start_command": "npx serve -s dist", "port": 80, "deployment_pattern": "static-frontend",
            },
        ],
        "compose": {"services": []},
    })
    provider = MockProvider(responses={"project": response})
    original_inspect = DeepInspector.inspect
    monkeypatch.setattr(DeepInspector, "inspect", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("rescan")))
    try:
        result = asyncio.run(DockerAgent(
            dry_run=True, repository=repository, provider=provider, model="devops-qwen:latest",
        ).execute(
            tmp_path, components=["backend", "frontend"], compose=False,
            inspection_run_id=run_id,
            docker_plan={"dockerfiles": {"backend": "generate", "frontend": "generate"}, "compose": "skip"},
        ))
    finally:
        monkeypatch.setattr(DeepInspector, "inspect", original_inspect)

    assert result.success, result.message
    assert result.files_created == []
    assert result.data["files_modified"] == []
    assert all("nginx" not in item["path"] for item in result.data["planned_actions"])
    assert all(".dockerignore" not in item["path"] for item in result.data["planned_actions"])
    assert {Path(item["path"]).name for item in result.data["rendered_artifacts"]} == {"Dockerfile"}
    assert len(provider.call_history) == 1
    repository.storage.close()
