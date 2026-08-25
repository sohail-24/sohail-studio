"""Deterministic, provenance-preserving engineering pattern recognition."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .models import EvidenceOrigin, EvidenceReference


@dataclass(frozen=True)
class VerifiedEngineeringPattern:
    """A policy boundary established from accepted repository evidence."""

    pattern_id: str
    category: str
    component: str
    policy: dict[str, Any]
    rationale: str
    evidence_references: tuple[EvidenceReference, ...]
    origin: EvidenceOrigin = EvidenceOrigin.VERIFIED_INFERENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", EvidenceOrigin(self.origin))
        if self.origin is not EvidenceOrigin.VERIFIED_INFERENCE:
            raise ValueError("Verified engineering patterns must retain VERIFIED_INFERENCE origin")
        if not self.pattern_id.strip() or not self.category.strip() or not self.component.strip():
            raise ValueError("A verified engineering pattern requires an id, category, and component")
        if not self.evidence_references:
            raise ValueError("A verified engineering pattern requires repository evidence references")
        if any(item.origin is not EvidenceOrigin.REPOSITORY_EVIDENCE for item in self.evidence_references):
            raise ValueError("Pattern evidence references must point to repository evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "category": self.category,
            "component": self.component,
            "policy": self.policy,
            "rationale": self.rationale,
            "evidence_references": [item.to_dict() for item in self.evidence_references],
            "origin": self.origin.value,
        }


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _belongs(source_file: str, component: Mapping[str, Any]) -> bool:
    component_path = str(component.get("path") or ".").strip("./")
    if not component_path:
        return True
    return source_file == component_path or source_file.startswith(component_path + "/")


def _reference(source_file: str, evidence_type: str, key: str, confidence: str) -> EvidenceReference:
    return EvidenceReference(
        source_file=source_file,
        evidence_type=evidence_type,
        key=key,
        confidence=confidence,
        origin=EvidenceOrigin.REPOSITORY_EVIDENCE,
    )


class VerifiedEngineeringPatternRecognizer:
    """Recognize only patterns whose policy prerequisites are all observable."""

    _EXACT_VERSION = re.compile(r"^v?\d+(?:\.\d+){0,2}$")

    def recognize(
        self,
        intelligence: Any,
        selected_components: Iterable[str] | None = None,
    ) -> list[VerifiedEngineeringPattern]:
        components = _value(intelligence, "components", []) or []
        selected = set(selected_components) if selected_components is not None else None
        return [
            pattern
            for component in components
            if selected is None or str(_value(component, "name")) in selected
            for pattern in (self._static_frontend(intelligence, component),)
            if pattern is not None
        ]

    def _static_frontend(self, intelligence: Any, component_value: Any) -> VerifiedEngineeringPattern | None:
        component = dict(component_value) if isinstance(component_value, Mapping) else {
            key: _value(component_value, key)
            for key in ("name", "path", "kind", "role", "runtimes")
        }
        name = str(component.get("name") or "")
        if component.get("kind") != "frontend" or not name:
            return None

        files = list(_value(intelligence, "files", []) or [])
        local_files = [
            item for item in files
            if _belongs(str(_value(item, "relative_path", "")), component)
        ]
        classifications = {str(_value(item, "classification", "")) for item in local_files}
        entry_file = next(
            (
                str(_value(item, "relative_path", ""))
                for item in local_files
                if str(_value(item, "relative_path", "")).rsplit("/", 1)[-1].lower() == "index.html"
            ),
            None,
        )
        if "dependency_manifest" not in classifications or "lockfile" not in classifications or not entry_file:
            return None

        commands = [
            item for item in (_value(intelligence, "commands", []) or [])
            if str(_value(item, "name", "")) == "build"
            and str(_value(item, "command", "")).strip()
            and _belongs(str(_value(item, "source_file", "")), component)
            and str(_value(item, "confidence", "")) == "high"
        ]
        if len(commands) != 1:
            return None

        runtimes = [
            item for item in (component.get("runtimes") or _value(intelligence, "runtimes", []) or [])
            if self._EXACT_VERSION.fullmatch(str(_value(item, "version", "")).strip())
        ]
        if len(runtimes) != 1:
            return None

        ports = [
            item for item in (_value(intelligence, "ports", []) or [])
            if str(_value(item, "component", "")) == name
            and _value(item, "port_type") == "application"
            and _value(item, "port") is not None
            and not _value(item, "conflict", False)
        ]
        if len(ports) != 1:
            return None

        references: list[EvidenceReference] = []

        def add(reference: EvidenceReference) -> None:
            marker = (reference.source_file, reference.evidence_type, reference.key)
            if not any((item.source_file, item.evidence_type, item.key) == marker for item in references):
                references.append(reference)

        build = commands[0]
        component_source = next(
            (
                str(_value(item, "relative_path"))
                for item in local_files
                if _value(item, "classification") == "dependency_manifest"
            ),
            str(_value(build, "source_file")),
        )
        add(_reference(component_source, "component_classification", "frontend", "high"))
        add(_reference(str(_value(build, "source_file")), "command", "build", str(_value(build, "confidence"))))
        for item in local_files:
            classification = str(_value(item, "classification", ""))
            if classification in {"dependency_manifest", "lockfile"}:
                add(_reference(str(_value(item, "relative_path")), "file", classification, "high"))
        add(_reference(entry_file, "entrypoint", "static_html_entry", "high"))
        runtime = runtimes[0]
        add(_reference(
            str(_value(runtime, "source_file")), "runtime", str(_value(runtime, "runtime")),
            str(_value(runtime, "confidence", "high")),
        ))
        port = ports[0]
        port_source = _value(port, "source_file") or next(
            (
                _value(source, "source_file")
                for source in (_value(port, "sources", []) or [])
                if _value(source, "source_file")
            ),
            None,
        )
        if not port_source:
            return None
        add(_reference(
            str(port_source), "port", "application", str(_value(port, "confidence", "high")),
        ))

        return VerifiedEngineeringPattern(
            pattern_id="static-frontend",
            category="static_frontend",
            component=name,
            policy={
                "requirements": [
                    "frontend component classification",
                    "exact runtime evidence",
                    "locked dependency manifest",
                    "high-confidence build command",
                    "explicit static HTML entry document",
                    "non-conflicting application port",
                ],
                "build_command": str(_value(build, "command")),
                "port": _value(port, "port"),
                "implementation": "static-content-serving",
                "allowed_start_command_families": ["nginx", "caddy", "serve", "npx serve"],
            },
            rationale=(
                "The component is classified as a frontend and has an exact runtime, "
                "locked dependencies, an explicit build command, a static HTML entry, "
                "and one non-conflicting application port."
            ),
            evidence_references=tuple(references),
        )


def recognize_verified_patterns(
    intelligence: Any,
    selected_components: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Return serializable patterns for Project Intelligence and API contexts."""

    return [
        pattern.to_dict()
        for pattern in VerifiedEngineeringPatternRecognizer().recognize(intelligence, selected_components)
    ]
