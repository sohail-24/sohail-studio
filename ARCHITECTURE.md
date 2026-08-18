# Project Overview

Sohail Studio is a local-first AI engineering workspace. It serves as a browser-based UI for the `Sohail-Agent-CLI` tool, providing an interactive, structured, and user-friendly interface for executing AI engineering workflows.

It exists to give a user-friendly frontend to the CLI tool, allowing users to better plan, manage, and execute complex workflows without relying solely on a text interface.

**Relationship with other projects:**

- **Sohail-Agent-CLI:** Sohail Studio acts as a thin wrapper and orchestrator for the `Sohail-Agent-CLI`. The studio does not implement agent logic, business rules, or generators; it solely orchestrates them by building commands and streaming the execution output from the underlying CLI process.

- **ai-terminal-dashboard:** The Studio uses `ai-terminal-dashboard` as a reference implementation for its PTY (Pseudo-Terminal) bridge, utilizing its approach for terminal integration within the browser.

---
# High-Level Architecture

The system operates strictly locally, establishing a bridge between a web-based dashboard and local shell commands execution.

```text
 Browser UI (HTML/JS/CSS)
         ↓
 Backend API (FastAPI)
         ↓
 CLI Bridge (Process Orchestrator)
         ↓
 Sohail-Agent-CLI
         ↓
 Terminal (PTY / Subprocess)
         ↓
 Local Machine
```

---

## Folder Structure

The repository is modularly designed, separating the frontend, backend orchestration, integration bridges, and runtime storage.

- **`backend/`**: Contains the FastAPI entrypoint and API routes, acting as the primary orchestration layer, WebSocket handler, and static file server.

- **`dashboard/`**: Contains the static single-page application (HTML, CSS, JS) that serves as the user interface.

- **`terminal/`**: Holds notes and integration boundaries for the PTY bridge.

- **`core/`**: Contains core backend components, including the `CliBridge` adapter for interfacing with `Sohail-Agent-CLI` and `SessionStore` for run state management.

- **`sessions/`**: Directory for storing local run/session memory as JSON files.

- **`workspace/`**: An optional local workspace mount point and default directory for terminal execution.

- **`logs/`**: Directory for local execution logs.

- **`settings/`**: Holds safe defaults and local configuration files.

---

## Application Flow

The standard execution lifecycle of a workflow prioritizes user consent:

1. **User opens dashboard**: The user loads the UI via the browser.
2. **Selects workflow**: The user picks a predefined workflow (e.g., "Inspect Project").
3. **Backend receives request**: A plan is requested via the API, returning required steps and confirming that user approval is needed.
4. **User approves plan**: After reviewing the generated plan, the user approves the run.
5. **CLI bridge invokes Sohail-Agent-CLI**: The `CliBridge` builds a strict, non-shell command and spawns the CLI process.
6. **Terminal executes approved command**: The underlying process runs the command within the `Sohail-Agent-CLI` environment.
7. **Output streams back**: Output, process IDs, and completion statuses are streamed back to the frontend via WebSockets and saved to the session store.

---

## Backend Architecture

The backend is built with **FastAPI** (`backend/main.py`) and serves both as a traditional REST API and a real-time WebSocket server.

- **FastAPI Entrypoint**: Defined in `backend/main.py`, it mounts the static `dashboard` directory and defines the API routes.

- **API Routes**:
  - `GET /`: Serves the main dashboard application (`index.html`).
  - `GET /api/health`: Health check, returns local status and CLI availability.
  - `GET /api/workflows`: Lists available workflows.
  - `GET /api/sessions`: Returns recent session histories from local JSON files.
  - `POST /api/workflows/plan`: Generates a plan for a chosen workflow, enforcing approval workflows.
  - `POST /api/runs`: Initializes a run based on an approved plan.
  - `GET /api/runs/{run_id}`: Retrieves the state of a specific run.

- **Services**:
  - `SessionStore` (`core/session_store.py`): Manages writing and retrieving run execution details (including `updated_at` timestamps) to/from local JSON files.
  - `RunManager` (`backend/main.py`): Manages concurrent run states and publishes events via queues.

- **WebSocket Usage**:
  - `/ws/runs/{run_id}`: Streams real-time run execution events (command, output, process info, completion status, errors) to the UI.
  - `/ws/terminal`: Implements a direct PTY bridge to a local shell instance for raw terminal interaction. Supports sending input and a specific `stop` action to send `SIGINT`.

- **CLI Bridge**: `core/cli_bridge.py` acts as a process adapter. It strictly maps studio workflows to exact `Sohail-Agent-CLI` commands (e.g., `inspect`, `dockerize`, `k8s`). It executes `sys.executable -m src.main` to invoke the CLI, passes `--dry-run` and `--overwrite` flags, and securely sets `SOHAIL_AI_PROVIDER` and `SOHAIL_AI_MODEL` environment variables. It prevents shell injection by bypassing `shell=True`.

---

## Dashboard Architecture

The dashboard (`dashboard/`) is a lightweight, dependency-free Single Page Application (SPA).

- **Pages / Views**: Managed via a simple state-based routing mechanism in JavaScript (Home, Workflows, Terminal, Sessions).

- **Components**: UI is built using vanilla HTML and CSS (`index.html`, `styles.css`). Dynamic generation of components like workflow cards, terminal windows, and session lists is handled by `app.js`.

