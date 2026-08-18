# Sohail Studio Architecture

Sohail Studio is a local-first AI engineering workspace combining the AI terminal/dashboard experience with the integrated Sohail-Agent-CLI engineering engine. The project is self-contained: `sohail_agent_cli/` is the authoritative CLI implementation and `.venv/` is the single Python environment.

## Final architecture

```text
Browser UI
    ↓
FastAPI
    ↓
Workflow planning
    ↓
User approval
    ↓
CliBridge
    ↓
Integrated sohail_agent_cli
    ↓
Studio .venv
    ↓
Local filesystem / Ollama
```

The raw terminal follows a separate interactive path:

```text
Browser Terminal
    ↓ WebSocket /ws/terminal
PTY
    ↓
Studio project root
    ↓
Studio .venv environment
```

There is no normal runtime dependency on a sibling CLI project or a second virtual environment.

## Project components

- `backend/main.py` serves the dashboard, REST API, workflow run manager, and WebSocket endpoints.
- `core/cli_bridge.py` maps approved Studio workflows to structured invocations of `python -m sohail_agent_cli.main` using the running Studio interpreter.
- `core/session_store.py` stores completed run state locally as JSON in `sessions/`.
- `sohail_agent_cli/` contains the integrated agents, analyzers, providers, planners, generators, workers, and CLI entry point.
- `dashboard/` contains the static HTML, CSS, JavaScript, and local visual assets.
- `terminal/` marks the terminal integration boundary.
- `settings/default.json` contains the shell, terminal working directory, and virtual-environment defaults.
- `workspace/` remains available for selected local project targets; the default embedded engineering terminal starts at the Studio root.
- `logs/` is reserved for local runtime logs.

## Workflow execution

The workflow lifecycle is approval-first:

1. The browser requests a plan with `POST /api/workflows/plan`.
2. FastAPI validates the workflow and target and returns the proposed steps with `requires_approval: true`.
3. The user reviews the plan in the dashboard.
4. The browser submits `POST /api/runs` with `approved: true`.
5. `RunManager` asks `CliBridge` to build an allowlisted command.
6. `CliBridge` launches the integrated CLI with `asyncio.create_subprocess_exec`.
7. Output and lifecycle events are sent over `/ws/runs/{run_id}`.
8. The completed run is persisted in `sessions/`.

The current Studio-backed mappings are:

| Studio workflow | CLI command |
| --- | --- |
| `inspect-project` | `inspect` |
| `dockerize-project` | `dockerize` |
| `kubernetes` | `k8s` |
| `cicd` | `cicd` |
| `documentation` | `docs` |

`create-project`, `debug-error`, and `ai-chat` remain visible dashboard placeholders and are not executable CLI workflows.

## Integrated CLI

The `sohail-agent` entry point is provided by the Studio project configuration:

```text
sohail-agent = sohail_agent_cli.main:main
```

The integrated CLI retains these commands:

```text
inspect
dockerize
k8s
cicd
docs
interview
plan
plan-v2
bootstrap
stack
specification
blueprint
all
```

Global options include `--version`, `--verbose`, `--dry-run`, `--overwrite`, and `--ollama`.

`CliBridge` keeps provider and model selections available through `SOHAIL_AI_PROVIDER` and `SOHAIL_AI_MODEL`. The integrated Ollama provider continues to use the local Ollama service and its existing `OLLAMA_BASE_URL` and `OLLAMA_MODEL` configuration.

## Raw terminal

The dashboard opens a WebSocket to `/ws/terminal`. FastAPI creates a PTY, changes the child process to the requested directory, and starts the configured shell. When no `cwd` query parameter is supplied, the child starts at the Studio root.

The PTY environment is configured inside Studio:

- `VIRTUAL_ENV` points to `sohail-studio/.venv`.
- `.venv/bin` is prepended to `PATH`.
- `PWD` is set to the PTY working directory.
- `SOHAIL_STUDIO_ROOT` identifies the project root.
- `PYTHONPATH` includes the Studio root so the integrated package is available.

The terminal supports normal input/output and the existing stop/SIGINT behavior. It does not require shell startup-file changes or manual virtual-environment activation.

## FastAPI and WebSockets

The backend exposes:

- `GET /` — dashboard shell.
- `GET /api/health` — local health and integrated CLI availability.
- `GET /api/workflows` — workflow catalog.
- `GET /api/sessions` — recent persisted runs.
- `POST /api/workflows/plan` — create a reviewable workflow plan.
- `POST /api/runs` — start an approved CLI-backed run.
- `GET /api/runs/{run_id}` — retrieve run state and buffered events.
- `WS /ws/runs/{run_id}` — stream command, output, process, completion, error, and close events.
- `WS /ws/terminal` — connect to the raw local PTY.

## Dashboard UI

The current three-column dashboard is preserved.

### Header

- Sohail avatar
- Sohail Studio branding
- Home
- Workflows
- Terminal
- Sessions
- Settings

### Left column

- Recents task
- AI Mentor
- 3D robot

### Center column

- Workspace Canvas
- Overview
- Plan
- Files
- Logs
- Documentation
- Architecture
- Diff
- Timeline
- Chat/Command Center

### Right column

- Engineering Knowledge Sphere
- Terminal / Execution Engine

The placeholder surfaces remain intentionally small until their underlying workflows are implemented.

## Security and local-first guarantees

- Workflow execution is local-first and approval-gated.
- Unknown workflow IDs are rejected.
- Only the explicit workflow mapping can start a CLI process.
- Workflow subprocesses use explicit argument lists and `create_subprocess_exec`; they do not use `shell=True`.
- The command preview is published before CLI output.
- Provider and model values are passed as environment variables, not interpolated into shell commands.
- Run state and output remain local.
- The raw PTY is exposed through the local application WebSocket and is not a hosted remote shell.
- Ollama remains an external local service; Studio does not install or start it.

## Runtime requirements

Python 3.11 or newer, the dependencies declared in `pyproject.toml`/`requirements.txt`, and a local Ollama installation are supported. The project’s `.venv/` is the only environment needed by Studio and the integrated CLI.

Run the backend from the project root with:

```bash
.venv/bin/uvicorn backend.main:app --reload
```

The integrated test suite is run with `.venv/bin/python -m pytest -q`.
