import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update

from core.cli_bridge import CliBridge
from core.evidence import AcquisitionResult
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
from sohail_agent_cli.inspection import DeepInspector, Evidence
from sohail_agent_cli.providers import GenerationResult, MockProvider


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def node_backend(root: Path, port: int = 5001) -> None:
    write(root / ".nvmrc", "20\n")
    write(root / "backend/package.json", json.dumps({"scripts": {"start": "node src/server.js"}}))
    write(root / "backend/package-lock.json", "{}")
    write(root / "backend/src/server.js", f"app.listen({port});\n")
    write(root / "backend/.env", f"PORT={port}\nMONGO_URI=mongodb://secret\n")


def node_backend_without_port(root: Path) -> None:
    write(root / ".nvmrc", "20\n")
    write(root / "backend/package.json", '{"scripts":{"start":"node src/server.js"}}')
    write(root / "backend/package-lock.json", "{}")
    write(root / "backend/src/server.js", "const PORT = process.env.PORT; server.listen(PORT);\n")


def repository_for(root: Path) -> ProjectIntelligenceRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repository = ProjectIntelligenceRepository(
        Storage(StorageConfig("postgresql://masked@localhost/studio"), engine=engine)
    )
    intelligence = DeepInspector().inspect(root)
    # These unit fixtures model a project whose platform policy has already
    # supplied exact container layout facts.  Production Inspect does not add
    # these defaults; tests that exercise missing policy use a separate context.
    if any(item.get("package_manager") in {"npm", "yarn", "pnpm"} for item in intelligence.components):
        intelligence.docker.setdefault("base_images", []).append({
            "image": "node:20-alpine", "source_file": "test-fixture-policy",
            "source_type": "EXPLICIT_EVIDENCE", "confidence": "high", "model_inference": False,
        })
        intelligence.docker.setdefault("working_directories", []).append({
            "path": "/app", "source_file": "test-fixture-policy",
            "source_type": "EXPLICIT_EVIDENCE", "confidence": "high", "model_inference": False,
        })
    repository.persist(intelligence)
    return repository


def test_docker_context_reuses_and_validates_the_persisted_inspection_run(tmp_path: Path):
    node_backend(tmp_path)
    repository = repository_for(tmp_path)
    intelligence = repository.load_latest(str(tmp_path))
    assert intelligence is not None
    assert intelligence.inspection_run_id

    context = DockerContextBuilder(repository).build(
        tmp_path,
        ["backend"],
        expected_inspection_run_id=intelligence.inspection_run_id,
    )

    assert context.project["inspection_run_id"] == intelligence.inspection_run_id
    with pytest.raises(DockerContextError, match="does not match"):
        DockerContextBuilder(repository).build(
            tmp_path,
            ["backend"],
            expected_inspection_run_id="different-run",
        )


def test_single_root_component_receives_application_port_from_nested_configuration(tmp_path: Path):
    write(
        tmp_path / "pom.xml",
        """<project><artifactId>sample</artifactId><version>1.0.0</version>
        <properties><java.version>17</java.version></properties>
        <build><plugins><plugin><artifactId>spring-boot-maven-plugin</artifactId></plugin></plugins></build>
        </project>""",
    )
    write(
        tmp_path / "src/main/java/example/Application.java",
        """@SpringBootApplication public class Application {
        public static void main(String[] args) { SpringApplication.run(Application.class, args); }
        }""",
    )
    write(tmp_path / "src/main/resources/application.properties", "server.port=9090\n")
    repository = repository_for(tmp_path)

    context = DockerContextBuilder(repository).build(tmp_path, ["application"])

    assert context.components[0]["ports"] == [{
        "name": "src_port",
        "port": 9090,
        "host_port": None,
        "source_file": "src/main/resources/application.properties",
        "confidence": "high",
        "component": "application",
        "port_type": "application",
        "protocol": None,
        "target_port": None,
        "service_name": None,
        "conflict": False,
    }]
    repository.storage.close()


def test_cli_bridge_carries_an_explicit_docker_artifact_plan(tmp_path: Path):
    command = CliBridge().build_agent_command(
        "dockerize",
        target=str(tmp_path),
        components=["backend"],
        inspection_run_id="inspection-123",
        docker_plan={"dockerfiles": {"backend": "generate"}, "compose": "skip"},
    )

    assert "--docker-plan" in command.argv
    assert any('"backend":"generate"' in argument for argument in command.argv)
    assert "--inspection-run-id" in command.argv


