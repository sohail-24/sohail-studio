"""Focused Step 4B tests for deterministic Compose intelligence."""

from dataclasses import replace

import pytest

from sohail_agent_cli.dockerize import (
    DETECTION_ONLY,
    ELIGIBLE,
    NEEDS_EVIDENCE,
    ComposeContextBuilder,
    ComposeContextError,
    DockerContext,
    evaluate_infrastructure_candidate,
)
from sohail_agent_cli.inspection import DeepInspector
from sohail_agent_cli.inspection.models import ProjectIntelligence


def multi_component_context() -> DockerContext:
    return DockerContext(
        project={
            "name": "full-stack",
            "root_path": "/tmp/full-stack",
            "inspection_run_id": "persisted-run",
            "selected_components": ["backend", "frontend"],
        },
        components=[
            {
                "name": "backend",
                "path": "backend",
                "role": "backend",
                "language": "JavaScript",
                "framework": "Express",
                "strategy_id": "node-backend",
                "technology_profile": {"languages": ["JavaScript"]},
                "runtimes": [{"runtime": "Node.js", "version": "20"}],
                "dockerfiles": [],
                "ports": [{"port": 5000, "port_type": "application", "conflict": False}],
                "environment": [{
                    "key": "DATABASE_URL",
                    "source_file": "backend/.env.example",
                    "sensitive": False,
                }],
            },
            {
                "name": "frontend",
                "path": "frontend",
                "role": "frontend",
                "language": "JavaScript",
                "framework": "Vite",
                "strategy_id": "react-vite-static",
                "technology_profile": {"languages": ["JavaScript"]},
                "runtimes": [{"runtime": "Node.js", "version": "20"}],
                "dockerfiles": [],
                "ports": [{"port": 80, "port_type": "application", "conflict": False}],
            },
        ],
        infrastructure={
            "databases": ["MongoDB"],
            "services": [],
            "relationships": [],
        },
        evidence=[
            {
                "source_file": "backend/package.json",
                "evidence_type": "database",
                "value": "MongoDB",
                "source_type": "EXPLICIT_EVIDENCE",
            }
        ],
        artifact_plan={
            "dockerfiles": {"backend": "generate", "frontend": "generate"},
            "compose": "generate",
        },
    )


def test_compose_context_preserves_scoped_components_and_never_reads_repository():
    context = multi_component_context()

    compose = ComposeContextBuilder.build(context)

    assert compose.inspection_run_id == "persisted-run"
    assert [(item["name"], item["component_root"], item["build_context"])
            for item in compose.components] == [
        ("backend", "backend", "./backend"),
        ("frontend", "frontend", "./frontend"),
    ]
    assert [item["dockerfile_path"] for item in compose.components] == [
        "backend/Dockerfile", "frontend/Dockerfile",
    ]
    assert compose.authority["repository_rescan"] is False
    assert compose.components[0]["environment_contract"] == [{
        "name": "DATABASE_URL",
        "source_file": "backend/.env.example",
        "sensitive": False,
        "value_authorized": False,
    }]
    assert compose.to_dict()["artifact_scope"]["selected_components"] == ["backend", "frontend"]


def test_supporting_nginx_and_database_detection_do_not_become_compose_services():
    compose = ComposeContextBuilder.build(multi_component_context())

    assert {item["name"] for item in compose.components} == {"backend", "frontend"}
    assert compose.relationships == ()
    assert compose.data_services[0]["service_type"] == "MongoDB"
    assert compose.data_services[0]["eligibility"] == DETECTION_ONLY
    assert compose.data_services[0]["missing_requirements"] == ["service_name", "image"]
    assert compose.data_services[0]["renderable"] is False
    assert compose.service_evidence == ()
    assert compose.authorized_infrastructure_services == ()
    assert compose.artifact_scope["generated_services"] == ["backend", "frontend"]


def test_unvalidated_relationship_is_not_promoted_to_compose_dependency():
    context = multi_component_context()
    context = replace(context, compose_context=ComposeContextBuilder.build(context).to_dict())

    with pytest.raises(ComposeContextError, match="unsupported Compose relationship"):
        ComposeContextBuilder.validate_proposal(
            context,
            {"services": [{
                "name": "frontend",
                "component": "frontend",
                "build_context": "./frontend",
                "depends_on": ["backend"],
            }]},
        )


