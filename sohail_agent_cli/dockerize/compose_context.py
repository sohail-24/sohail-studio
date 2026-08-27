"""Deterministic, persisted-evidence-only context for Compose decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .infrastructure_policy import evaluate_infrastructure_candidate


class ComposeContextError(ValueError):
    """Raised when a Compose proposal exceeds the validated context."""


@dataclass(frozen=True)
class ComposeRelationship:
    """One persisted relationship; no relationship is inferred here."""

    source: str
    target: str
    relationship_type: str
    evidence: tuple[dict[str, Any], ...] = ()
    source_type: str = "EXPLICIT_EVIDENCE"
    validation: str = "persisted_repository_evidence"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ComposeContext:
    """The bounded Compose input built from a selected Docker context."""

    project: dict[str, Any]
    components: tuple[dict[str, Any], ...]
    data_services: tuple[dict[str, Any], ...]
    service_evidence: tuple[dict[str, Any], ...]
    authorized_infrastructure_services: tuple[dict[str, Any], ...]
    relationships: tuple[ComposeRelationship, ...]
    artifact_scope: dict[str, Any]
    authority: dict[str, Any]
    inspection_run_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "components": [dict(item) for item in self.components],
            "data_services": [dict(item) for item in self.data_services],
            "service_evidence": [dict(item) for item in self.service_evidence],
            "authorized_infrastructure_services": [
                dict(item) for item in self.authorized_infrastructure_services
            ],
            "relationships": [item.to_dict() for item in self.relationships],
            "artifact_scope": self.artifact_scope,
            "authority": self.authority,
            "inspection_run_id": self.inspection_run_id,
        }


@dataclass(frozen=True)
class ComposeContextBuilder:
    """Build Compose context without accessing the repository filesystem."""

    @staticmethod
    def _dockerfile_path(component: dict[str, Any]) -> str:
        stored = [str(item) for item in component.get("dockerfiles", []) if str(item).strip()]
        if stored:
            return stored[0]
        root = str(component.get("path") or ".").strip("/") or "."
        return "Dockerfile" if root == "." else f"{root}/Dockerfile"

    @classmethod
    def build(
        cls,
        context: Any,
        validated_decision: Any | None = None,
    ) -> ComposeContext:
        """Normalize selected component facts and persisted service evidence.

        ``context`` is a DockerContext, but duck typing keeps this module
        independent from the decision implementation and avoids a cycle.
        """
        decision_by_name = {
            str(item.get("name")): item
            for item in (getattr(validated_decision, "components", None) or [])
            if isinstance(item, dict)
        }
        components: list[dict[str, Any]] = []
        for component in context.components:
            name = str(component.get("name") or "")
            path = str(component.get("path") or ".").strip("/") or "."
            decision = decision_by_name.get(name) or {}
            components.append({
                "name": name,
                "role": component.get("role"),
                "technology_profile": dict(component.get("technology_profile") or {}),
                "strategy_id": component.get("strategy_id"),
                "component_root": path,
                "build_context": "." if path == "." else f"./{path}",
                "dockerfile_path": cls._dockerfile_path(component),
                "runtime": [dict(item) for item in component.get("runtimes") or []],
                "build_command": decision.get("build_command"),
                "production_command": decision.get("start_command"),
                "artifact": [dict(item) for item in component.get("artifacts") or []],
                "ports": [dict(item) for item in component.get("ports") or []],
                "environment_contract": [
                    {
                        "name": item.get("name") or item.get("key"),
                        "source_file": item.get("source_file"),
                        "sensitive": bool(item.get("sensitive")),
                        "value_authorized": False,
                    }
                    for item in component.get("environment") or []
                    if item.get("name") or item.get("key")
                ],
                "working_directory": decision.get("working_directory"),
                "policy": _policy_summary(context, name),
                "authority": "validated_component_context",
            })

        relationships = tuple(
            ComposeRelationship(
                source=str(item.get("source")),
                target=str(item.get("target")),
                relationship_type=str(item.get("relationship_type") or "unspecified"),
                evidence=(dict(item),),
                source_type=str(item.get("source_type") or "EXPLICIT_EVIDENCE"),
                validation=str(item.get("validation") or "persisted_repository_evidence"),
            )
            for item in context.infrastructure.get("relationships", [])
            if isinstance(item, dict) and item.get("source") and item.get("target")
        )

        data_services = tuple(
            evaluate_infrastructure_candidate({
                "service_type": str(database),
                "evidence": [
                    dict(item) for item in context.evidence
                    if item.get("evidence_type") == "database"
                    and str(item.get("value")) == str(database)
                ],
                "source_type": "EXPLICIT_EVIDENCE",
                "renderable": False,
            })
            for database in dict.fromkeys(context.infrastructure.get("databases", []))
        )
        service_evidence = tuple(
            evaluate_infrastructure_candidate({
                **dict(item),
                "source_type": str(item.get("source_type") or "EXPLICIT_EVIDENCE"),
                "renderable": False,
            })
            for item in context.infrastructure.get("services", [])
            if isinstance(item, dict) and item.get("name")
        )
        authorized_infrastructure_services = tuple(
            dict(item) for item in (*data_services, *service_evidence)
            if item.get("eligibility") == "ELIGIBLE"
        )

        artifact_plan = dict(context.artifact_plan or {})
        selected = [str(item.get("name")) for item in context.components]
        return ComposeContext(
            project={
                "name": context.project.get("name"),
                "root_path": context.project.get("root_path"),
                "inspection_run_id": context.project.get("inspection_run_id"),
            },
            components=tuple(components),
            data_services=data_services,
            service_evidence=service_evidence,
            authorized_infrastructure_services=authorized_infrastructure_services,
            relationships=relationships,
            artifact_scope={
                "selected_components": selected,
                "dockerfiles": dict(artifact_plan.get("dockerfiles") or {}),
                "compose": artifact_plan.get("compose", "unspecified"),
                "generated_services": selected,
            },
            authority={
                "source": "persisted_project_intelligence",
                "inspection_run_id": context.project.get("inspection_run_id"),
                "repository_rescan": False,
            },
            inspection_run_id=context.project.get("inspection_run_id"),
        )

    @staticmethod
    def validate_proposal(context: Any, compose: dict[str, Any]) -> None:
        """Reject model services, paths, dependencies, or scopes outside context."""
        compose_context = context.compose_context
        if not compose_context:
            return
        normalized = (
            compose_context
            if isinstance(compose_context, dict)
            else compose_context.to_dict()
        )
        expected = {str(item["name"]): item for item in normalized.get("components", [])}
        services = compose.get("services") or []
        if not isinstance(services, list):
            raise ComposeContextError("Docker Compose services must be a list")
        for service in services:
            if not isinstance(service, dict):
                raise ComposeContextError("Docker Compose service must be an object")
            name = str(service.get("name") or "")
            component = str(service.get("component") or "")
            if component not in expected or name != component:
                raise ComposeContextError("Docker decision invented a Compose service or component")
            authoritative = expected[component]
            if service.get("build_context") not in {None, authoritative["build_context"]}:
                raise ComposeContextError(
                    "Docker decision changed the evidence-backed Compose build context"
                )
            for key in (
                "path", "root", "root_path", "dockerfile",
                "dockerfile_path", "artifact_path", "image", "volumes",
                "networks", "healthcheck", "secrets", "configs",
                "container_name", "restart", "profiles",
            ):
                if service.get(key) is not None:
                    category = (
                        "placement" if key in {
                            "path", "root", "root_path", "dockerfile",
                            "dockerfile_path", "artifact_path",
                        } else "infrastructure"
                    )
                    raise ComposeContextError(
                        "Docker decision proposed unauthorized Compose "
                        f"{category} "
                        f"field: {key}"
                    )
            relationships = {
                (item["source"], item["target"])
                for item in normalized.get("relationships", [])
                if item.get("validation") == "persisted_repository_evidence"
            }
            for dependency in service.get("depends_on") or []:
                if (component, str(dependency)) not in relationships:
                    raise ComposeContextError(
                        "Docker decision invented an unsupported Compose relationship: "
                        f"{component} -> {dependency}"
                    )
            component_ports = [
                item for item in authoritative.get("ports", [])
                if item.get("port_type") == "application"
                and not item.get("conflict")
                and item.get("port") is not None
            ]
            service_port = service.get("port")
            target_port = service.get("target_port", service_port)
            expected_port_pairs = {
                (item.get("port"), item.get("port")) for item in component_ports
            }
            if component_ports and (service_port, target_port) not in expected_port_pairs:
                raise ComposeContextError(
                    "Docker Compose service port conflicts with authoritative "
                    f"component port evidence for {component}"
                )
            if not component_ports and (service_port is not None or target_port is not None):
                raise ComposeContextError(
                    f"Docker Compose service invented a port for {component}; "
                    "no component port evidence exists"
                )


def _policy_summary(context: Any, component_name: str) -> dict[str, Any] | None:
    for policy in context.platform_policies:
        if str(policy.get("component") or "") == component_name:
            return {
                "policy_id": policy.get("policy_id"),
                "policy_version": policy.get("policy_version"),
                "source_type": policy.get("source_type"),
                "applicable_reason": policy.get("applicable_reason"),
            }
    return None
