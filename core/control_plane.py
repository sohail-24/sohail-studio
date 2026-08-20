"""Small, explicit read-only tool layer for Sohail Studio Chat.

The control plane deliberately exposes fixed operations only.  It never turns
model output into a shell command and every subprocess invocation below uses a
literal argument list and a bounded timeout.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Awaitable, Callable


MAX_OUTPUT = 4000
MAX_CONTEXT = 6000
COMMAND_TIMEOUT = 8.0
SKIP_DIRECTORIES = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"}


@dataclass(frozen=True)
class ToolResult:
    """Structured result returned by one registered read-only tool."""

    name: str
    payload: dict[str, Any] | None = None
    error: str | None = None

    def as_context(self) -> str:
        """Format a tool result as private context for the model."""
        if self.error:
            body = {"error": self.error}
        else:
            body = self.payload or {}
        serialized = _clip(json.dumps(body, ensure_ascii=False, indent=2), MAX_CONTEXT)
        return (
            "A Sohail Studio read-only inspection result is available below. "
            "Treat it as factual context, do not invent missing values, and do "
            "not describe any write or execution action as completed.\n"
            f"Tool: {self.name}\n"
            f"Result: {serialized}"
        )


ToolHandler = Callable[[str], Awaitable[ToolResult]]


def _clip(text: str, limit: int = MAX_OUTPUT) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n[output truncated]"


def _compact_error(text: str) -> str:
    """Keep command failures readable without forwarding diagnostic floods."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return _clip(lines[-1] if lines else "unknown error", 1000)


def _friendly_command_error(command: tuple[str, ...], detail: str) -> str:
    if command[0] == "docker":
        return "Docker is not currently available or its daemon is not running."
    if command[0] == "kubectl":
        return "Kubernetes is not currently available or no cluster is reachable."
    return f"{command[0]} inspection failed: {detail}"


async def _run_read_only(command: tuple[str, ...], cwd: Path) -> ToolResult:
    """Run one fixed read-only command without invoking a shell."""
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
    except FileNotFoundError:
        return ToolResult(command[0], error=_friendly_command_error(command, f"{command[0]} is not installed or available."))
    except subprocess.TimeoutExpired:
        return ToolResult(command[0], error=_friendly_command_error(command, f"did not respond within {COMMAND_TIMEOUT:g} seconds."))
    except OSError as exc:
        return ToolResult(command[0], error=_friendly_command_error(command, f"could not run: {exc.strerror or exc}."))

    output = _clip(completed.stdout or completed.stderr)
    if completed.returncode != 0:
        detail = _compact_error(output) if output else f"exit code {completed.returncode}"
        return ToolResult(command[0], error=_friendly_command_error(command, detail))
    return ToolResult(command[0], payload={"command": list(command), "output": output})


async def _local_time(_message: str) -> ToolResult:
    now = datetime.now().astimezone()
    return ToolResult(
        "local_time",
        payload={
            "date": now.date().isoformat(),
            "time": now.strftime("%H:%M:%S"),
            "day": now.strftime("%A"),
            "timezone": now.tzname() or "local",
        },
    )


async def _workspace_pwd(_message: str, root: Path) -> ToolResult:
    """Run the fixed read-only pwd operation in the configured workspace."""
    result = await _run_read_only(("pwd",), root)
    return ToolResult("pwd", result.payload, result.error)


async def _workspace_ls(_message: str, root: Path) -> ToolResult:
    """Run the fixed read-only ls operation in the configured workspace."""
    result = await _run_read_only(("ls",), root)
    return ToolResult("ls", result.payload, result.error)


async def _project_files(message: str, root: Path) -> ToolResult:
    if not root.exists() or not root.is_dir():
        return ToolResult("project_files", error="The configured Sohail Studio workspace is unavailable.")

    search = re.search(r"\b(?:folder|directory|file)\s+(?:named|called)\s+[\"'`]?([\w.-]+)", message, flags=re.IGNORECASE)
    if search is None:
        search = re.search(r"\bfind\b.*?\b(?:my\s+)?([\w.-]+)\s+(?:folder|directory|file)\b", message, flags=re.IGNORECASE)
    search_name = search.group(1) if search else None
    search_roots = [root, root.parent, root.parent.parent]
    if search_name:
        matches: list[dict[str, Any]] = []
        seen: set[Path] = set()
        for search_root in search_roots:
            if not search_root.exists() or not search_root.is_dir():
                continue
            for current, dirnames, filenames in os.walk(search_root):
                dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRECTORIES)
                candidates = [Path(current) / name for name in dirnames + filenames if name.lower() == search_name.lower()]
                for candidate in candidates:
                    resolved = candidate.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    try:
                        stat = resolved.stat()
                        item: dict[str, Any] = {
                            "path": str(resolved),
                            "kind": "directory" if resolved.is_dir() else "file",
                            "size_bytes": stat.st_size,
                        }
                        if resolved.is_dir() and re.search(r"dockerfile", message, flags=re.IGNORECASE):
                            dockerfile = resolved / "Dockerfile"
                            item["contains_dockerfile"] = dockerfile.is_file()
                        matches.append(item)
                    except OSError:
                        continue
                    if len(matches) >= 20:
                        break
                if len(matches) >= 20:
                    break
            if len(matches) >= 20:
                break
        return ToolResult(
            "project_files",
            payload={"workspace": str(root), "search_name": search_name, "matches": matches},
        )

    directories: list[str] = []
    files: list[str] = []
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRECTORIES)
        relative = Path(current).relative_to(root)
        for name in dirnames:
            directories.append(str(relative / name) if str(relative) != "." else name)
        for name in sorted(filenames):
            files.append(str(relative / name) if str(relative) != "." else name)

    payload: dict[str, Any] = {
        "workspace": str(root),
        "directories": directories[:120],
        "files": files[:200],
    }

    requested = re.findall(r"[\w.-]+\.(?:py|json|md|ya?ml|toml|txt)", message, flags=re.IGNORECASE)
    if requested:
        candidate = (root / requested[0]).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            candidate = root / "__not_a_workspace_file__"
        if candidate.is_file():
            try:
                payload["file_preview"] = {
                    "path": str(candidate.relative_to(root)),
                    "content": _clip(candidate.read_text(encoding="utf-8", errors="replace")),
                }
            except OSError as exc:
                payload["file_preview_error"] = str(exc)
    return ToolResult("project_files", payload=payload)