@pytest.mark.asyncio
async def test_docker_plan_keeps_existing_artifacts_without_model_or_overwrite(tmp_path: Path):
    node_backend(tmp_path)
    write(tmp_path / "backend/Dockerfile", "FROM node:20-alpine\n# existing\n")
    repository = repository_for(tmp_path)
    provider = MockProvider(responses={"project": decision_response()})

    result = await DockerAgent(
        repository=repository,
        provider=provider,
        model="devops-qwen:latest",
    ).execute(
        tmp_path,
        components=["backend"],
        docker_plan={"dockerfiles": {"backend": "keep"}, "compose": "skip"},
    )

    assert result.success
    assert result.message == "Existing Docker configuration kept"
    assert tmp_path / "backend/Dockerfile" in result.files_skipped
    assert provider.call_history == []
    assert "# existing" in (tmp_path / "backend/Dockerfile").read_text(encoding="utf-8")
    repository.storage.close()


@pytest.mark.asyncio
async def test_docker_plan_upgrade_is_explicit_and_targets_only_selected_artifact(tmp_path: Path):
    node_backend(tmp_path)
    write(tmp_path / "backend/Dockerfile", "FROM node:20-alpine\n# old\n")
    repository = repository_for(tmp_path)
    provider = MockProvider(responses={"project": decision_response()})

    result = await DockerAgent(
        repository=repository,
        provider=provider,
        model="devops-qwen:latest",
    ).execute(
        tmp_path,
        components=["backend"],
        compose=True,
        docker_plan={"dockerfiles": {"backend": "upgrade"}, "compose": "skip"},
    )

    assert result.success
    assert tmp_path / "backend/Dockerfile" in result.files_created
    assert "node:20-alpine" in (tmp_path / "backend/Dockerfile").read_text(encoding="utf-8")
    assert "# old" not in (tmp_path / "backend/Dockerfile").read_text(encoding="utf-8")
    assert result.data["docker_plan"]["dockerfiles"]["backend"] == "upgrade"
    repository.storage.close()


@pytest.mark.asyncio
async def test_explicit_docker_plan_does_not_acquire_new_repository_evidence(tmp_path: Path):
    node_backend(tmp_path)
    repository = repository_for(tmp_path)
    provider = MockProvider(responses={
        "project": json.dumps({
            "status": "NEEDS_EVIDENCE",
            "reason": "Production start evidence is incomplete",
            "components": [],
            "compose": {},
        }),
    })

    class MustNotAcquire:
        async def acquire(self, *_args, **_kwargs):
            raise AssertionError("planned Dockerize must not acquire new repository evidence")

    result = await DockerAgent(
        repository=repository,
        provider=provider,
        acquisition_service=MustNotAcquire(),
        model="devops-qwen:latest",
    ).execute(
        tmp_path,
        components=["backend"],
        docker_plan={"dockerfiles": {"backend": "generate"}, "compose": "skip"},
    )

    assert result.status == "NEEDS_EVIDENCE"
    assert "Production start evidence is incomplete" in result.message
    assert not (tmp_path / "backend/Dockerfile").exists()
    repository.storage.close()


@pytest.mark.asyncio
async def test_docker_plan_generates_only_selected_artifacts(tmp_path: Path):
    node_backend(tmp_path)
    write(
        tmp_path / "frontend/package.json",
        json.dumps({"scripts": {"start": "node server.js"}}),
    )
    write(tmp_path / "frontend/server.js", "server.listen(80);\n")
    repository = repository_for(tmp_path)
    provider = MockProvider(responses={"backend": decision_response()})

    result = await DockerAgent(
        dry_run=False,
        repository=repository,
        provider=provider,
        model="devops-qwen:latest",
    ).execute(
        tmp_path,
        components=["backend", "frontend"],
        compose=True,
        docker_plan={
            "dockerfiles": {"backend": "generate", "frontend": "skip"},
            "compose": "skip",
        },
    )

    assert result.success, result.message
    assert (tmp_path / "backend/Dockerfile").exists()
    assert not (tmp_path / "frontend/Dockerfile").exists()
    assert result.data["context"]["project"]["selected_components"] == ["backend"]
    assert len(provider.call_history) == 1
    repository.storage.close()


