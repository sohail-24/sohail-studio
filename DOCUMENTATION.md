# Sohail Studio Documentation

## Project Overview
Sohail Studio is a local-first AI engineering workspace and DevOps control environment. It integrates an interactive 3-column web dashboard, deterministic repository inspection, structured workflow planning with human-in-the-loop approval, an isolated raw PTY terminal, and an AI engineering mentor.

The system runs entirely as a Node.js 22 TypeScript full-stack application (`server.ts` + `dashboard/`), eliminating complex external runtime dependencies.

---

## Getting Started

### Prerequisites
- **Runtime**: Node.js 22 or later
- **Package Manager**: `npm` (v10+)
- **Operating System**: Linux / macOS / POSIX environment

### Installation & Build
Install project dependencies and build the server bundle:

```bash
# Install dependencies
npm install

# Type-check the codebase
npm run lint

# Compile the server bundle
npm run build
```

### Running the Server
Start the development server with live TypeScript execution, or launch the production build:

```bash
# Start development server (via tsx on port 3000)
npm run dev

# Start production server
npm start
```

Access the studio in your browser at:
```text
http://localhost:3000
```

---

## Environment Configuration

Configure runtime options in your `.env` file or container environment:

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `PORT` | `3000` | HTTP and WebSocket server listening port. |
| `GEMINI_API_KEY` | *(Optional)* | Google Gemini API key for real-time AI mentor streaming via `gemini-2.5-flash`. |
| `SOHAIL_STUDIO_SHELL` | `/bin/bash` or `/bin/sh` | Shell binary used by the interactive terminal engine. |

*Note: If `GEMINI_API_KEY` is not provided, the studio automatically activates the built-in deterministic local mentor (`local-mentor`), providing contextual guidance on Docker, Kubernetes, CI/CD, and repository architecture without an external API key.*

---

## Core System Modules

### 1. 3-Column Dashboard UI
The dashboard (`dashboard/`) is a client-side interface built with vanilla JavaScript, modular CSS, and WebSockets:
- **Left Column**: Workflow launcher gallery and historic session logs.
- **Center Column**: Interactive 3D avatar and knowledge sphere (powered by Three.js), workflow configuration forms, and Project Intelligence inspector.
- **Right Column**: Dual-tab workspace containing the interactive Terminal (xterm.js) and the AI Mentor Chat.

### 2. Deep Inspector & Project Intelligence
The Deep Inspector scans any target directory (default: workspace root) to construct a normalized Project Intelligence snapshot:
- **Exclusion Filters**: Safely skips build artifacts and virtual environments (`.git`, `node_modules`, `.next`, `dist`, `build`, `.venv`, `__pycache__`).
- **File & Language Classification**: Analyzes file extensions across JavaScript, TypeScript, Python, Go, Rust, Java, HTML, CSS, JSON, and YAML.
- **Manifest Parsing**: Reads `package.json` to detect installed frameworks (Express, React, Next.js, Vite, Tailwind CSS) and package managers (`npm`).
- **Infrastructure Detection**: Identifies existing Dockerfiles, Compose files, Kubernetes manifests, and CI/CD configurations.
- **Port Mapping**: Discovers exposed network ports (e.g., port 3000 for web services) and links them to identified components.
- **Secret Sanitization**: Records the presence of configuration files (e.g., `.env`) without storing or exposing secret keys.

Snapshots adhere to Project Intelligence Schema v4 and are cached in memory for rapid retrieval.

### 3. Workflow Planning & Human-in-the-Loop Approval
Sohail Studio enforces explicit user consent before executing any DevOps workflow:
1. **Plan Stage (`POST /api/workflows/plan`)**: Generates an ordered step list with `requires_approval: true`.
2. **Approval Gate**: The user reviews the proposed plan in the dashboard UI.
3. **Execution Stage (`POST /api/runs`)**: Execution requires `approved: true`. The backend processes steps and streams structured progress events to the client over `/ws/runs/:run_id`.
4. **Session History**: Completed runs are recorded and saved to `sessions/history.json`.

