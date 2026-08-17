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
  - `GET /api/health`: Health check.
  - `GET /api/workflows`: Lists available workflows.
  - `GET /api/sessions`: Returns recent session histories.
  - `POST /api/workflows/plan`: Generates a plan for a chosen workflow.
  - `POST /api/runs`: Initializes a run based on an approved plan.
  - `GET /api/runs/{run_id}`: Retrieves the state of a specific run.

- **Services**:
  - `SessionStore` (`core/session_store.py`): Manages writing and retrieving run execution details to/from local JSON files.
  - `RunManager` (`backend/main.py`): Manages concurrent run states and publishes events.

- **WebSocket Usage**:
  - `/ws/runs/{run_id}`: Streams real-time run execution events (command, output, process info, completion status) to the UI.
  - `/ws/terminal`: Implements a direct PTY bridge to a local shell instance for raw terminal interaction.

- **CLI Bridge**: `core/cli_bridge.py` acts as a process adapter. It strictly maps studio workflows to exact `Sohail-Agent-CLI` commands, ensuring robust parameter quoting and preventing shell injection by bypassing `shell=True`.

---

## Dashboard Architecture

The dashboard (`dashboard/`) is a lightweight, dependency-free Single Page Application (SPA).

- **Pages / Views**: Managed via a simple state-based routing mechanism in JavaScript (Home, Workflows, Terminal, Sessions).

- **Components**: UI is built using vanilla HTML and CSS (`index.html`, `styles.css`). Dynamic generation of components like workflow cards, terminal windows, and session lists is handled by `app.js`.

- **Layout**: The dashboard follows a structured layout:
  - **Top Navigation**: Contains the main navigation routes (Home, Workflows, Terminal, Sessions).
  - **Top-Left Branding**: Displays a personal avatar (`/assets/sohail-avatar.png`) appearing *before* the "Sohail Studio" title, establishing the local workspace identity.
  - **Workspace Status**: A persistent strip showing the connection status, current directory, AI provider/model, and mode.
  - **Main Content Columns**: Features a Left side (Workspace Memory, AI Mentor), Center side (Workspace Canvas, Command Center), and Right side (Advanced Panel, Execution Engine / Terminal).
  - **AI Mentor Panel**: Located on the left side, containing an interactive **3D AI robot** visual element. The robot is programmatically rendered using Vanilla Three.js (`index.html` and `app.js`) and acts purely as a visual UI companion, *not* an autonomous AI agent.

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

## Configuration

The application is configured through environment variables and local files:

- **Environment Variables**:
  - `SOHAIL_AGENT_ROOT`: Specifies the path to the underlying `Sohail-Agent-CLI` installation (defaults to a predefined path if unset).
  - `SOHAIL_STUDIO_SHELL`: Specifies the shell to use for the PTY bridge (defaults to `/bin/bash`).

- **Configuration Files**: `settings/default.json` contains basic fallback configuration (e.g., CLI paths and local execution flags).

- **Runtime Requirements**: Python 3.11+, FastAPI, Uvicorn, and Pydantic. It requires a local installation of the `Sohail-Agent-CLI` to function for CLI-backed workflows.

---

## Design Principles

Sohail Studio adheres to the following principles:

- **Local-first**: The architecture requires no cloud services or hosted assets. Storage and execution remain local.

- **User approval**: Explicit user consent is mandatory before starting any workflow execution. Plans must be approved.

- **Transparent execution**: Every execution clearly states its exact command and purpose before execution.

- **Minimal dependencies**: The frontend is built without frameworks (React, Vue, etc.) utilizing plain HTML/JS/CSS to ensure it remains fast and straightforward. The backend avoids complex ORMs, utilizing simple JSON files for state.

- **No duplicated logic**: The Studio intentionally offloads all agent logic and business rules to the existing `Sohail-Agent-CLI`, acting purely as an orchestration and interface layer.
