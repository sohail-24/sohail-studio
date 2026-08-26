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
from sohail_agent_cli.providers import MockProvider


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
