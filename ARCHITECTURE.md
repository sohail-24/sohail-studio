# Sohail Studio Architecture

Sohail Studio is a self-contained local-first AI engineering workspace.

- The application uses a single Python environment (`.venv`).
- There is no standalone external CLI dependency.
- The engineering engine is integrated directly via `sohail_agent_cli/`.
- All execution requires explicit user approval.
- The UI strictly limits itself to three columns.

## System Flow

- **Browser UI** initiates workflows via HTTP REST.
- **FastAPI** generates workflow plans requiring manual approval.
- **CliBridge** builds safe execution commands from approved plans.
- **Sohail-Agent-CLI** (`sohail_agent_cli/`) executes the logic.
- **Local Filesystem** updates and **Ollama** runs inferences directly.

## Terminal Integration

- **Browser Terminal** sends raw inputs via WebSocket (`/ws/terminal`).
- **PTY** provides an interactive shell bridge.
- The shell automatically loads the `.venv` environment from the Studio root.
- The terminal does not require manual environment activation.

## Project Structure

- `backend/` serves the UI, plans workflows, and streams execution via WebSockets.
- `core/cli_bridge.py` wraps `sohail_agent_cli/` execution securely without `shell=True`.
- `sohail_agent_cli/` handles agents, generation, and orchestration.
- `dashboard/` contains the static UI (HTML, CSS, JS) and layout.
- `settings/` controls environment paths and preferred shells.
- `sessions/` locally stores JSON logs of completed workflows.
- `.venv/` is the sole Python environment handling both FastAPI and CLI operations.
