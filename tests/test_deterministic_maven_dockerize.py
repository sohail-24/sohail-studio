import asyncio
import json
from dataclasses import replace
from pathlib import Path

from sqlalchemy import create_engine

from core.storage.database import Storage, StorageConfig
from core.storage.project_intelligence import ProjectIntelligenceRepository, metadata
from sohail_agent_cli.agents.docker_agent import DockerAgent
from sohail_agent_cli.dockerize import DockerContext, DockerContextBuilder, DockerDecisionEngine
from sohail_agent_cli.dockerize.platform_policy import APPROVED_PLATFORM_POLICY, applicable_platform_policies
from sohail_agent_cli.inspection import DeepInspector
from sohail_agent_cli.providers import MockProvider


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def spring_boot_project(root: Path, *, modules: bool = False) -> None:
    module_block = "<modules><module>application</module></modules>" if modules else ""
    write(root / "pom.xml", f"""
      <project xmlns="http://maven.apache.org/POM/4.0.0">
        <modelVersion>4.0.0</modelVersion>
        <parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId><version>3.2.2</version></parent>
        <groupId>com.example</groupId><artifactId>expenses</artifactId><version>1.0.0</version>
        <properties><java.version>17</java.version></properties>
        {module_block}
        <build><plugins><plugin><groupId>org.springframework.boot</groupId><artifactId>spring-boot-maven-plugin</artifactId></plugin></plugins></build>
      </project>
    """)
    write(
        root / "src/main/java/com/example/ExpensesApplication.java",
        "package com.example; public class ExpensesApplication { public static void main(String[] args) {} }",
    )
    write(root / "src/main/resources/application.properties", "server.port=9090\n")
    if modules:
        write(root / "application/pom.xml", "<project><artifactId>application</artifactId><version>1</version></project>")


def repository_for(root: Path, *, explicit_container_evidence: bool = False) -> ProjectIntelligenceRepository:
    intelligence = DeepInspector().inspect(root)
    if explicit_container_evidence:
        dockerfile = root / "Dockerfile"
        write(dockerfile, "FROM eclipse-temurin:17-jre-jammy\nWORKDIR /app\n")
        intelligence = DeepInspector().inspect(root)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repository = ProjectIntelligenceRepository(
        Storage(StorageConfig("postgresql://masked@localhost/studio"), engine=engine)
    )
    repository.persist(intelligence)
    return repository


def java_decision(artifact: str) -> str:
    return json.dumps({
        "status": "ready",
        "reason": "All values are supplied by persisted evidence",
        "components": [{
            "name": "application",
            "base_image": "eclipse-temurin:17-jre-jammy",
            "working_directory": "/app",
            "package_manager": "maven",
            "install_command": "",
            "build_command": "mvn package",
            "start_command": ["java", "-jar", artifact],
            "port": 9090,
        }],
        "compose": {"services": [{
            "name": "application", "component": "application", "build_context": ".",
            "port": 9090, "target_port": 9090,
        }]},
    })


def test_spring_boot_artifact_is_derived_with_provenance_and_survives_persistence(tmp_path: Path):
    spring_boot_project(tmp_path)
    repository = repository_for(tmp_path)
    loaded = repository.load_latest(str(tmp_path))

    assert loaded is not None
    artifact = loaded.components[0]["artifacts"][0]
    assert artifact["path"] == "target/expenses-1.0.0.jar"
    assert artifact["launch_command"] == ["java", "-jar", "target/expenses-1.0.0.jar"]
    assert artifact["source_type"] == "DERIVED_DETERMINISTIC"
    assert artifact["rule_id"] == "maven.executable-artifact.spring-boot.v1"
    assert artifact["model_inference"] is False
    derived = next(item for item in loaded.evidence if item.key == "application.production_start_command")
    assert derived.source_type == "DERIVED_DETERMINISTIC"
    assert derived.derived_from
    assert derived.rule_id == "maven.executable-artifact.spring-boot.v1"
    context = DockerContextBuilder(repository).build(tmp_path, ["application"], loaded.inspection_run_id)
    assert context.components[0]["artifacts"][0]["path"] == "target/expenses-1.0.0.jar"
    repository.storage.close()


