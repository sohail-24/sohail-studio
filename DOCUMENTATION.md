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

### Header Elements

- **Top-left avatar**: The top-left branding area contains a personal avatar (loaded from `/assets/sohail-avatar.png`). It appears before the "Sohail Studio" title.

## Current Dashboard Layout

The UI utilizes a strict three-column layout designed for desktop viewports:

- **Left Column**: Contains the **Recents task** placeholder and the **AI Mentor panel**.
  - **Recents task**: An empty placeholder box with no current task data, API, or persistence.
  - **AI Mentor**: Features the 3D AI robot constructed programmatically with Three.js. It acts purely as a visual UI element and is not an autonomous AI agent. It also contains Play and Guide actions, and does not use the old large card-style presentation.
- **Center Column**: Contains the **Workspace Canvas** and Command Center. The workspace includes tabs (Overview, Plan, Files, Logs, Documentation, Architecture, Diff, Timeline), execution context, and quick actions like Chat, Terminal shortcut, Inspect shortcut, and "Ask Sohail Studio" input.
- **Right Column**: Contains the **Engineering Knowledge Sphere** (moved from the left sidebar) and the **Terminal** underneath it.
  - **Engineering Knowledge Sphere**: Visualizes the Workspace Memory and includes nodes for learning graph data (Docs, Python, FastAPI, Docker, Kubernetes, Git, CI/CD, Sessions).
  - The "Advanced Panel" has been completely removed.


## Navigation

The top navigation lets users jump between key views:

- **Home**: The central view summarizing current workspace state.

- **Workflows**: Available actions that the user can orchestrate.

- **Terminal**: A direct terminal connection (PTY) view.

- **Sessions**: History of past CLI runs and their outputs.

## Current Workflows

The UI exposes several configured workflows that either act independently or bridge to the CLI:

- **Inspect Project** (CLI backed)

- **Create New Project** (Placeholder)

- **Dockerize Project** (CLI backed)

- **Kubernetes** (CLI backed)

- **CI/CD** (CLI backed)

- **Generate Documentation** (CLI backed)

- **Debug Error** (Placeholder)

- **AI Chat** (Placeholder)

---

## Backend

The backend orchestrates the dashboard's needs and communicates with the underlying execution layer.

## Available Endpoints

- `GET /`: Serves the main `index.html` file.

- `GET /api/health`: Provides a status check, returning local status and validating the availability of the CLI root.

- `GET /api/workflows`: Lists all predefined workflows.

- `GET /api/sessions`: Lists recent execution sessions from local storage JSON files.
- `POST /api/workflows/plan`: Generates a pre-execution plan and enforces explicit user confirmation.
- `POST /api/runs`: Submits an approved execution, assigning a run ID.

- `GET /api/runs/{run_id}`: Retrieves the static execution state of a specific run.
- `WS /ws/runs/{run_id}`: Subscribes to real-time events (commands, outputs, process IDs, completions, errors) for a given run.
- `WS /ws/terminal`: Establishes a raw pseudo-terminal session.

## Communication with CLI

The backend delegates process creation to `CliBridge` (`core/cli_bridge.py`). It does not run shell strings. Instead, it carefully constructs `sys.executable -m src.main` calls that invoke the `Sohail-Agent-CLI` codebase based on the selected workflow.


---

## Configuration

Sohail Studio uses local configuration files and environment variables.

- **`settings/default.json`**:
  - `workspace_root`: The default path for terminal sessions.
  - `cli_root`: Fallback path for the CLI if `SOHAIL_AGENT_ROOT` is unset.
  - `shell`: Default shell for the PTY bridge (e.g. `/bin/bash`).
  - `local_only`: Flag enforcing local execution rules.

- **Environment Variables**:
  - `SOHAIL_AGENT_ROOT`: Specifies the root directory of the `Sohail-Agent-CLI` installation.
  - `SOHAIL_STUDIO_SHELL`: Shell to be used by the terminal.

---

## CLI Bridge

Sohail Studio integrates with `Sohail-Agent-CLI` strictly via process orchestration.

- **Usage**: The studio resolves the CLI root via the `SOHAIL_AGENT_ROOT` environment variable (falling back to a default path defined in `settings/default.json`).

- **Integration**: The bridge maps the studio's workflow IDs (e.g., `kubernetes`) to the equivalent CLI commands (e.g., `k8s`). It constructs a secure argument list (`argv`) avoiding `shell=True`, and appends specific flags like `--dry-run` and `--overwrite`. It also passes `SOHAIL_AI_PROVIDER` and `SOHAIL_AI_MODEL` as environment variables. The stdout and stderr are captured asynchronously to feed the WebSocket connections.

---

## Terminal

Sohail Studio provides raw interactive terminal access.

- **Execution Model**: The backend establishes a pseudo-terminal (PTY) using `pty.fork()` and `os.execvp()`. The frontend terminal connects via WebSockets (`/ws/terminal`), continuously polling the PTY's file descriptor for output, and piping raw input directly to the running shell process. If a specific "stop" payload is received, it sends a `SIGINT` to the shell process.

- **Safety Rules**:
  - Execution relies strictly on local resources.
  - Commands executed via workflows are read-only or strictly user-approved first via the plan mechanism.
  - The CLI bridge refuses to run unmapped workflows or execute shell injections implicitly. Output logic strictly streams without intervening or inferring beyond what the underlying tool does.


---

## Security / Safety Model

- **Local-first execution:** All processing and orchestration happen on the local machine.
- **Explicit workflow approval:** The application enforces a manual approval workflow for all tasks; AI-generated plans must never execute silently without user approval.
- **Transparent command execution:** The exact command and its purpose are displayed prior to execution.
- **CLI command allowlisting/mapping:** Commands are strictly mapped; Sohail Studio only runs defined commands from `Sohail-Agent-CLI`.
- **No implicit shell string execution:** To prevent shell injection vulnerabilities, structured workflows use explicit argument lists (via `CliBridge`) instead of running commands via `shell=True`.
- **Local PTY access:** Provides direct terminal bridging without remote exposure.
- **Session/run state:** Run states are isolated per execution and saved locally in JSON files for auditing.

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
- The `Recents task` section is currently only a visual placeholder with no task data, API, or persistence.
- Terminal integration uses a relatively simple polling mechanism on non-blocking file descriptors for the PTY bridge, which works well for standard local use but is not built for high-throughput buffering over high latency networks.
- The `Sohail-Agent-CLI` path is dependent on the `SOHAIL_AGENT_ROOT` environment variable or the fallback static default path.
- The local execution model strictly isolates workflows; there is currently no background daemon for continuous background processing.
---

## Future Extensions

- Implementing the remaining placeholder workflows (`Create New Project`, `Debug Error`, `AI Chat`).
- Building out backend API and task history functionality for the `Recents task` feature.
- Exposing broader configuration options directly from the UI.
- Improved terminal UI handling (e.g. implementing xterm.js integration).
