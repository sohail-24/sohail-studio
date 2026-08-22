import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update

from core.storage.database import Storage, StorageConfig
from core.storage.project_intelligence import (
    ProjectIntelligenceRepository,
    inspection_runs,
    metadata,
)
from sohail_agent_cli.agents.docker_agent import DockerAgent
from sohail_agent_cli.dockerize import (
    DockerContextBuilder,
    DockerContextError,
    DockerDecisionEngine,
    DockerDecisionError,
)
from sohail_agent_cli.inspection import DeepInspector
from sohail_agent_cli.providers import MockProvider


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def node_backend(root: Path, port: int = 5001) -> None:
    write(root / ".nvmrc", "20\n")
    write(root / "backend/package.json", json.dumps({"scripts": {"start": "node src/server.js"}}))
    write(root / "backend/package-lock.json", "{}")
    write(root / "backend/src/server.js", f"app.listen({port});\n")
    write(root / "backend/.env", f"PORT={port}\nMONGO_URI=mongodb://secret\n")


def repository_for(root: Path) -> ProjectIntelligenceRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repository = ProjectIntelligenceRepository(
        Storage(StorageConfig("postgresql://masked@localhost/studio"), engine=engine)
    )
    repository.persist(DeepInspector().inspect(root))
    return repository


def decision_response(port: int = 5001) -> str:
    return json.dumps({
        "status": "ready",
        "reason": "Evidence is sufficient",
        "components": [{
            "name": "backend",
            "base_image": "node:20-alpine",
            "working_directory": "/app",
            "package_manager": "npm",
            "install_command": "npm ci",
            "start_command": ["npm", "start"],
            "port": port,
        }],
        "compose": {"services": [{
            "name": "backend",
            "component": "backend",
            "build_context": "./backend",
            "port": port,
            "target_port": port,
        }]},
    })


def frontend_decision_response(start_command: str = "vite preview") -> str:
    return json.dumps({
        "status": "ready",
        "reason": "Evidence is sufficient",
        "components": [{
            "name": "frontend",
            "base_image": "node:20-alpine",
            "working_directory": "/app/frontend",
            "package_manager": "npm",
            "install_command": "npm ci",
            "start_command": start_command,
            "port": 80,
        }],
        "compose": {"services": [{
            "name": "frontend",
            "component": "frontend",
            "build_context": "./frontend",
            "port": 80,
            "target_port": 80,
        }]},
    })


@pytest.mark.asyncio
async def test_docker_decision_contract_accepts_ready_with_strict_json_validation(tmp_path: Path):
    node_backend(tmp_path)
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    provider = MockProvider(responses={"project": decision_response()})

    decision = await DockerDecisionEngine(provider, "devops-qwen:latest").decide(context)

    assert decision.status == "ready"
    assert decision.components[0]["name"] == "backend"
    assert context.components[0]["runtimes"] == [{
        "runtime": "Node.js",
        "version": "20",
        "source_file": ".nvmrc",
        "confidence": "high",
    }]
    assert provider.call_history[0].options["format"] == "json"
    assert provider.call_history[0].options["num_ctx"] == 16384
    assert provider.call_history[0].options["num_predict"] == 1024
    repository.storage.close()


