"""Base agent class for all agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from rich.console import Console

from sohail_agent_cli.analyzers import RepoAnalyzer, RepoAnalysis
from sohail_agent_cli.workers import FileWorker, WorkerSafetyLevel

console = Console()


class AgentResult:
    """Result from agent execution."""

    def __init__(
        self,
        success: bool,
        message: str,
        error: str | None = None,
        files_created: list[Path] | None = None,
        files_skipped: list[Path] | None = None,
        data: dict[str, Any] | None = None,
    ):
        self.success = success
        self.message = message
        self.error = error
        self.files_created = files_created or []
        self.files_skipped = files_skipped or []
        self.data = data or {}

    @classmethod
    def success(
        cls,
        message: str,
        files_created: list[Path] | None = None,
        data: dict[str, Any] | None = None,
    ) -> AgentResult:
        return cls(
            success=True,
            message=message,
            files_created=files_created,
            data=data,
        )

    @classmethod
    def failure(cls, message: str, error: str | None = None) -> AgentResult:
        return cls(
            success=False,
            message=message,
            error=error,
        )


class BaseAgent(ABC):
    """Base class for all agents."""

    def __init__(
        self,
        name: str,
        description: str,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.dry_run = dry_run
        self.verbose = verbose

        # Default worker for normal safe writes
        self.file_worker = FileWorker(
            safety_level=WorkerSafetyLevel.WRITE_SAFE,
            dry_run=dry_run,
        )

        self.repo_analyzer = RepoAnalyzer()

    def log(self, message: str, style: str = "") -> None:
        """Log a message if verbose."""
        if self.verbose:
            if style:
                console.print(f"[{style}]{message}[/{style}]")
            else:
                console.print(message)

    def info(self, message: str) -> None:
        """Print info message."""
        console.print(f"[cyan]ℹ[/cyan] {message}")

    def success(self, message: str) -> None:
        """Print success message."""
        console.print(f"[green]✓[/green] {message}")

    def warning(self, message: str) -> None:
        """Print warning message."""
        console.print(f"[yellow]⚠[/yellow] {message}")

    def error(self, message: str) -> None:
        """Print error message."""
        console.print(f"[red]✗[/red] {message}")

    async def analyze_repo(self, path: Path) -> RepoAnalysis:
        """Analyze a repository."""
        self.log(f"Analyzing repository: {path}")
        return self.repo_analyzer.analyze(path)

    async def write_file(
        self,
        path: Path,
        content: str,
        overwrite: bool = False,
    ) -> tuple[bool, str, bool]:
        """
        Write a file using the file worker.

        Returns:
            tuple[success, message, is_dry_run]
        """
        # If file exists and overwrite is not allowed, skip early
        if path.exists() and not overwrite:
            return False, f"File exists (use --overwrite): {path}", False

        # Dynamically choose safety level
        worker = FileWorker(
            safety_level=(
                WorkerSafetyLevel.WRITE_UNSAFE
                if overwrite
                else WorkerSafetyLevel.WRITE_SAFE
            ),
            dry_run=self.dry_run,
        )

        try:
            result = await worker.write(
                path=path,
                content=content,
                overwrite=overwrite,
            )

            is_dry_run = "[DRY RUN]" in result.message

            if result.success:
                return True, result.message, is_dry_run
            else:
                return False, result.message, False

        except PermissionError as e:
            return False, f"Permission error while writing {path}: {e}", False
        except Exception as e:
            return False, f"Unexpected error while writing {path}: {e}", False

    @abstractmethod
    
    async def execute(self, *args: Any, **kwargs: Any) -> AgentResult:
        """Execute the agent's main task."""
        pass
    