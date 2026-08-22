"""Build a small, secret-safe Docker context from the persisted snapshot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.storage.project_intelligence import ProjectIntelligenceRepository
from sohail_agent_cli.inspection.models import ProjectIntelligence


class DockerContextError(ValueError):
    """Raised when a Docker context cannot be built from project evidence."""


@dataclass(frozen=True)
class DockerContext:
    """Focused evidence supplied to the DevOps model."""

    project: dict[str, Any]
    components: list[dict[str, Any]]
    infrastructure: dict[str, Any]
    evidence: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "components": self.components,
            "infrastructure": self.infrastructure,
            "evidence": self.evidence,
        }

    def prompt(self) -> str:
        return (
            "You are making an engineering decision from supplied repository evidence.\n"
            "The FOCUSED_DOCKER_PROJECT_INTELLIGENCE object below is present and authoritative.\n"
            "Do not invent project facts or assume missing files, frameworks, ports, commands, or services.\n"
            "When evidence conflicts, identify the conflict and return NEEDS_EVIDENCE when it blocks a safe decision.\n"
            "Use the supplied project evidence as the source of truth.\n"
            "Return JSON only with status, a non-empty reason, a components array, and a compose object.\n"
            "A ready response must include each component name and compose.services as an array.\n\n"
            "FOCUSED_DOCKER_PROJECT_INTELLIGENCE:\n"
            + json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        )


class DockerContextBuilder:
    """Retrieve one successful Neon snapshot and select Docker-relevant facts."""

    def __init__(self, repository: ProjectIntelligenceRepository) -> None:
        self.repository = repository

    def build(self, project_path: Path, selected_components: list[str] | None = None) -> DockerContext:
        root = project_path.expanduser().resolve()
        intelligence = self.repository.load_latest(str(root))
        if intelligence is None:
            raise DockerContextError(
                "No successful Project Intelligence snapshot exists for this project; run Inspect first"
            )
        return self.from_intelligence(intelligence, selected_components)

    def from_intelligence(
        self,
        intelligence: ProjectIntelligence,
        selected_components: list[str] | None = None,
    ) -> DockerContext:
        available = {str(item.get("name")): item for item in intelligence.components}
        names = selected_components or list(available)
        missing = [name for name in names if name not in available]
        if missing:
            raise DockerContextError(f"Requested components were not discovered: {', '.join(missing)}")
        if not names:
            raise DockerContextError("No independently runnable components were discovered")

        selected = [available[name] for name in names]

        def fields(item: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
            return {name: item[name] for name in names if name in item}

        def belongs(source: str | None, component: dict[str, Any]) -> bool:
            if not source:
                return False
            component_path = str(component.get("path") or ".").strip("./")
            if not component_path:
                return True
            return source == component_path or source.startswith(component_path + "/")

        def selected_fact(item: dict[str, Any]) -> bool:
            component = item.get("component")
            return component in names or any(belongs(str(item.get("source_file", "")), part) for part in selected)

        components: list[dict[str, Any]] = []
        for component in selected:
            name = str(component["name"])
            path = str(component.get("path") or ".")
            all_files = [
                file.to_dict() if hasattr(file, "to_dict") else dict(file)
                for file in intelligence.files
                if belongs(file.relative_path if hasattr(file, "relative_path") else file.get("relative_path"), component)
            ]
            important_classifications = {
                "dependency_manifest", "lockfile", "docker", "docker_compose",
                "configuration", "environment_example", "ci_cd",
            }
            files = [
                fields(file, ("relative_path", "classification", "language", "size", "error"))
                for file in all_files
                if file.get("classification") in important_classifications
                or Path(str(file.get("relative_path", ""))).name.lower() in {
                    "server.js", "server.ts", "main.py", "manage.py", "app.py", "index.js", "index.ts",
                }
            ][:80]
            commands = [
                fields(item, ("name", "command", "source_file", "confidence"))
                for item in intelligence.commands
                if item.get("component") == name
                or belongs(str(item.get("source_file", "")), component)
                or (
                    "/" not in str(item.get("source_file", ""))
                    and name in str(item.get("command", ""))
                )
            ]
            dependencies = [
                fields(item, ("name", "version", "scope", "source_file", "confidence"))
                for item in intelligence.dependencies
                if belongs(str(item.get("source_file", "")), component)
            ]
            runtimes = [
                fields(item, ("runtime", "version", "source_file", "confidence"))
                for item in intelligence.runtimes
                if belongs(str(item.get("source_file", "")), component)
                or "/" not in str(item.get("source_file", ""))
            ]
            ports = [
                fields(item, ("name", "port", "source_file", "confidence", "component", "port_type", "target_port", "service_name", "conflict"))
                for item in intelligence.ports
                if item.get("component") == name
            ]
            environment = [
                fields(item, ("name", "key", "value", "sensitive", "source_file", "confidence"))
                for item in intelligence.environment_variables
                if belongs(str(item.get("source_file", "")), component)
                or "/" not in str(item.get("source_file", ""))
            ]
            framework = component.get("framework")
            language = next(
                (file.language for file in intelligence.files if file.relative_path.startswith(path + "/") and file.language),
                None,
            )
            components.append({
                "name": name,
                "path": path,
                "kind": component.get("kind"),
                "role": component.get("role"),
                "framework": framework,
                "language": language,
                "package_manager": component.get("package_manager"),
                "runtimes": runtimes,
                "commands": commands,
                "dependencies": dependencies,
                "ports": ports,
                "environment": environment,
                "files": files,
                "file_count": len(all_files),
            })

        evidence: list[dict[str, Any]] = []
        for item in intelligence.evidence:
            data = item.to_dict() if hasattr(item, "to_dict") else dict(item)
            if data.get("source_file") and selected_fact(data):
                evidence.append(fields(
                    data,
                    ("source_file", "evidence_type", "key", "value", "confidence", "line_number"),
                ))

        dockerfiles = list(intelligence.docker.get("dockerfiles", []))
        selected_dockerfiles = [
            item for item in dockerfiles
            if any(belongs(item, component) for component in selected)
        ]
        kubernetes = intelligence.kubernetes or {}
        infrastructure = {
            "dockerfiles": selected_dockerfiles,
            "docker_detected": bool(selected_dockerfiles),
            "compose_files": list(intelligence.docker.get("compose_files", [])),
            "compose_detected": intelligence.has_docker_compose,
            "kubernetes": {
                "detected": bool(kubernetes.get("files")),
                "files": list(kubernetes.get("files", [])),
                "resources": [
                    fields(resource, ("kind", "name"))
                    for resource in kubernetes.get("resources", [])
                ],
            },
            "ci_cd": {
                "platforms": list(intelligence.ci_cd.get("platforms", [])),
                "files": list(intelligence.ci_cd.get("files", [])),
            },
            "databases": intelligence.databases,
            "services": [
                fields(item, ("name", "component", "type", "port", "target_port"))
                for item in intelligence.services
            ],
            "documentation": {
                "detected": bool(intelligence.documentation.get("files")),
                "files": list(intelligence.documentation.get("files", [])),
            },
        }
        project = {
            "name": intelligence.name,
            "root_path": intelligence.root_path,
            "selected_components": names,
            "available_components": list(available),
        }
        return DockerContext(project, components, infrastructure, evidence)