@pytest.mark.asyncio
async def test_string_start_command_matches_rendered_exec_form(tmp_path: Path):
    node_backend(tmp_path)
    repository = repository_for(tmp_path)
    response = json.loads(decision_response())
    response["components"][0]["start_command"] = "node src/server.js"
    provider = MockProvider(responses={"backend": json.dumps(response)})

    result = await DockerAgent(
        dry_run=True,
        repository=repository,
        provider=provider,
        model="devops-qwen:latest",
    ).execute(
        tmp_path,
        components=["backend"],
        compose=False,
        docker_plan={"dockerfiles": {"backend": "generate"}, "compose": "skip"},
    )

    assert result.success, result.message
    repository.storage.close()


@pytest.mark.asyncio
async def test_invalid_rendered_artifact_is_not_written_before_validation(tmp_path: Path, monkeypatch):
    node_backend(tmp_path)
    repository = repository_for(tmp_path)
    provider = MockProvider(responses={"backend": decision_response()})
    monkeypatch.setattr(
        "sohail_agent_cli.agents.docker_agent.DockerDecisionEngine.render_dockerfile",
        staticmethod(lambda _component: "FROM node:20-alpine\n"),
    )

    result = await DockerAgent(
        repository=repository,
        provider=provider,
        model="devops-qwen:latest",
    ).execute(
        tmp_path,
        components=["backend"],
        compose=False,
        docker_plan={"dockerfiles": {"backend": "generate"}, "compose": "skip"},
    )

    assert not result.success
    assert "install command is missing" in result.message
    assert not (tmp_path / "backend/Dockerfile").exists()
    repository.storage.close()


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