def test_ambiguous_maven_project_remains_needs_evidence(tmp_path: Path):
    spring_boot_project(tmp_path, modules=True)
    intelligence = DeepInspector().inspect(tmp_path)
    component = next(item for item in intelligence.components if item["name"] == "application")
    assert component["deployment_evidence"]["status"] == "UNSUPPORTED"
    assert not component["artifacts"]
    assert any(item.source_type == "UNSUPPORTED" for item in intelligence.evidence)


def test_explicit_production_command_is_accepted_without_deterministic_artifact():
    context = DockerContext(
        project={"name": "explicit", "root_path": ".", "selected_components": ["backend"]},
        components=[{
            "name": "backend", "path": ".", "package_manager": "npm", "commands": [{
                "name": "start", "command": "node server.js", "source_file": "package.json",
            }], "ports": [], "runtimes": [], "base_images": [], "working_directories": [],
        }],
        infrastructure={}, evidence=[], artifact_plan={},
    )
    provider = MockProvider(responses={"project": json.dumps({
        "status": "NEEDS_EVIDENCE", "reason": "base image is not supplied", "components": [], "compose": {},
    })})
    decision = asyncio.run(DockerDecisionEngine(provider, "devops-qwen:latest").decide(context))
    assert decision.model_called is False
    assert decision.repair_attempted is False
    assert "base image" in decision.raw["reason"]
    assert "working directory" in decision.raw["reason"]
    assert provider.call_history == []


def test_missing_base_image_blocks_before_ollama_and_repair(tmp_path: Path):
    spring_boot_project(tmp_path)
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["application"])
    component = dict(context.components[0])
    component["framework"] = "Unrecognized"
    context = replace(context, components=[component], platform_policies=[])
    provider = MockProvider(responses={"project": java_decision("target/expenses-1.0.0.jar")})

    decision = asyncio.run(DockerDecisionEngine(provider, "devops-qwen:latest").decide(context))

    assert decision.status == "NEEDS_EVIDENCE"
    assert decision.model_called is False
    assert decision.repair_attempted is False
    assert "application: exact Docker base image" in decision.raw["missing_requirements"]
    assert "application: exact working directory" in decision.raw["missing_requirements"]
    assert decision.raw["stage"] == "deterministic Docker requirement preflight"
    assert provider.call_history == []
    repository.storage.close()


def test_missing_working_directory_blocks_before_ollama(tmp_path: Path):
    spring_boot_project(tmp_path)
    repository = repository_for(tmp_path, explicit_container_evidence=True)
    context = DockerContextBuilder(repository).build(tmp_path, ["application"])
    component = dict(context.components[0])
    component["framework"] = "Unrecognized"
    component["working_directories"] = []
    context = replace(context, components=[component], platform_policies=[])
    provider = MockProvider(responses={"project": java_decision("target/expenses-1.0.0.jar")})

    decision = asyncio.run(DockerDecisionEngine(provider, "devops-qwen:latest").decide(context))

    assert decision.status == "NEEDS_EVIDENCE"
    assert decision.model_called is False
    assert "application: exact working directory" in decision.raw["missing_requirements"]
    assert provider.call_history == []
    repository.storage.close()


def test_derived_spring_boot_start_and_artifact_pass_preflight_when_layout_is_authorized(tmp_path: Path):
    spring_boot_project(tmp_path)
    repository = repository_for(tmp_path, explicit_container_evidence=True)
    intelligence = repository.load_latest(str(tmp_path))
    assert intelligence is not None
    context = DockerContextBuilder(repository).build(tmp_path, ["application"], intelligence.inspection_run_id)
    provider = MockProvider(responses={"project": java_decision("target/expenses-1.0.0.jar")})

    decision = asyncio.run(DockerDecisionEngine(provider, "devops-qwen:latest").decide(context))

    assert decision.status == "ready"
    assert decision.model_called is True
    assert len(provider.call_history) == 1
    assert context.platform_policies[0]["policy_id"] == "java-spring-boot-container-v1"
    assert context.platform_policies[0]["source_type"] == APPROVED_PLATFORM_POLICY
    assert context.platform_policies[0]["values"]["base_image"]["value"] == "eclipse-temurin:17-jre-jammy"
    assert context.platform_policies[0]["values"]["working_directory"]["value"] == "/app"
    repository.storage.close()


