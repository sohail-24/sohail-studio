"""FastAPI orchestration layer for Sohail Studio."""

from __future__ import annotations

import asyncio
import errno
import json
import os
import pty
import shutil
import signal
from time import perf_counter
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.cli_bridge import CliBridge
from core.control_plane import ControlPlane
from core.session_store import SessionStore
from sohail_agent_cli.providers import GenerationRequest, OllamaProvider, ProviderConfig
from sohail_agent_cli.analyzers import RepoAnalyzer


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
SETTINGS_PATH = ROOT / "settings" / "default.json"


def _load_settings() -> dict[str, Any]:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


SETTINGS = _load_settings()
STUDIO_VENV = (ROOT / SETTINGS.get("venv_path", ".venv")).resolve()
DEFAULT_TERMINAL_CWD = (ROOT / SETTINGS.get("terminal_cwd", ".")).resolve()
store = SessionStore(ROOT / "sessions")
cli = CliBridge()
CHAT_MODEL = SETTINGS.get("ollama_model", "devops-qwen:latest")
chat_provider = OllamaProvider(ProviderConfig(default_model=CHAT_MODEL))
control_plane = ControlPlane(ROOT)
MAX_CHAT_MESSAGES = 12
CHAT_SYSTEM_PROMPT = """You are the Sohail Studio assistant.
Chat mode is conversational and may receive factual results from explicitly
approved read-only local inspection tools. No write or destructive tools are
available; only approved read-only results may be supplied. Never execute or claim to execute shell commands, create or delete
files, modify systems, run Docker, Git, Kubernetes, Terraform, or install
software. When a user provides a command, explain what it would do and describe
manual steps as suggestions. Never claim that an action happened unless an
authorized tool result explicitly confirms it. Use supplied local-time results
for current date/time questions; otherwise say live time is unavailable. Answer
concise technical questions clearly and do not reveal internal reasoning."""

app = FastAPI(title="Sohail Studio", version="0.1.0")
app.mount("/assets", StaticFiles(directory=DASHBOARD), name="assets")


WORKFLOWS: list[dict[str, Any]] = [
    {"id": "inspect-project", "label": "Inspect Project", "eyebrow": "Understand", "description": "Map the stack, structure, and deployment readiness.", "icon": "⌘", "cli_backed": True},
    {"id": "create-project", "label": "Create New Project", "eyebrow": "Scaffold", "description": "Shape a new project with a guided engineering brief.", "icon": "+", "cli_backed": False},
    {"id": "dockerize-project", "label": "Dockerize Project", "eyebrow": "Package", "description": "Plan a reproducible container workflow for your app.", "icon": "□", "cli_backed": True},
    {"id": "kubernetes", "label": "Kubernetes", "eyebrow": "Deploy", "description": "Prepare production-minded Kubernetes manifests.", "icon": "◇", "cli_backed": True},
    {"id": "cicd", "label": "CI/CD", "eyebrow": "Automate", "description": "Create a delivery pipeline with clear checkpoints.", "icon": "↗", "cli_backed": True},
    {"id": "documentation", "label": "Generate Documentation", "eyebrow": "Explain", "description": "Turn project knowledge into useful documentation.", "icon": "≡", "cli_backed": True},
    {"id": "debug-error", "label": "Debug Error", "eyebrow": "Resolve", "description": "Bring an error and work through it methodically.", "icon": "⊘", "cli_backed": False},
    {"id": "ai-chat", "label": "AI Chat", "eyebrow": "Think", "description": "Ask an engineering mentor before changing anything.", "icon": "✦", "cli_backed": False},
]


class PlanRequest(BaseModel):
    workflow: str
    target: str = Field(default="", description="Local project directory")
    provider: str = Field(default="")
    model: str = Field(default="")


class RunRequest(PlanRequest):
    approved: bool = False
    dry_run: bool = False
    overwrite: bool = False


