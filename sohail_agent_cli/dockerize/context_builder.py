"""Build a small, secret-safe Docker context from the persisted snapshot."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.evidence.patterns import recognize_verified_patterns
from core.storage.project_intelligence import ProjectIntelligenceRepository
from sohail_agent_cli.inspection.models import ProjectIntelligence

from .platform_policy import applicable_platform_policies
from .strategies import strategy_for_component


class DockerContextError(ValueError):
    """Raised when a Docker context cannot be built from project evidence."""


def _technology_profile(
    component: dict[str, Any],
    runtimes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize technology identity without inventing missing classifications."""
    profile: dict[str, Any] = {}
    languages = [str(item) for item in component.get("languages") or [] if str(item).strip()]
    if not languages and component.get("language"):
        languages = [str(component["language"])]
    if languages:
        profile["languages"] = languages
    if runtimes:
        profile["runtimes"] = [dict(item) for item in runtimes]
    if component.get("framework"):
        profile["frameworks"] = [component["framework"]]
    if component.get("package_manager"):
        profile["build_system"] = component["package_manager"]
    if component.get("kind"):
        profile["application_type"] = component["kind"]
    if component.get("role"):
        profile["component_role"] = component["role"]
    return profile


@dataclass(frozen=True)
class DockerContext:
    """Focused evidence supplied to the DevOps model."""

    project: dict[str, Any]
    components: list[dict[str, Any]]
    infrastructure: dict[str, Any]
    evidence: list[dict[str, Any]]
    user_evidence: list[dict[str, Any]] = field(default_factory=list)
    verified_patterns: list[dict[str, Any]] = field(default_factory=list)
    artifact_plan: dict[str, Any] = field(default_factory=dict)
    platform_policies: list[dict[str, Any]] = field(default_factory=list)
    compose_context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "components": self.components,
            "infrastructure": self.infrastructure,
            "evidence": self.evidence,
            "user_evidence": self.user_evidence or [],
            "verified_patterns": self.verified_patterns,
            "artifact_plan": self.artifact_plan or {},
            "platform_policies": self.platform_policies or [],
            "compose_context": self.compose_context or {},
        }

    def prompt(self) -> str:
        return (
            "You are making an engineering decision from supplied repository evidence.\n"
            "The FOCUSED_DOCKER_PROJECT_INTELLIGENCE object below is present and authoritative.\n"
            "Do not invent project facts or assume missing files, frameworks, ports, commands, or services.\n"
            "When evidence conflicts, identify the conflict and return NEEDS_EVIDENCE when it blocks a safe decision.\n"
            "Use the supplied project evidence as the source of truth.\n"
            "Command roles are authoritative: only a component's literal 'start' script\n"
            "or an explicit production start command, or a\n"
            "DERIVED_DETERMINISTIC production start strategy with provenance is acceptable.\n"
            "Treat 'dev' and 'preview' scripts as non-production roles; never place them in start_command.\n"
            "If neither explicit nor deterministically derived production start evidence is\n"
            "supplied for a PROCESS_RUNTIME component, return NEEDS_EVIDENCE. A\n"
            "STATIC_ARTIFACT_SERVER component does not need an application start\n"
            "script; its approved static serving policy is authoritative instead.\n"
            "A verified engineering pattern is a deterministic policy boundary, not a model fact.\n"
            "When a component has a verified pattern, include its pattern_id as deployment_pattern\n"
            "verbatim as a required field on that component, and propose implementation\n"
            "details that satisfy that pattern's policy. Omitting the pattern_id is invalid.\n"
            "The artifact_plan is authoritative: generate or upgrade only selected artifacts,\n"
            "preserve keep actions, and exclude skipped components.\n"
            "Return exactly one component decision for every name in project.selected_components,\n"
            "with no omitted or additional component names.\n"
            "For every component with a non-conflicting port whose port_type is application,\n"
            "copy that exact port into component.port and into its Compose service's port\n"
            "and target_port. If no application port evidence is supplied, omit those\n"
            "fields. Never invent a port. Use the evidence-backed component path as a relative Compose\n"
            "build_context. Do not omit or substitute documented/service-only ports.\n"
            "Return JSON only with status, a non-empty reason, a components array, and a compose object.\n"
            "A ready response must include each component name and compose.services as an array.\n\n"
            "Base images and working directories must copy the exact authorized value from\n"
            "explicit repository evidence or APPROVED_PLATFORM_POLICY in the supplied context.\n"
            "APPROVED_PLATFORM_POLICY values are application policy, not repository truth;\n"
            "preserve that provenance and do not describe them as discovered project files.\n"
            "Never replace an authorized value with a model convention or a different image/path.\n"
            "A detected database dependency does not authorize a Compose database service;\n"
            "emit services only for the selected components and supplied service evidence.\n\n"
            "FOCUSED_DOCKER_PROJECT_INTELLIGENCE:\n"
            + json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        )


