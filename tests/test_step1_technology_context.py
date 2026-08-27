"""Focused Step 1 tests for technology-neutral Docker context boundaries."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from core.storage.database import Storage, StorageConfig
from core.storage.project_intelligence import ProjectIntelligenceRepository, metadata
from sohail_agent_cli.dockerize import (
    DockerContextBuilder,
    DockerDecisionEngine,
    DockerDecisionError,
)
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
    repository.persist(DeepInspector().inspect(root))
    return repository


def spring_boot_project(root: Path) -> None:
    write(root / "pom.xml", """
      <project xmlns="http://maven.apache.org/POM/4.0.0">
        <modelVersion>4.0.0</modelVersion>
        <parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId><version>3.2.2</version></parent>
        <groupId>com.example</groupId><artifactId>expenses</artifactId><version>1.0.0</version>
        <properties><java.version>17</java.version></properties>
        <build><plugins><plugin><groupId>org.springframework.boot</groupId><artifactId>spring-boot-maven-plugin</artifactId></plugin></plugins></build>
      </project>
    """)
    write(root / "src/main/java/com/example/ExpensesApplication.java", "public class ExpensesApplication { public static void main(String[] args) {} }")


def test_java_profile_and_policy_are_built_from_persisted_evidence(tmp_path: Path):
    spring_boot_project(tmp_path)
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["application"])

    profile = context.components[0]["technology_profile"]
    assert profile["languages"] == ["Java"]
    assert profile["frameworks"] == ["Spring Boot"]
    assert profile["build_system"] == "maven"
    assert profile["runtimes"][0]["version"] == "17"
    assert context.platform_policies[0]["policy_id"] == "java-spring-boot-container-v1"
    repository.storage.close()


def test_non_java_component_does_not_inherit_java_runtime_or_policy(tmp_path: Path):
    write(tmp_path / ".nvmrc", "20\n")
    write(tmp_path / "package.json", json.dumps({"scripts": {"start": "node server.js"}}))
    write(tmp_path / "package-lock.json", "{}")
    write(tmp_path / "server.js", "server.listen(3000);\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["application"])

    assert context.components[0]["technology_profile"]["languages"] == ["JavaScript"]
    assert all(item["runtime"] != "Java" for item in context.components[0]["runtimes"])
    assert all(item["policy_id"] != "java-spring-boot-container-v1" for item in context.platform_policies)
    repository.storage.close()


def test_components_keep_separate_technology_profiles(tmp_path: Path):
    spring_boot_project(tmp_path)
    write(tmp_path / ".nvmrc", "20\n")
    write(tmp_path / "frontend/package.json", json.dumps({"scripts": {"start": "node server.js"}}))
    write(tmp_path / "frontend/package-lock.json", "{}")
    write(tmp_path / "frontend/server.js", "server.listen(3001);\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["application", "frontend"])
    profiles = {item["name"]: item["technology_profile"] for item in context.components}

    assert profiles["application"]["languages"] == ["Java"]
    assert profiles["frontend"]["languages"] == ["JavaScript"]
    assert profiles["application"]["build_system"] == "maven"
    assert profiles["frontend"]["build_system"] == "npm"
    assert all(item["runtime"] != "Java" for item in context.components[1]["runtimes"])
    repository.storage.close()


def test_unknown_technology_has_no_policy_and_remains_unresolved():
    intelligence = ProjectIntelligence(
        name="unknown", root_path="/tmp/unknown",
        components=[{"name": "service", "path": ".", "kind": "service", "role": "service/application"}],
    )
    from sohail_agent_cli.dockerize import DockerContextBuilder
    context = DockerContextBuilder.__new__(DockerContextBuilder).from_intelligence(intelligence, ["service"])

    assert context.components[0]["technology_profile"] == {
        "application_type": "service",
        "component_role": "service/application",
    }
    assert context.platform_policies == []
    with pytest.raises(DockerDecisionError, match="No validated Docker rendering strategy"):
        DockerDecisionEngine.render_dockerfile({"name": "service", "package_manager": "pip"})


def test_explicit_inspection_run_is_reused_without_mixing_newer_snapshot(tmp_path: Path):
    write(tmp_path / "package.json", json.dumps({"scripts": {"start": "node server.js"}}))
    write(tmp_path / "package-lock.json", "{}")
    write(tmp_path / "server.js", "server.listen(3000);\n")
    repository = repository_for(tmp_path)
    first = repository.load_latest(str(tmp_path))
    assert first is not None
    first_run = first.inspection_run_id

    for path in (tmp_path / "package.json", tmp_path / "package-lock.json", tmp_path / "server.js"):
        path.unlink()
    spring_boot_project(tmp_path)
    repository.persist(DeepInspector().inspect(tmp_path))
    latest = repository.load_latest(str(tmp_path))
    assert latest is not None and latest.inspection_run_id != first_run

    old_context = DockerContextBuilder(repository).build(tmp_path, ["application"], first_run)
    new_context = DockerContextBuilder(repository).build(tmp_path, ["application"], latest.inspection_run_id)

    assert old_context.project["inspection_run_id"] == first_run
    assert old_context.components[0]["technology_profile"]["build_system"] == "npm"
    assert new_context.project["inspection_run_id"] == latest.inspection_run_id
    assert new_context.components[0]["technology_profile"]["build_system"] == "maven"
    repository.storage.close()


def test_model_cannot_redefine_detected_technology(tmp_path: Path):
    write(tmp_path / ".nvmrc", "20\n")
    write(tmp_path / "backend/package.json", json.dumps({"scripts": {"start": "node server.js"}}))
    write(tmp_path / "backend/package-lock.json", "{}")
    write(tmp_path / "backend/server.js", "server.listen(3000);\n")
    write(tmp_path / "backend/Dockerfile", "FROM node:20-alpine\nWORKDIR /app\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    payload = {
        "status": "ready", "reason": "proposal", "components": [{
            "name": "backend", "language": "Python", "base_image": "node:20-alpine",
            "working_directory": "/app", "package_manager": "npm", "install_command": "npm ci",
            "build_command": "", "start_command": "node server.js", "port": 3000,
        }], "compose": {"services": [{
            "name": "backend", "component": "backend", "build_context": "./backend",
            "port": 3000, "target_port": 3000,
        }]},
    }
    provider = MockProvider(responses={"project": json.dumps(payload)})
    decision = __import__("asyncio").run(
        DockerDecisionEngine(provider, "devops-qwen:latest").decide(context)
    )

    assert decision.status == "NEEDS_EVIDENCE"
    assert "language" in decision.raw["reason"]
    repository.storage.close()
