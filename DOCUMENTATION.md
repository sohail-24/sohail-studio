# Installation

Sohail Studio runs locally and relies on a local environment to orchestrate its tasks.

## Requirements

- **Python Version**: `>=3.11`

- **Virtual Environment**: It is highly recommended to use a virtual environment.

- **Dependencies**: The core backend relies on `fastapi`, `uvicorn[standard]`, and `pydantic`. The frontend has no external dependencies.

- **Sohail-Agent-CLI**: The system requires a local copy of the `Sohail-Agent-CLI`. Ensure it is accessible.

### Running Locally

To run the application locally:

```bash
# 1. Navigate to the directory
cd path/to/sohail-studio

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the development server
uvicorn backend.main:app --reload
```

Then, open your browser to `http://127.0.0.1:8000`.

---

## Project Structure

The project separates the logic into clearly defined boundaries:

- `backend/`: FastAPI application acting as the main API and WebSocket server.
- `core/`: Integration components, including the session storage layer and the process bridge to the underlying CLI.
- `dashboard/`: A purely static set of HTML, CSS, and JS files defining the interface.
- `logs/`, `sessions/`, `workspace/`: Local runtime storage for output, run records, and a default terminal environment.
- `settings/`: Basic configuration templates.

---

## Running the application

During development, use the reload flag with uvicorn:
`uvicorn backend.main:app --reload`

**Production Notes:**
This application is designed specifically as a "local-first" engineering tool. It is not currently intended for deployment to public internet-facing production environments. It relies on executing system commands and assumes single-user local access.

---

## Dashboard

The Dashboard provides a UI constructed purely from plain web technologies (HTML/JS/CSS).

## Navigation

The sidebar lets users jump between key views:

- **Home**: The central view summarizing current workspace state.

- **Workflows**: Available actions that the user can orchestrate.

- **Terminal**: A direct terminal connection (PTY) view.

- **Sessions**: History of past CLI runs and their outputs.

## Current Workflows

The UI exposes several configured workflows that either act independently or bridge to the CLI:

- **Inspect Project** (CLI backed)

- **Create New Project**

- **Dockerize Project** (CLI backed)

- **Kubernetes** (CLI backed)

- **CI/CD** (CLI backed)

- **Generate Documentation** (CLI backed)

- **Debug Error**

- **AI Chat**

---

## Backend

The backend orchestrates the dashboard's needs and communicates with the underlying execution layer.

## Available Endpoints

- `GET /`: Serves the main `index.html` file.

- `GET /api/health`: Provides a status check and validates the availability of the CLI root.

- `GET /api/workflows`: Lists all predefined workflows.

- `GET /api/sessions`: Lists recent execution sessions from local storage.
- `POST /api/workflows/plan`: Generates a pre-execution plan and requires explicit user confirmation.
- `POST /api/runs`: Submits an approved execution, assigning a run ID.

- `GET /api/runs/{run_id}`: Retrieves the static execution state of a specific run.
- `WS /ws/runs/{run_id}`: Subscribes to real-time events (commands, outputs, completions) for a given run.
- `WS /ws/terminal`: Establishes a raw pseudo-terminal session.

## Communication with CLI

The backend delegates process creation to `CliBridge` (`core/cli_bridge.py`). It does not run shell strings. Instead, it carefully constructs `sys.executable` calls that invoke the `src.main` module of the `Sohail-Agent-CLI` codebase based on the selected workflow.

---

## CLI Bridge

Sohail Studio integrates with `Sohail-Agent-CLI` strictly via process orchestration.

- **Usage**: The studio resolves the CLI root via the `SOHAIL_AGENT_ROOT` environment variable (falling back to a default path).

- **Integration**: The bridge maps the studio's workflow IDs (e.g., `kubernetes`) to the equivalent CLI commands (e.g., `k8s`). It constructs a secure argument list (`argv`) avoiding `shell=True` and capturing `stdout` and `stderr` asynchronously to feed the WebSocket connections.

---

## Terminal

Sohail Studio provides raw interactive terminal access.

- **Execution Model**: The backend establishes a pseudo-terminal (PTY) using `pty.fork()` and `os.execvp()`. The frontend terminal connects via WebSockets (`/ws/terminal`), continuously polling the PTY's file descriptor for output, and piping raw input directly to the running shell process.

- **Safety Rules**:
  - Execution relies strictly on local resources.
  - Commands executed via workflows are read-only or strictly user-approved first via the plan mechanism.
  - The CLI bridge refuses to run unmapped workflows or execute shell injections implicitly. Output logic strictly streams without intervening or inferring beyond what the underlying tool does.

---

## Development Guide

## Coding Style

- Standard Python formats are enforced using `ruff` with a line length of 100 characters.
- Frontend uses plain JavaScript (ES6+), HTML, and CSS without transpilers or external build chains.

## Folder Conventions

- Keep static assets entirely within `dashboard/`.
- Fast API orchestration should remain within `backend/`.
- Process-level boundary logic belongs strictly in `core/`.

## Adding new Workflows

1. Add the new workflow definition to the `WORKFLOWS` list in `backend/main.py`.
2. Define the workflow's step plan in the `create_plan` endpoint mapping.
3. If it requires underlying CLI execution, add the command mapping to `WORKFLOW_COMMANDS` in `core/cli_bridge.py`.

## Adding new API Endpoints

Endpoints are defined in `backend/main.py`. Define standard REST endpoints using Pydantic models for validation. Ensure any logic requiring storage utilizes the `SessionStore` inside `core/`.

## Adding Dashboard Pages

1. Update `app.js` routing logic (`setRoute`, rendering switch statement).
2. Create standard render functions in `app.js`.
3. Update HTML IDs and styles in `dashboard/index.html` and `dashboard/styles.css` if necessary.

---

## Current Limitations

- Workflows such as `Create New Project`, `Debug Error`, and `AI Chat` are currently exposed in the UI but are not explicitly mapped to `Sohail-Agent-CLI` execution commands in the bridge, acting as placeholders.
- Terminal integration uses a relatively simple polling mechanism on non-blocking file descriptors for the PTY bridge, which works well for standard local use but is not built for high-throughput buffering over high latency networks.
- The `Sohail-Agent-CLI` path is heavily dependent on a static default absolute path (`/Users/sohal/Downloads/testing-project/Sohail-Agent-CLI`) if not overwritten by the `SOHAIL_AGENT_ROOT` environment variable.

---

## Future Extensions

- Implementing remaining workflows.
- Exposing broader configuration options directly from the UI.
- Improved terminal UI handling (e.g. implementing xterm.js integration).
