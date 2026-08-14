"""FastAPI orchestration layer for Sohail Studio."""

from __future__ import annotations

import asyncio
import json
import os
import pty
import signal
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.cli_bridge import CliBridge
from core.session_store import SessionStore


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
store = SessionStore(ROOT / "sessions")
cli = CliBridge()

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


class RunRequest(PlanRequest):
    approved: bool = False
    dry_run: bool = False
    overwrite: bool = False


@dataclass
class RunState:
    run_id: str
    workflow: str
    target: str
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
        state = RunState(run_id, request.workflow, request.target)
        self.runs[run_id] = state
        asyncio.create_task(self._execute(state, request))
        return state

    async def _execute(self, state: RunState, request: RunRequest) -> None:
        target = Path(request.target).expanduser().resolve()
        try:
            command = cli.build_command(
                request.workflow,
                target,
                dry_run=request.dry_run,
                overwrite=request.overwrite,
            )
            await state.publish({"type": "command", "command": command.display, "purpose": command.purpose})

            pid: int | None = None

            def record_pid(process_id: int) -> None:
                nonlocal pid
                pid = process_id

            output: list[str] = []
            async for kind, chunk in cli.stream(command, on_start=record_pid):
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
            if pid is not None:
                await state.publish({"type": "process", "pid": pid})
        except Exception as exc:  # surfaced to the UI; no fake success
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


@app.websocket("/ws/terminal")
async def terminal_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    target = websocket.query_params.get("cwd") or str(ROOT / "workspace")
    cwd = Path(target).expanduser().resolve()
    if not cwd.exists() or not cwd.is_dir():
        cwd = ROOT / "workspace"
    shell = os.getenv("SOHAIL_STUDIO_SHELL", "/bin/bash")
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        os.execvp(shell, [shell])

    os.set_blocking(fd, False)

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
            except (OSError, WebSocketDisconnect):
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
                os.write(fd, payload["data"].encode())
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