@pytest.mark.asyncio
async def test_frontend_preview_command_survives_persistence_and_is_accepted(tmp_path: Path):
    write(tmp_path / ".nvmrc", "20\n")
    write(tmp_path / "frontend/package.json", '{"scripts":{"dev":"vite","build":"vite build","preview":"vite preview"}}')
    write(tmp_path / "frontend/package-lock.json", "{}")
    write(tmp_path / "frontend/src/main.js", "console.log('frontend');\n")
    write(tmp_path / "k8s/frontend-deployment.yml", "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: frontend\nspec:\n  template:\n    metadata:\n      labels:\n        app: frontend\n    spec:\n      containers:\n        - name: frontend\n          ports:\n            - containerPort: 80\n")
    write(tmp_path / "k8s/frontend-service.yml", "apiVersion: v1\nkind: Service\nmetadata:\n  name: frontend\nspec:\n  selector:\n    app: frontend\n  ports:\n    - port: 80\n      targetPort: 80\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["frontend"])

    commands = context.components[0]["commands"]
    assert {item["name"] for item in commands} >= {"dev", "build", "preview"}
    assert any(item["command"] == "vite preview" for item in commands if item["name"] == "preview")

    decision = await DockerDecisionEngine(
        MockProvider(responses={"project": frontend_decision_response()}),
        "devops-qwen:latest",
    ).decide(context)

    assert decision.status == "ready"
    repository.storage.close()


@pytest.mark.asyncio
async def test_frontend_invented_start_command_is_rejected(tmp_path: Path):
    write(tmp_path / ".nvmrc", "20\n")
    write(tmp_path / "frontend/package.json", '{"scripts":{"preview":"vite preview"},"dependencies":{"vite":"^5"}}')
    write(tmp_path / "frontend/package-lock.json", "{}")
    write(tmp_path / "frontend/src/main.js", "console.log('frontend');\n")
    write(tmp_path / "k8s/frontend-deployment.yml", "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: frontend\nspec:\n  template:\n    metadata:\n      labels:\n        app: frontend\n    spec:\n      containers:\n        - name: frontend\n          ports:\n            - containerPort: 80\n")
    write(tmp_path / "k8s/frontend-service.yml", "apiVersion: v1\nkind: Service\nmetadata:\n  name: frontend\nspec:\n  selector:\n    app: frontend\n  ports:\n    - port: 80\n      targetPort: 80\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["frontend"])

    decision = await DockerDecisionEngine(
        MockProvider(responses={"project": frontend_decision_response("vite serve")}),
        "devops-qwen:latest",
    ).decide(context)

    assert decision.status == "NEEDS_EVIDENCE"
    assert "invented start command for frontend" in decision.raw["reason"]
    repository.storage.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("base_image", ["node:14", "node:20", "node:22"])
async def test_readme_runtime_range_does_not_authorize_any_node_base_image(
    tmp_path: Path, base_image: str,
):
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node src/server.js"}}')
    write(tmp_path / "backend/package-lock.json", "{}")
    write(tmp_path / "backend/src/server.js", "server.listen(5001);\n")
    write(tmp_path / "README.md", "Node.js (v14 or higher)\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    response = decision_response().replace("node:20-alpine", base_image)

    decision = await DockerDecisionEngine(
        MockProvider(responses={"project": response}), "devops-qwen:latest",
    ).decide(context)

    assert decision.status == "NEEDS_EVIDENCE"
    assert decision.raw["reason"] == (
        "An exact Node.js runtime version is required to select a Node base image, "
        "but Project Intelligence only contains the non-authoritative range "
        "'Node.js v14 or higher' from README.md."
    )
    repository.storage.close()


@pytest.mark.asyncio
async def test_exact_package_engines_runtime_authorizes_matching_node_base_image(tmp_path: Path):
    write(
        tmp_path / "backend/package.json",
        '{"engines":{"node":"20"},"scripts":{"start":"node src/server.js"}}',
    )
    write(tmp_path / "backend/package-lock.json", "{}")
    write(tmp_path / "backend/src/server.js", "server.listen(5001);\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])

    decision = await DockerDecisionEngine(
        MockProvider(responses={"project": decision_response()}), "devops-qwen:latest",
    ).decide(context)

    assert decision.status == "ready"
    assert context.components[0]["runtimes"][0]["version"] == "20"
    repository.storage.close()


@pytest.mark.asyncio
async def test_docker_decision_contract_returns_needs_evidence_safely(tmp_path: Path):
    node_backend(tmp_path)
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    response = json.dumps({
        "status": "NEEDS_EVIDENCE",
        "reason": "Backend port evidence conflicts",
        "components": [],
        "compose": {},
    })
    provider = MockProvider(responses={"project": response})

    decision = await DockerDecisionEngine(provider, "devops-qwen:latest").decide(context)

    assert decision.status == "NEEDS_EVIDENCE"
    assert decision.raw["reason"] == "Backend port evidence conflicts"
    repository.storage.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"status": "success"}, "missing required field"),
        ({"error": True, "message": "Docker command not specified"}, "missing required field"),
        ({"status": "ready"}, "missing required field"),
        ({"status": "ready", "reason": "x", "components": []}, "missing required field"),
        ({"status": "success", "reason": "x", "components": [], "compose": {}}, "status must be"),
        ({"status": "READY", "reason": "x", "components": [], "compose": {}}, "status must be"),
        ({"status": "ready", "reason": "x", "components": {}, "compose": {}}, "components must be a list"),
        ({"status": "ready", "reason": "x", "components": [], "compose": []}, "compose must be an object"),
        ({"status": "ready", "reason": "", "components": [], "compose": {}}, "reason must be a non-empty string"),
    ],
)
async def test_docker_decision_contract_rejects_invalid_schema(
    tmp_path: Path,
    payload: dict[str, object],
    message: str,
):
    node_backend(tmp_path)
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    provider = MockProvider(responses={"project": json.dumps(payload)})

    with pytest.raises(DockerDecisionError, match=message):
        await DockerDecisionEngine(provider, "devops-qwen:latest").decide(context)
    repository.storage.close()


