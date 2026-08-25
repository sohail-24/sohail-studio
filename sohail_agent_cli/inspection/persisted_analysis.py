"""Adapt canonical persisted Project Intelligence for legacy generators."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from sohail_agent_cli.analyzers.repo_analyzer import ComponentAnalysis, RepoAnalysis
from sohail_agent_cli.analyzers.stack_detector import DetectedStack, StackType

from .models import ProjectIntelligence


_STACK_BY_NAME = {
    "angular": StackType.ANGULAR,
    "django": StackType.DJANGO,
    "express": StackType.NODE,
    "fastapi": StackType.FASTAPI,
    "flask": StackType.FLASK,
    "go": StackType.GO,
    "java": StackType.JAVA,
    "next.js": StackType.NEXTJS,
    "nextjs": StackType.NEXTJS,
    "node.js": StackType.NODE,
    "node": StackType.NODE,
    "python": StackType.PYTHON,
    "react": StackType.REACT,
    "rust": StackType.RUST,
    "typescript": StackType.TYPESCRIPT,
    "vue": StackType.VUE,
}


def _stack_type(framework: str | None, runtime: str | None, languages: list[str]) -> StackType:
    for value in (framework, runtime, *languages):
        normalized = str(value or "").strip().lower()
        if normalized in _STACK_BY_NAME:
            return _STACK_BY_NAME[normalized]
    return StackType.UNKNOWN


def _runtime_for(component: dict[str, Any], intelligence: ProjectIntelligence) -> str:
    runtimes = component.get("runtimes") or []
    if runtimes:
        item = runtimes[0]
        return " ".join(str(item.get(key)) for key in ("runtime", "version") if item.get(key))
    component_path = str(component.get("path") or ".").strip("./")
    for item in intelligence.runtimes:
        source = str(item.get("source_file") or "")
        if not component_path or source == component_path or source.startswith(component_path + "/"):
            return " ".join(str(item.get(key)) for key in ("runtime", "version") if item.get(key))
    return "unknown"


def repo_analysis_from_intelligence(intelligence: ProjectIntelligence) -> RepoAnalysis:
    """Build generator-compatible analysis exclusively from persisted facts."""

    root = Path(intelligence.root_path)
    all_ports = list(intelligence.ports)
    components: list[ComponentAnalysis] = []
    for item in intelligence.components:
        name = str(item.get("name") or "component")
        relative_path = str(item.get("path") or ".")
        framework = str(item.get("framework") or "unknown")
        runtime = _runtime_for(item, intelligence)
        local_ports = [
            int(port["port"])
            for port in all_ports
            if port.get("component") == name and port.get("port") is not None
        ]
        commands = [
            command for command in intelligence.commands
            if command.get("component") == name
            or str(command.get("source_file") or "").startswith(relative_path.rstrip("/") + "/")
        ]
        component_files = [
            file.relative_path for file in intelligence.files
            if file.relative_path == relative_path
            or file.relative_path.startswith(relative_path.rstrip("/") + "/")
        ]
        component_languages = [
            file.language for file in intelligence.files
            if file.language and (
                file.relative_path == relative_path
                or file.relative_path.startswith(relative_path.rstrip("/") + "/")
            )
        ]
        stack = DetectedStack(
            primary=_stack_type(framework, runtime, component_languages),
            framework=framework,
            runtime=runtime,
            port=local_ports[0] if local_ports else None,
        )
        components.append(ComponentAnalysis(
            name=name,
            path=root / relative_path,
            stack=stack,
            package_manager=str(item.get("package_manager") or "unknown"),
            framework=framework,
            scripts={str(command.get("name")): str(command.get("command")) for command in commands if command.get("name") and command.get("command")},
            runtime=runtime,
            ports=local_ports,
            important_files=component_files,
            has_dockerfile=any(Path(path).name == "Dockerfile" for path in component_files),
        ))

    root_framework = next(iter(intelligence.frameworks), None)
    root_runtime = " ".join(str(item.get(key)) for item in (intelligence.runtimes[:1] or [{}]) for key in ("runtime", "version") if item.get(key))
    root_port = next((int(item["port"]) for item in all_ports if item.get("port") is not None), None)
    root_stack = components[0].stack if components else DetectedStack(
        primary=_stack_type(root_framework, root_runtime, intelligence.languages),
        framework=root_framework or "unknown",
        runtime=root_runtime or "unknown",
        port=root_port,
    )
    file_counts = Counter(Path(file.relative_path).suffix.lower() for file in intelligence.files if Path(file.relative_path).suffix)
    ci_files = list(intelligence.ci_cd.get("files", []))
    return RepoAnalysis(
        name=intelligence.name,
        path=root,
        stack=root_stack,
        dependencies=[str(item.get("name")) for item in intelligence.dependencies if item.get("name")],
        file_counts=dict(file_counts),
        has_docker=bool(intelligence.docker.get("dockerfiles")),
        has_docker_compose=bool(intelligence.docker.get("compose_files")),
        has_ci_cd=bool(ci_files),
        ci_cd_files=ci_files,
        important_files=[file.relative_path for file in intelligence.files],
        has_readme=any(Path(file.relative_path).name.lower().startswith("readme") for file in intelligence.files),
        has_k8s=bool(intelligence.kubernetes.get("files")),
        components=components,
    )
