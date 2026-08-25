"""Minimal Dockerize adapter for the shared evidence-gap contract."""

from __future__ import annotations

from core.evidence import EvidenceGap, EvidenceReference

from .context_builder import DockerContext


class DockerEvidenceGapAdapter:
    """Describe a Docker gap without changing Dockerize decision behavior."""

    @staticmethod
    def from_context(
        context: DockerContext,
        component_name: str,
        *,
        reason: str | None = None,
    ) -> EvidenceGap:
        component = next(
            (item for item in context.components if str(item.get("name")) == component_name),
            None,
        )
        if component is None:
            raise ValueError(f"Docker component was not found in context: {component_name}")

        component_path = str(component.get("path") or ".").strip("./")
        references: dict[tuple[str, str, str], EvidenceReference] = {}

        def add_reference(source_file: str, evidence_type: str, key: str, confidence: str = "low") -> None:
            if not source_file or not key:
                return
            reference = EvidenceReference(source_file, evidence_type, key, confidence)
            references[(reference.source_file, reference.evidence_type, reference.key)] = reference

        def belongs(source_file: str) -> bool:
            return (
                not component_path
                or source_file == component_path
                or source_file.startswith(component_path + "/")
                or component_name.lower() in source_file.lower()
            )

        for item in context.evidence:
            source_file = str(item.get("source_file") or "")
            if belongs(source_file):
                add_reference(
                    source_file,
                    str(item.get("evidence_type") or "fact"),
                    str(item.get("key") or "fact"),
                    str(item.get("confidence") or "low"),
                )
        for group_name, evidence_type in (("runtimes", "runtime"), ("commands", "command"), ("ports", "port")):
            for item in component.get(group_name, []):
                add_reference(
                    str(item.get("source_file") or ""),
                    evidence_type,
                    str(item.get("key") or item.get("name") or evidence_type),
                    str(item.get("confidence") or "low"),
                )
        for item in component.get("files", []):
            add_reference(
                str(item.get("relative_path") or ""),
                "file",
                str(item.get("classification") or "file"),
                "high",
            )

        return EvidenceGap(
            workflow="Dockerize",
            project=str(context.project.get("name") or "unknown"),
            root_path=str(context.project.get("root_path") or ""),
            component=component_name,
            clarification_type="production_start_command",
            requirement="evidence-backed production Docker runtime/start strategy",
            reason=reason or f"{component_name} lacks an evidence-backed production Docker runtime/start strategy",
            missing_evidence="An accepted production Docker runtime and start strategy for this component",
            observed_evidence=tuple(references.values()),
            deterministic_constraints=(
                "Only repository evidence, accepted user evidence, or verified inference may affect generation",
                "Development and preview commands are not production start evidence",
                "No artifact may be generated until deterministic validation succeeds",
            ),
            allowed_decisions=(
                "Use a production strategy explicitly supported by accepted evidence",
                "Request additional deterministic inspection or user clarification",
            ),
            forbidden_decisions=(
                "Treat a development command as a production start command",
                "Treat a preview command as a production start command",
                "Invent a Docker or Nginx strategy",
                "Invent Docker commands, runtime versions, ports, or services",
            ),
        )