class DockerContextBuilder:
    """Retrieve one successful Neon snapshot and select Docker-relevant facts."""

    def __init__(self, repository: ProjectIntelligenceRepository) -> None:
        self.repository = repository

    def build(
        self,
        project_path: Path,
        selected_components: list[str] | None = None,
        expected_inspection_run_id: str | None = None,
    ) -> DockerContext:
        root = project_path.expanduser().resolve()
        intelligence = (
            self.repository.load_run(str(root), expected_inspection_run_id)
            if expected_inspection_run_id
            else self.repository.load_latest(str(root))
        )
        if intelligence is None:
            if expected_inspection_run_id:
                raise DockerContextError(
                    "The stored Project Intelligence snapshot does not match the requested inspection run; re-inspect explicitly"
                )
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
        verified_patterns = recognize_verified_patterns(intelligence, names)

        def fields(item: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
            return {name: item[name] for name in names if name in item}

        def belongs(source: str | None, component: dict[str, Any]) -> bool:
            if not source:
                return False
            component_path = str(component.get("path") or ".").strip("./")
            if not component_path:
                # A root component owns repository-level files and source
                # paths that are not owned by another selected component.
                # This keeps a root Java app from absorbing a nested Node or
                # Python component's evidence.
                other_paths = [
                    str(item.get("path") or ".").strip("./")
                    for item in selected
                    if str(item.get("path") or ".").strip("./")
                ]
                return not any(
                    source == path or source.startswith(path + "/")
                    for path in other_paths
                )
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
                fields(item, ("name", "command", "source_file", "confidence", "origin", "source_type", "derived_from", "rule_id", "model_inference"))
                for item in intelligence.commands
                if item.get("component") == name
                or belongs(str(item.get("source_file", "")), component)
            ]
            user_evidence = [
                dict(item) for item in intelligence.user_evidence
                if item.get("component") in {None, name}
            ]
            for item in user_evidence:
                if item.get("key") == "production_start_command":
                    commands.append({
                        "name": "start",
                        "command": item.get("confirmed_value"),
                        "source_file": "user-provided",
                        "confidence": "user-confirmed",
                        "origin": "USER_PROVIDED_EVIDENCE",
                    })
            dependencies = [
                fields(item, ("name", "version", "scope", "source_file", "confidence"))
                for item in intelligence.dependencies
                if belongs(str(item.get("source_file", "")), component)
            ]
            runtimes = [
                fields(item, ("runtime", "version", "source_file", "confidence"))
                for item in intelligence.runtimes
                if (
                    belongs(str(item.get("source_file", "")), component)
                    and (
                        str(component.get("path") or ".").strip("./")
                        or str(item.get("runtime")) == str(component.get("framework"))
                        or component.get("package_manager") in {"maven", "gradle"}
                        or component.get("package_manager") in {"npm", "yarn", "pnpm"}
                        or component.get("package_manager") in {"pip", "poetry", "pipenv", "go", "cargo"}
                    )
                )
                or (
                    "/" not in str(item.get("source_file", ""))
                    and (
                        (
                            str(item.get("runtime")) == "Java"
                            and (
                                component.get("framework") == "Spring Boot"
                                or component.get("package_manager") in {"maven", "gradle"}
                            )
                        )
                        or (
                            str(item.get("runtime")) == "Node.js"
                            and (
                                component.get("package_manager") in {"npm", "yarn", "pnpm"}
                                or component.get("framework") in {"Express", "NestJS", "React", "Vite", "Next.js", "Angular"}
                            )
                        )
                        or (
                            str(item.get("runtime")) == "Python"
                            and (
                                component.get("package_manager") in {"pip", "poetry", "pipenv"}
                                or component.get("language") == "Python"
                            )
                        )
                        or (
                            str(item.get("runtime")) == "Go"
                            and component.get("package_manager") == "go"
                        )
                        or (
                            str(item.get("runtime")) == "Rust"
                            and component.get("package_manager") == "cargo"
                        )
                    )
                )
            ]
            ports = [
                fields(item, ("name", "port", "source_file", "confidence", "component", "port_type", "target_port", "service_name", "conflict"))
                for item in intelligence.ports
                if item.get("component") == name
            ]
            base_images = [
                dict(item) for item in intelligence.docker.get("base_images", [])
                if item.get("component") in {None, name}
                or belongs(str(item.get("source_file", "")), component)
            ]
            working_directories = [
                dict(item) for item in intelligence.docker.get("working_directories", [])
                if item.get("component") in {None, name}
                or belongs(str(item.get("source_file", "")), component)
            ]
            environment = [
                fields(item, ("name", "key", "value", "sensitive", "source_file", "confidence"))
                for item in intelligence.environment_variables
                if belongs(str(item.get("source_file", "")), component)
                or "/" not in str(item.get("source_file", ""))
            ]
            framework = component.get("framework")
            local_languages = sorted({
                str(file.language) for file in intelligence.files
                if belongs(file.relative_path, component) and file.language
            })
            manager = component.get("package_manager")
            technology_languages = local_languages
            if framework == "Spring Boot" or manager in {"maven", "gradle"}:
                technology_languages = ["Java"] if "Java" in local_languages or "Java" in intelligence.languages else []
            elif manager in {"npm", "yarn", "pnpm"} or component.get("kind") == "frontend":
                technology_languages = [
                    item for item in ("JavaScript", "TypeScript")
                    if item in local_languages
                ]
            elif manager in {"pip", "poetry", "pipenv"}:
                technology_languages = ["Python"] if "Python" in local_languages else []
            elif manager == "go":
                technology_languages = ["Go"] if "Go" in local_languages else []
            elif manager == "cargo":
                technology_languages = ["Rust"] if "Rust" in local_languages else []
            language = (
                "Java" if framework == "Spring Boot" and "Java" in intelligence.languages
                else technology_languages[0] if len(technology_languages) == 1 else None
            )
            profile_component = {**component, "language": language, "languages": technology_languages}
            strategy = strategy_for_component(profile_component, verified_patterns)
            technology_profile = _technology_profile(profile_component, runtimes)
            if strategy:
                technology_profile["strategy_id"] = strategy.strategy_id
                technology_profile["execution_strategy"] = strategy.execution_strategy
            components.append({
                "name": name,
                "path": path,
                "kind": component.get("kind"),
                "role": component.get("role"),
                "framework": framework,
                "language": language,
                "package_manager": component.get("package_manager"),
                "evidence": list(component.get("evidence") or []),
                "artifacts": [dict(item) for item in component.get("artifacts") or []],
                "deployment_evidence": dict(component.get("deployment_evidence") or {}),
                "runtimes": runtimes,
                "technology_profile": technology_profile,
                **({"strategy_id": strategy.strategy_id} if strategy else {}),
                **({"execution_strategy": strategy.execution_strategy} if strategy else {}),
                "build_metadata": [
                    dict(item) for item in intelligence.build_metadata
                    if belongs(str(item.get("source_file", "")), component)
                ],
                "entrypoints": [
                    dict(item) for item in intelligence.entrypoints
                    if belongs(str(item.get("source_file", "")), component)
                ],
                "commands": commands,
                "dependencies": dependencies,
                "ports": ports,
                "base_images": base_images,
                "working_directories": working_directories,
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
                    ("source_file", "evidence_type", "key", "value", "confidence", "line_number", "extraction_method", "source_type", "derived_from", "rule_id", "model_inference"),
                ))

        dockerfiles = list(intelligence.docker.get("dockerfiles", []))

        def artifact_belongs(source: str, component: dict[str, Any]) -> bool:
            if belongs(source, component):
                return True
            name = str(component.get("name") or "").strip().lower()
            path_name = Path(str(component.get("path") or ".")).name.strip().lower()
            filename = Path(source).name.lower()
            tokens = {token for token in (name, path_name) if token and token != "."}
            return any(filename in {f"dockerfile.{token}", f"{token}.dockerfile"} for token in tokens)

        selected_dockerfiles = [
            item for item in dockerfiles
            if any(artifact_belongs(item, component) for component in selected)
        ]
        for component in components:
            component["dockerfiles"] = [
                item for item in dockerfiles if artifact_belongs(item, component)
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
                fields(item, ("name", "component", "type", "port", "target_port", "depends_on", "source_file", "image", "image_source_file", "image_source_type", "model_inference"))
                for item in intelligence.services
            ],
            "relationships": [dict(item) for item in intelligence.relationships],
            "documentation": {
                "detected": bool(intelligence.documentation.get("files")),
                "files": list(intelligence.documentation.get("files", [])),
            },
        }
        project = {
            "name": intelligence.name,
            "root_path": intelligence.root_path,
            "inspection_run_id": intelligence.inspection_run_id,
            "selected_components": names,
            "available_components": list(available),
        }
        selected_user_evidence = [
            dict(item) for item in intelligence.user_evidence
            if item.get("component") in {None, *names}
        ]
        platform_policies = applicable_platform_policies(components, verified_patterns)
        return DockerContext(
            project, components, infrastructure, evidence, selected_user_evidence,
            verified_patterns, {}, platform_policies, None,
        )
