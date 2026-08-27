import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from core.evidence import EvidenceOrigin, VerifiedEngineeringPatternRecognizer
from core.storage.database import Storage, StorageConfig
from core.storage.project_intelligence import ProjectIntelligenceRepository, metadata
from sohail_agent_cli.agents.docker_agent import DockerAgent
from sohail_agent_cli.dockerize import DockerContextBuilder, DockerDecisionEngine
from sohail_agent_cli.inspection import DeepInspector, ProjectIntelligence
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
    intelligence = DeepInspector().inspect(root)
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


def static_site(root: Path, *, include_entry: bool = True) -> None:
    write(root / ".nvmrc", "20\n")
    write(
        root / "site/package.json",
        json.dumps({"scripts": {"build": "compile-assets"}, "dependencies": {"asset-tool": "1.0.0"}}),
    )
    write(root / "site/package-lock.json", "{}")
    write(root / "site/src/main.js", "console.log('site');\n")
    if include_entry:
        write(root / "site/index.html", "<!doctype html><html><body></body></html>\n")
    write(
        root / "kubernetes/site-deployment.yml",
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: site\nspec:\n  template:\n    spec:\n      containers:\n        - name: site\n          ports:\n            - containerPort: 80\n",
    )
    write(
        root / "kubernetes/site-service.yml",
        "apiVersion: v1\nkind: Service\nmetadata:\n  name: site\nspec:\n  selector:\n    app: site\n  ports:\n    - port: 80\n      targetPort: 80\n",
    )


def test_verified_static_pattern_is_deterministic_traceable_and_persisted(tmp_path: Path):
    static_site(tmp_path)

    intelligence = DeepInspector().inspect(tmp_path)
    patterns = VerifiedEngineeringPatternRecognizer().recognize(intelligence)

    assert [pattern.category for pattern in patterns] == ["static_frontend"]
    pattern = patterns[0]
    assert pattern.origin is EvidenceOrigin.VERIFIED_INFERENCE
    assert pattern.component == "site"
    reference_files = {item.source_file for item in pattern.evidence_references}
    assert reference_files >= {
        "site/package.json",
        "site/package-lock.json",
        "site/index.html",
        ".nvmrc",
    }
    assert reference_files.intersection({
        "kubernetes/site-deployment.yml",
        "kubernetes/site-service.yml",
    })
    assert all(item.origin is EvidenceOrigin.REPOSITORY_EVIDENCE for item in pattern.evidence_references)
    assert "site" not in pattern.policy["implementation"]

    repository = repository_for(tmp_path)
    persisted = repository.load_latest(str(tmp_path))
    assert persisted is not None
    assert persisted.verified_patterns[0]["origin"] == "VERIFIED_INFERENCE"
    assert persisted.verified_patterns[0]["evidence_references"]
    repository.storage.close()


def test_insufficient_evidence_does_not_create_a_false_pattern(tmp_path: Path):
    static_site(tmp_path, include_entry=False)

    intelligence = DeepInspector().inspect(tmp_path)

    assert intelligence.verified_patterns == []
    assert VerifiedEngineeringPatternRecognizer().recognize(intelligence) == []


def test_pattern_recognizer_is_not_tied_to_project_or_framework_names():
    intelligence = ProjectIntelligence(
        name="arbitrary-repository",
        root_path="/tmp/arbitrary-repository",
        files=[
            {"relative_path": "web/deps.manifest", "classification": "dependency_manifest"},
            {"relative_path": "web/deps.lock", "classification": "lockfile"},
            {"relative_path": "web/index.html", "classification": "unknown"},
        ],
        components=[{
            "name": "web",
            "path": "web",
            "kind": "frontend",
            "runtimes": [{"runtime": "CustomRuntime", "version": "7.2", "source_file": "runtime.conf", "confidence": "high"}],
        }],
        commands=[{
            "name": "build",
            "command": "assemble-assets",
            "source_file": "web/deps.manifest",
            "confidence": "high",
        }],
        runtimes=[{"runtime": "CustomRuntime", "version": "7.2", "source_file": "runtime.conf", "confidence": "high"}],
        ports=[{
            "component": "web",
            "port_type": "application",
            "port": 8080,
            "source_file": "web/service.conf",
            "confidence": "high",
            "conflict": False,
        }],
    )

    patterns = VerifiedEngineeringPatternRecognizer().recognize(intelligence)

    assert len(patterns) == 1
    assert patterns[0].component == "web"


def static_decision_response() -> str:
    return json.dumps({
        "status": "ready",
        "reason": "A verified static frontend pattern authorizes the serving strategy",
        "components": [{
            "name": "site",
            "deployment_pattern": "static-frontend",
            "base_image": "node:20-alpine",
            "working_directory": "/app",
            "package_manager": "npm",
            "install_command": "npm ci",
            "build_command": "compile-assets",
            "start_command": ["npx", "serve", "-s", "dist", "-l", "80"],
            "port": 80,
        }],
        "compose": {"services": [{
            "name": "site",
            "component": "site",
            "build_context": "./site",
            "port": 80,
            "target_port": 80,
        }]},
    })


@pytest.mark.asyncio
async def test_omitted_verified_pattern_identity_is_restored_from_persisted_context(tmp_path: Path):
    static_site(tmp_path)
    repository = repository_for(tmp_path)
    response = json.loads(static_decision_response())
    del response["components"][0]["deployment_pattern"]

    decision = await DockerDecisionEngine(
        MockProvider(responses={"project": json.dumps(response)}), "devops-qwen:latest",
    ).decide(DockerContextBuilder(repository).build(tmp_path, ["site"]))

    assert decision.status == "ready"
    assert decision.components[0]["deployment_pattern"] == "static-frontend"
    repository.storage.close()


