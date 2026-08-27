"""Focused Step 2 coverage for technology-specific Docker strategies."""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from core.storage.database import Storage, StorageConfig
from core.storage.project_intelligence import ProjectIntelligenceRepository, metadata
from sohail_agent_cli.dockerize import DockerContextBuilder, DockerDecisionEngine
from sohail_agent_cli.inspection import DeepInspector
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


def decision_response(component: dict, compose: bool = True) -> str:
    service = {
        "name": component["name"], "component": component["name"],
        "build_context": ".", "port": component.get("port"),
        "target_port": component.get("port"),
    }
    payload = {
        "status": "ready", "reason": "authorized strategy",
        "components": [component],
        "compose": {"services": [service] if compose else []},
    }
    return json.dumps(payload)


@pytest.mark.parametrize(
    ("name", "manifest", "source", "runtime_file", "framework", "port"),
    [
        ("FastAPI", "requirements.txt", "from fastapi import FastAPI\napp = FastAPI()\n", ".python-version", "FastAPI", 8000),
        ("Flask", "requirements.txt", "from flask import Flask\napp = Flask(__name__)\napp.run(port=8001)\n", ".python-version", "Flask", 8001),
    ],
)
def test_python_strategy_requires_real_launch_evidence(
    tmp_path: Path, name: str, manifest: str, source: str,
    runtime_file: str, framework: str, port: int,
):
    write(tmp_path / manifest, f"{framework.lower()}\n")
    write(tmp_path / runtime_file, "3.12\n")
    write(tmp_path / "main.py", source)
    write(tmp_path / "README.md", f"$ uvicorn main:app --host 0.0.0.0 --port {port}\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])

    assert context.components[0]["strategy_id"] == "python-application"
    assert context.platform_policies[0]["policy_id"] == f"python-{framework.lower()}-container-v1"
    response = decision_response({
        "name": "backend", "base_image": "python:3.12-slim", "working_directory": "/app",
        "package_manager": "pip",
        "install_command": "pip install --no-cache-dir -r requirements.txt",
        "build_command": "", "start_command": f"uvicorn main:app --host 0.0.0.0 --port {port}",
        "port": port,
    })
    decision = asyncio.run(DockerDecisionEngine(
        MockProvider(responses={"project": response}), "devops-qwen:latest",
    ).decide(context))
    assert decision.status == "ready", (name, decision.raw)
    repository.storage.close()


def test_python_without_exact_runtime_or_start_remains_needs_evidence(tmp_path: Path):
    write(tmp_path / "requirements.txt", "fastapi\n")
    write(tmp_path / "main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend"])
    decision = asyncio.run(DockerDecisionEngine(
        MockProvider(responses={}), "devops-qwen:latest",
    ).decide(context))
    assert decision.status == "NEEDS_EVIDENCE"
    assert decision.model_called is False
    assert any("exact production start command" in item for item in decision.raw["missing_requirements"])