class AgentRunRequest(BaseModel):
    operation: str
    target: str = ""
    goal: str = ""
    plan_dir: str = ""
    spec_dir: str = ""
    output_dir: str = ""
    dry_run: bool = False
    overwrite: bool = False
    components: list[str] = Field(default_factory=list)
    compose_action: str = "keep"
    organization: str = "automatic"
    cicd_action: str = "analyze"
    cicd_platform: str = "jenkins"
    compose: bool = True


class AgentConsoleRequest(BaseModel):
    command: str = Field(default="", description="A command for the integrated sohail-agent CLI")


@dataclass
class RunState:
    run_id: str
    workflow: str
    target: str
    provider: str = ""
    model: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    complete: bool = False

    async def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        for queue in tuple(self.subscribers):
            await queue.put(event)


class RunManager:
    def __init__(self) -> None:
        self.runs: dict[str, RunState] = {}

    def create(self, request: RunRequest) -> RunState:
        run_id = uuid.uuid4().hex[:12]
        state = RunState(run_id, request.workflow, request.target, request.provider, request.model)
        self.runs[run_id] = state
        asyncio.create_task(self._execute(state, request))
        return state

    def create_agent(self, request: AgentRunRequest) -> RunState:
        run_id = uuid.uuid4().hex[:12]
        state = RunState(run_id, request.operation, request.target or request.output_dir)
        self.runs[run_id] = state
        asyncio.create_task(self._execute_agent(state, request))
        return state

    def create_console(self, request: AgentConsoleRequest) -> RunState:
        run_id = uuid.uuid4().hex[:12]
        state = RunState(run_id, "agent-console", request.command)
        self.runs[run_id] = state
        asyncio.create_task(self._execute_console(state, request))
        return state

    async def _stream_command(self, state: RunState, command_request: Any, command: Any) -> None:
        await state.publish({"type": "command", "command": command.display, "purpose": command.purpose})
        output: list[str] = []
        async for kind, chunk in cli.stream(command, getattr(command_request, "provider", ""), getattr(command_request, "model", "")):
            if kind == "output":
                output.append(chunk)
                await state.publish({"type": "output", "message": chunk})
            else:
                code = int(chunk)
                status = "completed" if code == 0 else "failed"
                await state.publish({"type": "complete", "status": status, "exit_code": code})
                store.write(
                    state.run_id,
                    {
                        "run_id": state.run_id,
                        "workflow": state.workflow,
                        "target": state.target,
                        "status": status,
                        "exit_code": code,
                        "output": "".join(output),
                    },
                )

    async def _execute(self, state: RunState, request: RunRequest) -> None:
        target = Path(request.target).expanduser().resolve()
        try:
            command = cli.build_command(
                request.workflow,
                target,
                dry_run=request.dry_run,
                overwrite=request.overwrite,
                provider=request.provider,
                model=request.model,
            )
            await self._stream_command(state, request, command)
        except Exception as exc:  # surfaced to the UI; no fake success
            await state.publish({"type": "error", "message": str(exc)})
            store.write(
                state.run_id,
                {"run_id": state.run_id, "workflow": state.workflow, "target": state.target, "status": "error", "error": str(exc)},
            )
        finally:
            state.complete = True
            await state.publish({"type": "closed"})

    async def _execute_agent(self, state: RunState, request: AgentRunRequest) -> None:
        try:
            command = cli.build_agent_command(
                request.operation,
                target=request.target,
                goal=request.goal,
                plan_dir=request.plan_dir,
                spec_dir=request.spec_dir,
                output_dir=request.output_dir,
                dry_run=request.dry_run,
                overwrite=request.overwrite,
                components=request.components,
                compose_action=request.compose_action,
                organization=request.organization,
                cicd_action=request.cicd_action,
                cicd_platform=request.cicd_platform,
                compose=request.compose,
            )
            await self._stream_command(state, request, command)
        except Exception as exc:
            await state.publish({"type": "error", "message": str(exc)})
            store.write(
                state.run_id,
                {"run_id": state.run_id, "workflow": state.workflow, "target": state.target, "status": "error", "error": str(exc)},
            )
        finally:
            state.complete = True
            await state.publish({"type": "closed"})

    async def _execute_console(self, state: RunState, request: AgentConsoleRequest) -> None:
        try:
            command = cli.build_console_command(request.command)
            await self._stream_command(state, request, command)
        except Exception as exc:
            await state.publish({"type": "error", "message": str(exc)})
            store.write(
                state.run_id,
                {"run_id": state.run_id, "workflow": state.workflow, "target": state.target, "status": "error", "error": str(exc)},
            )
        finally:
            state.complete = True
            await state.publish({"type": "closed"})


