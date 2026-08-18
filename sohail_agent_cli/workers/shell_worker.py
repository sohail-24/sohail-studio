"""Shell worker for safe command execution."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import Any

from .base_worker import BaseWorker, WorkerResult, WorkerSafetyLevel


class ShellWorker(BaseWorker):
    """
    Worker for safe shell command execution.
    
    Provides methods for executing shell commands
    with safety checks, timeouts, and output capture.
    """
    
    # Commands that are always blocked for safety
    BLOCKED_COMMANDS = {
        "rm -rf /",
        "rm -rf /*",
        "> /dev/sda",
        "dd if=/dev/zero",
        "mkfs",
        "fdisk",
        ":(){ :|:& };:",  # Fork bomb
    }
    
    # Commands allowed at EXECUTE_SAFE level
    SAFE_COMMANDS = {
        "git",
        "docker",
        "docker-compose",
        "kubectl",
        "helm",
        "python",
        "python3",
        "pip",
        "npm",
        "yarn",
        "node",
        "go",
        "cargo",
        "make",
        "pytest",
        "black",
        "ruff",
        "mypy",
        "echo",
        "cat",
        "ls",
        "pwd",
        "mkdir",
        "touch",
        "cp",
        "mv",
        "find",
        "grep",
        "head",
        "tail",
        "wc",
    }
    
    def __init__(
        self,
        safety_level: WorkerSafetyLevel = WorkerSafetyLevel.EXECUTE_SAFE,
        dry_run: bool = False,
        timeout: float = 60.0,
        cwd: Path | None = None,
    ) -> None:
        """
        Initialize the shell worker.
        
        Args:
            safety_level: The safety level for operations
            dry_run: If True, don't actually execute commands
            timeout: Default timeout for commands
            cwd: Working directory for commands
        """
        super().__init__(safety_level, dry_run)
        self.timeout = timeout
        self.cwd = cwd or Path.cwd()
    
    async def execute(self, operation: str, **kwargs: Any) -> WorkerResult:
        """
        Execute a shell operation.
        
        Args:
            operation: The operation to execute (command string)
            **kwargs: Operation-specific arguments
        
        Returns:
            The result of the operation
        """
        return await self.run(operation, **kwargs)
    
    async def run(
        self,
        command: str,
        timeout: float | None = None,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        capture_output: bool = True,
    ) -> WorkerResult:
        """
        Run a shell command.
        
        Args:
            command: The command to run
            timeout: Timeout in seconds
            cwd: Working directory
            env: Environment variables
            capture_output: Whether to capture stdout/stderr
        
        Returns:
            WorkerResult with command output
        """
        # Check if command is blocked
        for blocked in self.BLOCKED_COMMANDS:
            if blocked in command:
                return WorkerResult.failure_result(
                    f"Command blocked for safety: {blocked}",
                    "SafetyError",
                )
        
        # Check safety level
        if not self._is_safe_command(command):
            self._check_safety(WorkerSafetyLevel.EXECUTE_UNSAFE)
        
        if self.dry_run:
            return WorkerResult.success_result(
                f"[DRY RUN] Would execute: {command}",
                {"command": command},
            )
        
        timeout = timeout or self.timeout
        cwd = cwd or self.cwd
        
        try:
            # Run the command
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE if capture_output else None,
                stderr=asyncio.subprocess.PIPE if capture_output else None,
                cwd=cwd,
                env=env,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return WorkerResult.failure_result(
                    f"Command timed out after {timeout}s: {command}",
                    "TimeoutError",
                )
            
            # Build result
            result_data: dict[str, Any] = {
                "command": command,
                "returncode": process.returncode,
            }
            
            if capture_output:
                result_data["stdout"] = stdout.decode("utf-8", errors="replace") if stdout else ""
                result_data["stderr"] = stderr.decode("utf-8", errors="replace") if stderr else ""
            
            if process.returncode == 0:
                return WorkerResult.success_result(
                    f"Command succeeded: {command[:50]}...",
                    result_data,
                )
            else:
                return WorkerResult.failure_result(
                    f"Command failed with exit code {process.returncode}: {command[:50]}...",
                    f"Exit code: {process.returncode}",
                )
        
        except Exception as e:
            return WorkerResult.failure_result(
                f"Error executing command: {e}",
                str(e),
            )
    
    async def run_safe(
        self,
        command: list[str],
        timeout: float | None = None,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> WorkerResult:
        """
        Run a command with arguments (safer than shell string).
        
        Args:
            command: Command and arguments as list
            timeout: Timeout in seconds
            cwd: Working directory
            env: Environment variables
        
        Returns:
            WorkerResult with command output
        """
        cmd_str = shlex.join(command)
        
        if self.dry_run:
            return WorkerResult.success_result(
                f"[DRY RUN] Would execute: {cmd_str}",
                {"command": cmd_str},
            )
        
        timeout = timeout or self.timeout
        cwd = cwd or self.cwd
        
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return WorkerResult.failure_result(
                    f"Command timed out after {timeout}s: {cmd_str}",
                    "TimeoutError",
                )
            
            result_data: dict[str, Any] = {
                "command": cmd_str,
                "returncode": process.returncode,
                "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
            }
            
            if process.returncode == 0:
                return WorkerResult.success_result(
                    f"Command succeeded: {cmd_str[:50]}...",
                    result_data,
                )
            else:
                return WorkerResult.failure_result(
                    f"Command failed with exit code {process.returncode}: {cmd_str[:50]}...",
                    f"Exit code: {process.returncode}",
                )
        
        except Exception as e:
            return WorkerResult.failure_result(
                f"Error executing command: {e}",
                str(e),
            )
    
    def _is_safe_command(self, command: str) -> bool:
        """
        Check if a command is in the safe list.
        
        Args:
            command: The command to check
        
        Returns:
            True if the command is considered safe
        """
        # Get the base command
        parts = command.strip().split()
        if not parts:
            return False
        
        base_cmd = parts[0]
        
        return base_cmd in self.SAFE_COMMANDS
