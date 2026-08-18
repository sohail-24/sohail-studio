"""Repository analyzer for comprehensive project analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .stack_detector import DetectedStack, StackDetector


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
    has_readme: bool = False
    has_k8s: bool = False
    has_helm: bool = False
    has_terraform: bool = False
    has_makefile: bool = False
    has_env_example: bool = False
    missing_devops_files: list[str] = field(default_factory=list)
    structure_summary: str = ""
    
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
            "has_readme": self.has_readme,
            "has_k8s": self.has_k8s,
            "has_helm": self.has_helm,
            "has_terraform": self.has_terraform,
            "has_makefile": self.has_makefile,
            "has_env_example": self.has_env_example,
            "missing_devops_files": self.missing_devops_files,
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
        has_ci_cd = (directory / ".github" / "workflows").exists()
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
            has_readme=has_readme,
            has_k8s=has_k8s,
            has_helm=has_helm,
            has_terraform=has_terraform,
            has_makefile=has_makefile,
            has_env_example=has_env_example,
            missing_devops_files=missing,
            structure_summary=structure,
        )
    
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