def test_java_spring_boot_policy_is_non_applicable_without_executable_jar_proof(tmp_path: Path):
    spring_boot_project(tmp_path, modules=True)
    intelligence = DeepInspector().inspect(tmp_path)
    component = next(item for item in intelligence.components if item["name"] == "application")
    assert applicable_platform_policies([component]) == []


def test_conflicting_explicit_layout_evidence_blocks_policy_instead_of_overriding_it(tmp_path: Path):
    spring_boot_project(tmp_path)
    write(tmp_path / "Dockerfile", "FROM registry.example/java:17\nWORKDIR /srv\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["application"])
    provider = MockProvider(responses={"project": java_decision("target/expenses-1.0.0.jar")})

    decision = asyncio.run(DockerDecisionEngine(provider, "devops-qwen:latest").decide(context))

    assert decision.status == "NEEDS_EVIDENCE"
    assert any("conflicting Docker base image evidence" in item for item in decision.raw["missing_requirements"])
    assert any("conflicting working directory evidence" in item for item in decision.raw["missing_requirements"])
    assert decision.model_called is False
    assert provider.call_history == []
    repository.storage.close()


def test_model_cannot_override_policy_authorized_base_image_or_workdir(tmp_path: Path):
    spring_boot_project(tmp_path)
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["application"])
    wrong = java_decision("target/expenses-1.0.0.jar").replace(
        "eclipse-temurin:17-jre-jammy", "openjdk:17"
    ).replace('"working_directory": "/app"', '"working_directory": "/srv"')
    provider = MockProvider(responses={"project": wrong})

    decision = asyncio.run(DockerDecisionEngine(provider, "devops-qwen:latest").decide(context))

    assert decision.status == "NEEDS_EVIDENCE"
    assert decision.model_called is True
    assert decision.repair_attempted is True
    assert decision.raw["model_proposed"]["components"][0]["base_image"] == "openjdk:17"
    assert decision.raw["model_proposed"]["components"][0]["working_directory"] == "/srv"
    assert len(provider.call_history) == 2
    repository.storage.close()


def test_explicit_production_start_is_authorized_when_all_layout_facts_exist():
    context = DockerContext(
        project={"name": "explicit", "root_path": ".", "selected_components": ["backend"]},
        components=[{
            "name": "backend", "path": ".", "package_manager": "maven",
            "runtimes": [{"runtime": "Java", "version": "17", "source_file": "pom.xml"}],
            "commands": [
                {"name": "start", "command": "java -jar app.jar", "source_file": "README.md"},
                {"name": "package", "command": "mvn package", "source_file": "pom.xml"},
            ],
            "ports": [],
            "base_images": [{"image": "registry.example/java:17", "source_file": "Dockerfile", "source_type": "EXPLICIT_EVIDENCE", "model_inference": False}],
            "working_directories": [{"path": "/srv/app", "source_file": "Dockerfile", "source_type": "EXPLICIT_EVIDENCE", "model_inference": False}],
        }],
        infrastructure={}, evidence=[], artifact_plan={},
    )
    provider = MockProvider(responses={"project": json.dumps({
        "status": "ready", "reason": "Explicit evidence supplied", "components": [{
            "name": "backend", "base_image": "registry.example/java:17", "working_directory": "/srv/app",
            "package_manager": "maven", "install_command": "", "build_command": "mvn package",
            "start_command": "java -jar app.jar", "port": None,
        }], "compose": {"services": [{
            "name": "backend", "component": "backend", "build_context": ".", "port": None, "target_port": None,
        }]},
    })})

    decision = asyncio.run(DockerDecisionEngine(provider, "devops-qwen:latest").decide(context))

    assert decision.status == "ready"
    assert len(provider.call_history) == 1