@pytest.mark.asyncio
async def test_context_builder_retrieves_latest_snapshot_without_secret_values(tmp_path: Path):
    node_backend(tmp_path)
    repository = repository_for(tmp_path)

    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])

    assert context.project["selected_components"] == ["backend"]
    assert context.components[0]["ports"][0]["component"] == "backend"
    prompt = context.prompt()
    assert "MONGO_URI" in prompt
    assert "mongodb://secret" not in prompt
    repository.storage.close()


@pytest.mark.asyncio
async def test_persist_then_load_scopes_focused_context_to_selected_components(tmp_path: Path):
    node_backend(tmp_path)
    write(tmp_path / "frontend/package.json", '{"scripts":{"dev":"vite"},"dependencies":{"react":"^18","vite":"^5"}}')
    write(tmp_path / "frontend/src/App.jsx", "export default function App() { return null; }\n")
    repository = repository_for(tmp_path)

    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])

    assert context.project["selected_components"] == ["backend"]
    assert [item["name"] for item in context.components] == ["backend"]
    assert all("frontend" not in json.dumps(item) for item in context.components)
    assert all("frontend" not in json.dumps(item) for item in context.evidence)
    repository.storage.close()


def test_load_latest_hydrates_normalized_facts_when_summary_is_incomplete(tmp_path: Path):
    node_backend(tmp_path)
    repository = repository_for(tmp_path)
    persisted = repository.persist(DeepInspector().inspect(tmp_path))
    with repository.storage.engine.begin() as connection:
        connection.execute(
            update(inspection_runs).where(inspection_runs.c.id == persisted.run_id).values(
                summary={"project": tmp_path.name},
            )
        )

    loaded = repository.load_latest(str(tmp_path))

    assert loaded is not None
    assert [item["name"] for item in loaded.components] == ["backend"]
    assert any(
        item["runtime"] == "Node.js"
        and item["version"] == "20"
        and item["source_file"] == ".nvmrc"
        for item in loaded.components[0]["runtimes"]
    )
    assert loaded.evidence
    repository.storage.close()


def test_api_context_and_dockerize_share_persisted_project_identity(tmp_path: Path, monkeypatch):
    node_backend(tmp_path)
    write(tmp_path / "frontend/package.json", '{"scripts":{"dev":"vite"}}')
    write(tmp_path / "frontend/src/App.jsx", "export default function App() { return null; }\n")
    repository = repository_for(tmp_path)

    import backend.main as main

    captured: dict[str, object] = {}

    def capture_agent_run(request):
        captured["target"] = request.target
        captured["components"] = request.components
        return main.RunState("api-test-run", request.operation, request.target)

    monkeypatch.setattr(main.runs, "create_agent", capture_agent_run)
    with TestClient(main.app) as client:
        api_response = client.get(
            "/api/agent/context",
            params={"target": str(tmp_path)},
        )
        run_response = client.post(
            "/api/agent/runs",
            json={
                "operation": "dockerize",
                "target": str(tmp_path),
                "components": ["backend"],
                "dry_run": True,
            },
        )

    assert api_response.status_code == 200
    api_context = api_response.json()
    docker_context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    assert api_context["root_path"] == docker_context.project["root_path"]
    assert {item["name"] for item in api_context["components"]} == {"backend", "frontend"}
    for component in api_context["components"]:
        assert any(
            runtime["runtime"] == "Node.js"
            and runtime["version"] == "20"
            and runtime["source_file"] == ".nvmrc"
            and runtime["confidence"] == "high"
            for runtime in component["runtimes"]
        )
    assert [item["name"] for item in docker_context.components] == ["backend"]
    assert docker_context.evidence
    assert run_response.status_code == 200
    assert Path(str(captured["target"])).expanduser().resolve() == Path(docker_context.project["root_path"])
    assert captured["components"] == ["backend"]
    repository.storage.close()


