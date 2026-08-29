"""Recursive, deterministic repository inspection.

The inspector extracts engineering facts and provenance. It never sends
repository data to an LLM and never retains source contents in its result.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import tomllib
import xml.etree.ElementTree as ET
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from .models import DiscoveredFile, Evidence, ProjectIntelligence
from .setup import ProjectSetupBuilder


class InspectionError(ValueError):
    """Raised when an inspection target cannot be inspected."""


EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".cache", "dist", "build", "coverage", "htmlcov",
    ".next", "target", ".tox", "*.egg-info", "vendor", "tmp", "temp",
}
SECRET_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development", ".env.test",
    "credentials", "credentials.json", "service-account.json", "id_rsa", "id_ed25519",
}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".pkcs12"}
TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".html", ".java", ".js", ".jsx",
    ".json", ".md", ".mjs", ".properties", ".py", ".rs", ".sh", ".sql", ".ts",
    ".tsx", ".toml", ".txt", ".xml", ".yaml", ".yml", ".lock", ".ini", ".cfg", ".prisma",
}
SOURCE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".go", ".java", ".js", ".jsx", ".mjs", ".php",
    ".py", ".rb", ".rs", ".ts", ".tsx", ".kt", ".swift",
}
CONFIG_NAMES = {
    "Makefile", "Pipfile", "Pipfile.lock", "poetry.lock", "pyproject.toml", "setup.cfg",
    "setup.py", "vite.config.js", "vite.config.ts", "angular.json", "next.config.js",
    "next.config.mjs", "next.config.ts", ".nvmrc", "application.yml", "application.yaml",
    "application.properties",
}
MANIFEST_NAMES = {
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile", "Pipfile.lock",
    "poetry.lock", "pom.xml", "build.gradle", "build.gradle.kts", "gradle.properties",
    "Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
}
PORT_RE = re.compile(
    r"\b(?:PORT|port|server\.port)\b\s*(?:=|:)?\s*"
    r"(?:process\.env\.\w+\s*\|\|\s*)?(\d{2,5})\b"
)
LISTEN_RE = re.compile(r"\b(?:listen|run|serve)\s*\([^\n]{0,100}?\b(\d{2,5})\b", re.IGNORECASE)
NODE_VERSION_RE = re.compile(r"(?:^|\s)(?:v)?(\d+(?:\.\d+){0,2})(?:\s|$)")


def _unique(values: Iterable[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value not in (None, "", "unknown")))


def _component_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    if path == root:
        return "root"
    return relative.parts[0]


def _language(path: Path) -> str | None:
    mapping = {
        ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".ts": "TypeScript",
        ".tsx": "TypeScript", ".py": "Python", ".go": "Go", ".rs": "Rust",
        ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP",
        ".html": "HTML", ".css": "CSS", ".sql": "SQL", ".sh": "Shell",
    }
    return mapping.get(path.suffix.lower())


def _is_secret(path: Path) -> bool:
    name = path.name.lower()
    return name in SECRET_NAMES or path.suffix.lower() in SECRET_SUFFIXES or (
        name.startswith(".env.") and name not in {".env.example", ".env.sample", ".env.template"}
    )


def classify_file(path: Path, content: str | None = None) -> str:
    """Return a deterministic, explainable file classification."""

    name = path.name
    lower = name.lower()
    parts = {part.lower() for part in path.parts}
    if _is_secret(path):
        return "secret_excluded"
    if name in {".env.example", ".env.sample", ".env.template"}:
        return "environment_example"
    if "node_modules" in parts or "__pycache__" in parts:
        return "ignored"
    if name == "Dockerfile" or name.startswith("Dockerfile."):
        return "docker"
    if lower in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
        return "docker_compose"
    if name == "Jenkinsfile" or ".github" in parts and "workflows" in parts:
        return "ci_cd"
    if lower in {".gitlab-ci.yml", "azure-pipelines.yml"} or ".circleci" in parts:
        return "ci_cd"
    if any(part in {"k8s", "kubernetes", "helm", "charts"} for part in parts):
        if content and ("apiVersion:" in content or "kind:" in content):
            return "kubernetes"
    if name in MANIFEST_NAMES:
        return "lockfile" if lower.endswith((".lock", "-lock.json", "-shrinkwrap.json")) else "dependency_manifest"
    if lower.endswith(".prisma"):
        return "data_schema"
    if name in {"README", "README.md", "README.rst", "CONTRIBUTING.md", "CHANGELOG.md"} or lower.endswith((".md", ".rst")):
        return "documentation"
    if name in CONFIG_NAMES or path.suffix.lower() in {".ini", ".cfg", ".conf", ".properties"}:
        return "configuration"
    if any(part in {"test", "tests", "__tests__", "spec", "specs"} for part in parts) or re.search(r"(?:test|spec)\.[^.]+$", lower):
        return "test"
    if path.suffix.lower() in SOURCE_SUFFIXES:
        return "source"
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".bin"}:
        return "binary"
    return "unknown"


class DeepInspector:
    """Inspect a repository recursively without external commands or Ollama."""

    def inspect(
        self,
        directory: Path,
        progress: Callable[[str], None] | None = None,
    ) -> ProjectIntelligence:
        root = Path(directory).expanduser().resolve()
        self._validate_root(root)
        self._emit_progress(progress, "Discovering repository structure")
        return self._inspect_paths(root, self._walk(root), progress=progress)

    def inspect_targets(self, directory: Path, targets: Iterable[Path]) -> ProjectIntelligence:
        """Inspect only validated existing files/directories under ``directory``."""

        root = Path(directory).expanduser().resolve()
        self._validate_root(root)
        selected = [Path(target).resolve() for target in targets]
        if not selected:
            raise InspectionError("No safe inspection targets were supplied")
        paths = (
            path for path in self._walk(root)
            if any(path == target or target in path.parents for target in selected)
        )
        return self._inspect_paths(root, paths)

    @staticmethod
    def _validate_root(root: Path) -> None:
        if not root.exists():
            raise InspectionError(f"Inspection path does not exist: {root}")
        if not root.is_dir():
            raise InspectionError(f"Inspection path is not a directory: {root}")
        if not os.access(root, os.R_OK):
            raise InspectionError(f"Inspection path is not readable: {root}")

    def _inspect_paths(
        self,
        root: Path,
        paths: Iterable[Path],
        *,
        progress: Callable[[str], None] | None = None,
    ) -> ProjectIntelligence:
        intelligence = ProjectIntelligence(name=root.name, root_path=str(root))
        text_cache: dict[str, str] = {}
        for path in paths:
            relative = path.relative_to(root).as_posix()
            if _is_secret(path):
                # Read only to extract variable names and safe configuration facts.
                # The raw content is deliberately never put in the cache or result.
                secret_content, secret_error = self._read_text(path)
                intelligence.files.append(
                    DiscoveredFile(
                        relative, "secret_excluded", None, self._size(path), None,
                        error=secret_error,
                    )
                )
                if secret_content is not None:
                    self._env_file(intelligence, relative, secret_content)
                continue
            content, error = self._read_text(path)
            if content is not None:
                text_cache[relative] = content
            classification = classify_file(path, content)
            digest = self._hash(path) if error is None and classification != "binary" else None
            intelligence.files.append(
                DiscoveredFile(relative, classification, _language(path), self._size(path), digest, error=error)
            )
            if error:
                intelligence.warnings.append(f"Could not read {relative}: {error}")

        self._emit_progress(progress, "Extracting repository evidence")
        self._extract(intelligence, root, text_cache)
        intelligence.languages = sorted(_unique(intelligence.languages))
        intelligence.frameworks = sorted(_unique(intelligence.frameworks))
        intelligence.package_managers = sorted(_unique(intelligence.package_managers))
        intelligence.databases = sorted(_unique(intelligence.databases))
        self._emit_progress(progress, "Recognizing verified engineering patterns")
        # Import lazily: the evidence package also depends on Deep Inspector
        # for bounded acquisition, so importing it at module load would cycle.
        from core.evidence.patterns import recognize_verified_patterns

        intelligence.verified_patterns = recognize_verified_patterns(intelligence)
        from .derivation import derive_deterministic_evidence

        derive_deterministic_evidence(intelligence)
        intelligence.project_setup = ProjectSetupBuilder.build(intelligence)
        return intelligence

    @staticmethod
    def _emit_progress(progress: Callable[[str], None] | None, message: str) -> None:
        if progress is not None:
            progress(message)

    def _walk(self, root: Path) -> Iterable[Path]:
        for current, directories, filenames in os.walk(root, followlinks=False):
            directories[:] = sorted(
                name for name in directories if name not in EXCLUDED_DIRS and not name.endswith(".egg-info")
            )
            for name in sorted(filenames):
                path = Path(current) / name
                if path.is_symlink() or not path.is_file():
                    continue
                yield path

    @staticmethod
    def _read_text(path: Path) -> tuple[str | None, str | None]:
        try:
            data = path.read_bytes()
        except (OSError, PermissionError) as exc:
            return None, str(exc)
        if b"\x00" in data[:8192]:
            return None, None
        if len(data) > 2_000_000:
            return None, "file exceeds 2MB analysis limit"
        try:
            return data.decode("utf-8"), None
        except UnicodeDecodeError:
            return None, None

    @staticmethod
    def _size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    @staticmethod
    def _hash(path: Path) -> str | None:
        try:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError:
            return None

    def _add(self, intelligence: ProjectIntelligence, **kwargs: Any) -> None:
        intelligence.evidence.append(Evidence(**kwargs))

    @staticmethod
    def _add_evidence_gap(
        intelligence: ProjectIntelligence,
        *,
        kind: str,
        decision: str,
        missing_evidence: str,
        search_scope: str,
        resolution: str,
        external_input_required: bool,
        confidence: str,
        component: str | None = None,
        name: str | None = None,
        source_file: str | None = None,
    ) -> None:
        """Persist a machine-readable blocker instead of a display-only warning."""
        gap = {
            "kind": kind,
            "status": "NEEDS_EVIDENCE",
            "decision": decision,
            "component": component,
            "name": name,
            "source_file": source_file,
            "missing_evidence": missing_evidence,
            "search_scope": search_scope,
            "repository_search_complete": True,
            "external_input_required": external_input_required,
            "resolution": resolution,
            "message": missing_evidence,
            "confidence": confidence,
        }
        identity = (
            gap["kind"], gap["decision"], gap["component"], gap["name"], gap["source_file"]
        )
        if not any(
            (
                item.get("kind"), item.get("decision"), item.get("component"),
                item.get("name"), item.get("source_file"),
            ) == identity
            for item in intelligence.evidence_gaps
        ):
            intelligence.evidence_gaps.append(gap)

    def _extract(self, intelligence: ProjectIntelligence, root: Path, files: dict[str, str]) -> None:
        package_metadata: dict[str, dict[str, Any]] = {}
        manifest_paths: list[str] = []
        has_manage_py = False
        for relative, content in files.items():
            path = root / relative
            name = path.name
            component = _component_name(root, path.parent)
            self._infrastructure_file(intelligence, relative, content)
            if name == "package.json":
                manifest_paths.append(relative)
                data = self._package_json(intelligence, relative, content, component)
                if data is not None:
                    package_metadata[relative] = data
            elif name in {"pyproject.toml", "requirements.txt", "Pipfile", "Pipfile.lock", "poetry.lock"}:
                manifest_paths.append(relative)
                self._python_manifest(intelligence, relative, content, component)
            elif name == "pom.xml":
                manifest_paths.append(relative)
                self._java_manifest(intelligence, relative, content, component)
            elif name in {"build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"}:
                manifest_paths.append(relative)
                self._gradle_manifest(intelligence, relative, content, component)
            elif name == "go.mod":
                manifest_paths.append(relative)
                self._go_manifest(intelligence, relative, content, component)
            elif name == "Cargo.toml":
                manifest_paths.append(relative)
                self._cargo_manifest(intelligence, relative, content, component)
            elif path.suffix.lower() == ".prisma":
                self._prisma_schema(intelligence, relative, content, component)
            elif name == "rust-toolchain.toml" or name == "rust-toolchain":
                self._rust_toolchain(intelligence, relative, content)
            elif name in {"Dockerfile"} or name.startswith("Dockerfile."):
                self._dockerfile(intelligence, relative, content, component)
            elif name.lower() in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
                self._compose(intelligence, relative, content)
            elif name == ".nvmrc":
                self._runtime(intelligence, relative, "Node.js", content.strip(), "high", "nvmrc")
            elif name == ".python-version":
                version = content.strip()
                if re.fullmatch(r"""\d+(?:\.\d+){0,2}""", version):
                    self._runtime(intelligence, relative, "Python", version, "high", "python-version")
            elif name == "Makefile":
                self._makefile(intelligence, relative, content)
            elif name in {"README.md", "README.rst", "README"}:
                self._readme(intelligence, relative, content)
            elif name == "nginx.conf" or name.endswith(".nginx.conf"):
                self._nginx_config(intelligence, relative, content, component)
            elif name == ".env.example" or name == ".env.sample" or name == ".env.template":
                self._env_example(intelligence, relative, content)
            elif _is_secret(path):
                self._env_file(intelligence, relative, content)
            elif name == "manage.py":
                has_manage_py = True
                self._add(
                    intelligence, source_file=relative, evidence_type="entrypoint",
                    key="manage_py", value="manage.py", confidence="high",
                )
            elif path.suffix.lower() == ".java":
                self._java_source(intelligence, relative, content)
            elif path.suffix.lower() == ".go":
                self._go_source(intelligence, relative, content)
            elif path.suffix.lower() == ".rs":
                self._rust_source(intelligence, relative, content)

            self._source_ports(intelligence, relative, content, component)
            self._kubernetes(intelligence, relative, content)
            self._ci_cd(intelligence, relative, content)
            self._language_and_frameworks(intelligence, relative, content)
            self._environment_access(intelligence, relative, content, component)
            if name in {
                "vite.config.js", "vite.config.ts", "angular.json",
                "next.config.js", "next.config.mjs", "next.config.ts",
            }:
                self._build_configuration(intelligence, relative, content, component)

        intelligence.components = self._detect_components(
            intelligence, root, files, package_metadata, manifest_paths, has_manage_py,
        )
        self._normalize_ports(intelligence)
        self._normalize_commands(intelligence)
        self._enrich_components(intelligence, files)
        self._finalize_data_services(intelligence, files)
        self._finalize_environment(intelligence)
        self._detect_relationships(intelligence, files)
        self._detect_contradictions(intelligence)
        self._finalize_infrastructure(intelligence)

    def _normalize_ports(self, intelligence: ProjectIntelligence) -> None:
        """Collapse repeated reports while retaining conflicts and provenance."""
        component_names = [str(item.get("name")) for item in intelligence.components]
        application_candidates = [item for item in intelligence.ports if item.get("port_type") == "application"]
        container_ports = {
            (str(item.get("component") or "root"), item.get("port"))
            for item in intelligence.ports
            if item.get("port_type") == "container"
        }
        correlated_container_ports = {
            (str(item.get("component") or "root"), item.get("target_port"))
            for item in intelligence.ports
            if item.get("port_type") == "service"
            and item.get("target_port") is not None
            and (str(item.get("component") or "root"), item.get("target_port")) in container_ports
        }
        normalized: dict[tuple[str, str, str | None], dict[str, Any]] = {}
        for raw in intelligence.ports:
            component = str(raw.get("component") or "root")
            if component not in component_names:
                source_file = str(raw.get("source_file") or "")
                source_matches = []
                for candidate in intelligence.components:
                    candidate_name = str(candidate.get("name") or "")
                    candidate_path = str(candidate.get("path") or ".").strip("./")
                    if not candidate_name:
                        continue
                    if not candidate_path or source_file == candidate_path or source_file.startswith(candidate_path + "/"):
                        source_matches.append(candidate_name)
                if len(source_matches) == 1:
                    component = source_matches[0]
            if component == "root":
                raw_port_type = str(raw.get("port_type") or "application")
                matching = [item for item in application_candidates if item.get("port") == raw.get("port") and item.get("component") not in {None, "root"}]
                if len(component_names) == 1:
                    component = component_names[0]
                elif matching:
                    component = str(matching[0].get("component"))
                elif raw_port_type != "documented" and "backend" in component_names:
                    component = "backend"
            port_type = str(raw.get("port_type") or "application")
            if port_type == "container" and (component, raw.get("port")) in correlated_container_ports:
                port_type = "application"
            service_name = raw.get("service_name")
            group_key = (component, port_type, str(service_name) if service_name else None)
            source = {
                "source_file": raw.get("source_file"), "confidence": raw.get("confidence"),
            }
            if raw.get("line_number") is not None:
                source["line_number"] = raw["line_number"]
            entry = normalized.setdefault(
                group_key,
                {
                    "name": raw.get("name", "port"), "component": component,
                    "port_type": port_type, "port": raw.get("port"),
                    "target_port": raw.get("target_port"), "host_port": raw.get("host_port", raw.get("port")) if port_type == "service" else None,
                    "service_name": service_name, "protocol": raw.get("protocol"),
                    "confidence": raw.get("confidence", "low"), "sources": [],
                    "candidates": [], "conflict": False,
                },
            )
            if source not in entry["sources"]:
                entry["sources"].append(source)
            candidate = {
                "port": raw.get("port"), "target_port": raw.get("target_port"), "host_port": raw.get("host_port", raw.get("port")),
                "source_file": raw.get("source_file"), "confidence": raw.get("confidence", "low"),
            }
            if candidate not in entry["candidates"]:
                entry["candidates"].append(candidate)
            if entry["port"] != raw.get("port") or entry["target_port"] != raw.get("target_port"):
                entry["conflict"] = True
                entry["port"] = None
                entry["target_port"] = None
            if entry["confidence"] != "high" and raw.get("confidence") == "high":
                entry["confidence"] = "high"
        documented = [
            item for item in normalized.values() if item["port_type"] == "documented" and item["port"] is not None
        ]
        for entry in normalized.values():
            if entry["port_type"] != "application" or entry["port"] is None:
                continue
            conflicts = [
                item for item in documented
                if item["component"] == entry["component"] and item["port"] != entry["port"]
            ]
            for conflict in conflicts:
                entry["conflict"] = True
                entry["port"] = None
                entry["target_port"] = None
                for source in conflict["sources"]:
                    if source not in entry["sources"]:
                        entry["sources"].append(source)
                for candidate in conflict["candidates"]:
                    if candidate not in entry["candidates"]:
                        entry["candidates"].append(candidate)
        intelligence.ports = list(normalized.values())

    def _normalize_commands(self, intelligence: ProjectIntelligence) -> None:
        """Annotate commands with purpose without treating every script as production."""
        purposes = {
            "dev": "development", "develop": "development", "serve": "development",
            "build": "build", "test": "test", "lint": "lint", "check": "test",
            "preview": "preview", "start": "production_runtime", "prod": "production_runtime",
        }
        for item in intelligence.commands:
            name = str(item.get("name") or "").lower()
            item.setdefault("purpose", purposes.get(name, "unknown"))
            item.setdefault("source_type", "EXPLICIT_EVIDENCE")
            item.setdefault("model_inference", False)

    def _enrich_components(self, intelligence: ProjectIntelligence, files: dict[str, str]) -> None:
        """Attach scoped facts so global technology lists do not own component facts."""
        for component in intelligence.components:
            name = str(component.get("name") or "")
            path = str(component.get("path") or ".").strip("./")

            def belongs(source: str) -> bool:
                return not path or source == path or source.startswith(path + "/")

            component_commands = [dict(item) for item in intelligence.commands if item.get("component") == name or belongs(str(item.get("source_file") or ""))]
            component["commands"] = component_commands
            component["development_commands"] = [item for item in component_commands if item.get("purpose") == "development"]
            component["build_commands"] = [item for item in component_commands if item.get("purpose") == "build"]
            component["test_commands"] = [item for item in component_commands if item.get("purpose") in {"test", "lint"}]
            component["production_commands"] = [item for item in component_commands if item.get("purpose") == "production_runtime"]
            component["entrypoints"] = [dict(item) for item in intelligence.entrypoints if belongs(str(item.get("source_file") or ""))]
            component["dependencies"] = [dict(item) for item in intelligence.dependencies if belongs(str(item.get("source_file") or ""))]
            component["environment"] = [dict(item) for item in intelligence.environment_variables if belongs(str(item.get("source_file") or "")) or "/" not in str(item.get("source_file") or "")]
            component_build_metadata = [
                dict(item) for item in intelligence.build_metadata
                if item.get("component") == name or belongs(str(item.get("source_file") or ""))
            ]
            component["build_metadata"] = component_build_metadata
            outputs = sorted({
                str(output)
                for item in component_build_metadata
                for output in item.get("outputs", [])
                if output
            })
            component["build_outputs"] = outputs
            component["artifacts"] = [
                {
                    "kind": "build_output",
                    "path": output,
                    "source_file": next(
                        (
                            str(item.get("source_file"))
                            for item in component_build_metadata
                            if output in item.get("outputs", [])
                        ),
                        None,
                    ),
                    "confidence": "high",
                    "source_type": "EXPLICIT_EVIDENCE",
                    "model_inference": False,
                }
                for output in outputs
            ]
            component["boundary_evidence"] = [
                {"source_file": source, "reason": "manifest or source file is inside this component boundary", "confidence": "high"}
                for source in sorted(files) if belongs(source)
            ][:20]

    def _enrich_data_services(self, intelligence: ProjectIntelligence, files: dict[str, str]) -> None:
        for service in intelligence.data_services:
            component = str(service.get("component") or "")
            component_path = component.strip("./")
            names = []
            source_files = []
            for variable in intelligence.environment_variables:
                variable_component = str(variable.get("component") or "")
                name = str(variable.get("name") or variable.get("key") or "")
                if (
                    variable_component in {component, "root", ""}
                    and self._data_service_environment_match(str(service.get("service_type") or ""), name)
                ):
                    names.append(name)
                    source_files.extend(str(path) for path in variable.get("source_files", []) if path)
                    if variable.get("source_file"):
                        source_files.append(str(variable["source_file"]))
            service["configuration_variables"] = sorted(set(service.get("configuration_variables", []) + names))
            service["connection_source_files"] = sorted(set(service.get("connection_source_files", []) + source_files))
            locations = [path for path in files if component_path and (path == component_path or path.startswith(component_path + "/"))]
            service["migration_locations"] = [path for path in locations if re.search(r"(?:migration|migrations)", path, re.IGNORECASE)]
            service["seed_locations"] = [path for path in locations if re.search(r"(?:seed|seeds)", path, re.IGNORECASE)]
            if names:
                service["connection_sources"] = sorted(set(
                    service.get("connection_sources", [])
                    + [f"environment variable {name}" for name in names]
                ))

    @staticmethod
    def _data_service_environment_match(service_type: str, variable_name: str) -> bool:
        """Match data-service-shaped variables, never generic PORT values."""
        name = variable_name.upper()
        tokens = {
            "PostgreSQL": ("DATABASE", "POSTGRES", "PG_"),
            "MySQL": ("DATABASE", "MYSQL"),
            "MariaDB": ("DATABASE", "MARIADB"),
            "SQL Server": ("DATABASE", "SQLSERVER", "MSSQL"),
            "CockroachDB": ("DATABASE", "COCKROACH"),
            "SQLite": ("DATABASE", "SQLITE"),
            "MongoDB": ("MONGO", "DATABASE"),
            "Redis": ("REDIS",),
            "Supabase": ("SUPABASE",),
            "Firebase": ("FIREBASE",),
            "Elasticsearch": ("ELASTIC", "ELASTICSEARCH"),
            "DynamoDB": ("DYNAMO",),
            "Prisma": ("DATABASE",),
        }.get(service_type, ())
        return any(token in name for token in tokens)

    def _finalize_data_services(self, intelligence: ProjectIntelligence, files: dict[str, str]) -> None:
        """Promote candidates only when independent repository evidence corroborates them."""
        self._enrich_data_services(intelligence, files)
        for service in intelligence.data_services:
            if service.get("status") == "VERIFIED":
                service["evidence_basis"] = sorted(set(service.get("evidence_basis", []) + ["explicit repository configuration or schema evidence"]))
                continue
            corroboration = []
            if service.get("configuration_variables"):
                corroboration.append("configuration variable reference")
            if service.get("connection_source_files"):
                corroboration.append("configuration source location")
            if service.get("schema_or_model_locations"):
                corroboration.append("schema or model location")
            if service.get("migration_locations"):
                corroboration.append("migration location")
            if service.get("deployment_configuration"):
                corroboration.append("deployment configuration")
            if corroboration:
                service["status"] = "VERIFIED"
                service["confidence"] = "high" if len(corroboration) > 1 else service.get("confidence", "medium")
                service["evidence_basis"] = sorted(set(service.get("evidence_basis", []) + corroboration))
                continue
            service["status"] = "NEEDS_EVIDENCE"
            service["confidence"] = "low"
            service["evidence_basis"] = sorted(set(service.get("evidence_basis", []) + ["client or library dependency only"]))
            self._add_evidence_gap(
                intelligence,
                kind="data_service",
                decision="data_service_selection",
                component=service.get("component"),
                name=service.get("service_type"),
                source_file=service.get("source_file"),
                missing_evidence="A client or library was found, but no connection, schema, migration, or deployment evidence verifies the service.",
                search_scope="dependency manifests, source/configuration references, schemas, migrations, seeds, and deployment manifests",
                resolution="repository_evidence_or_user_confirmation",
                external_input_required=False,
                confidence="medium",
            )

    def _add_data_service(
        self, intelligence: ProjectIntelligence, *, service_type: str, role: str,
        client_or_library: str | None, component: str | None, source_file: str,
        confidence: str, configuration_variables: list[str] | None = None,
        connection_source: str | None = None, schema_location: str | None = None,
        deployment_configuration: str | None = None,
        status: str = "NEEDS_EVIDENCE",
        evidence_basis: str = "client or library dependency only",
    ) -> None:
        existing = next(
            (item for item in intelligence.data_services
             if item.get("service_type") == service_type
             and item.get("role") == role and item.get("component") == component),
            None,
        )
        if existing is not None:
            clients = {value.strip() for value in str(existing.get("client_or_library") or "").split(",") if value.strip()}
            if client_or_library:
                clients.add(client_or_library)
            existing["client_or_library"] = ", ".join(sorted(clients)) or None
            existing["configuration_variables"] = sorted(set(existing.get("configuration_variables", []) + (configuration_variables or [])))
            existing["source_files"] = sorted(set(existing.get("source_files", []) + [source_file]))
            existing["evidence_basis"] = sorted(set(existing.get("evidence_basis", []) + [evidence_basis]))
            if status == "VERIFIED":
                existing["status"] = "VERIFIED"
                existing["confidence"] = confidence
            if schema_location and schema_location not in existing["schema_or_model_locations"]:
                existing["schema_or_model_locations"].append(schema_location)
            if connection_source and connection_source not in existing["connection_sources"]:
                existing["connection_sources"].append(connection_source)
            if deployment_configuration:
                existing["deployment_configuration"] = deployment_configuration
            return
        item = {
            "service_type": service_type, "role": role, "client_or_library": client_or_library,
            "component": component, "configuration_variables": sorted(set(configuration_variables or [])),
            "connection_sources": [connection_source] if connection_source else [],
            "schema_or_model_locations": [schema_location] if schema_location else [],
            "migration_locations": [], "seed_locations": [],
            "deployment_configuration": deployment_configuration,
            "evidence": [{"source_file": source_file, "evidence_type": "data_service", "confidence": confidence, "basis": evidence_basis}],
            "confidence": confidence, "status": status,
            "evidence_basis": [evidence_basis],
            "source_file": source_file,
            "source_files": [source_file],
        }
        intelligence.data_services.append(item)
        if service_type not in intelligence.databases:
            # Legacy projection retained for downstream consumers; discovery is
            # driven by the generic data_services records above.
            intelligence.databases.append(service_type)
        self._add(intelligence, source_file=source_file, evidence_type="data_service", key=service_type, value=item, confidence=confidence)

    @staticmethod
    def _data_service_marker(name: str) -> tuple[str, str] | None:
        normalized = name.lower().replace("_", "-")
        markers = (
            (("mongoose", "mongodb"), ("MongoDB", "document database")),
            (("pg", "postgres", "postgresql", "psycopg"), ("PostgreSQL", "database")),
            (("mysql", "mysql2"), ("MySQL", "database")),
            (("mariadb",), ("MariaDB", "database")),
            (("sqlite", "sqlite3"), ("SQLite", "database")),
            (("redis", "ioredis"), ("Redis", "cache")),
            (("supabase", "@supabase/supabase-js"), ("Supabase", "managed data service")),
            (("firebase",), ("Firebase", "managed data service")),
            (("elasticsearch",), ("Elasticsearch", "search data service")),
            (("dynamodb", "@aws-sdk/client-dynamodb"), ("DynamoDB", "database")),
            (("prisma", "@prisma/client"), ("Prisma", "data access layer")),
        )
        for names, result in markers:
            if normalized in names or any(value in normalized for value in names):
                return result
        return None

    def _package_json(self, intelligence: ProjectIntelligence, source: str, content: str, component: str) -> dict[str, Any] | None:
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            intelligence.warnings.append(f"Invalid JSON manifest: {source}")
            return None
        manager = self._package_manager_for_manifest(source, intelligence)
        if manager:
            intelligence.package_managers.append(manager)
            self._add(intelligence, source_file=source, evidence_type="package_manager", key="package_manager", value=manager, confidence="high")
        for scope in ("dependencies", "devDependencies"):
            for name, version in (data.get(scope) or {}).items():
                dependency = {"name": str(name), "version": str(version), "scope": scope, "source_file": source, "confidence": "high"}
                intelligence.dependencies.append(dependency)
                self._add(intelligence, source_file=source, evidence_type="dependency", key=str(name), value=str(version), confidence="high")
                marker = self._data_service_marker(str(name))
                if marker:
                    service_type, role = marker
                    self._add_data_service(
                        intelligence, service_type=service_type, role=role,
                        client_or_library=str(name), component=component,
                        source_file=source, confidence="high",
                    )
        for script, command in (data.get("scripts") or {}).items():
            command_text = str(command)
            item = {"name": str(script), "command": command_text, "source_file": source, "confidence": "high", "component": component}
            intelligence.commands.append(item)
            self._add(intelligence, source_file=source, evidence_type="command", key=f"{component}.{script}_command", value=command_text, confidence="high")
            if str(script).lower() == "build":
                outputs = self._explicit_build_outputs(command_text)
                metadata = {
                    "source_file": source,
                    "component": component,
                    "build_system": manager,
                    "command": command_text,
                    "inputs": [source],
                    "outputs": outputs,
                    "output_basis": "explicit command argument" if outputs else "not specified",
                }
                intelligence.build_metadata.append(metadata)
                self._add(intelligence, source_file=source, evidence_type="build_configuration", key=f"{component}.build", value=metadata, confidence="high")
            if str(script).lower() in {"start", "prod"}:
                self._entrypoint_from_command(intelligence, source, command_text, component)
        workspaces = data.get("workspaces")
        if workspaces:
            patterns = workspaces if isinstance(workspaces, list) else (workspaces.get("packages") or []) if isinstance(workspaces, dict) else []
            metadata = {
                "source_file": source,
                "build_system": manager,
                "workspace_root": source,
                "workspace_patterns": [str(item) for item in patterns],
            }
            intelligence.build_metadata.append(metadata)
            self._add(intelligence, source_file=source, evidence_type="workspace_configuration", key="workspaces", value=metadata, confidence="high")
        engines = data.get("engines") or {}
        if engines.get("node"):
            self._runtime(intelligence, source, "Node.js", str(engines["node"]), "high", "package.json engines")
        return data

    @staticmethod
    def _explicit_build_outputs(command: str) -> list[str]:
        outputs = re.findall(
            r"(?:--outDir|--output-path|--output-paths?|--dist-dir|--distDir|-d)\s*[= ]\s*['\"]?([^\s'\"]+)",
            command,
            re.IGNORECASE,
        )
        return list(dict.fromkeys(outputs))

    def _build_configuration(
        self, intelligence: ProjectIntelligence, source: str, content: str, component: str,
    ) -> None:
        """Record only explicitly configured build output directories."""
        path = Path(source).name.lower()
        patterns = {
            "vite.config.js": r"\boutDir\s*:\s*['\"]([^'\"]+)['\"]",
            "vite.config.ts": r"\boutDir\s*:\s*['\"]([^'\"]+)['\"]",
            "angular.json": r"['\"]outputPath['\"]\s*:\s*['\"]([^'\"]+)['\"]",
            "next.config.js": r"\bdistDir\s*:\s*['\"]([^'\"]+)['\"]",
            "next.config.mjs": r"\bdistDir\s*:\s*['\"]([^'\"]+)['\"]",
            "next.config.ts": r"\bdistDir\s*:\s*['\"]([^'\"]+)['\"]",
        }
        match = re.search(patterns.get(path, r"$^"), content)
        if not match:
            return
        metadata = {
            "source_file": source,
            "component": component,
            "build_system": "framework_configuration",
            "outputs": [match.group(1)],
            "output_basis": "explicit framework configuration",
        }
        intelligence.build_metadata.append(metadata)
        self._add(intelligence, source_file=source, evidence_type="build_configuration", key=f"{component}.output", value=metadata, confidence="high")

    def _entrypoint_from_command(
        self, intelligence: ProjectIntelligence, source: str, command: str, component: str,
    ) -> None:
        match = re.search(
            r"(?:^|\s)(?:node|bun|deno)\s+([^\s;&|]+)|(?:^|\s)(?:uvicorn|gunicorn)\s+([^\s;&|]+)|(?:^|\s)python(?:3)?\s+([^\s;&|]+)|(?:^|\s)java\s+-jar\s+([^\s;&|]+)",
            command,
        )
        value = next((item for item in match.groups() if item), None) if match else None
        if not value:
            return
        entrypoint = {
            "kind": "command_entrypoint",
            "value": value,
            "command": command,
            "component": component,
            "source_file": source,
            "confidence": "high",
            "source_type": "EXPLICIT_EVIDENCE",
            "model_inference": False,
        }
        if entrypoint not in intelligence.entrypoints:
            intelligence.entrypoints.append(entrypoint)
        self._add(intelligence, source_file=source, evidence_type="entrypoint", key=f"{component}.command", value=value, confidence="high")

    @staticmethod
    def _package_framework(data: dict[str, Any]) -> str | None:
        names = {str(name).lower() for scope in ("dependencies", "devDependencies") for name in (data.get(scope) or {})}
        for framework, markers in (
            ("Next.js", {"next"}), ("Angular", {"@angular/core"}),
            ("React", {"react", "react-dom"}), ("Vite", {"vite"}),
            ("Express", {"express"}), ("NestJS", {"@nestjs/core"}),
        ):
            if names.intersection(markers):
                return framework
        return None

    @staticmethod
    def _relative_files(root: Path, files: dict[str, str], directory: Path) -> list[str]:
        result = []
        for relative in files:
            path = root / relative
            try:
                path.relative_to(directory)
            except ValueError:
                continue
            result.append(relative)
        return result

    def _detect_components(
        self,
        intelligence: ProjectIntelligence,
        root: Path,
        files: dict[str, str],
        package_metadata: dict[str, dict[str, Any]],
        manifest_paths: list[str],
        has_manage_py: bool,
    ) -> list[dict[str, Any]]:
        """Return only independently runnable or deployable units.

        A manifest is evidence about a directory, not proof that the directory
        is an application. Workspace roots and metadata-only packages are kept
        in evidence but are intentionally omitted from deployable components.
        """
        components: list[dict[str, Any]] = []
        seen: set[str] = set()
        source_suffixes = SOURCE_SUFFIXES | {".html"}

        def runtimes_for_component(
            path: str, kind: str, framework: str | None, manager: str | None,
        ) -> list[dict[str, Any]]:
            component_path = path.strip("./")
            node_component = manager in {"npm", "yarn", "pnpm"} or kind == "frontend" or framework in {
                "React", "Vite", "Next.js", "Angular", "Express", "NestJS",
            }
            result = []
            for runtime in intelligence.runtimes:
                source = str(runtime.get("source_file") or "")
                local = not component_path or source == component_path or source.startswith(component_path + "/")
                repository_level = node_component and "/" not in source
                if local or repository_level:
                    result.append(dict(runtime))
            return result

        def add(name: str, path: str, kind: str, role: str, framework: str | None, manager: str | None, evidence: list[str]) -> None:
            if name in seen:
                return
            seen.add(name)
            components.append({
                "name": name, "path": path or ".", "kind": kind, "role": role,
                "framework": framework, "package_manager": manager,
                "runtimes": runtimes_for_component(path, kind, framework, manager),
                "evidence": sorted(set(evidence)),
            })

        for source, data in sorted(package_metadata.items()):
            manifest_dir = (root / source).parent
            relative_dir = manifest_dir.relative_to(root).as_posix() if manifest_dir != root else "."
            child_files = self._relative_files(root, files, manifest_dir)
            child_contents = [files[item] for item in child_files]
            local_parts = {
                item: (root / item).relative_to(manifest_dir).parts for item in child_files
            }
            scripts = {str(key): str(value) for key, value in (data.get("scripts") or {}).items()}
            framework = self._package_framework(data)
            manager = self._package_manager_for_manifest(source, intelligence)
            has_source = any(
                Path(item).suffix.lower() in source_suffixes
                and (relative_dir != "." or len(local_parts[item]) == 1 or local_parts[item][:1] == ("src",))
                for item in child_files
            )
            has_src_dir = any(local_parts[item][:1] == ("src",) for item in child_files if item != source)
            has_server_signal = any(
                re.search(r"\b(?:app|server|http|fastify|express)\s*\.?(?:listen|run)\s*\(", content, re.IGNORECASE)
                or re.search(r"\b(?:listen|uvicorn|gunicorn)\b", content, re.IGNORECASE)
                for content in child_contents
            )
            workspace = bool(data.get("workspaces")) or any(
                "--prefix" in command or re.search(r"\b(?:frontend|backend|worker)/", command)
                for command in scripts.values()
            )
            runnable_script = any(key in scripts for key in ("start", "dev", "serve", "run"))
            frontend_signal = framework in {"React", "Vite", "Next.js", "Angular"} and (has_src_dir or has_source)
            static_frontend_signal = "build" in scripts and any(
                Path(item).name.lower() == "index.html" for item in child_files
            )
            backend_signal = framework in {"Express", "NestJS"} or has_server_signal
            deployable = has_source and (
                runnable_script or framework is not None or backend_signal or static_frontend_signal
            )
            if relative_dir == "." and workspace and not has_server_signal and not has_src_dir:
                deployable = False
            if not deployable:
                self._add(
                    intelligence, source_file=source, evidence_type="component_classification",
                    key="package_role", value="workspace_or_metadata", confidence="high",
                )
                continue
            if frontend_signal or static_frontend_signal:
                kind, role = "frontend", "frontend/application"
            elif relative_dir == ".":
                kind, role = "application", "application"
            elif backend_signal:
                kind, role = "backend", "backend/application"
            else:
                kind, role = "service", "service/application"
            name = "application" if relative_dir == "." else Path(relative_dir).name
            add(name, relative_dir, kind, role, framework, manager, [source, *child_files])

        python_files = {relative for relative in files if Path(relative).suffix.lower() == ".py"}
        python_manifest = any(Path(item).name in {"pyproject.toml", "requirements.txt", "Pipfile", "poetry.lock"} for item in manifest_paths)
        python_framework = next((name for name in ("Django", "FastAPI", "Flask") if name in intelligence.frameworks), None)
        if (has_manage_py or (python_manifest and python_files)) and "backend" not in seen:
            evidence = [item for item in manifest_paths if Path(item).suffix.lower() in {".toml", ".txt", ".lock"}]
            if has_manage_py:
                evidence.append("manage.py")
            add(
                "backend", ".", "backend", "backend/application", python_framework,
                next((m for m in intelligence.package_managers if m in {"pip", "poetry", "pipenv"}), None),
                evidence,
            )

        java_manifests = [
            item for item in manifest_paths
            if Path(item).name in {"pom.xml", "build.gradle", "build.gradle.kts"}
        ]
        java_manifest = next(iter(java_manifests), None)
        if (
            java_manifest
            and any(Path(item).as_posix().startswith("src/main/") for item in files)
            and "application" not in seen
        ):
            manager = "gradle" if Path(java_manifest).name.startswith("build.gradle") else "maven"
            add(
                "application", ".", "backend", "backend/application",
                "Spring Boot" if "Spring Boot" in intelligence.frameworks else None,
                manager, [java_manifest],
            )

        go_manifest = next((item for item in manifest_paths if Path(item).name == "go.mod"), None)
        if go_manifest and any(Path(item).suffix.lower() == ".go" for item in files) and "application" not in seen:
            add("application", ".", "backend", "backend/application", None, "go", [go_manifest])

        cargo_manifest = next((item for item in manifest_paths if Path(item).name == "Cargo.toml"), None)
        if cargo_manifest and any(Path(item).suffix.lower() == ".rs" for item in files) and "application" not in seen:
            add("application", ".", "backend", "backend/application", None, "cargo", [cargo_manifest])

        nginx_files = [
            item for item in files
            if Path(item).name == "nginx.conf" or Path(item).name.endswith(".nginx.conf")
        ]
        # A configuration file can support another component's static-serving
        # strategy.  An independent Nginx component requires explicit service
        # evidence in the persisted repository facts; nginx.conf alone is not
        # deployability evidence.
        explicit_nginx_service = any(
            str(item.get("name") or "").lower() == "nginx"
            or str(item.get("component") or "").lower() == "nginx"
            for item in intelligence.services
        )
        if nginx_files and explicit_nginx_service and "nginx" not in seen:
            add("nginx", ".", "server", "server/nginx", "Nginx", None, nginx_files)
        return components

    def _python_manifest(self, intelligence: ProjectIntelligence, source: str, content: str, component: str) -> None:
        path = Path(source)
        if path.name == "pyproject.toml":
            try:
                data = tomllib.loads(content)
            except tomllib.TOMLDecodeError:
                intelligence.warnings.append(f"Invalid TOML manifest: {source}")
                return
            project = data.get("project", {})
            if project.get("requires-python"):
                self._runtime(intelligence, source, "Python", str(project["requires-python"]), "high", "pyproject project.requires-python")
            deps = [*project.get("dependencies", []), *data.get("tool", {}).get("poetry", {}).get("dependencies", {}).keys()]
            for dependency in deps:
                value = str(dependency)
                name = value.split()[0].split(">=")[0]
                intelligence.dependencies.append({"name": name, "version": value, "scope": "runtime", "source_file": source, "confidence": "high"})
                self._add(intelligence, source_file=source, evidence_type="dependency", key=name, value=value, confidence="high")
                marker = self._data_service_marker(name)
                if marker:
                    service_type, role = marker
                    self._add_data_service(
                        intelligence, service_type=service_type, role=role,
                        client_or_library=name, component=component,
                        source_file=source, confidence="high",
                    )
            for name, command in (project.get("scripts") or {}).items():
                intelligence.commands.append({"name": str(name), "command": str(command), "source_file": source, "confidence": "high", "component": component})
                self._add(intelligence, source_file=source, evidence_type="command", key=f"{component}.{name}_command", value=str(command), confidence="high")
        elif path.name == "requirements.txt" or path.name.startswith("requirements"):
            intelligence.package_managers.append("pip")
            self._add(intelligence, source_file=source, evidence_type="package_manager", key="package_manager", value="pip", confidence="high")
            for line in content.splitlines():
                value = line.strip()
                if not value or value.startswith(("#", "-")):
                    continue
                name = re.split(r"[<>=!~\[]", value, maxsplit=1)[0].strip()
                intelligence.dependencies.append({"name": name, "version": value, "scope": "runtime", "source_file": source, "confidence": "high"})
                self._add(intelligence, source_file=source, evidence_type="dependency", key=name, value=value, confidence="high")
                marker = self._data_service_marker(name)
                if marker:
                    service_type, role = marker
                    self._add_data_service(
                        intelligence, service_type=service_type, role=role,
                        client_or_library=name, component=component,
                        source_file=source, confidence="high",
                    )
        elif path.name == "Pipfile" or path.name in {"poetry.lock", "Pipfile.lock"}:
            manager = "poetry" if path.name == "poetry.lock" else "pipenv"
            intelligence.package_managers.append(manager)
            self._add(intelligence, source_file=source, evidence_type="package_manager", key="package_manager", value=manager, confidence="high")

    def _gradle_manifest(self, intelligence: ProjectIntelligence, source: str, content: str, component: str) -> None:
        """Extract only declarative Gradle facts; build output is derived later."""
        name = Path(source).name
        if name.startswith("settings.gradle"):
            includes = re.findall(r"""(?:include|includeProjects)\s*\(?\s*['"]([^'"]+)['"]""", content)
            root_name = re.search(r"""rootProject\.name\s*=\s*['"]([^'"]+)['"]""", content)
            intelligence.build_metadata.append({
                "source_file": source,
                "build_system": "gradle",
                "settings": True,
                "root_project_name": root_name.group(1).strip() if root_name else None,
                "modules": includes,
            })
            self._add(intelligence, source_file=source, evidence_type="build_configuration", key="gradle.settings", value={"modules": includes}, confidence="high")
            return
        intelligence.package_managers.append("gradle")
        plugin_ids = re.findall(r"""(?:id\s*\(?\s*['"]([^'"]+)['"]|apply\s+plugin:\s*['"]([^'"]+)['"])""", content)
        plugins = [next((value for value in match if value), "") for match in plugin_ids]
        dependencies = re.findall(r"""['"]([^'"]*spring[^'"]*)['"]""", content, re.IGNORECASE)
        java_version = re.search(r"""(?:JavaLanguageVersion\.of|sourceCompatibility\s*=|targetCompatibility\s*=)\s*['"]?(?:JavaVersion\.VERSION_)?(\d{1,2})['"]?""", content)
        group = re.search(r"""(?:^|\n)\s*group\s*=\s*['"]([^'"]+)['"]""", content)
        version = re.search(r"""(?:^|\n)\s*version\s*=\s*['"]([^'"]+)['"]""", content)
        archive = re.search(r"""archiveFileName\s*=\s*['"]([^'"]+)['"]""", content)
        archive_base = re.search(r"""archiveBaseName\s*=\s*['"]([^'"]+)['"]""", content)
        classifier = re.search(r"""archiveClassifier\s*=\s*['"]([^'"]*)['"]""", content)
        main_class = re.search(r"""(?:mainClass\.set|mainClass\s*=)\s*['"]([^'"]+)['"]""", content)
        metadata = {
            "source_file": source,
            "build_system": "gradle",
            "group_id": group.group(1).strip() if group else None,
            "version": version.group(1).strip() if version else None,
            "plugins": [{"id": item} for item in plugins if item],
            "spring_boot_plugin": "org.springframework.boot" in plugins,
            "spring_dependencies": dependencies,
            "java_version": java_version.group(1) if java_version else None,
            "archive_file_name": archive.group(1).strip() if archive else None,
            "archive_base_name": archive_base.group(1).strip() if archive_base else None,
            "archive_classifier": classifier.group(1).strip() if classifier else None,
            "main_class": main_class.group(1).strip() if main_class else None,
        }
        intelligence.build_metadata.append(metadata)
        self._add(intelligence, source_file=source, evidence_type="build_configuration", key="gradle", value=metadata, confidence="high")
        if java_version:
            self._runtime(intelligence, source, "Java", java_version.group(1), "high", "Gradle Java version")
        if "org.springframework.boot" in plugins or dependencies:
            intelligence.frameworks.append("Spring Boot")

    def _go_manifest(self, intelligence: ProjectIntelligence, source: str, content: str, component: str) -> None:
        intelligence.package_managers.append("go")
        module = re.search(r"""^module\s+([^\s]+)""", content, re.MULTILINE)
        version = re.search(r"""^go\s+(\d+(?:\.\d+)?)""", content, re.MULTILINE)
        metadata = {
            "source_file": source,
            "build_system": "go",
            "module": module.group(1).strip() if module else None,
            "go_version": version.group(1) if version else None,
        }
        intelligence.build_metadata.append(metadata)
        self._add(intelligence, source_file=source, evidence_type="build_configuration", key="go.mod", value=metadata, confidence="high")
        if version:
            self._runtime(intelligence, source, "Go", version.group(1), "high", "go.mod go directive")

    def _cargo_manifest(self, intelligence: ProjectIntelligence, source: str, content: str, component: str) -> None:
        intelligence.package_managers.append("cargo")
        package_name = re.search(r"""(?ms)^\[package\].*?^name\s*=\s*['"]([^'"]+)['"]""", content)
        version = re.search(r"""(?ms)^\[package\].*?^version\s*=\s*['"]([^'"]+)['"]""", content)
        bins = re.findall(r"""(?ms)^\[\[bin\]\].*?^name\s*=\s*['"]([^'"]+)['"]""", content)
        metadata = {
            "source_file": source,
            "build_system": "cargo",
            "package_name": package_name.group(1).strip() if package_name else None,
            "version": version.group(1).strip() if version else None,
            "binaries": bins,
            "workspace": bool(re.search(r"""(?m)^\[workspace\]""", content)),
        }
        intelligence.build_metadata.append(metadata)
        self._add(intelligence, source_file=source, evidence_type="build_configuration", key="Cargo.toml", value=metadata, confidence="high")

    def _rust_toolchain(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        channel = re.search(r"""(?:^|\n)\s*(?:channel|toolchain)\s*=\s*['"]([^'"]+)['"]""", content)
        if channel and re.fullmatch(r"""\d+\.\d+(?:\.\d+)?""", channel.group(1).strip()):
            self._runtime(intelligence, source, "Rust", channel.group(1).strip(), "high", "rust-toolchain channel")
            self._add(intelligence, source_file=source, evidence_type="runtime", key="Rust", value=channel.group(1).strip(), confidence="high")

    def _go_source(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        if re.search(r"""(?m)^\s*package\s+main\b""", content) and re.search(r"""\bfunc\s+main\s*\(""", content):
            self._add(
                intelligence, source_file=source, evidence_type="entrypoint",
                key="go_main_package", value=source, confidence="high",
            )
            intelligence.entrypoints.append({
                "kind": "go_main_package", "source_file": source, "confidence": "high",
            })

    def _rust_source(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        if re.search(r"""\bfn\s+main\s*\(""", content):
            self._add(
                intelligence, source_file=source, evidence_type="entrypoint",
                key="rust_main_function", value=source, confidence="high",
            )
            intelligence.entrypoints.append({
                "kind": "rust_main_function", "source_file": source, "confidence": "high",
            })

    def _nginx_config(self, intelligence: ProjectIntelligence, source: str, content: str, component: str) -> None:
        intelligence.frameworks.append("Nginx")
        self._add(intelligence, source_file=source, evidence_type="server_configuration", key="nginx.conf", value=True, confidence="high")
        for line_number, match in enumerate(re.finditer(r"""\blisten\s+(\d{1,5})\b""", content), start=1):
            port = int(match.group(1))
            if 1 <= port <= 65535:
                self._port(intelligence, source, "nginx_listen", port, "high", "nginx listen directive", line_number, component=component, port_type="proxy", protocol="tcp")

    def _java_manifest(self, intelligence: ProjectIntelligence, source: str, content: str, component: str) -> None:
        manager = "maven"
        intelligence.package_managers.append(manager)
        self._add(intelligence, source_file=source, evidence_type="package_manager", key="package_manager", value=manager, confidence="high")
        metadata = self._parse_maven_metadata(source, content)
        intelligence.build_metadata.append(metadata)
        for key, value in (
            ("groupId", metadata.get("group_id")),
            ("artifactId", metadata.get("artifact_id")),
            ("version", metadata.get("version")),
            ("packaging", metadata.get("packaging")),
            ("build.finalName", metadata.get("build_final_name")),
            ("build.directory", metadata.get("build_directory")),
        ):
            if value:
                self._add(
                    intelligence, source_file=source, evidence_type="maven_configuration",
                    key=key, value=value, confidence="high",
                )
        for plugin in metadata.get("plugins") or []:
            if plugin.get("artifact_id"):
                self._add(
                    intelligence, source_file=source, evidence_type="maven_plugin",
                    key=str(plugin.get("artifact_id")),
                    value={"groupId": plugin.get("group_id"), "executions": plugin.get("executions") or []},
                    confidence="high",
                )
        if metadata.get("parent", {}).get("artifact_id"):
            self._add(
                intelligence, source_file=source, evidence_type="maven_parent",
                key="parent", value=metadata["parent"], confidence="high",
            )
        for module in metadata.get("modules") or []:
            self._add(
                intelligence, source_file=source, evidence_type="maven_module",
                key="module", value=module, confidence="high",
            )
        for name in re.findall(r"<artifactId>\s*([^<]+)\s*</artifactId>", content):
            intelligence.dependencies.append({"name": name.strip(), "version": "", "scope": "runtime", "source_file": source, "confidence": "medium"})
            self._add(intelligence, source_file=source, evidence_type="dependency", key=name.strip(), value="maven artifact", confidence="medium")
        match = re.search(r"<java\.version>\s*([^<]+)\s*</java\.version>", content)
        if match:
            self._runtime(intelligence, source, "Java", match.group(1).strip(), "high", "pom.xml java.version")
        intelligence.commands.append({
            "name": "package", "command": "mvn package", "source_file": source,
            "confidence": "high", "component": component,
            "source_type": "DERIVED_DETERMINISTIC", "rule_id": "maven.lifecycle.package.v1",
            "derived_from": [{"source_file": source, "key": "package_manager"}],
            "model_inference": False,
        })
        self._add(
            intelligence, source_file=source, evidence_type="build_system", key="build_command",
            value="mvn package", confidence="high", source_type="DERIVED_DETERMINISTIC",
            rule_id="maven.lifecycle.package.v1",
            derived_from=[{"source_file": source, "key": "package_manager"}],
        )

    @staticmethod
    def _parse_maven_metadata(source: str, content: str) -> dict[str, Any]:
        """Extract a bounded Maven model without resolving external parents."""
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            return {"source_file": source, "parse_error": str(exc), "plugins": [], "modules": []}

        def tag(value: ET.Element) -> str:
            return value.tag.rsplit("}", 1)[-1]

        def child(parent: ET.Element, name: str) -> str | None:
            for item in list(parent):
                if tag(item) == name and (item.text or "").strip():
                    return (item.text or "").strip()
            return None

        def config(element: ET.Element | None) -> dict[str, Any]:
            if element is None:
                return {}
            result: dict[str, Any] = {}
            for item in list(element):
                key = tag(item)
                if list(item):
                    result[key] = {tag(child_item): (child_item.text or "").strip() for child_item in list(item)}
                else:
                    result[key] = (item.text or "").strip()
            return result

        parent_element = next((item for item in list(root) if tag(item) == "parent"), None)
        parent = {
            "group_id": child(parent_element, "groupId") if parent_element is not None else None,
            "artifact_id": child(parent_element, "artifactId") if parent_element is not None else None,
            "version": child(parent_element, "version") if parent_element is not None else None,
            "relative_path": child(parent_element, "relativePath") if parent_element is not None else None,
        }
        parent_source = None
        if parent.get("relative_path") and str(parent["relative_path"]).endswith(".xml"):
            parent_source = str(Path(source).parent / str(parent["relative_path"])).replace("\\", "/")
        build = next((item for item in list(root) if tag(item) == "build"), None)
        plugins: list[dict[str, Any]] = []
        if build is not None:
            plugins_element = next((item for item in list(build) if tag(item) == "plugins"), None)
            for plugin_element in list(plugins_element) if plugins_element is not None else []:
                if tag(plugin_element) != "plugin":
                    continue
                executions_element = next((item for item in list(plugin_element) if tag(item) == "executions"), None)
                executions: list[dict[str, Any]] = []
                for execution_element in list(executions_element) if executions_element is not None else []:
                    if tag(execution_element) != "execution":
                        continue
                    goals_element = next((item for item in list(execution_element) if tag(item) == "goals"), None)
                    executions.append({
                        "id": child(execution_element, "id"),
                    "goals": [child_item.text.strip() for child_item in (list(goals_element) if goals_element is not None else []) if tag(child_item) == "goal" and (child_item.text or "").strip()],
                        "configuration": config(next((item for item in list(execution_element) if tag(item) == "configuration"), None)),
                    })
                plugins.append({
                    "group_id": child(plugin_element, "groupId"),
                    "artifact_id": child(plugin_element, "artifactId"),
                    "executions": executions,
                    "configuration": config(next((item for item in list(plugin_element) if tag(item) == "configuration"), None)),
                })
        modules_element = next((item for item in list(root) if tag(item) == "modules"), None)
        modules = [child_item.text.strip() for child_item in (list(modules_element) if modules_element is not None else []) if tag(child_item) == "module" and (child_item.text or "").strip()]
        properties_element = next((item for item in list(root) if tag(item) == "properties"), None)
        properties = {tag(item): (item.text or "").strip() for item in (list(properties_element) if properties_element is not None else []) if (item.text or "").strip()}
        return {
            "source_file": source,
            "parent": parent,
            "parent_source_file": parent_source,
            "group_id": child(root, "groupId"),
            "artifact_id": child(root, "artifactId"),
            "version": child(root, "version"),
            "packaging": child(root, "packaging"),
            "build_final_name": child(build, "finalName") if build is not None else None,
            "build_directory": child(build, "directory") if build is not None else None,
            "plugins": plugins,
            "modules": modules,
            "properties": properties,
        }

    def _java_source(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        """Record uniquely identifiable Java main classes as explicit facts."""
        if not re.search(r"\bpublic\s+static\s+void\s+main\s*\(", content):
            return
        class_match = re.search(r"\b(?:public\s+)?class\s+([A-Za-z_$][\w$]*)", content)
        if class_match is None:
            return
        package_match = re.search(r"\bpackage\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*;", content)
        class_name = f"{package_match.group(1)}.{class_match.group(1)}" if package_match else class_match.group(1)
        item = {"kind": "java_main_class", "class_name": class_name, "source_file": source, "confidence": "high"}
        if item not in intelligence.entrypoints:
            intelligence.entrypoints.append(item)
        self._add(intelligence, source_file=source, evidence_type="entrypoint", key="java_main_class", value=class_name, confidence="high")

    def _package_manager_for_manifest(self, source: str, intelligence: ProjectIntelligence) -> str | None:
        directory = Path(source).parent
        names = {file.relative_path for file in intelligence.files if Path(file.relative_path).parent == directory}
        if "pnpm-lock.yaml" in names:
            return "pnpm"
        if "yarn.lock" in names:
            return "yarn"
        if "package-lock.json" in names or "npm-shrinkwrap.json" in names:
            return "npm"
        return "npm"

    def _runtime(self, intelligence: ProjectIntelligence, source: str, name: str, version: str, confidence: str, method: str) -> None:
        item = {"runtime": name, "version": version, "source_file": source, "confidence": confidence}
        if item not in intelligence.runtimes:
            intelligence.runtimes.append(item)
        intelligence.languages.append(name)
        self._add(intelligence, source_file=source, evidence_type="runtime", key=name, value=version, confidence=confidence, extraction_method=method)

    def _dockerfile(self, intelligence: ProjectIntelligence, source: str, content: str, component: str) -> None:
        intelligence.docker.setdefault("dockerfiles", []).append(source)
        bases = list(re.finditer(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", content, re.MULTILINE | re.IGNORECASE))
        for index, base in enumerate(bases):
            # In a multi-stage Dockerfile, only the final FROM is the runtime
            # image.  Preserve every explicit image, but make that role
            # deterministic so build images cannot create a false runtime
            # conflict in Dockerize.
            intelligence.docker.setdefault("base_images", []).append({
                "image": base.group(1),
                "source_file": source,
                "component": component,
                "stage": base.group(2),
                "role": "runtime" if index == len(bases) - 1 else "build",
                "source_type": "EXPLICIT_EVIDENCE",
                "confidence": "high",
                "model_inference": False,
            })
        workdir = re.search(r"^WORKDIR\s+(\S+)", content, re.MULTILINE | re.IGNORECASE)
        if workdir:
            intelligence.docker.setdefault("working_directories", []).append({
                "path": workdir.group(1),
                "source_file": source,
                "component": component,
                "source_type": "EXPLICIT_EVIDENCE",
                "confidence": "high",
                "model_inference": False,
            })
        runtime = re.search(r"^FROM\s+node:(\S+)", content, re.MULTILINE | re.IGNORECASE)
        if runtime:
            version = runtime.group(1).split("-", 1)[0]
            self._runtime(intelligence, source, "Node.js", version, "high", "Dockerfile node base image")
        match = re.search(r"^EXPOSE\s+(\d{2,5})", content, re.MULTILINE | re.IGNORECASE)
        if match:
            self._port(intelligence, source, "container_port", int(match.group(1)), "high", "Dockerfile EXPOSE", component=component, port_type="container")
        command = re.search(r"""^CMD\s+(.+?)\s*$""", content, re.MULTILINE | re.IGNORECASE)
        if command:
            raw = command.group(1).strip()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list) and parsed and all(isinstance(item, str) for item in parsed):
                raw = " ".join(parsed)
            elif isinstance(parsed, str):
                raw = parsed
            if raw:
                self._add(
                    intelligence, source_file=source, evidence_type="command",
                    key=f"{component}.start_command", value=raw, confidence="high",
                )
                intelligence.commands.append({
                    "name": "start", "command": raw, "source_file": source,
                    "confidence": "high", "component": component,
                })
        self._add(intelligence, source_file=source, evidence_type="docker_configuration", key="dockerfile", value=True, confidence="high")

    def _compose(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        intelligence.docker.setdefault("compose_files", []).append(source)
        try:
            data = yaml.safe_load(content) or {}
        except yaml.YAMLError:
            intelligence.warnings.append(f"Invalid Compose YAML: {source}")
            return
        for service, config in (data.get("services") or {}).items():
            item = {"name": str(service), "source_file": source}
            if isinstance(config, dict):
                if str(config.get("image") or "").strip():
                    item.update({
                        "image": str(config["image"]),
                        "image_source_file": source,
                        "image_source_type": "EXPLICIT_EVIDENCE",
                        "model_inference": False,
                    })
                if config.get("build") is not None:
                    item["build"] = config.get("build")
                depends_on = config.get("depends_on") or []
                if isinstance(depends_on, dict):
                    depends_on = list(depends_on)
                if isinstance(depends_on, list):
                    item["depends_on"] = [str(value) for value in depends_on]
                    for dependency in item["depends_on"]:
                        intelligence.relationships.append({
                            "source": str(service),
                            "target": dependency,
                            "relationship_type": "compose_dependency",
                            "source_file": source,
                            "evidence": f"services.{service}.depends_on",
                            "source_type": "EXPLICIT_EVIDENCE",
                            "model_inference": False,
                            "validation": "persisted_repository_evidence",
                        })
            intelligence.services.append(item)
            self._add(intelligence, source_file=source, evidence_type="service", key=str(service), value="docker compose service", confidence="high")
            service_lower = str(service).lower()
            service_image = str(item.get("image") or "").lower()
            for marker, result in (
                ("mongo", ("MongoDB", "document database")), ("postgres", ("PostgreSQL", "database")),
                ("mysql", ("MySQL", "database")), ("mariadb", ("MariaDB", "database")),
                ("redis", ("Redis", "cache")), ("sqlite", ("SQLite", "database")),
                ("elasticsearch", ("Elasticsearch", "search data service")),
            ):
                if marker in service_lower or marker in service_image:
                    service_type, role = result
                    self._add_data_service(
                        intelligence, service_type=service_type, role=role,
                        client_or_library=None, component=str(service), source_file=source,
                        confidence="high", deployment_configuration=source,
                        status="VERIFIED", evidence_basis="explicit service/image configuration",
                    )
                    break
            for mapping in (config.get("ports") or []) if isinstance(config, dict) else []:
                numbers = re.findall(r"\d{1,5}", str(mapping))
                if len(numbers) >= 2:
                    self._port(
                        intelligence, source, "service_port", int(numbers[-2]), "high",
                        "Compose service port mapping", component=str(service),
                        port_type="service", target_port=int(numbers[-1]), service_name=str(service),
                    )
            for env in (config.get("environment") or []) if isinstance(config, dict) else []:
                if isinstance(env, str) and env.startswith("PORT=") and env[5:].isdigit():
                    self._port(intelligence, source, "application_port", int(env[5:]), "high", "Compose PORT environment", component=str(service), port_type="application", service_name=str(service))

    def _source_ports(self, intelligence: ProjectIntelligence, source: str, content: str, component: str) -> None:
        if classify_file(Path(source), content) not in {"source", "configuration", "environment_example"}:
            return
        for line_number, line in enumerate(content.splitlines(), start=1):
            match = (
                PORT_RE.search(line)
                or LISTEN_RE.search(line)
                or re.search(r"""\bListenAndServe\s*\(\s*["'][^"']*:(\d+)""", line)
            )
            if match:
                port = int(match.group(1))
                if 1 <= port <= 65535:
                    self._port(intelligence, source, f"{component}_port", port, "high", "source/configuration port pattern", line_number, component=component, port_type="application")

    def _port(
        self, intelligence: ProjectIntelligence, source: str, key: str, value: int,
        confidence: str, method: str, line_number: int | None = None,
        *, component: str | None = None, port_type: str = "application",
        target_port: int | None = None, service_name: str | None = None,
        protocol: str | None = None,
    ) -> None:
        item = {
            "name": key, "port": value, "source_file": source, "confidence": confidence,
            "component": component or "root", "port_type": port_type,
            "target_port": target_port, "host_port": value if port_type == "service" else None,
            "service_name": service_name, "protocol": protocol,
        }
        if line_number is not None:
            item["line_number"] = line_number
        if item not in intelligence.ports:
            intelligence.ports.append(item)
        self._add(intelligence, source_file=source, evidence_type="port", key=key, value=value, confidence=confidence, line_number=line_number, extraction_method=method)

    def _makefile(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        for line_number, match in enumerate(re.finditer(r"^([A-Za-z0-9_.-]+):\s*(?:#.*)?$", content, re.MULTILINE), start=1):
            name = match.group(1)
            command = f"make {name}"
            intelligence.commands.append({"name": name, "command": command, "source_file": source, "confidence": "high"})
            self._add(intelligence, source_file=source, evidence_type="command", key=f"make.{name}_command", value=command, confidence="high", line_number=line_number)
        for line_number, line in enumerate(content.splitlines(), start=1):
            command = line.strip()
            if not command or line == command:
                continue
            if re.search(r"""\b(?:go\s+build|cargo\s+build|uvicorn|gunicorn|flask\s+run|python\s+manage\.py)\b""", command):
                name = "build" if re.search(r"""\b(?:go\s+build|cargo\s+build)\b""", command) else "start"
                intelligence.commands.append({"name": name, "command": command, "source_file": source, "confidence": "high"})
                self._add(intelligence, source_file=source, evidence_type="command", key=f"make.{name}_recipe", value=command, confidence="high", line_number=line_number)

    @staticmethod
    def _upsert_environment(intelligence: ProjectIntelligence, item: dict[str, Any]) -> None:
        """Keep one safe variable contract while retaining every source path."""
        name = str(item.get("name") or item.get("key") or "")
        item["value_status"] = str(item.get("value_status") or "NEEDS_EVIDENCE").upper()
        existing = next((value for value in intelligence.environment_variables if value.get("name") == name), None)
        if existing is None:
            item["source_files"] = list(dict.fromkeys([*(item.get("source_files") or []), item.get("source_file")]))
            item["required_sources"] = [item.get("source_file")] if item.get("access") and item.get("required") else []
            intelligence.environment_variables.append(item)
            return
        existing["sensitive"] = bool(existing.get("sensitive") or item.get("sensitive"))
        existing["source_files"] = list(dict.fromkeys([*(existing.get("source_files") or []), existing.get("source_file"), *(item.get("source_files") or []), item.get("source_file")]))
        status_rank = {"NEEDS_EVIDENCE": 0, "TEMPLATE_ONLY": 1, "DEFAULT_ONLY": 2, "AVAILABLE": 3, "AVAILABLE_REDACTED": 3}
        existing_status = str(existing.get("value_status") or "NEEDS_EVIDENCE").upper()
        item_status = str(item.get("value_status") or "NEEDS_EVIDENCE").upper()
        if status_rank.get(item_status, 0) > status_rank.get(existing_status, 0):
            existing["value_status"] = item_status
        if status_rank.get(item_status, 0) > status_rank.get(existing_status, 0) and item.get("value") not in {None, "", "required"}:
            existing["value"] = item.get("value")
            existing["source_file"] = item.get("source_file")
        if item.get("component") and item.get("component") != existing.get("component"):
            if not existing.get("component"):
                existing["component"] = item["component"]
            existing["components"] = list(dict.fromkeys([existing.get("component"), *(existing.get("components") or []), item.get("component")]))
        required_sources = list(existing.get("required_sources") or [])
        if item.get("access") and item.get("required") and item.get("source_file"):
            required_sources.append(item["source_file"])
        existing["required_sources"] = list(dict.fromkeys(required_sources))
        if item.get("access"):
            existing["required"] = bool(existing["required_sources"])

    @staticmethod
    def _finalize_environment(intelligence: ProjectIntelligence) -> None:
        """Resolve source-level missing-value gaps only when repository evidence verifies them."""
        statuses = {
            str(item.get("name") or item.get("key") or ""): str(item.get("value_status") or "NEEDS_EVIDENCE").upper()
            for item in intelligence.environment_variables
        }
        intelligence.evidence_gaps = [
            gap for gap in intelligence.evidence_gaps
            if gap.get("kind") != "environment_value"
            or statuses.get(str(gap.get("name") or "")) not in {"AVAILABLE", "AVAILABLE_REDACTED", "DEFAULT_ONLY"}
        ]

    def _env_example(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        for line_number, line in enumerate(content.splitlines(), start=1):
            match = re.match(r"\s*([A-Z][A-Z0-9_]+)\s*=", line)
            if match:
                name = match.group(1)
                value_match = re.match(r"\s*[A-Z][A-Z0-9_]+\s*=\s*(.*?)\s*(?:#.*)?$", line)
                explicit_value = (value_match.group(1).strip().strip("\"'") if value_match else "") or None
                sensitive = self._is_sensitive_environment_name(name)
                item = {
                    "name": name, "key": name, "value": "REDACTED" if sensitive and explicit_value else explicit_value,
                    "sensitive": sensitive, "required": not bool(explicit_value), "value_status": "TEMPLATE_ONLY",
                    "component": source.split("/", 1)[0] if "/" in source else "root", "source_file": source,
                    "source_files": [source], "role": "build_time" if name.startswith(("VITE_", "NEXT_PUBLIC_")) else "runtime",
                    "confidence": "high",
                }
                self._upsert_environment(intelligence, item)
                self._add(intelligence, source_file=source, evidence_type="secret" if sensitive else "environment_variable", key=name, value=item["value"] or "required", confidence="high", line_number=line_number)

    def _env_file(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        """Extract environment shape while discarding all sensitive values."""
        for line_number, line in enumerate(content.splitlines(), start=1):
            match = re.match(r"\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)(?:\s+#.*)?$", line)
            if not match:
                continue
            key, raw_value = match.groups()
            is_sensitive = self._is_sensitive_environment_name(key)
            raw_value = raw_value.strip().strip("\"'")
            value = "REDACTED" if is_sensitive else raw_value
            value_status = "AVAILABLE_REDACTED" if is_sensitive and raw_value else "AVAILABLE" if raw_value and not self._is_placeholder_value(raw_value) else "NEEDS_EVIDENCE"
            item = {
                "name": key, "key": key, "value": value, "sensitive": is_sensitive,
                "value_status": value_status, "required": not bool(raw_value),
                "component": source.split("/", 1)[0] if "/" in source else "root",
                "source_file": source, "confidence": "high",
            }
            self._upsert_environment(intelligence, item)
            evidence_type = "secret" if is_sensitive else "environment_variable"
            self._add(
                intelligence, source_file=source, evidence_type=evidence_type, key=key,
                value=value, confidence="high", line_number=line_number,
                extraction_method="redacted-env-parser" if is_sensitive else "env-parser",
            )
            if key == "PORT" and value.isdigit():
                self._port(intelligence, source, "root_port", int(value), "high", "environment PORT", line_number, component="root", port_type="application")

    @staticmethod
    def _is_sensitive_environment_name(name: str) -> bool:
        return any(marker in name for marker in (
            "SECRET", "TOKEN", "PASSWORD", "PASS", "API_KEY", "PRIVATE",
            "CREDENTIAL", "DATABASE_URL", "DB_URL", "CONNECTION_STRING", "DSN",
            "MONGO", "JWT",
        ))

    @staticmethod
    def _is_placeholder_value(value: str) -> bool:
        normalized = value.strip().lower()
        return (
            not normalized
            or normalized.startswith("<")
            or normalized.startswith("your_")
            or normalized in {"changeme", "change_me", "placeholder", "example", "todo", "replace_me"}
            or "replace-with" in normalized
            or "your-value" in normalized
        )

    def _environment_access(self, intelligence: ProjectIntelligence, source: str, content: str, component: str) -> None:
        """Record source-level configuration requirements without inventing values."""
        patterns = (
            re.compile(r"\bprocess\.env\.([A-Z][A-Z0-9_]*)(?:\s*\|\|\s*['\"]?([A-Za-z0-9_.:/-]+)['\"]?)?"),
            re.compile(r"\b(?:import\.meta\.env|env)\.([A-Z][A-Z0-9_]*)"),
            re.compile(r"\bos\.getenv\(\s*['\"]([A-Z][A-Z0-9_]*)['\"](?:\s*,\s*['\"]([^'\"]*)['\"])?"),
            re.compile(r"\bos\.environ\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]\s*\]"),
        )
        accesses: dict[str, str | None] = {}
        for pattern in patterns:
            for match in pattern.finditer(content):
                default = match.group(2) if match.lastindex and match.lastindex > 1 else None
                if match.group(1) not in accesses or default is not None:
                    accesses[match.group(1)] = default
        for name, default in accesses.items():
            sensitive = self._is_sensitive_environment_name(name)
            item = {
                "name": name, "key": name, "value": "REDACTED" if sensitive and default else default,
                "sensitive": sensitive, "required": default is None,
                "value_status": "DEFAULT_ONLY" if default is not None and not self._is_placeholder_value(default) else "NEEDS_EVIDENCE",
                "component": component,
                "source_file": source, "source_files": [source],
                "role": "build_time" if "import.meta.env" in content or name.startswith(("VITE_", "NEXT_PUBLIC_")) else "runtime",
                "confidence": "high", "access": True,
            }
            self._upsert_environment(intelligence, item)
            self._add(intelligence, source_file=source, evidence_type="secret" if sensitive else "environment_variable", key=name, value={"required": default is None, "default": "REDACTED" if sensitive and default else default}, confidence="high", extraction_method="source-environment-access")
            if default is None:
                sensitive_gap = sensitive
                self._add_evidence_gap(
                    intelligence,
                    kind="environment_value",
                    decision="runtime_configuration" if item["role"] == "runtime" else "build_configuration",
                    component=component,
                    name=name,
                    source_file=source,
                    missing_evidence=(
                        f"{name} is referenced by source but no repository value or explicit default is available."
                    ),
                    search_scope="environment files, environment examples, configuration modules, source access, container and CI/CD declarations",
                    resolution="runtime_secret_or_user_provided_configuration" if sensitive_gap else "repository_configuration_or_user_provided_configuration",
                    external_input_required=sensitive_gap,
                    confidence="high",
                )

    def _infrastructure_file(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        path = Path(source)
        lower = path.as_posix().lower()
        infra_type = None
        if path.name == "Dockerfile" or path.name.startswith("Dockerfile."):
            infra_type = "container_build"
        elif path.name.lower() in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
            infra_type = "container_orchestration"
        elif path.name == "nginx.conf" or path.name.endswith(".nginx.conf"):
            infra_type = "reverse_proxy"
        elif classify_file(path, content) == "kubernetes":
            infra_type = "kubernetes"
        elif classify_file(path, content) == "ci_cd":
            infra_type = "ci_cd"
        elif path.suffix.lower() in {".tf", ".tfvars"} or "/terraform/" in f"/{lower}/":
            infra_type = "terraform"
        elif path.name in {"Jenkinsfile", "Procfile", "ecosystem.config.js", "ecosystem.config.cjs"} or "/systemd/" in f"/{lower}/":
            infra_type = "process_or_deployment"
        if not infra_type:
            return
        status = "referenced" if infra_type == "ci_cd" else "unknown"
        item = {
            "type": infra_type, "path": source, "status": status,
            "evidence": [{"source_file": source, "reason": "recognized infrastructure configuration", "confidence": "high"}],
            "confidence": "high",
        }
        if item not in intelligence.infrastructure:
            intelligence.infrastructure.append(item)
        self._add(intelligence, source_file=source, evidence_type="infrastructure", key=infra_type, value={"path": source, "status": status}, confidence="high")

    def _finalize_infrastructure(self, intelligence: ProjectIntelligence) -> None:
        compose_sources = set(intelligence.docker.get("compose_files", []))
        for item in intelligence.infrastructure:
            if item["type"] == "container_build" and any(service.get("build") is not None for service in intelligence.services):
                item["status"] = "referenced"
            if item["type"] == "container_orchestration" and item["path"] in compose_sources:
                item["status"] = "referenced"
            if item["type"] == "reverse_proxy":
                item["status"] = "referenced" if any(
                    str(service.get("name") or "").lower() == "nginx"
                    and str(service.get("source_file") or "") in compose_sources
                    for service in intelligence.services
                ) else "unknown"

    def _detect_relationships(self, intelligence: ProjectIntelligence, files: dict[str, str]) -> None:
        component_names = {str(item.get("name")) for item in intelligence.components}
        backends = component_names.intersection({"backend", "api", "server"})
        workspace_metadata = [
            item for item in intelligence.build_metadata
            if item.get("workspace_patterns") and item.get("workspace_root")
        ]
        for workspace in workspace_metadata:
            source_file = str(workspace.get("source_file") or "repository")
            for component in intelligence.components:
                name = str(component.get("name") or "")
                path = str(component.get("path") or ".").strip("./")
                if not name or not path or name == "application":
                    continue
                if any(fnmatch(path, pattern) or fnmatch(f"{path}/package.json", pattern) for pattern in workspace.get("workspace_patterns", [])):
                    relationship = {
                        "source": "repository",
                        "target": name,
                        "relationship_type": "workspace_member",
                        "source_file": source_file,
                        "evidence": "workspace pattern explicitly includes component path",
                        "source_type": "EXPLICIT_EVIDENCE",
                        "confidence": "high",
                        "model_inference": False,
                    }
                    if relationship not in intelligence.relationships:
                        intelligence.relationships.append(relationship)
                    self._add(intelligence, source_file=source_file, evidence_type="relationship", key="workspace_member", value=relationship, confidence="high")
        for source, content in files.items():
            component = source.split("/", 1)[0] or "application"
            if component in component_names and component not in backends and re.search(r"\b(?:BACKEND_URL|API_URL|VITE_API_URL|NEXT_PUBLIC_API_URL)\b", content):
                target = sorted(backends)[0]
                relationship = {
                    "source": component, "target": target, "relationship_type": "frontend_to_backend",
                    "source_file": source, "evidence": "frontend source references an API/backend configuration variable",
                    "source_type": "EXPLICIT_EVIDENCE", "confidence": "medium", "model_inference": False,
                }
                if relationship not in intelligence.relationships:
                    intelligence.relationships.append(relationship)
                self._add(intelligence, source_file=source, evidence_type="relationship", key="frontend_to_backend", value=relationship, confidence="medium")
            for match in re.finditer(
                r"\bproxy_pass\s+https?://([^\s;/:]+)(?::(\d+))?", content, re.IGNORECASE
            ):
                if component not in component_names:
                    continue
                target = match.group(1)
                target_component = target if target in component_names else None
                relationship = {
                    "source": component,
                    "target": target_component or target,
                    "target_kind": "component" if target_component else "external_upstream",
                    "target_port": int(match.group(2)) if match.group(2) else None,
                    "relationship_type": "proxy_to_upstream",
                    "source_file": source,
                    "line_number": content.count("\n", 0, match.start()) + 1,
                    "evidence": "explicit proxy_pass upstream configuration",
                    "source_type": "EXPLICIT_EVIDENCE",
                    "confidence": "high",
                    "model_inference": False,
                }
                if relationship not in intelligence.relationships:
                    intelligence.relationships.append(relationship)
                self._add(
                    intelligence, source_file=source, evidence_type="relationship",
                    key="proxy_to_upstream", value=relationship, confidence="high",
                    line_number=relationship["line_number"],
                )

    def _detect_contradictions(self, intelligence: ProjectIntelligence) -> None:
        for port in intelligence.ports:
            if not port.get("conflict"):
                continue
            contradiction = {
                "kind": "network_port", "status": "CONTRADICTORY", "component": port.get("component"),
                "port_type": port.get("port_type"), "candidates": port.get("candidates", []),
                "evidence": port.get("sources", []), "message": "Multiple incompatible port values were found; no single port was selected.",
            }
            intelligence.contradictions.append(contradiction)
            self._add(intelligence, source_file=str((port.get("sources") or [{}])[0].get("source_file") or "repository"), evidence_type="contradiction", key="network_port", value=contradiction, confidence="high")
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for command in intelligence.commands:
            purpose = str(command.get("purpose") or "unknown")
            if purpose == "unknown":
                continue
            grouped.setdefault((str(command.get("component") or "root"), purpose), []).append(command)
        for (component, purpose), commands in grouped.items():
            values = {str(item.get("command")) for item in commands}
            if len(values) > 1 and purpose in {"production_runtime", "build"}:
                contradiction = {
                    "kind": "command", "status": "CONTRADICTORY", "component": component,
                    "purpose": purpose, "candidates": sorted(values),
                    "evidence": [{"source_file": item.get("source_file"), "confidence": item.get("confidence")} for item in commands],
                    "message": f"Conflicting {purpose} commands were found; no command was selected.",
                }
                intelligence.contradictions.append(contradiction)
                self._add(intelligence, source_file=str(commands[0].get("source_file") or "repository"), evidence_type="contradiction", key=f"{component}.{purpose}", value=contradiction, confidence="high")
        def owner(source_file: str) -> str:
            scoped = []
            for component in intelligence.components:
                name = str(component.get("name") or "")
                path = str(component.get("path") or ".").strip("./")
                if path and (source_file == path or source_file.startswith(path + "/")):
                    scoped.append((len(path), name))
            if scoped:
                return max(scoped)[1] or "repository"
            for component in intelligence.components:
                if not str(component.get("path") or ".").strip("./"):
                    return str(component.get("name") or "repository")
            return "repository"

        runtime_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for runtime in intelligence.runtimes:
            version = str(runtime.get("version") or "").strip().lstrip("v")
            if re.fullmatch(r"\d+(?:\.\d+){0,2}", version):
                runtime_groups.setdefault((str(runtime.get("runtime") or "unknown"), owner(str(runtime.get("source_file") or ""))), []).append(runtime)
        for (runtime_name, component), runtimes in runtime_groups.items():
            versions = sorted({str(item.get("version")).lstrip("v") for item in runtimes})
            if len(versions) < 2:
                continue
            contradiction = {
                "kind": "runtime",
                "status": "CONTRADICTORY",
                "component": component,
                "runtime": runtime_name,
                "candidates": versions,
                "evidence": [{"source_file": item.get("source_file"), "confidence": item.get("confidence")} for item in runtimes],
                "message": f"Multiple exact {runtime_name} versions were found for {component}; no version was selected.",
            }
            intelligence.contradictions.append(contradiction)
            self._add(intelligence, source_file=str(runtimes[0].get("source_file") or "repository"), evidence_type="contradiction", key=f"{component}.{runtime_name}", value=contradiction, confidence="high")

        output_groups: dict[str, list[dict[str, Any]]] = {}
        for metadata in intelligence.build_metadata:
            outputs = [str(item) for item in metadata.get("outputs", []) if item]
            component = str(metadata.get("component") or owner(str(metadata.get("source_file") or "")))
            if outputs:
                output_groups.setdefault(component, []).append({"source_file": metadata.get("source_file"), "outputs": outputs})
        for component, records in output_groups.items():
            outputs = sorted({output for record in records for output in record["outputs"]})
            if len(outputs) < 2:
                continue
            contradiction = {
                "kind": "build_output",
                "status": "CONTRADICTORY",
                "component": component,
                "candidates": outputs,
                "evidence": records,
                "message": f"Multiple explicit build output directories were found for {component}; no output was selected.",
            }
            intelligence.contradictions.append(contradiction)
            self._add(intelligence, source_file=str(records[0].get("source_file") or "repository"), evidence_type="contradiction", key=f"{component}.build_output", value=contradiction, confidence="high")

        service_groups: dict[str, list[dict[str, Any]]] = {}
        physical_roles = {"database", "document database", "cache", "managed data service", "search data service"}
        for service in intelligence.data_services:
            if service.get("status") == "VERIFIED" and service.get("role") in physical_roles:
                service_groups.setdefault(str(service.get("component") or "repository"), []).append(service)
        for component, services in service_groups.items():
            service_types = sorted({str(item.get("service_type")) for item in services})
            if len(service_types) < 2:
                continue
            typed_evidence = any(
                any(basis in {"explicit schema provider", "explicit service/image configuration"} for basis in item.get("evidence_basis", []))
                for item in services
            )
            if typed_evidence:
                continue
            for service in services:
                service["status"] = "AMBIGUOUS"
            contradiction = {
                "kind": "data_service",
                "status": "CONTRADICTORY",
                "component": component,
                "candidates": service_types,
                "evidence": [{"source_file": item.get("source_file"), "service_type": item.get("service_type")} for item in services],
                "message": f"Multiple data-service types share generic configuration evidence for {component}; no single service identity was selected.",
            }
            intelligence.contradictions.append(contradiction)
            self._add(intelligence, source_file=str(services[0].get("source_file") or "repository"), evidence_type="contradiction", key=f"{component}.data_service", value=contradiction, confidence="high")

        environment_groups: dict[str, list[Evidence]] = {}
        for evidence in intelligence.evidence:
            if evidence.evidence_type not in {"environment_variable", "secret"} or evidence.evidence_type == "secret":
                continue
            value = evidence.value
            if isinstance(value, dict) or value in {None, "", "required", "REDACTED"}:
                continue
            environment_groups.setdefault(evidence.key, []).append(evidence)
        for name, records in environment_groups.items():
            values = {str(item.value) for item in records}
            if len(values) < 2:
                continue
            contradiction = {
                "kind": "configuration",
                "status": "CONTRADICTORY",
                "name": name,
                "candidates": [{"source_file": item.source_file, "value_present": True} for item in records],
                "message": f"Different explicit values for {name} were found across repository configuration sources; no value was selected.",
            }
            intelligence.contradictions.append(contradiction)
            self._add(intelligence, source_file=records[0].source_file, evidence_type="contradiction", key=name, value=contradiction, confidence="high")

    def _readme(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        intelligence.documentation.setdefault("files", []).append(source)
        setup_instructions = intelligence.documentation.setdefault("setup_instructions", [])
        setup_directory: str | None = None
        setup_environment_file: str | None = None
        self._add(intelligence, source_file=source, evidence_type="documentation", key="readme", value=True, confidence="high")
        for line_number, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            cd_match = re.search(r"(?:^|[`$>\s])cd\s+([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)", stripped)
            if cd_match:
                setup_directory = self._safe_readme_path(cd_match.group(1))

            env_path_match = re.search(
                r"(?<![A-Za-z0-9_.-])((?:[A-Za-z0-9_.-]+/)*\.env(?:\.(?:example|sample|template))?)(?![A-Za-z0-9_.-])",
                stripped,
                re.IGNORECASE,
            )
            if env_path_match:
                env_reference = env_path_match.group(1)
                target = self._env_target_path(env_reference)
                if target == ".env" and setup_directory is not None and "/" not in env_reference:
                    target = self._env_target_path(posixpath.join(setup_directory, ".env"))
                setup_environment_file = target

            # A README assignment is useful setup evidence only when it is
            # attached to an explicit env-file/cd context. Its value is never
            # persisted for sensitive variables.
            assignment = re.fullmatch(r"[`$>\s]*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*[`\s]*", stripped)
            if assignment:
                name, raw_value = assignment.groups()
                raw_value = raw_value.strip().strip("\"'")
                sensitive = self._is_sensitive_environment_name(name)
                placeholder = self._is_placeholder_value(raw_value)
                location = setup_environment_file
                if location is None and setup_directory is not None:
                    location = self._env_target_path(posixpath.join(setup_directory, ".env"))
                if location is not None:
                    setup_instructions.append({
                        "name": name,
                        "source_file": source,
                        "line_number": line_number,
                        "location": location,
                        "value": None if sensitive else (None if placeholder else raw_value),
                        "value_status": "DOCUMENTED_PLACEHOLDER" if placeholder else "DOCUMENTED_VALUE",
                        "sensitive": sensitive,
                        "component": self._readme_component(location),
                    })
                    self._add(
                        intelligence,
                        source_file=source,
                        evidence_type="documentation",
                        key=f"setup.{name}",
                        value={
                            "location": location,
                            "value_present": bool(raw_value) and not placeholder,
                            "sensitive": sensitive,
                        },
                        confidence="high",
                        line_number=line_number,
                        extraction_method="readme-setup-parser",
                    )
            match = PORT_RE.search(line)
            if match:
                self._port(intelligence, source, "documented_port", int(match.group(1)), "medium", "README port mention", line_number, component="root", port_type="documented")
            runtime = re.search(
                r"\bNode(?:\.js)?\s*(?:\(\s*)?(?:version\s+)?"
                r"(?P<version>v?\d+(?:\.\d+){0,2})"
                r"(?P<qualifier>\s+or\s+(?:higher|later))?\s*\)?",
                line,
                re.IGNORECASE,
            )
            if runtime:
                version = runtime.group("version")
                if runtime.group("qualifier"):
                    version += runtime.group("qualifier")
                self._runtime(intelligence, source, "Node.js", version, "medium", "README runtime mention")
            command_line = line.strip()
            if command_line[:1] in {"$", ">"}:
                command_line = command_line[1:].strip()
            command_match = re.fullmatch(
                r"""((?:uvicorn[ ]+[^#]+|gunicorn[ ]+[^#]+|flask[ ]+run[^#]*|python[ ]+manage[.]py[^#]*|go[ ]+build[ ]+[^#]+|cargo[ ]+build[ ]+[^#]+|[.]/[A-Za-z0-9_./-]+))[ ]*""",
                command_line,
                re.IGNORECASE,
            )
            if command_match:
                command = command_match.group(1).strip()
                name = "build" if re.match(r"""(?:go\s+build|cargo\s+build)\b""", command) else "start"
                intelligence.commands.append({
                    "name": name, "command": command, "source_file": source,
                    "confidence": "high",
                })
                port_argument = re.search(r"""(?:--port|port[=:])[ ]*(\d{2,5})\b""", command, re.IGNORECASE)
                if port_argument:
                    self._port(
                        intelligence, source, "command_port", int(port_argument.group(1)),
                        "high", "explicit production command port", line_number,
                        component="root", port_type="application",
                    )
                self._add(
                    intelligence, source_file=source, evidence_type="command",
                    key=f"readme.{name}_command", value=command,
                    confidence="high", line_number=line_number,
                )

    @staticmethod
    def _safe_readme_path(value: str) -> str | None:
        candidate = value.strip().strip("`'\"")
        if not candidate or candidate.startswith("/"):
            return None
        normalized = posixpath.normpath(candidate)
        if normalized == ".." or normalized.startswith("../"):
            return None
        # README clone instructions commonly use a placeholder such as
        # ``your-repo-name``.  It is not evidence of a directory in the
        # inspected repository, so it must not be turned into an env path.
        if any(part.lower().startswith(("your-", "your_")) for part in normalized.split("/")):
            return None
        return "." if normalized == "." else normalized

    @classmethod
    def _env_target_path(cls, value: str) -> str | None:
        candidate = cls._safe_readme_path(value)
        if candidate is None:
            return None
        path = posixpath.dirname(candidate)
        return posixpath.join(path, ".env") if path else ".env"

    @staticmethod
    def _readme_component(location: str) -> str:
        directory = posixpath.dirname(location)
        return directory.split("/", 1)[0] if directory else "root"

    def _kubernetes(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        if classify_file(Path(source), content) != "kubernetes":
            return
        try:
            documents = list(yaml.safe_load_all(content))
        except yaml.YAMLError:
            intelligence.warnings.append(f"Invalid Kubernetes YAML: {source}")
            return
        intelligence.kubernetes.setdefault("files", []).append(source)
        for document in documents:
            if not isinstance(document, dict) or not document.get("kind"):
                continue
            kind = str(document["kind"])
            intelligence.kubernetes.setdefault("resources", []).append({"kind": kind, "name": (document.get("metadata") or {}).get("name"), "source_file": source})
            self._add(intelligence, source_file=source, evidence_type="kubernetes_configuration", key=kind, value=(document.get("metadata") or {}).get("name", ""), confidence="high")
            if kind == "Service":
                for port in (document.get("spec") or {}).get("ports", []) or []:
                    if isinstance(port, dict) and port.get("port"):
                        target = port.get("targetPort")
                        target_value = int(target) if str(target).isdigit() else None
                        service_name = str((document.get("metadata") or {}).get("name") or "service")
                        selector = (document.get("spec") or {}).get("selector") or {}
                        component = str(selector.get("app") or selector.get("component") or service_name)
                        self._port(intelligence, source, "service_port", int(port["port"]), "high", "Kubernetes Service port", component=component, port_type="service", target_port=target_value, service_name=service_name)
            workload_spec = (document.get("spec") or {}).get("template", {}).get("spec", {})
            containers = workload_spec.get("containers", []) if isinstance(workload_spec, dict) else []
            if isinstance(containers, list):
                template_metadata = (document.get("spec") or {}).get("template", {}).get("metadata", {})
                labels = template_metadata.get("labels", {}) if isinstance(template_metadata, dict) else {}
                workload_labels = (document.get("metadata") or {}).get("labels", {})
                if not isinstance(workload_labels, dict):
                    workload_labels = {}
                for container in containers:
                    if not isinstance(container, dict):
                        continue
                    component = str(
                        labels.get("app")
                        or labels.get("component")
                        or workload_labels.get("app")
                        or workload_labels.get("component")
                        or container.get("name")
                        or (document.get("metadata") or {}).get("name")
                        or "root"
                    )
                    for container_port in container.get("ports", []) or []:
                        if not isinstance(container_port, dict):
                            continue
                        value = container_port.get("containerPort")
                        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
                            self._port(
                                intelligence, source, "container_port", int(value), "high",
                                "Kubernetes workload containerPort", component=component,
                                port_type="container",
                            )
                    for environment in container.get("env", []) or []:
                        if not isinstance(environment, dict) or environment.get("name") != "PORT":
                            continue
                        value = environment.get("value")
                        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
                            self._port(
                                intelligence, source, "application_port", int(value), "high",
                                "Kubernetes workload PORT environment", component=component,
                                port_type="application",
                            )

    def _ci_cd(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        path = Path(source)
        platform = None
        if path.name == "Jenkinsfile":
            platform = "Jenkins"
        elif ".github/workflows/" in path.as_posix():
            platform = "GitHub Actions"
        elif path.name == ".gitlab-ci.yml":
            platform = "GitLab CI"
        elif ".circleci/" in path.as_posix():
            platform = "CircleCI"
        elif path.name == "azure-pipelines.yml":
            platform = "Azure Pipelines"
        if not platform:
            return
        intelligence.ci_cd.setdefault("files", []).append(source)
        intelligence.ci_cd.setdefault("platforms", []).append(platform)
        self._add(intelligence, source_file=source, evidence_type="ci_cd_platform", key="platform", value=platform, confidence="high")

    def _language_and_frameworks(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        language = _language(Path(source))
        if language:
            intelligence.languages.append(language)
        lower = content.lower()
        frameworks = {
            "React": ("react", "react-dom"), "Vite": ("vite",), "Next.js": ("next",),
            "Express": ("express",), "FastAPI": ("fastapi",), "Flask": ("flask",),
            "Django": ("django",), "Spring Boot": ("spring-boot",),
        }
        for framework, markers in frameworks.items():
            if any(marker in lower for marker in markers):
                intelligence.frameworks.append(framework)
        for marker, result in (
            ("mongoose", ("MongoDB", "document database", "Mongoose")),
            ("mongodb", ("MongoDB", "document database", None)),
            ("postgres", ("PostgreSQL", "database", None)),
            ("mysql", ("MySQL", "database", None)),
            ("mariadb", ("MariaDB", "database", None)),
            ("sqlite", ("SQLite", "database", None)),
            ("redis", ("Redis", "cache", None)),
            ("supabase", ("Supabase", "managed data service", None)),
            ("firebase", ("Firebase", "managed data service", None)),
            ("elasticsearch", ("Elasticsearch", "search data service", None)),
            ("dynamodb", ("DynamoDB", "database", None)),
        ):
            if marker in lower:
                service_type, role, client = result
                self._add_data_service(
                    intelligence, service_type=service_type, role=role,
                    client_or_library=client, component=source.split("/", 1)[0] if "/" in source else "root",
                    source_file=source, confidence="medium",
                )

    def _prisma_schema(self, intelligence: ProjectIntelligence, source: str, content: str, component: str) -> None:
        provider = re.search(r"\bprovider\s*=\s*['\"]([^'\"]+)['\"]", content)
        if not provider:
            return
        provider_name = provider.group(1).lower()
        service_types = {
            "postgresql": ("PostgreSQL", "database"), "mysql": ("MySQL", "database"),
            "sqlite": ("SQLite", "database"), "mongodb": ("MongoDB", "document database"),
            "sqlserver": ("SQL Server", "database"), "cockroachdb": ("CockroachDB", "database"),
        }
        service_type, role = service_types.get(provider_name, ("Prisma", "data access layer"))
        self._add_data_service(
            intelligence, service_type=service_type, role=role,
            client_or_library="Prisma", component=component,
            source_file=source, confidence="high", schema_location=source,
            status="VERIFIED", evidence_basis="explicit schema provider",
        )

    def _component(self, intelligence: ProjectIntelligence, name: str, files: dict[str, str]) -> dict[str, Any]:
        relevant = [path for path in files if _component_name(Path(intelligence.root_path), Path(intelligence.root_path) / path) == name]
        framework = next((item for item in intelligence.frameworks if any(item.lower() in files[path].lower() for path in relevant)), None)
        manager = intelligence.package_managers[0] if intelligence.package_managers else None
        kind = "frontend" if framework in {"React", "Vite", "Next.js"} else "backend" if framework in {"Express", "FastAPI", "Flask", "Django", "Spring Boot"} else "service"
        return {"name": name, "path": "." if name == "root" else name, "kind": kind, "framework": framework, "package_manager": manager}
