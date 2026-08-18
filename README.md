# Sohail Studio

Sohail Studio is a local-first AI engineering workspace combining a browser dashboard, an embedded terminal, and the integrated Sohail-Agent-CLI engineering engine.

The CLI implementation lives in `sohail_agent_cli/`. Studio is self-contained: normal operation does not require a sibling CLI checkout or a second virtual environment.

## What it includes

- FastAPI backend with workflow planning, approval, execution, and WebSocket streaming.
- Three-column dashboard with the Workspace Canvas, AI Mentor, Engineering Knowledge Sphere, and Terminal / Execution Engine.
- Raw local PTY terminal that starts at the Studio project root with `.venv` on `PATH`.
- Integrated `sohail-agent` commands for repository inspection, generation, planning, and project scaffolding.
- Local session persistence and optional Ollama-backed generation.

## Install and run

From the Studio project root:

```bash
python3 -m venv .venv        # only if .venv does not already exist
.venv/bin/python -m pip install -e .
.venv/bin/uvicorn backend.main:app --reload
```

Open <http://127.0.0.1:8000>. The embedded terminal configures the same Studio environment automatically; no `source` command or directory switch is required.

## CLI

The installed entry point is:

```bash
.venv/bin/sohail-agent --help
.venv/bin/sohail-agent --version
```

Available commands:

`inspect`, `dockerize`, `k8s`, `cicd`, `docs`, `interview`, `plan`, `plan-v2`, `bootstrap`, `stack`, `specification`, `blueprint`, and `all`.

## Workflow model

Studio-backed workflows create a plan first. The user reviews and approves that plan before `CliBridge` launches an allowlisted CLI command. Output, process information, completion, and errors are streamed locally to the dashboard, and completed runs are stored in `sessions/`.

Workflow execution uses structured subprocess arguments and does not use `shell=True`. Ollama remains an external local service; Studio does not install or start it.

## Project layout

```text
backend/            FastAPI API, workflow runs, and WebSockets
core/               CliBridge and session storage
dashboard/          Static dashboard application and assets
terminal/           Terminal integration boundary
settings/           Local runtime defaults
sohail_agent_cli/   Integrated Sohail-Agent-CLI implementation
tests/              Studio and integrated CLI tests
.venv/              Single Python environment
```

## Testing

Install test dependencies and run the integrated suite:

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

The Phase 4 baseline is 146 passing tests.
