"""Technology-specific Docker strategy registry.

The registry classifies already-inspected component facts.  It never reads a
repository and it never supplies deployment defaults; applicability is only a
dispatch boundary for policies, validation, and rendering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

Predicate = Callable[[dict[str, Any], list[dict[str, Any]]], bool]

PROCESS_RUNTIME = "PROCESS_RUNTIME"
STATIC_ARTIFACT_SERVER = "STATIC_ARTIFACT_SERVER"


@dataclass(frozen=True)
class DockerStrategy:
    strategy_id: str
    family: str
    predicate: Predicate
    execution_strategy: str = PROCESS_RUNTIME

    def applies(self, component: dict[str, Any], patterns: list[dict[str, Any]]) -> bool:
        return self.predicate(component, patterns)


def _has_pattern(component: dict[str, Any], patterns: list[dict[str, Any]], category: str) -> bool:
    return any(
        str(item.get("component")) == str(component.get("name"))
        and item.get("category") == category
        and item.get("origin") == "VERIFIED_INFERENCE"
        for item in patterns
    )


def _has_start(component: dict[str, Any]) -> bool:
    return any(
        item.get("name") == "start" and str(item.get("command") or "").strip()
        for item in component.get("commands", [])
    )


def _exact_runtime(component: dict[str, Any], name: str) -> bool:
    import re

    return any(
        str(item.get("runtime")) == name
        and re.fullmatch(r"v?\d+(?:\.\d+){0,2}", str(item.get("version") or "").strip())
        for item in component.get("runtimes", [])
    )


def _static_frontend(component: dict[str, Any], patterns: list[dict[str, Any]]) -> bool:
    return (
        component.get("kind") == "frontend"
        and _has_pattern(component, patterns, "static_frontend")
    )


def _java_maven(component: dict[str, Any], patterns: list[dict[str, Any]]) -> bool:
    return component.get("package_manager") == "maven" and (
        component.get("language") == "Java"
        or any(str(item.get("runtime")) == "Java" for item in component.get("runtimes", []))
    )


def _java_gradle(component: dict[str, Any], patterns: list[dict[str, Any]]) -> bool:
    return component.get("package_manager") == "gradle" and (
        component.get("language") == "Java"
        or any(str(item.get("runtime")) == "Java" for item in component.get("runtimes", []))
    )


def _python(component: dict[str, Any], patterns: list[dict[str, Any]]) -> bool:
    return (
        component.get("language") == "Python"
        and component.get("package_manager") in {"pip", "poetry", "pipenv"}
    )


def _node(component: dict[str, Any], patterns: list[dict[str, Any]]) -> bool:
    return (
        component.get("package_manager") in {"npm", "yarn", "pnpm"}
        and component.get("kind") != "frontend"
    )


def _nginx(component: dict[str, Any], patterns: list[dict[str, Any]]) -> bool:
    return component.get("framework") == "Nginx"


def _go(component: dict[str, Any], patterns: list[dict[str, Any]]) -> bool:
    return component.get("package_manager") == "go" or component.get("language") == "Go"


def _rust(component: dict[str, Any], patterns: list[dict[str, Any]]) -> bool:
    return component.get("package_manager") == "cargo" or component.get("language") == "Rust"


STRATEGIES: tuple[DockerStrategy, ...] = (
    DockerStrategy(
        "react-vite-static", "static_frontend", _static_frontend,
        execution_strategy=STATIC_ARTIFACT_SERVER,
    ),
    DockerStrategy("java-maven-spring-boot", "java", _java_maven),
    DockerStrategy("java-gradle-spring-boot", "java", _java_gradle),
    DockerStrategy("python-application", "python", _python),
    DockerStrategy("node-backend", "node", _node),
    DockerStrategy("nginx-server", "nginx", _nginx),
    DockerStrategy("go-application", "go", _go),
    DockerStrategy("rust-application", "rust", _rust),
)


def matching_strategies(
    component: dict[str, Any],
    patterns: Iterable[dict[str, Any]] = (),
) -> list[DockerStrategy]:
    pattern_list = list(patterns)
    return [strategy for strategy in STRATEGIES if strategy.applies(component, pattern_list)]


def strategy_for_component(
    component: dict[str, Any],
    patterns: Iterable[dict[str, Any]] = (),
) -> DockerStrategy | None:
    matches = matching_strategies(component, patterns)
    return matches[0] if len(matches) == 1 else None


def has_exact_runtime(component: dict[str, Any], runtime: str) -> bool:
    """Public helper for policy applicability without exposing predicates."""
    return _exact_runtime(component, runtime)


def has_production_start(component: dict[str, Any]) -> bool:
    return _has_start(component)