async def _docker_read(message: str, _root: Path) -> ToolResult:
    lowered = message.lower()
    if "image" in lowered:
        command = ("docker", "images")
    elif "docker" in lowered and ("running" in lowered or "container" in lowered or "status" in lowered):
        command = ("docker", "ps")
    else:
        command = ("docker", "info")
    result = await _run_read_only(command, _root)
    return ToolResult("docker_read", result.payload, result.error)


async def _git_read(message: str, root: Path) -> ToolResult:
    status = await _run_read_only(("git", "status", "--short", "--branch"), root)
    if status.error:
        return ToolResult("git_read", error=status.error)
    latest = await _run_read_only(("git", "log", "-1", "--oneline"), root)
    return ToolResult(
        "git_read",
        payload={"status": status.payload, "latest_commit": latest.payload if not latest.error else {"error": latest.error}},
    )


async def _kubernetes_read(message: str, root: Path) -> ToolResult:
    lowered = message.lower()
    if "namespace" in lowered:
        command = ("kubectl", "get", "namespaces")
    elif "node" in lowered:
        command = ("kubectl", "get", "nodes")
    elif "version" in lowered:
        command = ("kubectl", "version")
    else:
        command = ("kubectl", "get", "pods")
    result = await _run_read_only(command, root)
    return ToolResult("kubernetes_read", result.payload, result.error)


class ControlPlane:
    """Routes natural-language requests to explicitly registered tools."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.tools: dict[str, ToolHandler] = {
            "local_time": _local_time,
            "pwd": lambda message: _workspace_pwd(message, self.workspace),
            "ls": lambda message: _workspace_ls(message, self.workspace),
            "project_files": lambda message: _project_files(message, self.workspace),
            "docker_read": lambda message: _docker_read(message, self.workspace),
            "git_read": lambda message: _git_read(message, self.workspace),
            "kubernetes_read": lambda message: _kubernetes_read(message, self.workspace),
        }

    def routes(self, message: str) -> list[str]:
        """Return only the explicitly registered tools needed for this message."""
        lowered = message.lower()
        selected: list[str] = []
        if re.search(r"\b(today(?:'s|s)? date|current date|what date is it|what day is today|which day is today|current time|what time is it|date and time|local time)\b", lowered):
            selected.append("local_time")
        if re.search(r"\b(show|what is|where)\s+(?:my\s+)?(?:current\s+)?(?:working\s+)?(?:directory|folder|path)\b", lowered) or re.search(r"\b(show|run)\s+pwd\b", lowered) or "where am i" in lowered:
            selected.append("pwd")
        simple_ls_request = bool(
            re.search(r"\b(?:show|list)\s+(?:the\s+)?files?\s+(?:here|in this directory)\b", lowered)
            or re.search(r"\bls\b", lowered)
        )
        if simple_ls_request:
            selected.append("ls")
        docker_state_request = re.search(r"\b(running|status|available|installed|list|have|unhealthy|healthy)\w*\b", lowered)
        docker_resource_request = re.search(r"\b(container|image)\w*\b", lowered) and re.search(r"\b(what|which|list|show|running|have)\b", lowered)
        if "docker" in lowered and (docker_state_request or docker_resource_request):
            selected.append("docker_read")
        kubernetes_resource = re.search(r"\b(pod|pods|namespace|namespaces|node|nodes)\b", lowered)
        kubernetes_state_request = re.search(r"\b(what|which|list|show|running|exist|get|tell|version)\w*\b", lowered)
        if ("kubectl" in lowered or kubernetes_resource or ("kubernetes" in lowered and "version" in lowered)) and kubernetes_state_request:
            selected.append("kubernetes_read")
        if ("git" in lowered or "branch" in lowered or "commit" in lowered) and re.search(r"\b(branch|modified|change|status|commit|log|diff)\w*\b", lowered):
            selected.append("git_read")
        if not simple_ls_request and re.search(r"\b(project|workspace|directory|directories|file|files|folder|folders|dockerfile)\b", lowered) and re.search(r"\b(show|list|find|exist|path|what|which|inspect|read|content|check|whether|using|contains|has)\b", lowered):
            selected.append("project_files")
        return selected

    def route(self, message: str) -> str | None:
        """Backward-compatible single-tool view of the message routing."""
        return next(iter(self.routes(message)), None)

    async def inspect_many(self, message: str) -> list[ToolResult]:
        """Run the selected read-only tools and return concise structured results."""
        names = self.routes(message)
        results = await asyncio.gather(
            *(self.tools[name](message) for name in names),
            return_exceptions=True,
        )
        output: list[ToolResult] = []
        for value, name in zip(results, names):
            if isinstance(value, ToolResult):
                output.append(value)
            elif isinstance(value, Exception):
                output.append(ToolResult(name, error=f"{name} inspection is unavailable: {value}"))
        return output

    async def inspect(self, message: str) -> ToolResult | None:
        results = await self.inspect_many(message)
        return results[0] if results else None