def test_model_proposed_paths_and_unselected_services_are_rejected():
    context = multi_component_context()
    context = replace(context, compose_context=ComposeContextBuilder.build(context).to_dict())

    with pytest.raises(ComposeContextError, match="placement field"):
        ComposeContextBuilder.validate_proposal(
            context,
            {"services": [{
                "name": "backend",
                "component": "backend",
                "build_context": "./backend",
                "dockerfile_path": "/tmp/other/Dockerfile",
            }]},
        )

    with pytest.raises(ComposeContextError, match="invented a Compose service"):
        ComposeContextBuilder.validate_proposal(
            context,
            {"services": [{
                "name": "nginx",
                "component": "nginx",
                "build_context": "./frontend",
            }]},
        )


@pytest.mark.parametrize("field", ["image", "volumes", "networks", "healthcheck"])
def test_model_proposed_infrastructure_fields_are_rejected(field):
    context = multi_component_context()
    context = replace(context, compose_context=ComposeContextBuilder.build(context).to_dict())

    with pytest.raises(ComposeContextError, match="infrastructure field"):
        ComposeContextBuilder.validate_proposal(
            context,
            {"services": [{
                "name": "backend",
                "component": "backend",
                "build_context": "./backend",
                field: "model-proposed",
            }]},
        )


def test_docker_context_serializes_compose_foundation_without_dockerignore():
    context = multi_component_context()
    context = replace(context, compose_context=ComposeContextBuilder.build(context).to_dict())

    serialized = context.to_dict()

    assert "compose_context" in serialized
    assert ".dockerignore" not in serialized["artifact_plan"]
    assert serialized["compose_context"]["authority"]["inspection_run_id"] == "persisted-run"


def test_explicit_compose_relationship_survives_intelligence_snapshot_round_trip(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend/package.json").write_text(
        '{"scripts":{"start":"node server.js"}}', encoding="utf-8"
    )
    (tmp_path / "backend/package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  backend:\n    build: ./backend\n    depends_on:\n"
        "      - database\n  database:\n    image: postgres:16\n",
        encoding="utf-8",
    )

    inspected = DeepInspector().inspect(tmp_path)
    restored = ProjectIntelligence.from_summary(
        inspected.summary(), root_path=str(tmp_path), inspection_run_id="persisted-run"
    )

    assert restored.relationships == inspected.relationships
    assert restored.relationships[0]["source"] == "backend"
    assert restored.relationships[0]["target"] == "database"
    assert restored.relationships[0]["source_type"] == "EXPLICIT_EVIDENCE"


def test_exact_persisted_infrastructure_metadata_can_be_eligible_without_being_auto_rendered():
    candidate = evaluate_infrastructure_candidate({
        "service_name": "postgres",
        "service_type": "PostgreSQL",
        "image": "postgres:16.4",
        "source_type": "EXPLICIT_EVIDENCE",
        "image_source_type": "EXPLICIT_EVIDENCE",
        "model_inference": False,
    })

    assert candidate["eligibility"] == ELIGIBLE
    assert candidate["authorized_fields"] == ["service_name", "technology", "image"]


@pytest.mark.parametrize("image", ["postgres:latest", "mongo:latest"])
def test_latest_infrastructure_image_remains_unavailable(image):
    candidate = evaluate_infrastructure_candidate({
        "service_name": "database",
        "service_type": "PostgreSQL" if image.startswith("postgres") else "MongoDB",
        "image": image,
        "source_type": "MODEL_PROPOSED",
        "image_source_type": "MODEL_PROPOSED",
        "model_inference": True,
    })

    assert candidate["eligibility"] == NEEDS_EVIDENCE
    assert ":latest" in candidate["unsupported_reason"]


def test_infrastructure_credentials_are_never_authorized():
    candidate = evaluate_infrastructure_candidate({
        "service_name": "mysql",
        "service_type": "MySQL",
        "image": "mysql:8.4",
        "password": "do-not-render",
        "source_type": "EXPLICIT_EVIDENCE",
    })

    assert candidate["eligibility"] == "UNSUPPORTED"
    assert "password" in candidate["rejected_fields"]


def test_model_proposed_image_is_not_authorized_even_if_other_metadata_looks_explicit():
    candidate = evaluate_infrastructure_candidate({
        "service_name": "mongo",
        "service_type": "MongoDB",
        "image": "mongo:7.0",
        "source_type": "EXPLICIT_EVIDENCE",
        "image_source_type": "MODEL_PROPOSED",
        "model_inference": False,
    })

    assert candidate["eligibility"] == NEEDS_EVIDENCE
    assert candidate["authorized_fields"] == []
