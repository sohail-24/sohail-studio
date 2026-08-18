"""A thin process adapter around the integrated Sohail-Agent-CLI.

This module intentionally owns process wiring only. Agent behavior, analysis,
generators, and business rules stay in the integrated CLI package.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator


DEFAULT_CLI_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CliCommand:
    """The exact command shown to the user before it runs."""

    argv: tuple[str, ...]
    display: str
    purpose: str


class CliBridge:
    """Build and execute commands using the integrated CLI entry point."""

    WORKFLOW_COMMANDS = {
        "inspect-project": ("inspect", "Understand repository structure, stack, and deployment readiness."),
        "dockerize-project": ("dockerize", "Generate Docker configuration through Sohail-Agent-CLI."),
        "kubernetes": ("k8s", "Generate Kubernetes manifests through Sohail-Agent-CLI."),
        "cicd": ("cicd", "Generate CI/CD workflows through Sohail-Agent-CLI."),
        "documentation": ("docs", "Generate project documentation through Sohail-Agent-CLI."),
    }

    def __init__(self) -> None:
        """Use the CLI package integrated into this Studio checkout."""
        self.cli_root = DEFAULT_CLI_ROOT

    def build_command(
        self,
        workflow: str,
        target: Path,
        *,
        dry_run: bool = False,
        overwrite: bool = False,
        provider: str = "",
        model: str = "",
    ) -> CliCommand:
        """Build one intentional CLI invocation; never use a shell string."""
        if workflow not in self.WORKFLOW_COMMANDS:
            raise ValueError(f"Workflow is not CLI-backed yet: {workflow}")
        command, purpose = self.WORKFLOW_COMMANDS[workflow]
        args = [sys.executable, "-m", "sohail_agent_cli.main"]
        if dry_run:
            args.append("--dry-run")
        if overwrite:
            args.append("--overwrite")
        args.extend([command, str(target)])
        display = " ".join(self._quote(arg) for arg in args)
        if provider:
            display = f"SOHAIL_AI_PROVIDER={self._quote(provider)} " + display
        if model:
            display = f"SOHAIL_AI_MODEL={self._quote(model)} " + display
        return CliCommand(tuple(args), display, purpose)

    async def stream(
        self,
        command: CliCommand,
        provider: str = "",
        model: str = "",
        *,
        on_start: callable,
    ) -> AsyncIterator[tuple[str, str]]:
        """Yield `(stream, chunk)` pairs from the real CLI process."""
        package_root = self.cli_root / "sohail_agent_cli"
        if not package_root.is_dir():
            raise FileNotFoundError(f"Integrated sohail_agent_cli package not found at {package_root}")

        env = {**os.environ, "PYTHONPATH": str(self.cli_root)}
        if provider:
            env["SOHAIL_AI_PROVIDER"] = provider
        if model:
            env["SOHAIL_AI_MODEL"] = model

        process = await asyncio.create_subprocess_exec(
            *command.argv,
            cwd=self.cli_root,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        on_start(process.pid)
        assert process.stdout is not None
        async for raw in process.stdout:
            yield "output", raw.decode(errors="replace")
        return_code = await process.wait()
        yield "exit", str(return_code)

    @staticmethod
    def _quote(value: str) -> str:
        if any(char in value for char in " \t\n'\""):
            return "'" + value.replace("'", "'\\''") + "'"
        return value