def test_node_and_vite_policies_use_explicit_compatibility_policy_without_runtime_marker(tmp_path: Path):
    write(tmp_path / "backend/package.json", json.dumps({
        "scripts": {"start": "node src/index.js"},
        "dependencies": {"express": "^4"},
    }))
    write(tmp_path / "backend/package-lock.json", "{}")
    write(tmp_path / "backend/src/index.js", "server.listen(process.env.PORT);\n")
    write(tmp_path / "frontend/package.json", json.dumps({
        "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
        "dependencies": {"react": "^18", "vite": "^5"},
    }))
    write(tmp_path / "frontend/package-lock.json", "{}")
    write(tmp_path / "frontend/index.html", "<div id='root'></div>\n")
    write(tmp_path / "frontend/src/main.jsx", "console.log('frontend');\n")
    write(tmp_path / "frontend/nginx.conf", "server { listen 80; }\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["backend", "frontend"])

    policies = {item["component"]: item for item in context.platform_policies}
    assert policies["backend"]["policy_id"] == "node-backend-container-v1"
    assert policies["backend"]["values"]["base_image"]["value"] == "node:22-alpine"
    assert policies["frontend"]["policy_id"] == "react-static-container-v1"
    assert policies["frontend"]["values"]["base_image"]["value"] == "node:22-alpine"
    assert context.components[0]["strategy_id"] == "node-backend"
    assert context.components[1]["strategy_id"] == "react-vite-static"
    assert not any(item["name"] == "nginx" for item in context.components)
    repository.storage.close()
    repository.storage.close()


def test_gradle_spring_boot_strategy_derives_exact_jar(tmp_path: Path):
    write(tmp_path / "settings.gradle", "rootProject.name = 'gradle-app'\n")
    write(tmp_path / "build.gradle", """
        plugins {
            id 'java'
            id 'org.springframework.boot' version '3.2.2'
        }
        group = 'com.example'
        version = '1.0.0'
        sourceCompatibility = '17'
    """)
    write(tmp_path / "gradlew", "#!/bin/sh\n")
    write(tmp_path / "src/main/java/App.java", "class App { public static void main(String[] args) {} }")
    repository = repository_for(tmp_path)
    intelligence = repository.load_latest(str(tmp_path))
    assert intelligence is not None
    artifact = intelligence.components[0]["artifacts"][0]
    assert artifact["path"] == "build/libs/gradle-app-1.0.0.jar"
    context = DockerContextBuilder(repository).build(tmp_path, ["application"])
    assert context.components[0]["strategy_id"] == "java-gradle-spring-boot"
    assert context.platform_policies[0]["policy_id"] == "java-spring-boot-gradle-container-v1"
    response = decision_response({
        "name": "application", "base_image": "eclipse-temurin:17-jre-jammy",
        "working_directory": "/app", "package_manager": "gradle",
        "install_command": "", "build_command": "./gradlew bootJar",
        "start_command": ["java", "-jar", "build/libs/gradle-app-1.0.0.jar"],
        "port": None,
    })
    decision = asyncio.run(DockerDecisionEngine(
        MockProvider(responses={"project": response}), "devops-qwen:latest",
    ).decide(context))
    assert decision.status == "ready", decision.raw
    repository.storage.close()


def test_go_strategy_requires_explicit_output_and_renders_compiled_strategy(tmp_path: Path):
    write(tmp_path / "go.mod", "module example.com/server\ngo 1.22\n")
    write(tmp_path / "main.go", "package main\nfunc main() { http.ListenAndServe(\":8080\", nil) }\n")
    write(tmp_path / "Makefile", "build:\n\tgo build -o bin/server .\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["application"])
    assert context.components[0]["strategy_id"] == "go-application"
    assert context.components[0]["artifacts"][0]["path"] == "bin/server"
    assert context.platform_policies[0]["policy_id"] == "go-container-v1"
    component = {
        "name": "application", "base_image": "golang:1.22-alpine",
        "working_directory": "/app", "package_manager": "go",
        "install_command": "", "build_command": "go build -o bin/server .",
        "start_command": ["./bin/server"], "port": 8080,
    }
    decision = asyncio.run(DockerDecisionEngine(
        MockProvider(responses={"project": decision_response(component)}), "devops-qwen:latest",
    ).decide(context))
    assert decision.status == "ready", decision.raw
    rendered = DockerDecisionEngine.render_dockerfile({
        **component, "strategy_id": "go-application",
        "artifacts": context.components[0]["artifacts"],
    })
    assert "go build -o bin/server ." in rendered
    assert 'CMD ["./bin/server"]' in rendered
    repository.storage.close()


def test_rust_strategy_requires_exact_toolchain_and_single_binary(tmp_path: Path):
    write(tmp_path / "Cargo.toml", "[package]\nname = 'tiny-server'\nversion = '0.1.0'\n")
    write(tmp_path / "Cargo.lock", "version = 3\n")
    write(tmp_path / "rust-toolchain.toml", "[toolchain]\nchannel = '1.78.0'\n")
    write(tmp_path / "src/main.rs", "fn main() { println!(\"ok\"); }\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["application"])
    assert context.components[0]["strategy_id"] == "rust-application"
    assert context.components[0]["artifacts"][0]["path"] == "target/release/tiny-server"
    assert context.platform_policies[0]["policy_id"] == "rust-container-v1"
    rendered = DockerDecisionEngine.render_dockerfile({
        "name": "application", "strategy_id": "rust-application",
        "base_image": "rust:1.78.0-slim", "working_directory": "/app",
        "build_command": "cargo build --release",
        "start_command": ["./target/release/tiny-server"],
        "artifacts": context.components[0]["artifacts"], "port": None,
    })
    assert "cargo build --release" in rendered
    repository.storage.close()


def test_nginx_strategy_uses_configuration_and_policy_start(tmp_path: Path):
    write(tmp_path / "nginx.conf", "server { listen 8088; location / { root /usr/share/nginx/html; } }\n")
    write(tmp_path / "docker-compose.yml", "services:\n  nginx:\n    image: nginx:alpine\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["nginx"])
    assert context.components[0]["strategy_id"] == "nginx-server"
    assert context.platform_policies[0]["policy_id"] == "nginx-container-v1"
    response = decision_response({
        "name": "nginx", "base_image": "nginx:alpine", "working_directory": "/etc/nginx",
        "package_manager": "", "install_command": "", "build_command": "",
        "start_command": ["nginx", "-g", "daemon off;"], "port": 8088,
    }, compose=False)
    decision = asyncio.run(DockerDecisionEngine(
        MockProvider(responses={"project": response}), "devops-qwen:latest",
    ).decide(context))
    assert decision.status == "ready", decision.raw
    repository.storage.close()


def test_multistage_dockerfile_keeps_runtime_base_distinct_from_build_base(tmp_path: Path):
    write(tmp_path / "Dockerfile", "FROM maven:3.9 AS build\nFROM eclipse-temurin:17-jre\nWORKDIR /app\n")
    intelligence = DeepInspector().inspect(tmp_path)
    bases = intelligence.docker["base_images"]

    assert [(item["image"], item["role"]) for item in bases] == [
        ("maven:3.9", "build"),
        ("eclipse-temurin:17-jre", "runtime"),
    ]


def test_model_cannot_change_selected_strategy(tmp_path: Path):
    write(tmp_path / ".nvmrc", "20\n")
    write(tmp_path / "package.json", json.dumps({"scripts": {"start": "node server.js"}}))
    write(tmp_path / "package-lock.json", "{}")
    write(tmp_path / "server.js", "server.listen(3000);\n")
    write(tmp_path / "Dockerfile", "FROM node:20-alpine\nWORKDIR /app\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["application"])
    response = decision_response({
        "name": "application", "strategy_id": "python-application",
        "base_image": "node:20-alpine", "working_directory": "/app",
        "package_manager": "npm", "install_command": "npm ci", "build_command": "",
        "start_command": "node server.js", "port": 3000,
    })

    decision = asyncio.run(DockerDecisionEngine(
        MockProvider(responses={"project": response}), "devops-qwen:latest",
    ).decide(context))

    assert decision.status == "NEEDS_EVIDENCE"
    assert "technology strategy" in decision.raw["reason"]
    repository.storage.close()


def test_unknown_technology_has_no_strategy_or_fallback_renderer(tmp_path: Path):
    write(tmp_path / "pom.xml", "<project><artifactId>mystery</artifactId><version>1</version></project>")
    write(tmp_path / "src/main/kotlin/Main.kt", "fun main() {}\n")
    repository = repository_for(tmp_path)
    context = DockerContextBuilder(repository).build(tmp_path, ["application"])
    assert context.components[0].get("strategy_id") is None
    decision = asyncio.run(DockerDecisionEngine(
        MockProvider(responses={}), "devops-qwen:latest",
    ).decide(context))
    assert decision.status == "NEEDS_EVIDENCE"
    assert "validated Docker strategy" in decision.raw["reason"]
    repository.storage.close()
