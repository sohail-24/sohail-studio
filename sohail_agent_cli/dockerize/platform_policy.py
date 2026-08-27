"""Small, explicit registry of approved deterministic Docker platform policies."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sohail_agent_cli.inspection.models import EvidenceSourceType

from .strategies import has_exact_runtime, has_production_start, strategy_for_component

APPROVED_PLATFORM_POLICY = EvidenceSourceType.APPROVED_PLATFORM_POLICY


JAVA_SPRING_BOOT_CONTAINER_V1: dict[str, Any] = {
    "policy_id": "java-spring-boot-container-v1",
    "policy_version": "1",
    "source_type": APPROVED_PLATFORM_POLICY,
    "model_inference": False,
    "strategy_id": "java-maven-spring-boot",
    "applicability_rule": "java.spring-boot.executable-jar.v1",
    "applicability": {
        "language": "Java",
        "runtime": "Java 17",
        "framework": "Spring Boot",
        "executable_artifact": "DERIVED_DETERMINISTIC executable JAR",
    },
    "values": {
        "base_image": {
            "value": "eclipse-temurin:17-jre-jammy",
            "source_type": APPROVED_PLATFORM_POLICY,
            "policy_id": "java-spring-boot-container-v1",
            "policy_version": "1",
            "model_inference": False,
        },
        "working_directory": {
            "value": "/app",
            "source_type": APPROVED_PLATFORM_POLICY,
            "policy_id": "java-spring-boot-container-v1",
            "policy_version": "1",
            "model_inference": False,
        },
        "build_image": {
            "value": "maven:3.9.16-eclipse-temurin-17",
            "source_type": APPROVED_PLATFORM_POLICY,
            "policy_id": "java-spring-boot-container-v1",
            "policy_version": "1",
            "model_inference": False,
        },
    },
}


def _policy_value(
    value: Any,
    policy_id: str,
    policy_version: str,
    *,
    rule_id: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "source_type": APPROVED_PLATFORM_POLICY,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "rule_id": rule_id,
        "model_inference": False,
    }


def _runtime_version(component: dict[str, Any], runtime: str) -> str | None:
    values = {
        str(item.get("version") or "").strip()
        for item in component.get("runtimes", [])
        if str(item.get("runtime")) == runtime
        and str(item.get("version") or "").strip()
    }
    return next(iter(values)) if len(values) == 1 else None


def _has_dependency_manifest(component: dict[str, Any]) -> bool:
    return any(
        str(item.get("classification")) == "dependency_manifest"
        for item in component.get("files", [])
    )


def _has_lockfile(component: dict[str, Any]) -> bool:
    return any(
        str(item.get("classification")) == "lockfile"
        for item in component.get("files", [])
    )


def _exact_runtime_version(component: dict[str, Any], runtime: str) -> str | None:
    value = _runtime_version(component, runtime)
    if value is None:
        return None
    import re

    return value if re.fullmatch(r"v?\d+(?:\.\d+){0,2}", value) else None


def _has_application_port(component: dict[str, Any]) -> bool:
    return any(
        item.get("port_type") == "application"
        and item.get("port") is not None
        and not item.get("conflict")
        for item in component.get("ports", [])
    )


def _static_output_directory(component: dict[str, Any]) -> str:
    """Return the output authorized by the verified static build pattern."""
    if component.get("framework") == "Vite" or any(
        str(item.get("name")) == "vite" for item in component.get("dependencies", [])
    ):
        return "dist"
    return "build"


def _locked_package_install_command(component: dict[str, Any]) -> str | None:
    """Return an install command only when the persisted lockfile proves it."""
    if not _has_lockfile(component):
        return None
    manager = str(component.get("package_manager") or "")
    return {
        "npm": "npm ci",
        "yarn": "yarn install --frozen-lockfile",
        "pnpm": "pnpm install --frozen-lockfile",
    }.get(manager)


def _policy(
    policy_id: str,
    strategy_id: str,
    applicability: dict[str, Any],
    values: dict[str, dict[str, Any]],
    reasons: list[str],
) -> dict[str, Any]:
    version = "1"
    return {
        "policy_id": policy_id,
        "policy_version": version,
        "source_type": APPROVED_PLATFORM_POLICY,
        "model_inference": False,
        "strategy_id": strategy_id,
        "applicability": applicability,
        "applicable_reason": reasons,
        "values": {
            key: _policy_value(value, policy_id, version, rule_id=f"platform.{strategy_id}.v1")
            for key, value in values.items()
        },
    }


def _dynamic_policies(
    component: dict[str, Any],
    patterns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    strategy = strategy_for_component(component, patterns)
    if strategy is None:
        return []
    if strategy.strategy_id == "java-maven-spring-boot":
        reasons = _java_spring_boot_reason(component)
        if len(reasons) != len(JAVA_SPRING_BOOT_CONTAINER_V1.get("applicability") or {}):
            return []
        policy = deepcopy(JAVA_SPRING_BOOT_CONTAINER_V1)
        policy["applicable_reason"] = reasons
        return [policy]
    if strategy.strategy_id == "java-gradle-spring-boot":
        if not has_exact_runtime(component, "Java") or not component.get("artifacts"):
            return []
        return [_policy(
            "java-spring-boot-gradle-container-v1",
            strategy.strategy_id,
            {"language": "Java", "runtime": "Java 17", "framework": "Spring Boot", "executable_artifact": "DERIVED_DETERMINISTIC executable JAR"},
            {
                "base_image": "eclipse-temurin:17-jre-jammy",
                "working_directory": "/app",
                "build_image": "gradle:8.7-jdk17",
            },
            ["language=Java", "runtime=Java 17", "framework=Spring Boot", "derived executable JAR"],
        ) if _runtime_version(component, "Java") in {"17", "v17"} else []]
    if strategy.strategy_id == "node-backend":
        version = _exact_runtime_version(component, "Node.js")
        has_node_evidence = (
            component.get("language") in {"JavaScript", "TypeScript"}
            and component.get("package_manager") == "npm"
            and component.get("framework") in {"Express", "Node.js", None}
            and _has_dependency_manifest(component)
            and _has_lockfile(component)
            and has_production_start(component)
        )
        if version and has_node_evidence:
            return [_policy(
                "node-backend-container-v1", strategy.strategy_id,
                {"language": component.get("language"), "runtime": f"Node.js {version}", "production_start": "explicit repository command"},
                {"base_image": f"node:{version}-alpine", "working_directory": "/app", "runtime_version": version},
                [f"runtime=Node.js {version}", "explicit production start command"],
            )]
        if not component.get("runtimes") and has_node_evidence:
            return [_policy(
                "node-backend-container-v1", strategy.strategy_id,
                {"language": component.get("language"), "runtime": "Node.js 22 (approved compatibility policy)", "production_start": "explicit repository command"},
                {"base_image": "node:22-alpine", "working_directory": "/app", "runtime_version": "22"},
                ["recognized npm/Express backend evidence", "explicit production start command", "approved Node.js 22 compatibility policy"],
            )]
        return []
    if strategy.strategy_id == "python-application":
        version = _runtime_version(component, "Python")
        if not version or not has_production_start(component) or not _has_dependency_manifest(component):
            return []
        framework = str(component.get("framework") or "application").lower().replace(" ", "-")
        policy_name = f"python-{framework}-container-v1"
        manifest = next(
            (
                str(item.get("relative_path") or "")
                for item in component.get("files", [])
                if str(item.get("classification")) == "dependency_manifest"
                and str(item.get("relative_path") or "").endswith("requirements.txt")
            ),
            None,
        )
        install_command = (
            f"pip install --no-cache-dir -r {manifest.rsplit('/', 1)[-1]}"
            if manifest else "pip install --no-cache-dir ."
        )
        return [_policy(
            policy_name, strategy.strategy_id,
            {"language": "Python", "runtime": f"Python {version}", "framework": component.get("framework") or "generic", "production_start": "explicit repository command"},
            {"base_image": f"python:{version}-slim", "working_directory": "/app", "install_command": install_command},
            [f"runtime=Python {version}", "dependency manifest", "explicit production start command"],
        )]
    if strategy.strategy_id == "react-vite-static":
        install_command = _locked_package_install_command(component)
        version = _exact_runtime_version(component, "Node.js")
        if not version or not _has_pattern(component, patterns, "static_frontend"):
            if version or not _has_pattern(component, patterns, "static_frontend"):
                return []
            return [_policy(
                f"{str(component.get('framework') or 'frontend').lower().replace('.', '')}-static-container-v1",
                strategy.strategy_id,
                {"component_type": "static frontend", "framework": component.get("framework"), "runtime": "Node.js 22 (approved compatibility policy)", "verified_pattern": "static-frontend"},
                {
                    "base_image": "node:22-alpine",
                    "working_directory": "/app",
                    **({"install_command": install_command} if install_command else {}),
                    "runtime_version": "22",
                    "output_directory": _static_output_directory(component),
                    "static_serving_command": ["npx", "serve", "-s", _static_output_directory(component)],
                },
                ["verified static-frontend pattern", "approved Node.js 22 compatibility policy"],
            )]
        output = _static_output_directory(component)
        return [_policy(
            f"{str(component.get('framework') or 'frontend').lower().replace('.', '')}-static-container-v1",
            strategy.strategy_id,
            {"component_type": "static frontend", "framework": component.get("framework"), "runtime": f"Node.js {version}", "verified_pattern": "static-frontend"},
            {
                "base_image": f"node:{version}-alpine",
                "working_directory": "/app",
                **({"install_command": install_command} if install_command else {}),
                "runtime_version": version,
                "output_directory": output,
                "static_serving_command": ["npx", "serve", "-s", output],
            },
            [f"framework={component.get('framework')}", f"runtime=Node.js {version}", "verified static-frontend pattern"],
        )]
    if strategy.strategy_id == "nginx-server":
        if not _has_application_port(component):
            return []
        return [_policy(
            "nginx-container-v1", strategy.strategy_id,
            {"technology": "Nginx", "listen_port": "explicit nginx listen directive"},
            {"base_image": "nginx:alpine", "working_directory": "/etc/nginx", "start_command": ["nginx", "-g", "daemon off;"]},
            ["Nginx configuration", "explicit listen port"],
        )]
    if strategy.strategy_id == "go-application":
        version = _runtime_version(component, "Go")
        if version and component.get("artifacts"):
            return [_policy(
                "go-container-v1", strategy.strategy_id,
                {"language": "Go", "runtime": f"Go {version}", "executable_artifact": "DERIVED_DETERMINISTIC"},
                {"base_image": f"golang:{version}-alpine", "working_directory": "/app"},
                [f"runtime=Go {version}", "derived executable artifact"],
            )]
        return []
    if strategy.strategy_id == "rust-application":
        version = _runtime_version(component, "Rust")
        if version and component.get("artifacts"):
            return [_policy(
                "rust-container-v1", strategy.strategy_id,
                {"language": "Rust", "runtime": f"Rust {version}", "executable_artifact": "DERIVED_DETERMINISTIC"},
                {"base_image": f"rust:{version}-slim", "working_directory": "/app"},
                [f"runtime=Rust {version}", "derived executable artifact"],
            )]
    return []


def _exact_java17(component: dict[str, Any]) -> bool:
    return any(
        str(item.get("runtime")) == "Java"
        and str(item.get("version")) in {"17", "v17"}
        for item in component.get("runtimes", [])
    )


def _proven_executable_jar(component: dict[str, Any]) -> bool:
    artifacts = [
        item for item in component.get("artifacts", [])
        if item.get("executable") is True
        and item.get("packaging") == "jar"
        and item.get("source_type") == EvidenceSourceType.DERIVED_DETERMINISTIC
        and item.get("model_inference") is False
        and item.get("rule_id")
        and item.get("derived_from")
        and item.get("launch_command")
    ]
    return len(artifacts) == 1 and artifacts[0].get("launch_command")[:2] == ["java", "-jar"]


def _java_spring_boot_reason(component: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if component.get("language") == "Java":
        reasons.append("language=Java")
    if _exact_java17(component):
        reasons.append("runtime=Java 17")
    if component.get("framework") == "Spring Boot":
        reasons.append("framework=Spring Boot")
    if _proven_executable_jar(component):
        reasons.append("one DERIVED_DETERMINISTIC executable JAR with java -jar launch")
    return reasons


def _has_pattern(component: dict[str, Any], patterns: list[dict[str, Any]], category: str) -> bool:
    return any(
        str(item.get("component")) == str(component.get("name"))
        and item.get("category") == category
        and item.get("origin") == "VERIFIED_INFERENCE"
        for item in patterns
    )


def applicable_platform_policies(
    components: list[dict[str, Any]],
    patterns: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return policy records applicable to the supplied persisted facts."""
    results: list[dict[str, Any]] = []
    pattern_list = list(patterns or [])
    for component in components:
        for policy in _dynamic_policies(component, pattern_list):
            record = deepcopy(policy)
            record["component"] = str(component.get("name"))
            results.append(record)
    return results


def policy_for_component(policies: list[dict[str, Any]], component_name: str) -> dict[str, Any] | None:
    matches = [
        dict(policy) for policy in policies
        if str(policy.get("component")) == component_name
        and policy.get("source_type") == APPROVED_PLATFORM_POLICY
        and policy.get("policy_id")
        and policy.get("policy_version")
        and policy.get("model_inference") is False
    ]
    return matches[0] if len(matches) == 1 else None


def policy_value(policy: dict[str, Any] | None, field: str) -> dict[str, Any] | None:
    if not policy:
        return None
    value = policy.get("values", {}).get(field)
    if not isinstance(value, dict):
        return None
    if (
        not value.get("value")
        or value.get("source_type") != APPROVED_PLATFORM_POLICY
        or value.get("policy_id") != policy.get("policy_id")
        or value.get("policy_version") != policy.get("policy_version")
        or value.get("model_inference") is not False
    ):
        return None
    return dict(value)