@pytest.mark.asyncio
async def test_static_verified_contract_is_restored_when_model_omits_strategy_fields(tmp_path: Path):
    static_site(tmp_path)
    repository = repository_for(tmp_path)
    response = json.loads(static_decision_response())
    response["components"][0].pop("deployment_pattern")
    response["components"][0].pop("install_command")
    response["components"][0].pop("start_command")
    provider = MockProvider(responses={"project": json.dumps(response)})
    context = DockerContextBuilder(repository).build(tmp_path, ["site"])

    decision = await DockerDecisionEngine(provider, "devops-qwen:latest").decide(context)

    assert decision.status == "ready"
    component = decision.components[0]
    assert component["deployment_pattern"] == "static-frontend"
    assert component["strategy_id"] == "react-vite-static"
    assert component["execution_strategy"] == "STATIC_ARTIFACT_SERVER"
    assert component["install_command"] == "npm ci"
    policy = context.platform_policies[0]
    serving = policy["values"]["static_serving_command"]
    assert serving["source_type"] == "APPROVED_PLATFORM_POLICY"
    assert serving["model_inference"] is False
    repository.storage.close()


@pytest.mark.asyncio
async def test_bounded_repair_restores_omitted_static_verified_contract(tmp_path: Path):
    static_site(tmp_path)
    repository = repository_for(tmp_path)
    first = json.loads(static_decision_response())
    first["compose"]["services"][0]["port"] = 81
    first["compose"]["services"][0]["target_port"] = 81
    repaired = json.loads(static_decision_response())
    for key in ("deployment_pattern", "install_command", "start_command"):
        repaired["components"][0].pop(key, None)

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
    decision = await DockerDecisionEngine(
        provider, "devops-qwen:latest",
    ).decide(DockerContextBuilder(repository).build(tmp_path, ["site"]))

    assert decision.status == "ready"
    component = decision.components[0]
    assert component["deployment_pattern"] == "static-frontend"
    assert component["execution_strategy"] == "STATIC_ARTIFACT_SERVER"
    assert component["install_command"] == "npm ci"
    assert decision.compose["services"][0]["port"] == 80
    assert decision.compose["services"][0]["target_port"] == 80
    assert decision.repair_attempted is True
    repository.storage.close()


@pytest.mark.asyncio
async def test_dockerize_uses_verified_pattern_before_clarification(tmp_path: Path):
    static_site(tmp_path)
    repository = repository_for(tmp_path)
    provider = MockProvider(responses={"project": static_decision_response()})

    result = await DockerAgent(
        dry_run=True,
        repository=repository,
        provider=provider,
        model="mock",
    ).execute(tmp_path, components=["site"], compose=False)

    assert result.success is True, result.message
    assert result.status == "SUCCESS"
    assert len(provider.call_history) == 1
    assert "static-frontend" in provider.call_history[0].prompt
    repository.storage.close()


@pytest.mark.asyncio
async def test_static_artifact_server_does_not_require_application_start_script(tmp_path: Path):
    static_site(tmp_path)
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["site"])
    component = context.components[0]

    assert component["execution_strategy"] == "STATIC_ARTIFACT_SERVER"
    response = json.loads(static_decision_response())
    response["components"][0].pop("start_command")
    response["components"][0]["build_command"] = "compile-assets"

    decision = await DockerDecisionEngine(
        MockProvider(responses={"project": json.dumps(response)}), "devops-qwen:latest",
    ).decide(context)

    assert decision.status == "ready"
    rendered = DockerDecisionEngine.render_dockerfile({
        **decision.components[0],
        "artifacts": component["artifacts"],
        "files": component["files"],
        "strategy_id": component["strategy_id"],
        "platform_policy": context.platform_policies[0],
    })
    assert 'CMD ["npx", "serve", "-s", "build"]' in rendered
    repository.storage.close()


@pytest.mark.asyncio
async def test_repair_canonicalizes_compose_port_to_evidenced_static_component_port(tmp_path: Path):
    static_site(tmp_path)
    repository = repository_for(tmp_path)
    response = json.loads(static_decision_response())
    response["compose"]["services"][0]["port"] = 81
    response["compose"]["services"][0]["target_port"] = 81
    provider = MockProvider(responses={"project": json.dumps(response)})

    decision = await DockerDecisionEngine(
        provider, "devops-qwen:latest",
    ).decide(DockerContextBuilder(repository).build(tmp_path, ["site"]))

    assert decision.status == "ready"
    assert decision.components[0]["port"] == 80
    assert decision.compose["services"][0]["port"] == 80
    assert decision.compose["services"][0]["target_port"] == 80
    assert decision.repair_attempted is True
    assert len(provider.call_history) == 2
    repository.storage.close()


def test_secret_values_stay_out_of_persisted_and_model_facing_pattern_context(tmp_path: Path):
    static_site(tmp_path)
    write(tmp_path / "site/.env", "PORT=80\nAPI_TOKEN=never-send-this\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["site"])

    serialized = json.dumps(context.to_dict())
    persisted = json.dumps(repository.load_latest(str(tmp_path)).to_dict())

    assert "never-send-this" not in serialized
    assert "never-send-this" not in context.prompt()
    assert "never-send-this" not in persisted
    assert "API_TOKEN" in serialized
    assert "REDACTED" in serialized
    repository.storage.close()
