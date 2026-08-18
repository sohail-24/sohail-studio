"""Technology stack detection for repositories."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class StackType(Enum):
    """Supported technology stacks."""
    PYTHON = "python"
    DJANGO = "django"
    FASTAPI = "fastapi"
    FLASK = "flask"
    NODE = "node"
    REACT = "react"
    VUE = "vue"
    ANGULAR = "angular"
    NEXTJS = "nextjs"
    GO = "go"
    RUST = "rust"
    JAVA = "java"
    KOTLIN = "kotlin"
    SCALA = "scala"
    RUBY = "ruby"
    RAILS = "rails"
    PHP = "php"
    LARAVEL = "laravel"
    ELIXIR = "elixir"
    TYPESCRIPT = "typescript"
    UNKNOWN = "unknown"


@dataclass
class DetectedStack:
    """Result of technology stack detection."""
    primary: StackType
    secondary: list[StackType] = field(default_factory=list)
    confidence: float = 0.0
    indicators: list[str] = field(default_factory=list)
    project_type: str = "unknown"
    architecture: str = "unknown"
    deployment_hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "primary": self.primary.value,
            "secondary": [s.value for s in self.secondary],
            "confidence": self.confidence,
            "indicators": self.indicators,
            "project_type": self.project_type,
            "architecture": self.architecture,
            "deployment_hints": self.deployment_hints,
        }


class StackDetector:
    """
    Detects the technology stack of a project.

    Uses file presence, dependency analysis, and project structure
    to determine the primary and secondary technology stacks.
    """

    STACK_RULES: dict[StackType, dict[str, Any]] = {
        StackType.DJANGO: {
            "files": ["manage.py"],
            "patterns_in_files": {
                "requirements.txt": ["django"],
                "pyproject.toml": ["django"],
            },
            "indicators": ["Django project detected"],
        },
        StackType.FASTAPI: {
            "files": [],
            "patterns_in_files": {
                "requirements.txt": ["fastapi", "uvicorn"],
                "pyproject.toml": ["fastapi", "uvicorn"],
            },
            "indicators": ["FastAPI application detected"],
        },
        StackType.FLASK: {
            "files": [],
            "patterns_in_files": {
                "requirements.txt": ["flask"],
                "pyproject.toml": ["flask"],
            },
            "indicators": ["Flask application detected"],
        },
        StackType.REACT: {
            "files": [],
            "patterns_in_files": {
                "package.json": ["react", "react-dom"],
            },
            "indicators": ["React frontend detected"],
        },
        StackType.VUE: {
            "files": [],
            "patterns_in_files": {
                "package.json": ["vue"],
            },
            "indicators": ["Vue.js frontend detected"],
        },
        StackType.ANGULAR: {
            "files": ["angular.json"],
            "patterns_in_files": {},
            "indicators": ["Angular application detected"],
        },
        StackType.NEXTJS: {
            "files": ["next.config.js", "next.config.ts", "next.config.mjs"],
            "patterns_in_files": {
                "package.json": ["next"],
            },
            "indicators": ["Next.js application detected"],
        },
        StackType.NODE: {
            "files": ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
            "patterns_in_files": {},
            "indicators": ["Node.js project detected"],
        },
        StackType.GO: {
            "files": ["go.mod", "go.sum"],
            "patterns_in_files": {},
            "indicators": ["Go project detected"],
        },
        StackType.RUST: {
            "files": ["Cargo.toml", "Cargo.lock"],
            "patterns_in_files": {},
            "indicators": ["Rust project detected"],
        },
        StackType.JAVA: {
            "files": ["pom.xml", "build.gradle", "gradlew"],
            "patterns_in_files": {},
            "indicators": ["Java project detected"],
        },
        StackType.RUBY: {
            "files": ["Gemfile"],
            "patterns_in_files": {},
            "indicators": ["Ruby project detected"],
        },
        StackType.RAILS: {
            "files": [],
            "patterns_in_files": {
                "Gemfile": ["rails"],
            },
            "indicators": ["Ruby on Rails application detected"],
        },
        StackType.PHP: {
            "files": ["composer.json"],
            "patterns_in_files": {},
            "indicators": ["PHP project detected"],
        },
        StackType.LARAVEL: {
            "files": ["artisan"],
            "patterns_in_files": {
                "composer.json": ["laravel"],
            },
            "indicators": ["Laravel application detected"],
        },
        StackType.PYTHON: {
            "files": ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile"],
            "patterns_in_files": {},
            "indicators": ["Python project detected"],
        },
    }

    def detect(self, directory: Path) -> DetectedStack:
        """
        Detect the technology stack of a project.

        Args:
            directory: The project directory to analyze

        Returns:
            DetectedStack with primary and secondary stacks
        """
        indicators: list[str] = []
        detected: dict[StackType, float] = {}

        # 1. Generic rule-based detection
        for stack_type, rules in self.STACK_RULES.items():
            score = 0.0
            stack_indicators: list[str] = []

            # Check root-level characteristic files
            for filename in rules["files"]:
                if (directory / filename).exists():
                    score += 1.0
                    stack_indicators.append(f"Found {filename}")

            # Check dependency patterns in known files
            for filename, patterns in rules["patterns_in_files"].items():
                file_path = directory / filename
                if file_path.exists():
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore").lower()
                        for pattern in patterns:
                            if pattern.lower() in content:
                                score += 1.5
                                stack_indicators.append(f"Found {pattern} in {filename}")
                    except Exception:
                        pass

            if score > 0:
                detected[stack_type] = detected.get(stack_type, 0.0) + score
                indicators.extend(stack_indicators)

        # 2. Structure-based detection (stronger real-world signals)
        self._apply_structure_detection(directory, detected, indicators)

        # 3. No stack found
        if not detected:
            return DetectedStack(
                primary=StackType.UNKNOWN,
                secondary=[],
                confidence=0.0,
                indicators=["No recognizable stack detected"],
                project_type="unknown",
                architecture="unknown",
                deployment_hints=[],
            )

        # 4. Sort by score
        sorted_stacks = sorted(detected.items(), key=lambda x: x[1], reverse=True)
        primary = sorted_stacks[0][0]
        primary_score = sorted_stacks[0][1]
        total_score = sum(detected.values())

        # 5. Better confidence calculation
        confidence = round(min(max(primary_score / max(total_score, 1.0), 0.35), 0.98), 2)

        # 6. Secondary stacks
        secondary = [
            stack for stack, score in sorted_stacks[1:]
            if score >= primary_score * 0.35
        ]

        # 7. Infer project metadata
        project_type, architecture, deployment_hints = self._infer_project_metadata(
            directory,
            primary,
            secondary,
        )

        return DetectedStack(
            primary=primary,
            secondary=secondary,
            confidence=confidence,
            indicators=list(dict.fromkeys(indicators)),
            project_type=project_type,
            architecture=architecture,
            deployment_hints=deployment_hints,
        )

    def _apply_structure_detection(
        self,
        directory: Path,
        detected: dict[StackType, float],
        indicators: list[str],
    ) -> None:
        """Apply recursive structure-based detection."""
        django_score, django_indicators = self._detect_django_structure(directory)
        if django_score > 0:
            detected[StackType.DJANGO] = detected.get(StackType.DJANGO, 0.0) + django_score
            indicators.extend(django_indicators)

        python_score, python_indicators = self._detect_python_structure(directory)
        if python_score > 0:
            detected[StackType.PYTHON] = detected.get(StackType.PYTHON, 0.0) + python_score
            indicators.extend(python_indicators)

        node_score, node_indicators = self._detect_node_structure(directory)
        if node_score > 0:
            detected[StackType.NODE] = detected.get(StackType.NODE, 0.0) + node_score
            indicators.extend(node_indicators)

    def _detect_django_structure(self, directory: Path) -> tuple[float, list[str]]:
        """Detect Django-specific project structure."""
        score = 0.0
        indicators: list[str] = []

        if (directory / "manage.py").exists():
            score += 3.0
            indicators.append("Found manage.py")

        settings_files = list(directory.rglob("settings.py"))
        if settings_files:
            score += 2.5
            indicators.extend([f"Found {f.relative_to(directory)}" for f in settings_files[:3]])

        urls_files = list(directory.rglob("urls.py"))
        if urls_files:
            score += 1.5
            indicators.extend([f"Found {f.relative_to(directory)}" for f in urls_files[:3]])

        wsgi_files = list(directory.rglob("wsgi.py"))
        if wsgi_files:
            score += 1.5
            indicators.extend([f"Found {f.relative_to(directory)}" for f in wsgi_files[:2]])

        asgi_files = list(directory.rglob("asgi.py"))
        if asgi_files:
            score += 1.5
            indicators.extend([f"Found {f.relative_to(directory)}" for f in asgi_files[:2]])

        if (directory / "templates").exists():
            score += 1.5
            indicators.append("Found templates/ directory")

        if (directory / "static").exists():
            score += 1.0
            indicators.append("Found static/ directory")

        if (directory / "apps").exists():
            score += 1.0
            indicators.append("Found apps/ directory")

        if (directory / "config").exists():
            score += 1.0
            indicators.append("Found config/ directory")

        if (directory / "requirements").exists():
            score += 0.5
            indicators.append("Found requirements/ directory")

        if (directory / "scripts").exists():
            score += 0.5
            indicators.append("Found scripts/ directory")

        if (directory / ".env.example").exists():
            score += 0.5
            indicators.append("Found .env.example")

        if (directory / ".github").exists():
            score += 0.5
            indicators.append("Found .github/ directory")

        if any(directory.rglob("apps.py")):
            score += 1.0
            indicators.append("Found apps.py")

        if any(directory.rglob("models.py")):
            score += 1.0
            indicators.append("Found models.py")

        if any(path.is_dir() and path.name == "migrations" for path in directory.rglob("*")):
            score += 1.0
            indicators.append("Found migrations/ directory")

        return score, indicators

    def _detect_python_structure(self, directory: Path) -> tuple[float, list[str]]:
        """Detect general Python project structure."""
        score = 0.0
        indicators: list[str] = []

        py_files = list(directory.rglob("*.py"))
        if py_files:
            score += 1.5
            indicators.append(f"Found {len(py_files)} Python source files")

        if (directory / "venv").exists() or (directory / ".venv").exists():
            score += 0.5
            indicators.append("Found virtual environment")

        return score, indicators

    def _detect_node_structure(self, directory: Path) -> tuple[float, list[str]]:
        """Detect general Node.js project structure."""
        score = 0.0
        indicators: list[str] = []

        if (directory / "package.json").exists():
            score += 2.0
            indicators.append("Found package.json")

        if (directory / "src").exists():
            if any(directory.rglob("*.js")) or any(directory.rglob("*.ts")):
                score += 1.0
                indicators.append("Found JavaScript/TypeScript source files")

        return score, indicators

    def _infer_project_metadata(
        self,
        directory: Path,
        primary: StackType,
        secondary: list[StackType],
    ) -> tuple[str, str, list[str]]:
        """Infer project type, architecture, and deployment hints."""
        project_type = "unknown"
        architecture = "unknown"
        deployment_hints: list[str] = []

        has_templates = (directory / "templates").exists()
        has_static = (directory / "static").exists()
        has_env_example = (directory / ".env.example").exists() or (directory / ".env").exists()
        has_github_actions = (directory / ".github").exists()

        if primary == StackType.DJANGO:
            project_type = "web application"
            if has_templates and has_static:
                architecture = "fullstack (server-rendered backend + frontend assets)"
            elif has_templates:
                architecture = "server-rendered web application"
            else:
                architecture = "backend application"

            deployment_hints.extend([
                "Use Gunicorn for production",
                "Handle static files during deployment",
            ])

            if has_env_example:
                deployment_hints.append("Requires environment variable configuration")

        elif primary in (StackType.FASTAPI, StackType.FLASK):
            project_type = "backend API"
            architecture = "backend service"
            deployment_hints.extend([
                "Run behind a production WSGI/ASGI server",
                "Use environment variables for config",
            ])

        elif primary in (StackType.REACT, StackType.VUE, StackType.ANGULAR, StackType.NEXTJS):
            project_type = "frontend web application"
            architecture = "frontend SPA/SSR app"
            deployment_hints.extend([
                "Build static assets before deployment",
                "Use Node-based build pipeline",
            ])

        elif primary == StackType.NODE:
            project_type = "backend or fullstack application"
            architecture = "node service"
            deployment_hints.append("Use environment variables for runtime configuration")

        elif primary == StackType.PYTHON:
            project_type = "python application"
            architecture = "backend/service"
            deployment_hints.append("Use virtual environment or containerized runtime")

        if has_github_actions:
            deployment_hints.append("CI/CD workflow directory detected")

        return project_type, architecture, list(dict.fromkeys(deployment_hints))

    def get_dependencies(self, directory: Path, stack: StackType) -> list[str]:
        """
        Extract dependencies from project files.

        Args:
            directory: The project directory
            stack: The detected stack type

        Returns:
            List of dependency names
        """
        deps: list[str] = []

        if stack in (StackType.PYTHON, StackType.DJANGO, StackType.FASTAPI, StackType.FLASK):
            deps = self._get_python_deps(directory)
        elif stack in (StackType.NODE, StackType.REACT, StackType.VUE, StackType.NEXTJS):
            deps = self._get_node_deps(directory)
        elif stack == StackType.GO:
            deps = self._get_go_deps(directory)
        elif stack == StackType.RUST:
            deps = self._get_rust_deps(directory)
        elif stack in (StackType.RUBY, StackType.RAILS):
            deps = self._get_ruby_deps(directory)
        elif stack in (StackType.PHP, StackType.LARAVEL):
            deps = self._get_php_deps(directory)

        return deps[:20]

    def _get_python_deps(self, directory: Path) -> list[str]:
        """Get Python dependencies."""
        deps: list[str] = []

        req_file = directory / "requirements.txt"
        if req_file.exists():
            try:
                content = req_file.read_text(encoding="utf-8", errors="ignore")
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        pkg = line.split("=")[0].split("<")[0].split(">")[0].split("[")[0].strip()
                        if pkg:
                            deps.append(pkg)
            except Exception:
                pass

        pyproject = directory / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8", errors="ignore")
                in_deps = False
                for line in content.splitlines():
                    if "dependencies" in line and "[" in line:
                        in_deps = True
                    elif in_deps:
                        if line.strip().startswith("[") and "dependencies" not in line:
                            in_deps = False
                        elif "=" in line or line.strip().startswith('"'):
                            pkg = line.split("=")[0].strip().strip('"\'')
                            if pkg and pkg not in ("python",):
                                deps.append(pkg)
            except Exception:
                pass

        return list(dict.fromkeys(deps))

    def _get_node_deps(self, directory: Path) -> list[str]:
        """Get Node.js dependencies."""
        deps: list[str] = []

        package_json = directory / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8", errors="ignore"))
                if "dependencies" in data:
                    deps.extend(data["dependencies"].keys())
                if "devDependencies" in data:
                    deps.extend(data["devDependencies"].keys())
            except Exception:
                pass

        return list(dict.fromkeys(deps))

    def _get_go_deps(self, directory: Path) -> list[str]:
        """Get Go dependencies."""
        deps: list[str] = []

        go_mod = directory / "go.mod"
        if go_mod.exists():
            try:
                content = go_mod.read_text(encoding="utf-8", errors="ignore")
                for line in content.splitlines():
                    if line.strip() and not line.startswith("module") and not line.startswith("go "):
                        parts = line.strip().split()
                        if parts:
                            deps.append(parts[0])
            except Exception:
                pass

        return list(dict.fromkeys(deps))

    def _get_rust_deps(self, directory: Path) -> list[str]:
        """Get Rust dependencies."""
        deps: list[str] = []

        cargo_toml = directory / "Cargo.toml"
        if cargo_toml.exists():
            try:
                content = cargo_toml.read_text(encoding="utf-8", errors="ignore")
                in_deps = False
                for line in content.splitlines():
                    if "[dependencies]" in line:
                        in_deps = True
                    elif in_deps and line.strip().startswith("["):
                        in_deps = False
                    elif in_deps and "=" in line:
                        pkg = line.split("=")[0].strip()
                        if pkg:
                            deps.append(pkg)
            except Exception:
                pass

        return list(dict.fromkeys(deps))

    def _get_ruby_deps(self, directory: Path) -> list[str]:
        """Get Ruby dependencies."""
        deps: list[str] = []

        gemfile = directory / "Gemfile"
        if gemfile.exists():
            try:
                content = gemfile.read_text(encoding="utf-8", errors="ignore")
                for line in content.splitlines():
                    if line.strip().startswith("gem "):
                        parts = line.split('"')
                        if len(parts) >= 2:
                            deps.append(parts[1])
            except Exception:
                pass

        return list(dict.fromkeys(deps))

    def _get_php_deps(self, directory: Path) -> list[str]:
        """Get PHP dependencies."""
        deps: list[str] = []

        composer = directory / "composer.json"
        if composer.exists():
            try:
                data = json.loads(composer.read_text(encoding="utf-8", errors="ignore"))
                if "require" in data:
                    deps.extend(data["require"].keys())
            except Exception:
                pass

        return list(dict.fromkeys(deps))