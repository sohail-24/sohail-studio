"""Transactional persistence for normalized Project Intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    insert,
    inspect,
    select,
    update,
)

from sohail_agent_cli.inspection.models import DiscoveredFile, Evidence, ProjectIntelligence

from .database import Storage

metadata = MetaData()
projects = Table(
    "projects", metadata,
    Column("id", String(36), primary_key=True), Column("name", String(255), nullable=False),
    Column("root_path", String(2048), nullable=False), Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False), Column("current_inspection_id", String(36)),
)
inspection_runs = Table(
    "inspection_runs", metadata,
    Column("id", String(36), primary_key=True), Column("project_id", String(36), ForeignKey("projects.id"), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False), Column("completed_at", DateTime(timezone=True)),
    Column("status", String(32), nullable=False), Column("file_count", Integer, nullable=False),
    Column("evidence_count", Integer, nullable=False), Column("summary", JSON, nullable=False), Column("error", Text),
)
project_files = Table(
    "project_files", metadata,
    Column("run_id", String(36), ForeignKey("inspection_runs.id"), primary_key=True),
    Column("relative_path", String(2048), primary_key=True), Column("classification", String(64), nullable=False),
    Column("language", String(64)), Column("size", BigInteger, nullable=False), Column("sha256", String(64)),
    Column("ignored", Boolean, nullable=False), Column("error", Text),
)
project_components = Table(
    "project_components", metadata,
    Column("id", String(36), primary_key=True), Column("run_id", String(36), ForeignKey("inspection_runs.id"), nullable=False),
    Column("name", String(255), nullable=False), Column("path", String(2048), nullable=False), Column("kind", String(64)),
    Column("framework", String(128)), Column("package_manager", String(64)), Column("role", String(128)),
)
project_dependencies = Table(
    "project_dependencies", metadata,
    Column("id", String(36), primary_key=True), Column("run_id", String(36), ForeignKey("inspection_runs.id"), nullable=False),
    Column("name", String(255), nullable=False), Column("version", String(255)), Column("scope", String(64)),
    Column("source_file", String(2048), nullable=False), Column("confidence", String(16), nullable=False),
)
project_runtimes = Table(
    "project_runtimes", metadata,
    Column("id", String(36), primary_key=True), Column("run_id", String(36), ForeignKey("inspection_runs.id"), nullable=False),
    Column("runtime", String(128), nullable=False), Column("version", String(255)),
    Column("source_file", String(2048), nullable=False), Column("confidence", String(16), nullable=False),
)
project_commands = Table(
    "project_commands", metadata,
    Column("id", String(36), primary_key=True), Column("run_id", String(36), ForeignKey("inspection_runs.id"), nullable=False),
    Column("name", String(128), nullable=False), Column("command", Text, nullable=False),
    Column("source_file", String(2048), nullable=False), Column("confidence", String(16), nullable=False),
)
project_ports = Table(
    "project_ports", metadata,
    Column("id", String(36), primary_key=True), Column("run_id", String(36), ForeignKey("inspection_runs.id"), nullable=False),
    Column("name", String(128), nullable=False), Column("port", Integer, nullable=True),
    Column("source_file", String(2048), nullable=False), Column("confidence", String(16), nullable=False),
    Column("component", String(255)), Column("port_type", String(64)), Column("target_port", Integer),
    Column("service_name", String(255)), Column("conflict", Boolean, nullable=False, default=False),
)
project_evidence = Table(
    "project_evidence", metadata,
    Column("id", String(36), primary_key=True), Column("run_id", String(36), ForeignKey("inspection_runs.id"), nullable=False),
    Column("source_file", String(2048), nullable=False), Column("evidence_type", String(128), nullable=False),
    Column("key", String(255), nullable=False), Column("value", JSON, nullable=False), Column("confidence", String(16), nullable=False),
    Column("line_number", Integer), Column("extraction_method", String(128), nullable=False),
)


@dataclass(frozen=True)
class PersistedInspection:
    project_id: str
    run_id: str


class ProjectIntelligencePersistenceError(RuntimeError):
    """Raised without exposing database credentials or driver diagnostics."""


class ProjectIntelligenceRepository:
    """Persist one complete inspection atomically through the existing Storage."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "ProjectIntelligenceRepository":
        return cls(Storage.from_env(environ))

    @staticmethod
    def _canonical_root_path(root_path: str) -> str:
        return str(Path(root_path).expanduser().resolve(strict=False))

    def persist(self, intelligence: ProjectIntelligence) -> PersistedInspection:
        try:
            return self._persist(intelligence)
        except ProjectIntelligencePersistenceError:
            raise
        except Exception as exc:
            raise ProjectIntelligencePersistenceError(
                "Project Intelligence persistence failed; the inspection was not marked successful"
            ) from exc

    def load_latest(self, root_path: str) -> ProjectIntelligence | None:
        """Load the current successful snapshot for one local project."""
        try:
            canonical_root = self._canonical_root_path(root_path)
            with self.storage.engine.connect() as connection:
                project = connection.execute(
                    select(
                        projects.c.id, projects.c.root_path, projects.c.current_inspection_id,
                    ).where(projects.c.root_path == canonical_root)
                ).one_or_none()
                if project is None or project.current_inspection_id is None:
                    return None
                row = connection.execute(
                    select(inspection_runs.c.summary, inspection_runs.c.completed_at).where(
                        inspection_runs.c.id == project.current_inspection_id,
                        inspection_runs.c.project_id == project.id,
                        inspection_runs.c.status == "completed",
                    )
                ).one_or_none()
            if row is None:
                return None
            completed_at = row.completed_at.isoformat() if row.completed_at else None
            intelligence = ProjectIntelligence.from_summary(
                row.summary or {}, root_path=canonical_root, inspected_at=completed_at,
            )
            self._hydrate_normalized_facts(intelligence, str(project.current_inspection_id))
            return intelligence
        except Exception as exc:
            raise ProjectIntelligencePersistenceError(
                "Project Intelligence retrieval failed; no project context was returned"
            ) from exc

    def _hydrate_normalized_facts(self, intelligence: ProjectIntelligence, run_id: str) -> None:
        """Rebuild the factual collections from the persisted inspection run.

        The summary is useful for infrastructure snapshots, but normalized
        component/fact/evidence tables are the authoritative Docker handoff.
        This also supports snapshots written before the summary gained all
        Project Intelligence fields.
        """
        with self.storage.engine.connect() as connection:
            component_columns = {column["name"] for column in inspect(connection).get_columns("project_components")}
            component_select = [
                project_components.c.name, project_components.c.path, project_components.c.kind,
                project_components.c.framework, project_components.c.package_manager,
            ]
            if "role" in component_columns:
                component_select.append(project_components.c.role)
            component_rows = connection.execute(
                select(*component_select).where(project_components.c.run_id == run_id)
            ).mappings().all()
            if component_rows:
                summary_components = {
                    item.get("name"): item for item in intelligence.components
                }
                intelligence.components = [
                    {
                        **dict(row),
                        "role": (summary_components.get(row["name"]) or {}).get("role"),
                    }
                    for row in component_rows
                ]

            file_rows = connection.execute(
                select(project_files).where(project_files.c.run_id == run_id)
            ).mappings().all()
            if file_rows:
                intelligence.files = [
                    DiscoveredFile(
                        relative_path=row["relative_path"], classification=row["classification"],
                        language=row["language"], size=row["size"], sha256=row["sha256"],
                        ignored=row["ignored"], error=row["error"],
                    )
                    for row in file_rows
                ]

            dependency_rows = connection.execute(
                select(project_dependencies).where(project_dependencies.c.run_id == run_id)
            ).mappings().all()
            runtime_rows = connection.execute(
                select(project_runtimes).where(project_runtimes.c.run_id == run_id)
            ).mappings().all()
            command_rows = connection.execute(
                select(project_commands).where(project_commands.c.run_id == run_id)
            ).mappings().all()
            if dependency_rows:
                intelligence.dependencies = [dict(row) for row in dependency_rows]
            if runtime_rows:
                intelligence.runtimes = [dict(row) for row in runtime_rows]
            if command_rows:
                intelligence.commands = [dict(row) for row in command_rows]

            port_columns = {column["name"] for column in inspect(connection).get_columns("project_ports")}
            port_select = [
                project_ports.c.name, project_ports.c.port, project_ports.c.source_file,
                project_ports.c.confidence,
            ]
            for optional in ("component", "port_type", "target_port", "service_name", "conflict"):
                if optional in port_columns:
                    port_select.append(getattr(project_ports.c, optional))
            port_rows = connection.execute(
                select(*port_select).where(project_ports.c.run_id == run_id)
            ).mappings().all()
            if port_rows and "component" in port_columns:
                intelligence.ports = [dict(row) for row in port_rows]

            evidence_rows = connection.execute(
                select(project_evidence).where(project_evidence.c.run_id == run_id)
            ).mappings().all()
            if evidence_rows:
                intelligence.evidence = [
                    Evidence(
                        source_file=row["source_file"], evidence_type=row["evidence_type"],
                        key=row["key"], value=row["value"], confidence=row["confidence"],
                        line_number=row["line_number"], extraction_method=row["extraction_method"],
                    )
                    for row in evidence_rows
                ]
                environment = []
                for evidence in intelligence.evidence:
                    if evidence.evidence_type in {"environment_variable", "secret"}:
                        environment.append({
                            "name": evidence.key,
                            "key": evidence.key,
                            "value": evidence.value,
                            "sensitive": evidence.evidence_type == "secret",
                            "source_file": evidence.source_file,
                            "confidence": evidence.confidence,
                        })
                if environment:
                    intelligence.environment_variables = environment

    def _persist(self, intelligence: ProjectIntelligence) -> PersistedInspection:
        now = datetime.now(timezone.utc)
        canonical_root = self._canonical_root_path(intelligence.root_path)
        project_id = str(uuid4())
        run_id = str(uuid4())
        with self.storage.engine.begin() as connection:
            existing = connection.execute(
                select(projects.c.id).where(projects.c.root_path == canonical_root)
            ).scalar_one_or_none()
            if existing:
                project_id = str(existing)
                connection.execute(
                    update(projects).where(projects.c.id == project_id).values(
                        name=intelligence.name, updated_at=now,
                    )
                )
            else:
                connection.execute(
                    insert(projects).values(
                        id=project_id, name=intelligence.name, root_path=canonical_root,
                        created_at=now, updated_at=now,
                    )
                )

            connection.execute(insert(inspection_runs).values(
                id=run_id, project_id=project_id, started_at=now,
                completed_at=now, status="completed", file_count=len(intelligence.files),
                evidence_count=len(intelligence.evidence), summary=intelligence.summary(),
            ))
            if intelligence.files:
                connection.execute(insert(project_files), [
                    {"run_id": run_id, **file.to_dict()} for file in intelligence.files
                ])
            if intelligence.components:
                connection.execute(insert(project_components), [
                    {"id": str(uuid4()), "run_id": run_id, "name": item.get("name", "unknown"),
                     "path": item.get("path", "."), "kind": item.get("kind"),
                     "framework": item.get("framework"), "package_manager": item.get("package_manager"),
                     "role": item.get("role")}
                    for item in intelligence.components
                ])
            self._insert_facts(connection, run_id, intelligence)
            if intelligence.evidence:
                connection.execute(insert(project_evidence), [
                    {"id": str(uuid4()), "run_id": run_id, **evidence.to_dict()}
                    for evidence in intelligence.evidence
                ])
            connection.execute(
                update(projects).where(projects.c.id == project_id).values(current_inspection_id=run_id, updated_at=now)
            )
        return PersistedInspection(project_id=project_id, run_id=run_id)

    @staticmethod
    def _insert_facts(connection, run_id: str, intelligence: ProjectIntelligence) -> None:
        if intelligence.dependencies:
            connection.execute(insert(project_dependencies), [
                {"id": str(uuid4()), "run_id": run_id, "name": item.get("name", "unknown"),
                 "version": item.get("version"), "scope": item.get("scope"),
                 "source_file": item.get("source_file", ""), "confidence": item.get("confidence", "low")}
                for item in intelligence.dependencies
            ])
        if intelligence.runtimes:
            connection.execute(insert(project_runtimes), [
                {"id": str(uuid4()), "run_id": run_id, "runtime": item.get("runtime", "unknown"),
                 "version": item.get("version"), "source_file": item.get("source_file", ""),
                 "confidence": item.get("confidence", "low")}
                for item in intelligence.runtimes
            ])
        if intelligence.commands:
            connection.execute(insert(project_commands), [
                {"id": str(uuid4()), "run_id": run_id, "name": item.get("name", "command"),
                 "command": item.get("command", ""), "source_file": item.get("source_file", ""),
                 "confidence": item.get("confidence", "low")}
                for item in intelligence.commands
            ])
        if intelligence.ports:
            connection.execute(insert(project_ports), [
                {"id": str(uuid4()), "run_id": run_id, "name": item.get("name", "port"),
                 "port": item.get("port"),
                 "confidence": item.get("confidence", "low"), "source_file": item.get("source_file") or ((item.get("sources") or [{}])[0].get("source_file", "")),
                 "component": item.get("component"),
                 "port_type": item.get("port_type"), "target_port": item.get("target_port"),
                 "service_name": item.get("service_name"), "conflict": bool(item.get("conflict"))}
                for item in intelligence.ports
            ])