runs = RunManager()


@app.get("/")
async def home() -> FileResponse:
    return FileResponse(DASHBOARD / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "local_only": True, "cli_root": str(cli.cli_root), "cli_available": cli.cli_root.exists()}


@app.get("/api/workflows")
async def workflows() -> list[dict[str, Any]]:
    return WORKFLOWS


@app.get("/api/agent/operations")
async def agent_operations() -> list[dict[str, Any]]:
    return [
        {"id": "inspect", "label": "Inspect", "description": "Read repository structure, stack, and deployment signals.", "requires": ["target"]},
        {"id": "dockerize", "label": "Dockerize", "description": "Generate Docker configuration for a local project.", "requires": ["target"]},
        {"id": "kubernetes", "label": "Kubernetes", "description": "Generate Kubernetes manifests for a local project.", "requires": ["target"]},
        {"id": "cicd", "label": "CI/CD", "description": "Generate CI/CD workflows for a local project.", "requires": ["target"]},
        {"id": "plan", "label": "Plan", "description": "Create a persistent planning package from a project goal.", "requires": ["goal"]},
        {"id": "blueprint", "label": "Blueprint", "description": "Generate implementation blueprints from plan and specification packages.", "requires": ["plan_dir", "spec_dir"]},
    ]


@app.get("/api/agent/context")
async def agent_context(target: str) -> dict[str, Any]:
    """Return one read-only, reusable inspection context for the GUI."""
    path = Path(target).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=400, detail="Target folder does not exist")
    return RepoAnalyzer().analyze(path).to_dict()


@app.get("/api/sessions")
async def sessions() -> list[dict[str, Any]]:
    return store.list_recent()


@app.post("/api/workflows/plan")
async def create_plan(request: PlanRequest) -> dict[str, Any]:
    workflow = next((item for item in WORKFLOWS if item["id"] == request.workflow), None)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Unknown workflow")
    target = request.target.strip()
    needs_target = request.workflow in cli.WORKFLOW_COMMANDS
    if needs_target and not target:
        raise HTTPException(status_code=400, detail="Choose a local project folder first")

    step_sets = {
        "inspect-project": ["Read only the signals needed for this repository", "Detect stack, framework, DevOps files, and entry points", "Save the inspection as project memory"],
        "dockerize-project": ["Review the detected application entry point", "Propose a minimal Docker setup", "Generate files only after approval"],
        "kubernetes": ["Review runtime and exposed port assumptions", "Draft deployment and service manifests", "Generate files only after approval"],
        "cicd": ["Identify the project test/build command", "Choose a local CI workflow shape", "Generate the workflow only after approval"],
        "documentation": ["Read the project signals needed for accurate docs", "Draft documentation sections", "Write updates only after approval"],
    }
    return {
        "workflow": workflow,
        "target": target,
        "requires_approval": True,
        "steps": step_sets.get(request.workflow, ["Clarify the engineering goal", "Create a focused plan", "Wait for approval before changes"]),
    }


@app.post("/api/runs")
async def create_run(request: RunRequest) -> dict[str, str]:
    if not request.approved:
        raise HTTPException(status_code=400, detail="A user-approved plan is required")
    if request.workflow not in cli.WORKFLOW_COMMANDS:
        raise HTTPException(status_code=400, detail="This workflow is a placeholder in the foundation release")
    target = Path(request.target).expanduser()
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail="Target folder does not exist")
    state = runs.create(request)
    return {"run_id": state.run_id}


