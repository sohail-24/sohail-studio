"""Small, explicit registry of approved deterministic Docker platform policies."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sohail_agent_cli.inspection.models import EvidenceSourceType


APPROVED_PLATFORM_POLICY = EvidenceSourceType.APPROVED_PLATFORM_POLICY


JAVA_SPRING_BOOT_CONTAINER_V1: dict[str, Any] = {
    "policy_id": "java-spring-boot-container-v1",
    "policy_version": "1",
    "source_type": APPROVED_PLATFORM_POLICY,
    "model_inference": False,
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


PLATFORM_POLICIES: tuple[dict[str, Any], ...] = (JAVA_SPRING_BOOT_CONTAINER_V1,)


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


def _applicable_reason(component: dict[str, Any]) -> list[str]:
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


def applicable_platform_policies(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return policy records applicable to the supplied persisted facts."""
    results: list[dict[str, Any]] = []
    for component in components:
        reasons = _applicable_reason(component)
        if len(reasons) != 4:
            continue
        for policy in PLATFORM_POLICIES:
            record = deepcopy(policy)
            record["component"] = str(component.get("name"))
            record["applicable_reason"] = reasons
            results.append(record)
    return results


def policy_for_component(policies: list[dict[str, Any]], component_name: str) -> dict[str, Any] | None:
    return next(
        (
            dict(policy) for policy in policies
            if str(policy.get("component")) == component_name
            and policy.get("source_type") == APPROVED_PLATFORM_POLICY
            and policy.get("policy_id")
            and policy.get("policy_version")
            and policy.get("model_inference") is False
        ),
        None,
    )


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