def test_dry_run_preflight_failure_writes_zero_files_and_does_not_rescan(tmp_path: Path, monkeypatch):
    spring_boot_project(tmp_path)
    repository = repository_for(tmp_path)
    intelligence = repository.load_latest(str(tmp_path))
    assert intelligence is not None
    intelligence.components[0]["framework"] = "Unrecognized"
    repository.persist(intelligence)
    intelligence = repository.load_latest(str(tmp_path))
    assert intelligence is not None
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    provider = MockProvider(responses={"project": java_decision("target/expenses-1.0.0.jar")})
    monkeypatch.setattr(
        "sohail_agent_cli.inspection.DeepInspector.inspect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Dockerize rescanned repository")),
    )

    result = asyncio.run(DockerAgent(
        dry_run=True, repository=repository, provider=provider, model="devops-qwen:latest",
    ).execute(
        tmp_path, components=["application"],
        docker_plan={"dockerfiles": {"application": "generate"}, "compose": "generate"},
        inspection_run_id=intelligence.inspection_run_id,
    ))

    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert result.status == "NEEDS_EVIDENCE"
    assert before == after
    assert provider.call_history == []
    assert result.data["model_called"] is False
    assert result.data["repair_attempts"] == 0
    assert result.data["diagnostic"]["stage"] == "deterministic Docker requirement preflight"
    assert result.data["diagnostic"]["missing_requirements"]
    repository.storage.close()


def test_dockerize_does_not_rescan_and_dry_run_keeps_files_unchanged(tmp_path: Path, monkeypatch):
    spring_boot_project(tmp_path)
    repository = repository_for(tmp_path, explicit_container_evidence=True)
    intelligence = repository.load_latest(str(tmp_path))
    assert intelligence is not None
    run_id = intelligence.inspection_run_id
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    monkeypatch.setattr("sohail_agent_cli.inspection.DeepInspector.inspect", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Dockerize rescanned repository")))
    artifact = "target/expenses-1.0.0.jar"
    result = asyncio.run(DockerAgent(
        dry_run=True, repository=repository,
        provider=MockProvider(responses={"project": java_decision(artifact)}),
        model="devops-qwen:latest",
    ).execute(
        tmp_path, components=["application"],
        docker_plan={"dockerfiles": {"application": "upgrade"}, "compose": "generate"},
        inspection_run_id=run_id,
    ))
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert result.success, result.message
    assert before == after
    assert result.data["inspection_run_id"] == run_id
    rendered = {Path(item["path"]).name: item["content"] for item in result.data["rendered_artifacts"]}
    assert "expenses-1.0.0.jar" in rendered["Dockerfile"]
    assert "FROM maven:3.9.16-eclipse-temurin-17 AS build" in rendered["Dockerfile"]
    assert "FROM eclipse-temurin:17-jre-jammy" in rendered["Dockerfile"]
    assert "WORKDIR /app" in rendered["Dockerfile"]
    assert 'CMD ["java", "-jar", "target/expenses-1.0.0.jar"]' in rendered["Dockerfile"]
    assert "RUN mvn package" in rendered["Dockerfile"]
    repository.storage.close()


def test_normal_run_writes_only_selected_validated_artifacts(tmp_path: Path):
    spring_boot_project(tmp_path)
    repository = repository_for(tmp_path, explicit_container_evidence=True)
    intelligence = repository.load_latest(str(tmp_path))
    assert intelligence is not None
    result = asyncio.run(DockerAgent(
        repository=repository,
        provider=MockProvider(responses={"project": java_decision("target/expenses-1.0.0.jar")}),
        model="devops-qwen:latest",
    ).execute(
        tmp_path, components=["application"],
        docker_plan={"dockerfiles": {"application": "upgrade"}, "compose": "generate"},
        inspection_run_id=intelligence.inspection_run_id,
    ))
    assert result.success, result.message
    assert (tmp_path / "Dockerfile").exists()
    assert (tmp_path / "docker-compose.yml").exists()
    assert not (tmp_path / "Jenkinsfile").exists()
    assert {item["name"] for item in result.data["decision"]["compose"]["services"]} == {"application"}
    assert "mysql" not in next(
        item["content"] for item in result.data["rendered_artifacts"]
        if item["path"].endswith("docker-compose.yml")
    ).lower()
    assert result.data["inspection_run_id"] == intelligence.inspection_run_id
    repository.storage.close()