@app.post("/api/agent/runs")
async def create_agent_run(request: AgentRunRequest) -> dict[str, str]:
    if request.operation not in cli.AGENT_OPERATIONS:
        raise HTTPException(status_code=400, detail="Unknown Sohail-Agent operation")
    try:
        cli.build_agent_command(
            request.operation,
            target=request.target,
            goal=request.goal,
            plan_dir=request.plan_dir,
            spec_dir=request.spec_dir,
            output_dir=request.output_dir,
            dry_run=request.dry_run,
            overwrite=request.overwrite,
            components=request.components,
            compose_action=request.compose_action,
            organization=request.organization,
            cicd_action=request.cicd_action,
            cicd_platform=request.cicd_platform,
            compose=request.compose,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    state = runs.create_agent(request)
    return {"run_id": state.run_id}


@app.post("/api/agent/console")
async def create_agent_console_run(request: AgentConsoleRequest) -> dict[str, str]:
    try:
        cli.build_console_command(request.command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    state = runs.create_console(request)
    return {"run_id": state.run_id}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    state = runs.runs.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": state.run_id, "workflow": state.workflow, "target": state.target, "complete": state.complete, "events": state.events}


@app.websocket("/ws/runs/{run_id}")
async def run_socket(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    state = runs.runs.get(run_id)
    if state is None:
        await websocket.send_json({"type": "error", "message": "Run not found"})
        await websocket.close()
        return
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    for event in state.events:
        await websocket.send_json(event)
    state.subscribers.add(queue)
    try:
        while True:
            if state.complete and queue.empty():
                break
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        state.subscribers.discard(queue)


@app.websocket("/ws/agent-runs/{run_id}")
async def agent_run_socket(websocket: WebSocket, run_id: str) -> None:
    await run_socket(websocket, run_id)


def _terminal_environment(cwd: Path) -> dict[str, str]:
    terminal_env = {**os.environ}
    terminal_env["VIRTUAL_ENV"] = str(STUDIO_VENV)
    terminal_env["PATH"] = os.pathsep.join(
        [str(STUDIO_VENV / "bin"), terminal_env.get("PATH", "")]
    )
    terminal_env["PWD"] = str(cwd)
    terminal_env["SOHAIL_STUDIO_ROOT"] = str(ROOT)
    terminal_env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), terminal_env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    return terminal_env


async def _pty_socket(
    websocket: WebSocket,
    *,
    cwd: Path,
    command: tuple[str, ...],
    session: str,
) -> None:
    await websocket.accept()
    terminal_env = _terminal_environment(cwd)
    if shutil.which(command[0], path=terminal_env.get("PATH")) is None:
        await websocket.send_json({
            "type": "error",
            "message": f"Executable not found for {session} session: {command[0]}",
        })
        await websocket.close()
        return

    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        os.execvpe(command[0], list(command), terminal_env)

    os.set_blocking(fd, False)
    await websocket.send_json({
        "type": "status",
        "status": "running",
        "session": session,
        "pid": pid,
        "cwd": str(cwd),
        "command": list(command),
    })

    async def read_pty() -> None:
        while True:
            try:
                await asyncio.sleep(0.02)
                data = os.read(fd, 4096).decode(errors="replace")
                if data:
                    await websocket.send_json({"type": "output", "message": data})
            except BlockingIOError:
                continue
            except asyncio.CancelledError:
                raise
            except OSError as exc:
                if exc.errno != errno.EIO:  # PTY masters report child exit as EIO on macOS.
                    try:
                        await websocket.send_json({"type": "error", "message": f"PTY read failed: {exc}"})
                    except (RuntimeError, WebSocketDisconnect):
                        pass
                try:
                    await websocket.send_json({"type": "status", "status": "exited"})
                except (RuntimeError, WebSocketDisconnect):
                    pass
                break
            except WebSocketDisconnect:
                break

    reader = asyncio.create_task(read_pty())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"action": "input", "data": raw}
            action = payload.get("action")
            if action == "input" and payload.get("data"):
                try:
                    os.write(fd, payload["data"].encode())
                except OSError as exc:
                    await websocket.send_json({"type": "error", "message": f"PTY write failed: {exc}"})
            elif action == "stop":
                try:
                    os.kill(pid, signal.SIGINT)
                    await websocket.send_json({"type": "system", "message": "\r\n[STOPPED BY USER]\r\n"})
                except ProcessLookupError:
                    await websocket.send_json({"type": "error", "message": "\r\n[SHELL PROCESS NOT FOUND]\r\n"})
    except WebSocketDisconnect:
        pass
    finally:
        reader.cancel()
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


@app.websocket("/ws/terminal")
async def terminal_socket(websocket: WebSocket) -> None:
    target = websocket.query_params.get("cwd") or str(DEFAULT_TERMINAL_CWD)
    cwd = Path(target).expanduser().resolve()
    if not cwd.exists() or not cwd.is_dir():
        cwd = DEFAULT_TERMINAL_CWD
    shell = os.getenv("SOHAIL_STUDIO_SHELL") or SETTINGS.get("shell") or "/bin/bash"
    await _pty_socket(
        websocket,
        cwd=cwd,
        command=(shell, "-i"),
        session="terminal",
    )


@app.websocket("/ws/chat")
async def chat_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    history: list[dict[str, str]] = []
    await websocket.send_json({
        "type": "status",
        "status": "ready",
        "session": "chat",
        "transport": "ollama-api",
        "model": CHAT_MODEL,
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"action": "input", "data": raw}

            if payload.get("action") not in {"input", "message"}:
                continue
            message = str(payload.get("data") or "").rstrip("\r\n")
            if not message.strip():
                continue

            previous_history = list(history)
            history.append({"role": "user", "content": message})
            if len(history) > MAX_CHAT_MESSAGES:
                history = history[-MAX_CHAT_MESSAGES:]
            request_started = perf_counter()
            tool_started = perf_counter()
            tool_results = await control_plane.inspect_many(message)
            tool_ms = (perf_counter() - tool_started) * 1000
            if tool_results:
                history.append({
                    "role": "system",
                    "content": "\n\n".join(result.as_context() for result in tool_results),
                })
                if len(history) > MAX_CHAT_MESSAGES:
                    history = history[-MAX_CHAT_MESSAGES:]
            request = GenerationRequest(
                prompt=message,
                model=CHAT_MODEL,
                system=CHAT_SYSTEM_PROMPT,
                messages=list(history),
                stream=True,
            )
            ollama_started = perf_counter()
            first_token_ms: float | None = None
            response_parts: list[str] = []
            completed_result = None
            failed = False

            async for result in chat_provider.generate_stream(request):
                if result.error:
                    failed = True
                    await websocket.send_json({"type": "error", "message": result.error})
                    break
                if result.text:
                    if first_token_ms is None:
                        first_token_ms = (perf_counter() - ollama_started) * 1000
                    response_parts.append(result.text)
                    await websocket.send_json({
                        "type": "output",
                        "message": result.text,
                        "transport": "ollama-api",
                    })
                if result.done:
                    completed_result = result
                    break

            if failed:
                history = previous_history
                continue

            assistant_text = "".join(response_parts)
            if assistant_text:
                history.append({"role": "assistant", "content": assistant_text})
            ollama_ms = (perf_counter() - ollama_started) * 1000
            total_ms = (perf_counter() - request_started) * 1000
            await websocket.send_json({
                "type": "complete",
                "status": "completed",
                "model": CHAT_MODEL,
                "timing": {
                    "first_token_ms": round(first_token_ms, 2) if first_token_ms is not None else None,
                    "server_ms": round(ollama_ms, 2),
                    "request_ms": round(total_ms, 2),
                    "tool_ms": round(tool_ms, 2),
                    "tool_names": [result.name for result in tool_results],
                    "ollama_total_duration_ms": getattr(completed_result, "total_duration_ms", None),
                    "load_duration_ms": getattr(completed_result, "load_duration_ms", None),
                    "prompt_eval_count": getattr(completed_result, "prompt_eval_count", None),
                    "eval_count": getattr(completed_result, "eval_count", None),
                },
            })
    except WebSocketDisconnect:
        pass