- **Layout**: The UI utilizes a strict three-column layout designed for desktop viewports:
  - **Left Column**: Contains the **Recents task** placeholder (an empty boxed area with no functional API yet) and the **AI Mentor panel**. The AI Mentor panel includes a **3D AI robot visual element**, constructed programmatically using Vanilla Three.js primitives rather than external `.glb` files. This robot functions strictly as a visual UI element, not as an autonomous AI agent. The AI Mentor panel no longer uses the old large card-style presentation.
  - **Center Column**: Contains the **Workspace Canvas** and Command Center. The workspace includes tabs like Overview, Plan, Files, Logs, Documentation, Architecture, Diff, and Timeline. Current workspace content also includes Welcome/workspace context, Current Task, Execution Plan, Recent Activity, Documentation Preview, Chat, Ask Sohail Studio input, and workflow quick actions.
  - **Right Column**: Contains the **Engineering Knowledge Sphere** (moved from the left sidebar) and the **Execution Engine / Terminal** underneath it. The Engineering Knowledge Sphere visualizes the Workspace Memory and includes nodes for learning graph data. The **Advanced Panel** (previously AI Settings) has been completely removed from the dashboard.

- **Header / Navigation**: Features a top navigation bar. The top-left branding area contains a personal avatar (`/assets/sohail-avatar.png`) that appears before the "Sohail Studio" title.

- **Navigation**: Client-side navigation updates the `state.route` variable and triggers a re-render of the main content area, interacting with backend APIs as needed.

---

## Terminal Integration

The terminal integration provides two distinct pathways: structured CLI execution and raw interactive shell access.

- **Structured CLI Execution**: Runs invoked via workflows use the `CliBridge`. Output from the `subprocess` stdout is captured asynchronously and streamed to the UI via the `/ws/runs/{run_id}` WebSocket connection.

- **Raw Interactive Shell (PTY Bridge)**:
  - The frontend connects to the `/ws/terminal` WebSocket.
  - The backend uses `pty.fork()` to spawn an interactive shell process (`/bin/bash` or equivalent).
  - A background task constantly reads from the PTY file descriptor and sends chunks to the WebSocket.
  - Incoming WebSocket messages containing input data are written directly to the PTY file descriptor.
  - Stop actions send a `SIGINT` to the shell process.


---

## CLI Bridge

`core/cli_bridge.py` builds and executes commands using the existing `Sohail-Agent-CLI` entry point. It acts as a thin process adapter and never uses implicit shell strings, protecting against shell injection.

- **Resolution:** Resolves the CLI using the `SOHAIL_AGENT_ROOT` environment variable, falling back to a default path.
- **Workflow Mapping:** Maps specific workflows (e.g., `inspect-project`, `dockerize-project`) to their corresponding CLI commands (e.g., `inspect`, `dockerize`). Unmapped workflows cannot be executed.
- **Command Construction:** Commands are explicitly constructed using a tuple argument list (e.g., `sys.executable`, `-m`, `src.main`).
- **Options and Flags:** Automatically appends `--dry-run` and `--overwrite` flags if requested. It securely injects `SOHAIL_AI_PROVIDER` and `SOHAIL_AI_MODEL` environment variables based on the active run request configuration.
- **Output Handling:** Uses `asyncio.create_subprocess_exec` to stream output and exit codes asynchronously from the real CLI process.

---

## Configuration

The application is configured through environment variables and local files:

- **Environment Variables**:
  - `SOHAIL_AGENT_ROOT`: Specifies the path to the underlying `Sohail-Agent-CLI` installation (defaults to a predefined path if unset).
  - `SOHAIL_STUDIO_SHELL`: Specifies the shell to use for the PTY bridge (defaults to `/bin/bash`).

- **Configuration Files**: `settings/default.json` contains basic configuration including:
  - `workspace_root`: The default path for the terminal.
  - `cli_root`: Fallback path for the CLI if `SOHAIL_AGENT_ROOT` is unset.
  - `shell`: Fallback shell.
  - `local_only`: Flag enforcing local execution rules.

- **Runtime Requirements**: Python 3.11+, FastAPI, Uvicorn, and Pydantic. It requires a local installation of the `Sohail-Agent-CLI` to function for CLI-backed workflows.


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

## Design Principles

Sohail Studio adheres to the following principles:

- **Local-first**: The architecture requires no cloud services or hosted assets. Storage and execution remain local.

- **User approval**: Explicit user consent is mandatory before starting any workflow execution. Plans must be approved.

- **Transparent execution**: Every execution clearly states its exact command and purpose before execution.

- **Minimal dependencies**: The frontend is built without frameworks (React, Vue, etc.) utilizing plain HTML/JS/CSS to ensure it remains fast and straightforward. 3D features are integrated via Three.js and GLTFLoader using CDN links, avoiding a frontend build step. The backend avoids complex ORMs, utilizing simple JSON files for state.

- **No duplicated logic**: The Studio intentionally offloads all agent logic and business rules to the existing `Sohail-Agent-CLI`, acting purely as an orchestration and interface layer.

---

## Current Limitations

- Workflows such as `debug-error`, `ai-chat`, and `create-project` are currently exposed in the UI but are not explicitly mapped to `Sohail-Agent-CLI` execution commands in the bridge, acting as placeholders.
- The `Recents task` section in the left sidebar is currently only a visual placeholder with no task data, API, or persistence.
- Terminal integration uses a relatively simple polling mechanism on non-blocking file descriptors for the PTY bridge, which works well for standard local use but is not built for high-throughput buffering over high latency networks.
- The `Sohail-Agent-CLI` path is heavily dependent on a static default absolute path if not overwritten by the `SOHAIL_AGENT_ROOT` environment variable.
- The local execution model strictly isolates workflows; there is currently no background daemon for continuous background processing.

---

## Future Extensions

- Implementing the remaining placeholder workflows (`debug-error`, `ai-chat`, `create-project`).
- Implementing the backend functionality and persistence for the `Recents task` feature.
- Exposing broader configuration options directly from the UI.
- Improved terminal UI handling (e.g. implementing xterm.js integration).