def feasibility_review_response() -> str:
    return json.dumps({
        "status": "INSUFFICIENT",
        "reason": "The repository evidence does not authorize all Docker requirements.",
        "repository_supported_decisions": [{
            "decision": "application_port",
            "value": "5001",
            "basis": "The application listener is explicitly represented in repository evidence.",
            "provenance": ["backend/src/server.js"],
        }],
        "deterministic_derivations": [],
        "model_proposals": [{
            "decision": "base_image",
            "value": "node:20-alpine",
            "status": "PROPOSED",
            "requires_authorization": True,
            "basis": "The runtime evidence suggests a compatible image family, but does not authorize an exact image.",
        }],
        "minimum_additional_evidence": [{
            "requirement": "exact Docker base image",
            "reason": "No exact repository or approved-policy base image is supplied.",
            "sources_to_check": ["current repository configuration"],
        }],
        "requested_user_action": "Supply authoritative Docker requirements and re-run Dockerize.",
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
    assert provider.call_history[0].options["format"]["additionalProperties"] is False
    assert provider.call_history[0].options["format"]["required"] == [
        "status", "reason", "components", "compose",
    ]
    assert provider.call_history[0].options["num_ctx"] == 16384
    assert provider.call_history[0].options["num_predict"] == 2048
    repository.storage.close()


def test_explicit_node_source_port_is_persisted(tmp_path: Path):
    node_backend(tmp_path, 5001)
    repository = repository_for(tmp_path)
    intelligence = repository.load_latest(str(tmp_path))
    assert intelligence is not None
    assert any(
        item["component"] == "backend"
        and item["port_type"] == "application"
        and item["port"] == 5001
        for item in intelligence.ports
    )
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    assert context.components[0]["ports"][0]["port"] == 5001
    repository.storage.close()


@pytest.mark.asyncio
async def test_missing_application_port_is_omitted_and_repair_removes_model_port(tmp_path: Path):
    node_backend_without_port(tmp_path)
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    assert not any(item.get("port_type") == "application" for item in context.components[0]["ports"])

    first = json.loads(decision_response())
    first["components"][0]["port"] = 3001
    first["compose"]["services"][0]["port"] = 3001
    first["compose"]["services"][0]["target_port"] = 3001
    repaired = json.loads(decision_response())
    repaired["components"][0].pop("port")
    repaired["compose"]["services"][0].pop("port")
    repaired["compose"]["services"][0].pop("target_port")

    class SequencedProvider(MockProvider):
        def __init__(self) -> None:
            super().__init__()
            self.responses_for_calls = [json.dumps(first), json.dumps(repaired)]

        async def generate(self, request):
            self.call_history.append(request)
            return GenerationResult(
                text=self.responses_for_calls.pop(0), model=request.model or "mock"
            )

    provider = SequencedProvider()
    decision = await DockerDecisionEngine(provider, "devops-qwen:latest").decide(context)

    assert decision.status == "NEEDS_EVIDENCE"
    assert "PORT" in decision.raw["reason"]
    assert provider.call_history == []
    repository.storage.close()


@pytest.mark.asyncio
async def test_bounded_repair_cannot_introduce_port_without_evidence(tmp_path: Path):
    node_backend_without_port(tmp_path)
    repository = repository_for(tmp_path)
    response = json.loads(decision_response(3001))
    provider = MockProvider(responses={"project": json.dumps(response)})

    decision = await DockerDecisionEngine(
        provider, "devops-qwen:latest",
    ).decide(DockerContextBuilder(repository).build(tmp_path, ["backend"]))

    assert decision.status == "NEEDS_EVIDENCE"
    assert "PORT" in decision.raw["reason"]
    assert decision.repair_attempted is False
    assert provider.call_history == []
    repository.storage.close()


@pytest.mark.asyncio
async def test_missing_application_port_does_not_render_expose_or_compose_mapping(tmp_path: Path):
    node_backend_without_port(tmp_path)
    repository = repository_for(tmp_path)
    response = json.loads(decision_response())
    response["components"][0].pop("port")
    response["compose"]["services"][0].pop("port")
    response["compose"]["services"][0].pop("target_port")
    result = await DockerAgent(
        dry_run=True,
        repository=repository,
        provider=MockProvider(responses={"project": json.dumps(response)}),
        model="devops-qwen:latest",
    ).execute(tmp_path, components=["backend"], compose=True, compose_action="generate")

    assert result.status == "NEEDS_EVIDENCE"
    assert "PORT" in result.message
    assert not (tmp_path / "backend/Dockerfile").exists()
    repository.storage.close()


@pytest.mark.asyncio
async def test_frontend_preview_command_survives_persistence_but_is_not_promoted_to_start(tmp_path: Path):
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

    provider = MockProvider(responses={"project": frontend_decision_response()})
    decision = await DockerDecisionEngine(provider, "devops-qwen:latest").decide(context)

    assert decision.status == "NEEDS_EVIDENCE"
    assert "frontend: exact production start command" in decision.raw["reason"]
    assert "development or preview commands are not authorized" in decision.raw["reason"]
    assert not provider.call_history
    assert "only a component's literal 'start' script" in context.prompt()
    assert "'dev' and 'preview' scripts as non-production roles" in context.prompt()
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
    assert "frontend: exact production start command" in decision.raw["reason"]
    repository.storage.close()


@pytest.mark.asyncio
async def test_backend_dev_command_is_rejected_as_production_start(tmp_path: Path):
    node_backend(tmp_path)
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    provider_payload = json.loads(decision_response())
    provider_payload["components"][0]["start_command"] = "nodemon src/server.js"
    provider_response = json.dumps(provider_payload)

    decision = await DockerDecisionEngine(
        MockProvider(responses={"project": provider_response}),
        "devops-qwen:latest",
    ).decide(context)

    assert decision.status == "NEEDS_EVIDENCE"
    assert "invented start command for backend" in decision.raw["reason"]
    repository.storage.close()


@pytest.mark.asyncio
async def test_known_runtime_gap_stops_docker_decision_and_artifacts_after_analysis(tmp_path: Path):
    node_backend(tmp_path)
    write(tmp_path / "frontend/package.json", '{"scripts":{"dev":"vite","preview":"vite preview"},"dependencies":{"vite":"^5"}}')
    write(tmp_path / "frontend/package-lock.json", "{}")
    write(tmp_path / "frontend/src/main.js", "console.log('frontend');\n")
    repository = repository_for(tmp_path)
    provider = MockProvider(responses={
        "DOCKER_FEASIBILITY_REVIEW_INPUT": feasibility_review_response(),
    })

    result = await DockerAgent(
        dry_run=True,
        repository=repository,
        provider=provider,
        model="devops-qwen:latest",
    ).execute(tmp_path, components=["backend", "frontend"], compose=True, compose_action="generate")

    assert not result.success
    assert result.status == "NEEDS_EVIDENCE"
    assert "frontend: exact production start command" in result.message
    assert len(provider.call_history) == 1
    assert result.data["feasibility_model_called"] is True
    assert result.data["model_called"] is False
    assert result.data["feasibility_review"]["status"] == "INSUFFICIENT"
    assert not (tmp_path / "backend/Dockerfile").exists()
    assert not (tmp_path / "frontend/Dockerfile").exists()
    assert not (tmp_path / "docker-compose.yml").exists()
    repository.storage.close()


@pytest.mark.asyncio
async def test_incomplete_preflight_reviews_current_evidence_without_authorizing_model_proposals(tmp_path: Path, capsys):
    node_backend_without_port(tmp_path)
    write(tmp_path / "backend/.env", "PORT=\nMONGO_URI=mongodb://secret\n")
    repository = repository_for(tmp_path)
    provider = MockProvider(responses={
        "DOCKER_FEASIBILITY_REVIEW_INPUT": feasibility_review_response(),
    })

    result = await DockerAgent(
        dry_run=True,
        repository=repository,
        provider=provider,
        model="devops-qwen:latest",
    ).execute(tmp_path, components=["backend"], compose=True, compose_action="generate")

    assert result.status == "NEEDS_EVIDENCE"
    assert result.data["model_called"] is False
    assert result.data["feasibility_model_called"] is True
    assert result.data["feasibility_review"]["status"] == "INSUFFICIENT"
    assert result.data["feasibility_review"]["model_output_is_repository_truth"] is False
    assert result.data["decision"]["missing_requirements"]
    assert len(provider.call_history) == 1
    prompt = provider.call_history[0].prompt
    assert "DOCKER_FEASIBILITY_REVIEW_INPUT" in prompt
    assert "mongodb://secret" not in prompt
    assert not (tmp_path / "backend/Dockerfile").exists()
    assert not (tmp_path / "docker-compose.yml").exists()
    from sohail_agent_cli.main import _print_docker_blocked

    _print_docker_blocked(result, dry_run=True, stage="Evidence-bound decision validation")
    output = capsys.readouterr().out
    assert "Docker Evidence Review:" in output
    assert "Model proposals — NOT REPOSITORY TRUTH:" in output
    assert "Ollama feasibility review was called: YES" in output
    assert "mongodb://secret" not in output
    repository.storage.close()


@pytest.mark.asyncio
async def test_malformed_evidence_target_does_not_claim_acquisition_started(tmp_path: Path, capsys):
    write(tmp_path / ".nvmrc", "20\n")
    write(tmp_path / "backend/package.json", '{"scripts":{"dev":"node src/server.js"}}')
    write(tmp_path / "backend/src/server.js", "app.listen(5001);\n")
    repository = repository_for(tmp_path)
    analysis_response = json.dumps({
        "status": "inspect_more",
        "findings": ["A relevant repository target may exist"],
        "evidence_relationships": [],
        "inspection_targets": ["malformed target proposal"],
        "clarification_questions": [],
        "candidate_hypotheses": [],
        "unsupported_assumptions": [],
    })

    class AnalysisOnlyProvider(MockProvider):
        async def generate(self, request):
            self.call_history.append(request)
            return GenerationResult(text=analysis_response, model=request.model or "mock")

    result = await DockerAgent(
        dry_run=True,
        repository=repository,
        provider=AnalysisOnlyProvider(),
        model="devops-qwen:latest",
    ).execute(tmp_path, components=["backend"], compose=True, compose_action="generate")

    output = capsys.readouterr().out
    assert result.status == "NEEDS_EVIDENCE"
    assert "Ollama feasibility review completed" in output
    assert "Deterministic evidence preflight remains authoritative" in output
    acquisition = result.data["evidence_acquisition"]
    assert len(acquisition) == 1
    assert acquisition[0]["scope"] == "docker"
    assert "malformed target proposal" not in acquisition[0]["inspected_targets"]
    assert "Acquisition started" not in output
    assert "Deterministic evidence inspection completed" not in output
    repository.storage.close()


@pytest.mark.asyncio
async def test_evidence_acquisition_retries_dockerize_at_most_once(tmp_path: Path):
    write(tmp_path / ".nvmrc", "20\n")
    write(tmp_path / "backend/package.json", '{"scripts":{"dev":"node src/server.js"},"dependencies":{"express":"^4"}}')
    write(tmp_path / "backend/package-lock.json", "{}")
    write(tmp_path / "backend/src/server.js", "app.listen(5001);\n")
    repository = repository_for(tmp_path)

    analysis_response = json.dumps({
        "status": "inspect_more", "findings": ["Inspect the component manifest"],
        "evidence_relationships": [], "inspection_targets": [],
        "clarification_questions": [], "candidate_hypotheses": [],
        "unsupported_assumptions": [],
    })

    class SequencedProvider(MockProvider):
        async def generate(self, request):
            self.call_history.append(request)
            if request.system and "evidence analysis assistant" in request.system:
                response = analysis_response
            else:
                response = decision_response()
            return GenerationResult(text=response, model=request.model or "mock")

    class AddsStartEvidence:
        def __init__(self, repository):
            self.repository = repository
            self.calls = 0

        def acquire(self, root, intelligence, gap, analysis):
            self.calls += 1
            refreshed = replace(intelligence)
            refreshed.commands = [*intelligence.commands, {
                "name": "start", "command": "node src/server.js", "source_file": "backend/package.json",
                "confidence": "high", "component": "backend",
            }]
            refreshed.evidence = [*intelligence.evidence, Evidence(
                "backend/package.json", "command", "backend.start_command", "node src/server.js", "high",
            )]
            self.repository.persist(refreshed)
            return AcquisitionResult(accepted_evidence_added=True, added_evidence_count=1, refreshed=refreshed)

    acquisition = AddsStartEvidence(repository)
    result = await DockerAgent(
        dry_run=True, repository=repository, provider=SequencedProvider(),
        model="devops-qwen:latest", acquisition_service=acquisition,
    ).execute(tmp_path, components=["backend"], compose=True, compose_action="generate")

    assert not result.success
    assert result.status == "NEEDS_EVIDENCE"
    assert acquisition.calls == 0
    assert result.data["evidence_acquisition"] == []
    assert not (tmp_path / "backend/Dockerfile").exists()
    repository.storage.close()


def test_root_commands_do_not_contaminate_component_context(tmp_path: Path):
    write(tmp_path / ".nvmrc", "20\n")
    write(
        tmp_path / "package.json",
        '{"scripts":{"start":"npm run start --prefix backend","build":"npm install --prefix backend && npm run build --prefix frontend"}}',
    )
    write(tmp_path / "backend/package.json", '{"scripts":{"start":"node src/index.js","dev":"nodemon src/index.js"},"dependencies":{"express":"^4"}}')
    write(tmp_path / "backend/package-lock.json", "{}")
    write(tmp_path / "backend/src/index.js", "app.listen(5001);\n")
    write(tmp_path / "frontend/package.json", '{"scripts":{"preview":"vite preview"},"dependencies":{"vite":"^5"}}')
    write(tmp_path / "frontend/package-lock.json", "{}")
    write(tmp_path / "frontend/src/main.js", "console.log('frontend');\n")
    repository = repository_for(tmp_path)

    backend_context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    frontend_context = DockerContextBuilder(repository).build(tmp_path, ["frontend"])

    assert {item["source_file"] for item in backend_context.components[0]["commands"]} == {"backend/package.json"}
    assert {item["source_file"] for item in frontend_context.components[0]["commands"]} == {"frontend/package.json"}
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
    assert "base image" in decision.raw["reason"]
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
async def test_empty_reason_gets_one_bounded_repair_and_revalidates(tmp_path: Path):
    node_backend(tmp_path)
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    invalid = json.dumps({"status": "ready", "reason": "", "components": [], "compose": {}})

    class SequentialProvider(MockProvider):
        def __init__(self, outputs: list[str]):
            super().__init__()
            self.outputs = outputs

        async def generate(self, request):
            self.call_history.append(request)
            return GenerationResult(text=self.outputs.pop(0), model=request.model or "mock")

    provider = SequentialProvider([invalid, decision_response()])
    decision = await DockerDecisionEngine(provider, "devops-qwen:latest").decide(context)

    assert decision.status == "ready"
    assert decision.repair_attempted is True
    assert len(provider.call_history) == 2
    assert "VALIDATION_ERROR" in provider.call_history[1].prompt
    assert "non-empty" in (provider.call_history[1].system or "")
    repository.storage.close()


@pytest.mark.asyncio
async def test_invalid_docker_output_fails_after_exactly_one_repair(tmp_path: Path):
    node_backend(tmp_path)
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    invalid = json.dumps({"status": "ready", "reason": "", "components": [], "compose": {}})

    class SequentialProvider(MockProvider):
        def __init__(self):
            super().__init__()
            self.outputs = [invalid, invalid]

        async def generate(self, request):
            self.call_history.append(request)
            return GenerationResult(text=self.outputs.pop(0), model=request.model or "mock")

    provider = SequentialProvider()
    with pytest.raises(DockerDecisionError, match="after one bounded repair attempt"):
        await DockerDecisionEngine(provider, "devops-qwen:latest").decide(context)
    assert len(provider.call_history) == 2
    repository.storage.close()


@pytest.mark.asyncio
async def test_missing_selected_component_is_repaired_from_its_scoped_context(tmp_path: Path):
    node_backend(tmp_path)
    write(tmp_path / "frontend/package.json", json.dumps({"scripts": {"start": "npx serve -s dist"}}))
    write(tmp_path / "frontend/package-lock.json", "{}")
    write(tmp_path / "frontend/index.html", "<div id=\"root\"></div>\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend", "frontend"])
    backend_only = decision_response()
    frontend_only = json.dumps({
        "status": "ready",
        "reason": "Frontend evidence is sufficient",
        "components": [{
            "name": "frontend",
            "base_image": "node:20-alpine",
            "working_directory": "/app",
            "package_manager": "npm",
            "install_command": "npm ci",
            "start_command": "npx serve -s dist",
        }],
        "compose": {"services": [{
            "name": "frontend",
            "component": "frontend",
            "build_context": "./frontend",
        }]},
    })

    class SequentialProvider(MockProvider):
        def __init__(self):
            super().__init__()
            self.outputs = [backend_only, frontend_only]

        async def generate(self, request):
            self.call_history.append(request)
            return GenerationResult(text=self.outputs.pop(0), model=request.model or "mock")

    provider = SequentialProvider()
    decision = await DockerDecisionEngine(provider, "devops-qwen:latest").decide(context)

    assert decision.status == "ready"
    assert {item["name"] for item in decision.components} == {"backend", "frontend"}
    assert {item["component"] for item in decision.compose["services"]} == {"backend", "frontend"}
    assert len(provider.call_history) == 2
    assert '"selected_components":["frontend"]' in provider.call_history[1].prompt
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
    assert all("value" not in item for item in context.components[0]["environment"])
    repository.storage.close()


@pytest.mark.asyncio
async def test_dockerize_setup_blocker_stops_before_ollama(tmp_path: Path):
    node_backend(tmp_path)
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    context = replace(
        context,
        infrastructure={
            **context.infrastructure,
            "project_setup": {
                "status": "NEEDS_EVIDENCE",
                "requirements": [{
                    "name": "PORT",
                    "component": "backend",
                    "status": "NEEDS_EVIDENCE",
                    "blocks": ["dockerfile"],
                    "message": "backend application port cannot be selected without verified evidence",
                    "value": None,
                }],
            },
        },
    )
    provider = MockProvider(responses={})

    decision = await DockerDecisionEngine(provider, "devops-qwen:latest").decide(context)

    assert decision.status == "NEEDS_EVIDENCE"
    assert decision.model_called is False
    assert "application port cannot be selected" in decision.raw["reason"]
    assert provider.call_history == []
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
    write(tmp_path / "backend/.dockerignore", "preserve-me\n")
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
    assert (tmp_path / "backend/.dockerignore").read_text(encoding="utf-8") == "preserve-me\n"
    assert result.data["dry_run"] is True
    assert {item["action"] for item in result.data["planned_actions"]} == {"generate"}
    assert all(".dockerignore" not in item["path"] for item in result.data["planned_actions"])
    assert any(item["path"].endswith("backend/Dockerfile") for item in result.data["planned_actions"])
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
            "working_directory": "/app",
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
    assert "base image" in decision.raw["reason"] or "exact Node.js runtime version" in decision.raw["reason"]
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
