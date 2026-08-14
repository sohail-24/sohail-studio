# Sohail Studio

Sohail Studio is a local-first AI engineering workspace. It gives the existing
Sohail-Agent-CLI a browser UI and keeps the existing `ai-terminal-dashboard`
available as the reference implementation for the PTY bridge.

## Architecture

```text
dashboard/  static single-page GUI
backend/    FastAPI API, run orchestration, and WebSocket endpoints
terminal/   PTY bridge notes and integration boundary
core/       adapter to the existing Sohail-Agent-CLI
sessions/   local run/session memory (ignored except for .gitkeep)
workspace/  optional local workspace mount point
logs/       local execution logs (ignored except for .gitkeep)
settings/   safe defaults and local configuration
```

The backend does not copy or reimplement agent logic. It invokes the existing
CLI checkout through `core/cli_bridge.py`. Set `SOHAIL_AGENT_ROOT` when the CLI
lives somewhere else.

## Run locally

```bash
cd /Users/sohal/Downloads/testing-project/sohail-studio
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000.

No cloud service or hosted asset is required. The dashboard is plain HTML,
CSS, and JavaScript so it can remain fast and offline-friendly.

## Safety model

- A workflow first produces a plan in the browser.
- The user must approve a plan before a CLI run is started.
- Each run emits its exact command and purpose before streaming real output.
- `git`, filesystem discovery, and other shell commands are not run implicitly.
- Generated files remain controlled by the underlying CLI flags and user approval.

## Relationship to the existing projects

The following projects are intentionally not modified:

- `/Users/sohal/Downloads/testing-project/Sohail-Agent-CLI`
- `/Users/sohal/Downloads/testing-project/ai-terminal-dashboard`

Sohail Studio references the CLI at runtime and uses the dashboard's PTY
approach as the integration reference.
