"""Normalized, provenance-preserving models produced by Deep Inspector."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

Confidence = str


@dataclass(frozen=True)
class Evidence:
    """One explainable fact extracted from one repository file."""

    source_file: str
    evidence_type: str
    key: str
    value: Any
    confidence: Confidence
    line_number: int | None = None
    extraction_method: str = "deterministic-parser"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiscoveredFile:
    """Metadata for a discovered file; source contents are never retained."""

    relative_path: str
    classification: str
    language: str | None
    size: int
    sha256: str | None
    ignored: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectIntelligence:
    """The single normalized project context produced by an inspection."""

    name: str
    root_path: str
    inspected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    files: list[DiscoveredFile] = field(default_factory=list)
    components: list[dict[str, Any]] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    runtimes: list[dict[str, Any]] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)
    ports: list[dict[str, Any]] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)
    databases: list[str] = field(default_factory=list)
    environment_variables: list[dict[str, Any]] = field(default_factory=list)
    docker: dict[str, Any] = field(default_factory=dict)
    kubernetes: dict[str, Any] = field(default_factory=dict)
    ci_cd: dict[str, Any] = field(default_factory=dict)
    documentation: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_summary(
        cls,
        summary: dict[str, Any],
        *,
        root_path: str,
        inspected_at: str | None = None,
    ) -> "ProjectIntelligence":
        """Rehydrate the normalized snapshot stored by the persistence layer."""
        known = {
            "name": summary.get("project") or summary.get("name") or Path(root_path).name,
            "root_path": root_path,
            "inspected_at": inspected_at or summary.get("inspected_at") or datetime.now(timezone.utc).isoformat(),
        }
        for field_name in (
            "files", "components", "languages", "frameworks", "runtimes", "package_managers",
            "dependencies", "commands", "ports", "services", "databases", "environment_variables",
            "evidence", "warnings",
        ):
            if field_name in summary:
                known[field_name] = summary[field_name]
        known["files"] = [
            item if isinstance(item, DiscoveredFile) else DiscoveredFile(**item)
            for item in known.get("files", [])
        ]
        known["evidence"] = [
            item if isinstance(item, Evidence) else Evidence(**item)
            for item in known.get("evidence", [])
        ]
        for field_name in ("docker", "kubernetes", "ci_cd", "documentation"):
            known[field_name] = summary.get(field_name) or {}
        return cls(**known)

    @property
    def evidence_counts(self) -> dict[str, int]:
        return {
            confidence: sum(item.confidence == confidence for item in self.evidence)
            for confidence in ("high", "medium", "low")
        }

    @property
    def has_docker(self) -> bool:
        return bool(self.docker.get("dockerfiles"))

    @property
    def has_docker_compose(self) -> bool:
        return bool(self.docker.get("compose_files"))

    @property
    def ci_cd_files(self) -> list[str]:
        return list(self.ci_cd.get("files", []))

    def summary(self) -> dict[str, Any]:
        return {
            "project": self.name,
            "root_path": self.root_path,
            "inspected_at": self.inspected_at,
            "files": [item.to_dict() for item in self.files],
            "components": self.components,
            "languages": self.languages,
            "frameworks": self.frameworks,
            "runtimes": self.runtimes,
            "package_managers": self.package_managers,
            "dependencies": self.dependencies,
            "commands": self.commands,
            "ports": self.ports,
            "services": self.services,
            "databases": self.databases,
            "environment_variables": self.environment_variables,
            "docker": self.docker,
            "kubernetes": self.kubernetes,
            "ci_cd": self.ci_cd,
            "documentation": self.documentation,
            "evidence": [item.to_dict() for item in self.evidence],
            "evidence_counts": self.evidence_counts,
            "warnings": self.warnings,
        }

    def to_dict(self) -> dict[str, Any]:
        data = self.summary()
        data.update(
            {
                "name": self.name,
                "path": self.root_path,
                "root_path": self.root_path,
                "inspected_at": self.inspected_at,
                "files": [item.to_dict() for item in self.files],
                "evidence": [item.to_dict() for item in self.evidence],
                "has_docker": self.has_docker,
                "has_docker_compose": self.has_docker_compose,
                "has_ci_cd": bool(self.ci_cd_files),
                "has_kubernetes": bool(self.kubernetes.get("files")),
                "ci_cd_files": self.ci_cd_files,
            }
        )
        return data
