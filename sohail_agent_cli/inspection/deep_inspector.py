"""Recursive, deterministic repository inspection.

The inspector extracts engineering facts and provenance. It never sends
repository data to an LLM and never retains source contents in its result.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from .models import DiscoveredFile, Evidence, ProjectIntelligence


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
    ".tsx", ".toml", ".txt", ".xml", ".yaml", ".yml", ".lock", ".ini", ".cfg",
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

    def _runtime_dependency(self, intelligence: ProjectIntelligence, component: str, dependency: str, source_file: str, confidence: str) -> None:
        from .models import RuntimeDependency
        item = RuntimeDependency(
            component=component, dependency=dependency, source_file=source_file, confidence=confidence
        )
        if item not in intelligence.runtime_dependencies:
            intelligence.runtime_dependencies.append(item)

    def _extract(self, intelligence: ProjectIntelligence, root: Path, files: dict[str, str]) -> None:
        package_metadata: dict[str, dict[str, Any]] = {}
        manifest_paths: list[str] = []
        has_manage_py = False
        for relative, content in files.items():
            path = root / relative
            name = path.name
            component = _component_name(root, path.parent)
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

        intelligence.components = self._detect_components(
            intelligence, root, files, package_metadata, manifest_paths, has_manage_py,
        )
        self._normalize_ports(intelligence)

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
                    "target_port": raw.get("target_port"), "service_name": service_name,
                    "confidence": raw.get("confidence", "low"), "sources": [],
                    "candidates": [], "conflict": False,
                },
            )
            if source not in entry["sources"]:
                entry["sources"].append(source)
            candidate = {
                "port": raw.get("port"), "target_port": raw.get("target_port"),
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

                name_lower = str(name).lower()
                if "mongoose" in name_lower or "mongodb" in name_lower:
                    self._runtime_dependency(intelligence, component, "MongoDB", source_file=source, confidence="high")
                elif "pg" in name_lower or "postgres" in name_lower:
                    self._runtime_dependency(intelligence, component, "PostgreSQL", source_file=source, confidence="high")
                elif "mysql" in name_lower:
                    self._runtime_dependency(intelligence, component, "MySQL", source_file=source, confidence="high")
                elif "redis" in name_lower:
                    self._runtime_dependency(intelligence, component, "Redis", source_file=source, confidence="high")

        for script, command in (data.get("scripts") or {}).items():
            item = {"name": str(script), "command": str(command), "source_file": source, "confidence": "high", "component": component}
            intelligence.commands.append(item)
            self._add(intelligence, source_file=source, evidence_type="command", key=f"{component}.{script}_command", value=str(command), confidence="high")
        engines = data.get("engines") or {}
        if engines.get("node"):
            self._runtime(intelligence, source, "Node.js", str(engines["node"]), "high", "package.json engines")
        return data

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
                intelligence.dependencies.append({"name": value.split()[0].split(">=")[0], "version": value, "scope": "runtime", "source_file": source, "confidence": "high"})
                self._add(intelligence, source_file=source, evidence_type="dependency", key=value.split()[0], value=value, confidence="high")
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
                self._port(intelligence, source, "nginx_listen", port, "high", "nginx listen directive", line_number, component=component, port_type="application")

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
            for marker, database in (("mongo", "MongoDB"), ("postgres", "PostgreSQL"), ("mysql", "MySQL"), ("redis", "Redis")):
                if marker in service_lower:
                    intelligence.databases.append(database)
                    self._add(intelligence, source_file=source, evidence_type="database", key="database", value=database, confidence="high")
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
    ) -> None:
        item = {
            "name": key, "port": value, "source_file": source, "confidence": confidence,
            "component": component or "root", "port_type": port_type,
            "target_port": target_port, "service_name": service_name,
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

    def _env_example(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        for line_number, line in enumerate(content.splitlines(), start=1):
            match = re.match(r"\s*([A-Z][A-Z0-9_]+)\s*=", line)
            if match:
                self._add(intelligence, source_file=source, evidence_type="environment_variable", key=match.group(1), value="configured", confidence="high", line_number=line_number)

    def _env_file(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        """Extract environment shape while discarding all sensitive values."""
        sensitive_markers = (
            "SECRET", "TOKEN", "PASSWORD", "PASS", "API_KEY", "PRIVATE",
            "CREDENTIAL", "DATABASE_URL", "MONGO_URI", "JWT",
        )
        for line_number, line in enumerate(content.splitlines(), start=1):
            match = re.match(r"\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)(?:\s+#.*)?$", line)
            if not match:
                continue
            key, raw_value = match.groups()
            is_sensitive = any(marker in key for marker in sensitive_markers)
            value = "REDACTED" if is_sensitive else raw_value.strip().strip("\"'")
            item = {
                "name": key, "key": key, "value": value, "sensitive": is_sensitive,
                "source_file": source, "confidence": "high",
            }
            intelligence.environment_variables.append(item)
            evidence_type = "secret" if is_sensitive else "environment_variable"
            self._add(
                intelligence, source_file=source, evidence_type=evidence_type, key=key,
                value=value, confidence="high", line_number=line_number,
                extraction_method="redacted-env-parser" if is_sensitive else "env-parser",
            )
            if key == "PORT" and value.isdigit():
                self._port(intelligence, source, "root_port", int(value), "high", "environment PORT", line_number, component="root", port_type="application")

            key_lower = key.lower()
            if "mongo" in key_lower:
                component_name = _component_name(Path(intelligence.root_path), Path(intelligence.root_path) / source)
                self._runtime_dependency(intelligence, component_name, "MongoDB", source_file=source, confidence="high")
            elif "postgres" in key_lower:
                component_name = _component_name(Path(intelligence.root_path), Path(intelligence.root_path) / source)
                self._runtime_dependency(intelligence, component_name, "PostgreSQL", source_file=source, confidence="high")
            elif "mysql" in key_lower:
                component_name = _component_name(Path(intelligence.root_path), Path(intelligence.root_path) / source)
                self._runtime_dependency(intelligence, component_name, "MySQL", source_file=source, confidence="high")
            elif "redis" in key_lower:
                component_name = _component_name(Path(intelligence.root_path), Path(intelligence.root_path) / source)
                self._runtime_dependency(intelligence, component_name, "Redis", source_file=source, confidence="high")

    def _readme(self, intelligence: ProjectIntelligence, source: str, content: str) -> None:
        intelligence.documentation.setdefault("files", []).append(source)
        self._add(intelligence, source_file=source, evidence_type="documentation", key="readme", value=True, confidence="high")
        for line_number, line in enumerate(content.splitlines(), start=1):
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
        for marker, database in (("mongoose", "MongoDB"), ("mongodb", "MongoDB"), ("postgres", "PostgreSQL"), ("mysql", "MySQL"), ("redis", "Redis")):
            if marker in lower:
                intelligence.databases.append(database)
                self._add(intelligence, source_file=source, evidence_type="database", key="database", value=database, confidence="medium")
                component_name = _component_name(Path(intelligence.root_path), Path(intelligence.root_path) / source)
                self._runtime_dependency(intelligence, component_name, database, source_file=source, confidence="medium")
                break

    def _component(self, intelligence: ProjectIntelligence, name: str, files: dict[str, str]) -> dict[str, Any]:
        relevant = [path for path in files if _component_name(Path(intelligence.root_path), Path(intelligence.root_path) / path) == name]
        framework = next((item for item in intelligence.frameworks if any(item.lower() in files[path].lower() for path in relevant)), None)
        manager = intelligence.package_managers[0] if intelligence.package_managers else None
        kind = "frontend" if framework in {"React", "Vite", "Next.js"} else "backend" if framework in {"Express", "FastAPI", "Flask", "Django", "Spring Boot"} else "service"
        return {"name": name, "path": "." if name == "root" else name, "kind": kind, "framework": framework, "package_manager": manager}