def test_correlated_kubernetes_ports_survive_persistence_and_api_context(tmp_path: Path):
    node_backend(tmp_path)
    write(tmp_path / "frontend/package.json", '{"scripts":{"preview":"vite preview"},"dependencies":{"vite":"^5"}}')
    write(tmp_path / "frontend/src/main.js", "console.log('frontend');\n")
    write(
        tmp_path / "k8s/backend-deployment.yml",
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: backend\nspec:\n  template:\n    metadata:\n      labels:\n        app: backend\n    spec:\n      containers:\n        - name: backend\n          ports:\n            - containerPort: 5001\n",
    )
    write(
        tmp_path / "k8s/backend-service.yml",
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: backend\nspec:\n  selector:\n    app: backend\n  ports:\n    - port: 5001\n      targetPort: 5001\n",
    )
    write(
        tmp_path / "k8s/frontend-deployment.yml",
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: frontend\nspec:\n  template:\n    metadata:\n      labels:\n        app: frontend\n    spec:\n      containers:\n        - name: frontend\n          ports:\n            - containerPort: 80\n",
    )
    write(
        tmp_path / "k8s/frontend-service.yml",
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: frontend\nspec:\n  selector:\n    app: frontend\n  ports:\n    - port: 80\n      targetPort: 80\n",
    )
    repository = repository_for(tmp_path)

    loaded = repository.load_latest(str(tmp_path))
    assert loaded is not None
    assert {
        (item["component"], item["port_type"], item["port"])
        for item in loaded.ports
        if item["port_type"] == "application"
    } >= {("backend", "application", 5001), ("frontend", "application", 80)}

    backend_context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    frontend_context = DockerContextBuilder(repository).build(tmp_path, ["frontend"])
    assert any(item["port"] == 5001 for item in backend_context.components[0]["ports"])
    assert not any(item["port"] == 80 for item in backend_context.components[0]["ports"])
    assert any(item["port"] == 80 for item in frontend_context.components[0]["ports"])
    assert not any(item["port"] == 5001 for item in frontend_context.components[0]["ports"])

    import backend.main as main

    with TestClient(main.app) as client:
        response = client.get("/api/agent/context", params={"target": str(tmp_path)})

    assert response.status_code == 200
    api_ports = response.json()["ports"]
    assert any(item["component"] == "frontend" and item["port_type"] == "application" and item["port"] == 80 for item in api_ports)
    assert any(item["component"] == "backend" and item["port_type"] == "application" and item["port"] == 5001 for item in api_ports)
    repository.storage.close()


