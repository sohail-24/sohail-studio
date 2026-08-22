"""Validation of generated Docker artifacts against Project Intelligence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .context_builder import DockerContext
from .decision import DockerDecision


class DockerValidationError(ValueError):
    """Raised when generated Docker artifacts contradict the inspected project."""


def validate_docker_result(
    root: Path,
    context: DockerContext,
    decision: DockerDecision,
    artifacts: dict[Path, str],
    *,
    compose_expected: bool = False,
) -> dict[str, Any]:
    """Validate in-memory dry-run artifacts or files already written to disk."""
    selected = {str(item["name"]): item for item in context.components}
    checked: list[str] = []
    for component in decision.components:
        name = str(component["name"])
        intelligence = selected[name]
        relative = str(intelligence.get("path") or ".")
        path = root / relative / "Dockerfile"
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
                else:
                    present = str(value) in content
                if not present:
                    raise DockerValidationError(f"Dockerfile {key} is missing for {name}")
        port = component.get("port")
        if port is not None and f"EXPOSE {int(port)}" not in content:
            raise DockerValidationError(f"Dockerfile port does not match Project Intelligence for {name}")
        checked.append(str(path))

    compose_path = root / "docker-compose.yml"
    compose_content = artifacts.get(compose_path)
    if compose_content is not None:
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
        for service in decision.compose.get("services") or []:
            name = str(service["name"])
            config = services.get(name) or {}
            build_context = str(service.get("build_context") or "")
            if build_context and not (root / build_context).is_dir():
                raise DockerValidationError(f"Docker Compose build context does not exist: {build_context}")
            target = service.get("target_port", service.get("port"))
            if target is not None:
                port_strings = [str(item) for item in config.get("ports", [])]
                if not any(str(target) in item for item in port_strings):
                    raise DockerValidationError(f"Docker Compose port is inconsistent for service {name}")
        checked.append(str(compose_path))
    elif compose_expected:
        raise DockerValidationError("Docker Compose was expected but was not generated")
    return {"validated": checked, "status": "passed"}
