"""Repository analyzer for comprehensive project analysis."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .stack_detector import DetectedStack, StackDetector, StackType


@dataclass
class ComponentAnalysis:
    """Evidence-backed context for one independently buildable component."""

    name: str
    path: Path
    stack: DetectedStack
    package_manager: str = "unknown"
    framework: str = "unknown"
    scripts: dict[str, str] = field(default_factory=dict)
    runtime: str = "unknown"
    ports: list[int] = field(default_factory=list)
    source_dirs: list[str] = field(default_factory=list)
    important_files: list[str] = field(default_factory=list)
    has_dockerfile: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "stack": self.stack.to_dict(),
            "package_manager": self.package_manager,
            "framework": self.framework,
            "scripts": self.scripts,
            "runtime": self.runtime,
            "ports": self.ports,
            "source_dirs": self.source_dirs,
            "important_files": self.important_files,
            "has_dockerfile": self.has_dockerfile,
        }


@dataclass
class RepoAnalysis:
    """Result of repository analysis."""
    name: str
    path: Path
    stack: DetectedStack
    entry_points: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    dev_dependencies: list[str] = field(default_factory=list)
    file_counts: dict[str, int] = field(default_factory=dict)
    has_docker: bool = False
    has_docker_compose: bool = False
    has_tests: bool = False
    has_ci_cd: bool = False
    ci_cd_files: list[str] = field(default_factory=list)
    important_files: list[str] = field(default_factory=list)
    has_readme: bool = False
    has_k8s: bool = False
    has_helm: bool = False
    has_terraform: bool = False
    has_makefile: bool = False
    has_env_example: bool = False
    missing_devops_files: list[str] = field(default_factory=list)
    structure_summary: str = ""
    components: list[ComponentAnalysis] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "path": str(self.path),
            "stack": self.stack.to_dict(),
            "entry_points": self.entry_points,
            "dependencies": self.dependencies,
            "dev_dependencies": self.dev_dependencies,
            "file_counts": self.file_counts,
            "has_docker": self.has_docker,
            "has_docker_compose": self.has_docker_compose,
            "has_tests": self.has_tests,
            "has_ci_cd": self.has_ci_cd,
            "ci_cd_files": self.ci_cd_files,
            "important_files": self.important_files,
            "has_readme": self.has_readme,
            "has_k8s": self.has_k8s,
            "has_helm": self.has_helm,
            "has_terraform": self.has_terraform,
            "has_makefile": self.has_makefile,
            "has_env_example": self.has_env_example,
            "missing_devops_files": self.missing_devops_files,
            "components": [component.to_dict() for component in self.components],
        }


class RepoAnalyzer:
    """
    Analyzes repositories for structure, stack, and DevOps configuration.
    """
    
    def __init__(self) -> None:
        """Initialize the repository analyzer."""
        self.stack_detector = StackDetector()
    
    def analyze(self, directory: Path, deep: bool = True) -> RepoAnalysis:
        """
        Analyze a repository.
        
        Args:
            directory: The repository directory
            deep: Whether to perform deep analysis
        
        Returns:
            RepoAnalysis with comprehensive information
        """
        # Detect stack
        stack = self.stack_detector.detect(directory)
        
        # Get project name
        name = self._get_project_name(directory)
        
        # Check for DevOps files
        has_docker = (directory / "Dockerfile").exists()
        has_docker_compose = (directory / "docker-compose.yml").exists() or \
                             (directory / "docker-compose.yaml").exists()
        has_tests = (directory / "tests").exists() or (directory / "test").exists()
        ci_cd_files = self._find_ci_cd_files(directory)
        has_ci_cd = bool(ci_cd_files)
        has_readme = (directory / "README.md").exists() or (directory / "README.rst").exists()
        has_k8s = (directory / "k8s").exists() or (directory / "kubernetes").exists()
        has_helm = (directory / "helm").exists() or (directory / "charts").exists()
        has_terraform = (directory / "terraform").exists()
        has_makefile = (directory / "Makefile").exists()
        has_env_example = (directory / ".env.example").exists()
        
        # Find missing DevOps files
        missing = self._find_missing_files(
            has_docker, has_docker_compose, has_tests, has_ci_cd,
            has_readme, has_k8s, has_helm, has_env_example
        )
        
        # Get dependencies
        deps = self.stack_detector.get_dependencies(directory, stack.primary)
        dev_deps = self._get_dev_dependencies(directory, stack.primary)
        
        # Find entry points
        entry_points = self._find_entry_points(directory, stack.primary)
        
        # Count files by extension
        file_counts = self._count_files(directory) if deep else {}
        
        # Get structure summary
        structure = self._get_structure_summary(directory) if deep else ""
        
        return RepoAnalysis(
            name=name,
            path=directory,
            stack=stack,
            entry_points=entry_points,
            dependencies=deps,
            dev_dependencies=dev_deps,
            file_counts=file_counts,
            has_docker=has_docker,
            has_docker_compose=has_docker_compose,
            has_tests=has_tests,
            has_ci_cd=has_ci_cd,
            ci_cd_files=ci_cd_files,
            important_files=self._find_important_files(directory),
            has_readme=has_readme,
            has_k8s=has_k8s,
            has_helm=has_helm,
            has_terraform=has_terraform,
            has_makefile=has_makefile,
            has_env_example=has_env_example,
            missing_devops_files=missing,
            structure_summary=structure,
            components=self._find_components(directory),
        )

    def _find_components(self, directory: Path) -> list[ComponentAnalysis]:
        """Find buildable child components from manifests, not folder names."""
        manifest_names = {
            "package.json", "pyproject.toml", "requirements.txt", "pom.xml",
            "build.gradle", "build.gradle.kts", "go.mod", "Cargo.toml",
        }
        components: list[ComponentAnalysis] = []
        for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir() or candidate.name.startswith("."):
                continue
            if not any((candidate / manifest).is_file() for manifest in manifest_names):
                continue
            stack = self.stack_detector.detect(candidate)
            package_manager = self._package_manager(candidate)
            scripts: dict[str, str] = {}
            framework = stack.framework
            package_json = candidate / "package.json"
            if package_json.exists():
                try:
                    data = json.loads(package_json.read_text(encoding="utf-8"))
                    scripts = {str(key): str(value) for key, value in data.get("scripts", {}).items()}
                    dependencies = {
                        str(key).lower()
                        for key in [*data.get("dependencies", {}).keys(), *data.get("devDependencies", {}).keys()]
                    }
                    if "vite" in dependencies:
                        framework = "Vite"
                    if "react" in dependencies or "react-dom" in dependencies:
                        framework = "React / Vite" if "vite" in dependencies else "React"
                        stack.primary = StackType.REACT
                    if "express" in dependencies:
                        framework = "Express"
                except (OSError, json.JSONDecodeError, AttributeError):
                    pass
            source_dirs = [name for name in ("src", "public", "app", "test", "tests") if (candidate / name).is_dir()]
            important = self._component_important_files(candidate)
            ports = self._component_ports(candidate, scripts, framework)
            components.append(
                ComponentAnalysis(
                    name=candidate.name,
                    path=candidate,
                    stack=stack,
                    package_manager=package_manager,
                    framework=framework,
                    scripts=scripts,
                    runtime=stack.runtime,
                    ports=ports,
                    source_dirs=source_dirs,
                    important_files=important,
                    has_dockerfile=(candidate / "Dockerfile").is_file(),
                )
            )
        compose_text = ""
        for compose_name in ("docker-compose.yml", "docker-compose.yaml"):
            compose_path = directory / compose_name
            if compose_path.exists():
                try:
                    compose_text = compose_path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    pass
                break
        if compose_text:
            for component in components:
                block = re.search(rf"(?ms)^  {re.escape(component.name)}:\s*(.*?)(?=^  \w[\w-]*:|\Z)", compose_text)
                if not block:
                    continue
                for port_text in re.findall(r"(?:PORT=|[-\"])(\d{2,5}):(\d{2,5})", block.group(1)):
                    for value in port_text:
                        port = int(value)
                        if port not in component.ports and 1 <= port <= 65535:
                            component.ports.append(port)
                for value in re.findall(r"(?:PORT=|port:\s*)(\d{2,5})", block.group(1), flags=re.IGNORECASE):
                    port = int(value)
                    if port not in component.ports and 1 <= port <= 65535:
                        component.ports.append(port)
        return components

    @staticmethod
    def _package_manager(directory: Path) -> str:
        if (directory / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (directory / "yarn.lock").exists():
            return "yarn"
        if (directory / "package-lock.json").exists():
            return "npm"
        if (directory / "Pipfile").exists():
            return "pipenv"
        if (directory / "pyproject.toml").exists() or (directory / "requirements.txt").exists():
            return "pip"
        if (directory / "pom.xml").exists() or (directory / "mvnw").exists():
            return "maven"
        if (directory / "go.mod").exists():
            return "go modules"
        if (directory / "Cargo.toml").exists():
            return "cargo"
        return "unknown"

    @staticmethod
    def _component_important_files(directory: Path) -> list[str]:
        names = [
            "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
            "vite.config.js", "vite.config.ts", "tailwind.config.js", "nginx.conf",
            "pyproject.toml", "requirements.txt", "pom.xml", "mvnw", "Dockerfile",
        ]
        return [name for name in names if (directory / name).exists()]

    @staticmethod
    def _component_ports(directory: Path, scripts: dict[str, str], framework: str) -> list[int]:
        """Extract explicit ports from scripts/config/source with conservative defaults."""
        text_parts: list[str] = list(scripts.values())
        for candidate in ("vite.config.js", "vite.config.ts", "nginx.conf", "src/index.js", "src/index.ts", "src/main.js", "src/main.ts"):
            path = directory / candidate
            if path.exists():
                try:
                    text_parts.append(path.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    pass
        text = "\n".join(text_parts)
        values: list[int] = []
        patterns = [
            r"(?:PORT|port)\s*(?:[:=]|\|\|)\s*(\d{2,5})",
            r"listen\s+(\d{2,5})",
            r"--port\s*(?:=|\s)\s*(\d{2,5})",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                port = int(match.group(1))
                if 1 <= port <= 65535 and port not in values:
                    values.append(port)
        if not values and framework == "React / Vite" and (directory / "nginx.conf").exists():
            values.append(80)
        return values

    def _find_ci_cd_files(self, directory: Path) -> list[str]:
        """Find common CI/CD configuration without treating a directory alone as a file."""
        candidates = [
            "Jenkinsfile",
            ".gitlab-ci.yml",
            ".circleci/config.yml",
        ]
        found = [item for item in candidates if (directory / item).is_file()]
        workflows = directory / ".github" / "workflows"
        if workflows.is_dir():
            found.extend(str(path.relative_to(directory)) for path in sorted(workflows.glob("*")) if path.is_file())
        return found

    def _find_important_files(self, directory: Path) -> list[str]:
        """Return high-signal manifests and deployment files for inspection output."""
        names = [
            "pom.xml", "mvnw", "mvnw.cmd", "build.gradle", "build.gradle.kts", "gradlew",
            "pyproject.toml", "requirements.txt", "setup.py", "Pipfile",
            "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "go.mod", "Cargo.toml",
            "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "README.md", "Jenkinsfile",
        ]
        found = [name for name in names if (directory / name).exists()]
        for name in ("src", "tests", "test", "k8s", "kubernetes"):
            if (directory / name).is_dir():
                found.append(f"{name}/")
        return found
    
    def _get_project_name(self, directory: Path) -> str:
        """Get project name from common sources."""
        # Try pyproject.toml
        pyproject = directory / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text()
                for line in content.split("\n"):
                    if line.strip().startswith("name") and "=" in line:
                        return line.split("=")[1].strip().strip('"\'')
            except Exception:
                pass
        
        # Try package.json
        package_json = directory / "package.json"
        if package_json.exists():
            try:
                import json
                data = json.loads(package_json.read_text())
                if "name" in data:
                    return data["name"]
            except Exception:
                pass
        
        # Try Cargo.toml
        cargo = directory / "Cargo.toml"
        if cargo.exists():
            try:
                content = cargo.read_text()
                for line in content.split("\n"):
                    if line.strip().startswith("name") and "=" in line:
                        return line.split("=")[1].strip().strip('"\'')
            except Exception:
                pass
        
        # Fallback to directory name
        return directory.name
    
    def _find_missing_files(
        self,
        has_docker: bool,
        has_docker_compose: bool,
        has_tests: bool,
        has_ci_cd: bool,
        has_readme: bool,
        has_k8s: bool,
        has_helm: bool,
        has_env_example: bool,
    ) -> list[str]:
        """Find missing DevOps files."""
        missing: list[str] = []
        
        if not has_docker:
            missing.append("Dockerfile")
        if not has_docker_compose:
            missing.append("docker-compose.yml")
        if not has_tests:
            missing.append("Test suite")
        if not has_ci_cd:
            missing.append("CI/CD workflow (.github/workflows)")
        if not has_readme:
            missing.append("README.md")
        if not has_k8s:
            missing.append("Kubernetes manifests")
        if not has_helm:
            missing.append("Helm charts")
        if not has_env_example:
            missing.append(".env.example")
        
        return missing
    
    def _get_dev_dependencies(self, directory: Path, stack: Any) -> list[str]:
        """Get development dependencies."""
        deps: list[str] = []
        
        # Node.js dev dependencies
        package_json = directory / "package.json"
        if package_json.exists():
            try:
                import json
                data = json.loads(package_json.read_text())
                if "devDependencies" in data:
                    deps.extend(data["devDependencies"].keys())
            except Exception:
                pass
        
        return deps[:20]
    
    def _find_entry_points(self, directory: Path, stack: Any) -> list[str]:
        """Find likely entry points."""
        entry_points: list[str] = []
        stack_value = stack.value if hasattr(stack, 'value') else str(stack)
        
        if stack_value in ("python", "django", "fastapi", "flask"):
            candidates = [
                "main.py", "app.py", "manage.py", "wsgi.py", "asgi.py",
                "__main__.py", "server.py", "run.py", "cli.py",
            ]
            for candidate in candidates:
                if (directory / candidate).exists():
                    entry_points.append(candidate)
            
            # Look for package with __main__.py
            for subdir in directory.iterdir():
                if subdir.is_dir() and (subdir / "__main__.py").exists():
                    entry_points.append(f"{subdir.name}/__main__.py")
        
        elif stack_value in ("node", "react", "nextjs"):
            candidates = ["index.js", "server.js", "app.js", "main.js", "index.ts", "server.ts"]
            for candidate in candidates:
                if (directory / candidate).exists():
                    entry_points.append(candidate)
        
        elif stack_value == "go":
            for go_file in directory.rglob("*.go"):
                try:
                    content = go_file.read_text()
                    if "package main" in content and "func main()" in content:
                        rel_path = go_file.relative_to(directory)
                        entry_points.append(str(rel_path))
                except Exception:
                    pass
        
        return entry_points[:5]
    
    def _count_files(self, directory: Path) -> dict[str, int]:
        """Count files by extension."""
        counts: dict[str, int] = {}
        
        extensions = [".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".rb", ".php"]
        
        for ext in extensions:
            count = len(list(directory.rglob(f"*{ext}")))
            if count > 0:
                counts[ext] = count
        
        return counts
    
    def _get_structure_summary(self, directory: Path, max_depth: int = 2) -> str:
        """Get a summary of directory structure."""
        lines: list[str] = [f"{directory.name}/"]
        
        def _tree(path: Path, prefix: str = "", depth: int = 0) -> None:
            if depth >= max_depth:
                return
            
            try:
                entries = sorted(
                    [e for e in path.iterdir() if not e.name.startswith(".")],
                    key=lambda e: (e.is_file(), e.name.lower())
                )[:20]  # Limit entries
            except PermissionError:
                return
            
            for i, entry in enumerate(entries):
                is_last = i == len(entries) - 1
                connector = "└── " if is_last else "├── "
                lines.append(f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}")
                
                if entry.is_dir():
                    extension = "    " if is_last else "│   "
                    _tree(entry, prefix + extension, depth + 1)
        
        _tree(directory)
        return "\n".join(lines)
