"""A thin process adapter around the integrated Sohail-Agent-CLI.

This module intentionally owns process wiring only. Agent behavior, analysis,
generators, and business rules stay in the integrated CLI package.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator


DEFAULT_CLI_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENV = DEFAULT_CLI_ROOT / ".venv"


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

    AGENT_OPERATIONS = {
        "inspect": ("Inspect", "inspect", "Inspect a local repository without changing it."),
        "dockerize": ("Dockerize", "dockerize", "Generate Docker configuration through Sohail-Agent-CLI."),
        "kubernetes": ("Kubernetes", "k8s", "Generate Kubernetes manifests through Sohail-Agent-CLI."),
        "cicd": ("CI/CD", "cicd", "Generate CI/CD workflows through Sohail-Agent-CLI."),
        "plan": ("Plan", "plan", "Create a planning package through Sohail-Agent-CLI."),
        "blueprint": ("Blueprint", "blueprint", "Generate implementation blueprints through Sohail-Agent-CLI."),
    }

    def __init__(self) -> None:
        """Use the CLI package integrated into this Studio checkout."""
        self.cli_root = DEFAULT_CLI_ROOT

    @property
    def python_executable(self) -> str:
        candidate = DEFAULT_VENV / "bin" / "python"
        return str(candidate) if candidate.exists() else sys.executable

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
        args = [self.python_executable, "-m", "sohail_agent_cli.main"]
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

    def build_agent_command(
        self,
        operation: str,
        *,
        target: str = "",
        goal: str = "",
        plan_dir: str = "",
        spec_dir: str = "",
        output_dir: str = "",
        dry_run: bool = False,
        overwrite: bool = False,
        components: list[str] | None = None,
        compose_action: str = "keep",
        organization: str = "automatic",
        cicd_action: str = "analyze",
        cicd_platform: str = "jenkins",
        compose: bool = True,
    ) -> CliCommand:
        """Build a command for the Terminal Sohail-Agent operation picker."""
        if operation not in self.AGENT_OPERATIONS:
            raise ValueError(f"Unknown Sohail-Agent operation: {operation}")

        _label, command, purpose = self.AGENT_OPERATIONS[operation]
        args = [self.python_executable, "-m", "sohail_agent_cli.main"]
        if dry_run:
            args.append("--dry-run")
        if overwrite:
            args.append("--overwrite")

        if operation in {"inspect", "dockerize", "kubernetes", "cicd"}:
            if not target.strip():
                raise ValueError("A local project path is required")
            args.extend([command, target.strip()])
            if operation == "dockerize":
                for component in components or []:
                    args.extend(["--component", component])
                args.extend(["--compose-action", compose_action])
                if not compose:
                    args.append("--no-compose")
            elif operation == "kubernetes":
                for component in components or []:
                    args.extend(["--component", component])
                args.extend(["--organization", organization])
            elif operation == "cicd":
                args.extend(["--action", cicd_action, "--platform", cicd_platform])
        elif operation == "plan":
            if not goal.strip():
                raise ValueError("A planning goal is required")
            args.extend([command, goal.strip(), "--output", output_dir.strip() or "./project-plan"])
        else:
            if not plan_dir.strip() or not spec_dir.strip():
                raise ValueError("Plan directory and specification directory are required")
            args.extend([
                command,
                "--plan-dir", plan_dir.strip(),
                "--spec-dir", spec_dir.strip(),
                "--output", output_dir.strip() or "./blueprints",
            ])

        display = " ".join(self._quote(arg) for arg in args)
        return CliCommand(tuple(args), display, purpose)

    def build_console_command(self, command_text: str) -> CliCommand:
        """Build a safe argv invocation for the integrated CLI console."""
        text = command_text.strip()
        if not text:
            raise ValueError("Enter a Sohail-Agent command")
        if any(operator in text for operator in (";", "&&", "||", "|", ">", "<", "`", "$(")):
            raise ValueError("The Sohail-Agent console accepts CLI arguments, not shell operators")
        try:
            tokens = shlex.split(text)
        except ValueError as exc:
            raise ValueError(f"Invalid command quoting: {exc}") from exc
        if not tokens:
            raise ValueError("Enter a Sohail-Agent command")
        if Path(tokens[0]).name not in {"sohail-agent", "sohail-agent-cli"}:
            raise ValueError("Only the existing sohail-agent CLI is allowed here")
        args = [self.python_executable, "-m", "sohail_agent_cli.main", *tokens[1:]]
        display = " ".join(self._quote(arg) for arg in ["sohail-agent", *tokens[1:]])
        return CliCommand(
            tuple(args),
            display,
            "Interactive command-console invocation through the integrated Sohail-Agent CLI.",
        )

    async def stream(
        self,
        command: CliCommand,
        provider: str = "",
        model: str = "",
        *,
        on_start: callable | None = None,
    ) -> AsyncIterator[tuple[str, str]]:
        """Yield `(stream, chunk)` pairs from the real CLI process."""
        package_root = self.cli_root / "sohail_agent_cli"
        if not package_root.is_dir():
            raise FileNotFoundError(f"Integrated sohail_agent_cli package not found at {package_root}")

        env = {
            **os.environ,
            "PYTHONPATH": str(self.cli_root),
            "VIRTUAL_ENV": str(DEFAULT_VENV),
            "PATH": os.pathsep.join([str(DEFAULT_VENV / "bin"), os.environ.get("PATH", "")]),
        }
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
        if on_start is not None:
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