@pytest.mark.asyncio
async def test_different_project_path_cannot_receive_another_projects_intelligence(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    node_backend(first)
    second.mkdir()
    repository = repository_for(first)

    with pytest.raises(DockerContextError, match="No successful Project Intelligence snapshot"):
        DockerContextBuilder(repository).build(second, ["backend"])
    repository.storage.close()


@pytest.mark.asyncio
async def test_dockerize_dry_run_does_not_write_and_uses_devops_model(tmp_path: Path):
    node_backend(tmp_path)
    provider = MockProvider(responses={"backend": decision_response()})
    agent = DockerAgent(
        dry_run=True,
        repository=repository_for(tmp_path),
        provider=provider,
        model="devops-qwen:latest",
    )

    result = await agent.execute(tmp_path, components=["backend"], compose=True, compose_action="generate")

    assert result.success
    assert not (tmp_path / "backend/Dockerfile").exists()
    assert not (tmp_path / "docker-compose.yml").exists()
    assert provider.call_history[0].model == "devops-qwen:latest"
    assert "mongodb://secret" not in provider.call_history[0].prompt


@pytest.mark.asyncio
async def test_dockerize_writes_only_selected_component_and_consistent_compose(tmp_path: Path):
    node_backend(tmp_path)
    write(tmp_path / "frontend/package.json", '{"scripts":{"dev":"vite"},"dependencies":{"react":"^18","vite":"^5"}}')
    write(tmp_path / "frontend/src/App.jsx", "export default function App() { return null; }\n")
    provider = MockProvider(responses={"backend": decision_response()})
    repository = repository_for(tmp_path)

    result = await DockerAgent(
        repository=repository,
        provider=provider,
        model="devops-qwen:latest",
    ).execute(tmp_path, components=["backend"], compose=True, compose_action="generate", overwrite=True)

    assert result.success, result.message
    dockerfile = (tmp_path / "backend/Dockerfile").read_text(encoding="utf-8")
    compose = (tmp_path / "docker-compose.yml").read_text(encoding="utf-8")
    assert "EXPOSE 5001" in dockerfile
    assert '"5001:5001"' in compose
    assert not (tmp_path / "frontend/Dockerfile").exists()
    repository.storage.close()


@pytest.mark.asyncio
async def test_conflicting_port_evidence_fails_before_generation(tmp_path: Path):
    node_backend(tmp_path, 5001)
    write(tmp_path / "README.md", "The backend runs on port 3000.\n")
    provider = MockProvider(responses={"backend": decision_response(5001)})
    repository = repository_for(tmp_path)

    result = await DockerAgent(
        repository=repository,
        provider=provider,
        model="devops-qwen:latest",
    ).execute(tmp_path, components=["backend"], compose=True, compose_action="generate")

    assert not result.success
    assert "conflicts" in result.message
    assert not (tmp_path / "backend/Dockerfile").exists()
    repository.storage.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("base_image", ["node:20.15.3-alpine", "node:22-alpine"])
async def test_model_cannot_invent_node_runtime_without_runtime_evidence(tmp_path: Path, base_image: str):
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node src/server.js"}}')
    write(tmp_path / "backend/package-lock.json", "{}")
    write(tmp_path / "backend/src/server.js", "server.listen(5001);\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    response = json.dumps({
        "status": "ready",
        "reason": "Evidence is sufficient",
        "components": [{
            "name": "backend",
            "base_image": base_image,
            "working_directory": "/app/backend",
            "package_manager": "npm",
            "install_command": "npm install",
            "start_command": "node src/server.js",
            "port": 5001,
        }],
        "compose": {"services": [{
            "name": "backend",
            "component": "backend",
            "build_context": "./backend",
            "port": 5001,
            "target_port": 5001,
        }]},
    })

    decision = await DockerDecisionEngine(
        MockProvider(responses={"project": response}), "devops-qwen:latest",
    ).decide(context)

    assert decision.status == "NEEDS_EVIDENCE"
    assert "exact Node.js runtime version" in decision.raw["reason"]
    repository.storage.close()


@pytest.mark.asyncio
async def test_missing_runtime_evidence_prevents_all_docker_artifacts(tmp_path: Path):
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node src/server.js"}}')
    write(tmp_path / "backend/package-lock.json", "{}")
    write(tmp_path / "backend/src/server.js", "server.listen(5001);\n")
    repository = repository_for(tmp_path)
    response = decision_response().replace("node:20-alpine", "node:22-alpine")
    provider = MockProvider(responses={"project": response})

    result = await DockerAgent(
        repository=repository, provider=provider, model="devops-qwen:latest",
    ).execute(tmp_path, components=["backend"], compose=True, compose_action="generate")

    assert not result.success
    assert "requires evidence" in result.message
    assert not (tmp_path / "backend/Dockerfile").exists()
    assert not (tmp_path / "docker-compose.yml").exists()
    repository.storage.close()


@pytest.mark.asyncio
async def test_existing_files_are_not_overwritten_without_permission(tmp_path: Path):
    node_backend(tmp_path)
    write(
        tmp_path / "backend/Dockerfile",
        "FROM node:20-alpine\nWORKDIR /app\nCOPY package*.json ./\nRUN npm ci\n"
        "COPY . .\nEXPOSE 5001\nCMD [\"npm\", \"start\"]\n",
    )
    provider = MockProvider(responses={"backend": decision_response()})
    repository = repository_for(tmp_path)

    result = await DockerAgent(
        repository=repository,
        provider=provider,
        model="devops-qwen:latest",
    ).execute(tmp_path, components=["backend"], compose=False)

    assert result.success
    assert "FROM node:20-alpine" in (tmp_path / "backend/Dockerfile").read_text(encoding="utf-8")
    assert tmp_path / "backend/Dockerfile" in result.files_skipped
    repository.storage.close()
