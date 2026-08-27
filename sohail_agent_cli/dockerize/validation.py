"""Validation of generated Docker artifacts against Project Intelligence."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

import yaml

from .compose_context import ComposeContextBuilder, ComposeContextError
from .context_builder import DockerContext
from .decision import DockerDecision
from .platform_policy import policy_for_component, policy_value
from .strategies import STATIC_ARTIFACT_SERVER


class DockerValidationError(ValueError):
    """Raised when generated Docker artifacts contradict the inspected project."""


def validate_docker_result(
    root: Path,
    context: DockerContext,
    decision: DockerDecision,
    artifacts: dict[Path, str],
    *,
    compose_expected: bool = False,
    compose_path: Path | None = None,
) -> dict[str, Any]:
    """Validate in-memory dry-run artifacts or files already written to disk."""
    selected = {str(item["name"]): item for item in context.components}
    checked: list[str] = []
    for component in decision.components:
        name = str(component["name"])
        intelligence = selected[name]
        relative = str(intelligence.get("path") or ".")
        dockerfiles = [str(item) for item in intelligence.get("dockerfiles", []) if str(item).strip()]
        path = root / dockerfiles[0] if dockerfiles else root / relative / "Dockerfile"
        content = artifacts.get(path)
        if content is None and path.exists():
            content = path.read_text(encoding="utf-8")
        if content is None:
            raise DockerValidationError(f"Dockerfile missing for component {name}: {path}")
        if f"FROM {component.get('base_image')}" not in content:
            raise DockerValidationError(f"Dockerfile runtime does not match the decision for {name}")
        install = component.get("install_command")
        if install and str(install) not in content:
            raise DockerValidationError(f"Dockerfile install command is missing for {name}")
        for key in ("build_command", "start_command"):
            value = component.get(key)
            if value:
                if isinstance(value, list):
                    present = all(str(part) in content for part in value)
                elif key == "start_command":
                    # The renderer serializes string commands as a JSON argv
                    # array in CMD, so validate the rendered representation
                    # rather than looking for the original shell string.
                    tokens = shlex.split(str(value))
                    present = bool(tokens) and all(
                        json.dumps(token) in content for token in tokens
                    )
                else:
                    present = str(value) in content
                if not present:
                    raise DockerValidationError(f"Dockerfile {key} is missing for {name}")
        if intelligence.get("execution_strategy") == STATIC_ARTIFACT_SERVER and not component.get("start_command"):
            serving = policy_value(
                policy_for_component(context.platform_policies, name),
                "static_serving_command",
            )
            value = serving.get("value") if serving else None
            tokens = value if isinstance(value, list) else shlex.split(str(value or ""))
            if not tokens or not all(json.dumps(str(token)) in content for token in tokens):
                raise DockerValidationError(
                    f"Dockerfile static serving command is missing for {name}"
                )
        port = component.get("port")
        if port is not None and f"EXPOSE {int(port)}" not in content:
            raise DockerValidationError(f"Dockerfile port does not match Project Intelligence for {name}")
        checked.append(str(path))

    compose_path = compose_path or root / "docker-compose.yml"
    compose_content = artifacts.get(compose_path)
    if compose_content is not None:
        try:
            ComposeContextBuilder.validate_proposal(context, decision.compose)
        except ComposeContextError as exc:
            raise DockerValidationError(str(exc)) from exc
        try:
            parsed = yaml.safe_load(compose_content) or {}
        except yaml.YAMLError as exc:
            raise DockerValidationError(f"Generated Docker Compose is invalid YAML: {exc}") from exc
        services = parsed.get("services") if isinstance(parsed, dict) else None
        if not isinstance(services, dict):
            raise DockerValidationError("Generated Docker Compose has no services mapping")
        expected_names = {str(item.get("name")) for item in decision.compose.get("services") or []}
        if set(services) != expected_names:
            raise DockerValidationError("Docker Compose services do not match the selected components")
        decision_components = {
            str(item.get("name")): item for item in decision.components
        }
        for service in decision.compose.get("services") or []:
            name = str(service["name"])
            config = services.get(name) or {}
            build_context = str(service.get("build_context") or "")
            if build_context and not (root / build_context).is_dir():
                raise DockerValidationError(f"Docker Compose build context does not exist: {build_context}")
            rendered_build = config.get("build")
            rendered_context = (
                rendered_build.get("context")
                if isinstance(rendered_build, dict)
                else rendered_build
            )
            if build_context and str(rendered_context or "") != build_context:
                raise DockerValidationError(
                    f"Docker Compose build context is inconsistent for service {name}"
                )
            compose_components = {
                str(item.get("name")): item
                for item in (context.compose_context or {}).get("components", [])
            }
            authoritative = compose_components.get(name)
            if authoritative is not None:
                rendered_dockerfile = (
                    rendered_build.get("dockerfile", "Dockerfile")
                    if isinstance(rendered_build, dict)
                    else "Dockerfile"
                )
                actual_dockerfile = str(
                    Path(build_context.lstrip("./")) / str(rendered_dockerfile)
                )
                if actual_dockerfile != str(authoritative.get("dockerfile_path")):
                    raise DockerValidationError(
                        f"Docker Compose Dockerfile path is inconsistent for service {name}"
                    )
            expected_working_directory = str(
                (decision_components.get(name) or {}).get("working_directory") or ""
            )
            if expected_working_directory and config.get("working_dir") != expected_working_directory:
                raise DockerValidationError(
                    f"Docker Compose working directory is inconsistent for service {name}"
                )
            target = service.get("target_port", service.get("port"))
            authoritative_ports = [
                item for item in (authoritative or {}).get("ports", [])
                if item.get("port_type") == "application"
                and not item.get("conflict")
                and item.get("port") is not None
            ]
            rendered_ports = [str(item) for item in config.get("ports", []) or []]
            rendered_pairs: set[tuple[int, int]] = set()
            for rendered in rendered_ports:
                parts = rendered.split(":")
                if len(parts) != 2:
                    raise DockerValidationError(
                        f"Docker Compose port mapping is invalid for service {name}"
                    )
                try:
                    rendered_pairs.add((int(parts[0]), int(parts[1])))
                except ValueError as exc:
                    raise DockerValidationError(
                        f"Docker Compose port mapping is invalid for service {name}"
                    ) from exc
            expected_pairs = {
                (int(item["port"]), int(item["port"])) for item in authoritative_ports
            }
            if authoritative_ports and rendered_pairs - expected_pairs:
                raise DockerValidationError(
                    f"Docker Compose port mapping conflicts with authoritative component port for service {name}"
                )
            if not authoritative_ports and rendered_pairs:
                raise DockerValidationError(
                    f"Docker Compose invented a port mapping for service {name}; no component port evidence exists"
                )
            if target is not None and not any(
                pair[1] == int(target) for pair in rendered_pairs
            ):
                raise DockerValidationError(f"Docker Compose port is inconsistent for service {name}")
        checked.append(str(compose_path))
    elif compose_expected:
        raise DockerValidationError("Docker Compose was expected but was not generated")
    return {"validated": checked, "status": "passed"}