Supported Workflows:
- `inspect-project`: Map repository structure, stack, and deployment signals.
- `create-project`: Scaffold new applications with a guided engineering brief.
- `dockerize-project`: Plan reproducible container configurations and Dockerfiles.
- `kubernetes`: Prepare production-grade Kubernetes manifests.
- `cicd`: Generate continuous integration and delivery pipelines.
- `documentation`: Turn project signals into clean developer guides.
- `debug-error`: Methodically diagnose and resolve runtime errors.
- `ai-chat`: Consult with the engineering mentor.

### 4. Interactive Terminal Engine
- **Socket Path**: `/ws/terminal?cwd=<path>`
- **Terminal Emulator**: xterm.js with full ANSI color support (`xterm-256color`).
- **Process Spawning**: Spawns an interactive login shell (`/bin/bash -i` or `/bin/sh -i`) tied directly to the WebSocket stream.
- **Signal Handling**: Supports user-initiated SIGINT (`action: "stop"`) to halt running processes, and cleans up with SIGKILL on socket closure.
- **Security Boundary**: Strictly isolated from the AI Chat; the AI cannot execute commands in the user's terminal session.

### 5. AI Engineering Mentor
- **Socket Path**: `/ws/chat`
- **Streaming Transport**: Delivers real-time incremental tokens over WebSockets.
- **AI SDK**: Uses `@google/genai` with model `gemini-2.5-flash` when `GEMINI_API_KEY` is present.
- **Local Fallback**: Employs a deterministic, rule-based mentor that provides architectural guidance for containerization, cluster deployment, pipeline automation, and stack inspection.
- **Execution Boundary**: Purely advisory; cannot perform state-mutating filesystem changes or execute shell scripts.

---

## REST & WebSocket API Reference

| Endpoint | Protocol | Purpose |
| :--- | :--- | :--- |
| `/api/health` | HTTP GET | Check server health, CLI root, and persistence engine (`in_memory`). |
| `/api/workflows` | HTTP GET | Retrieve catalog of all available workflows. |
| `/api/agent/operations` | HTTP GET | Retrieve catalog of CLI agent operations. |
| `/api/sessions` | HTTP GET | Retrieve recent session execution logs. |
| `/api/agent/project` | HTTP GET | Validate target directory path. |
| `/api/agent/context` | HTTP GET | Run Deep Inspector on target directory and return snapshot. |
| `/api/agent/intelligence`| HTTP GET | Retrieve cached Project Intelligence for target directory. |
| `/api/workflows/plan` | HTTP POST | Generate workflow plan (requires approval before run). |
| `/api/runs` | HTTP POST | Execute an approved workflow run (`approved: true` required). |
| `/api/runs/:run_id` | HTTP GET | Poll status and event log for a specific workflow run. |
| `/api/agent/runs` | HTTP POST | Execute a specialized CLI agent operation. |
| `/api/agent/console` | HTTP POST | Execute simulated CLI console command. |
| `/api/agent/runs/:id/clarification` | HTTP POST | Submit user-provided evidence to resolve clarification requests. |
| `/ws/runs/:run_id` | WebSocket | Stream real-time events for a workflow run. |
| `/ws/agent-runs/:run_id`| WebSocket | Stream real-time events for an agent operation run. |
| `/ws/terminal` | WebSocket | Two-way PTY interactive terminal session. |
| `/ws/chat` | WebSocket | Two-way AI engineering mentor chat session. |

---

## Code Quality & Verification

Verify project health and types:

```bash
# TypeScript compiler type check
npm run lint

# Bundle build verification
npm run build
```

---

## Current Limitations
- **Database Persistence**: Session history is stored in `sessions/history.json` and active runs/intelligence snapshots are held in memory. Integration with external relational databases (PostgreSQL) is designated for future phases.
- **Local Ollama Inference**: The container environment does not run an Ollama daemon; AI chat utilizes server-side Google Gemini streaming or the built-in local mentor.
- **Host Docker Access**: The environment runs inside a secured container sandbox; direct execution of local Docker builds requires an external Docker daemon connection.

