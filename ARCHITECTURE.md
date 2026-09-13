# Sohail Studio Architecture

## System Purpose
Sohail Studio is a local-first AI engineering workspace and DevOps control environment. It runs on a modern Node.js 22 runtime with TypeScript and Express, serving a 3-column dashboard that integrates repository inspection, guided workflow execution, an isolated interactive terminal, and AI engineering mentoring.

## High-Level Architecture
- **Browser UI**: A client-side web interface (`dashboard/`) providing an interactive 3D avatar visualizer (Three.js), terminal console (xterm.js), workflow gallery, intelligence inspector, and chat panel.
- **Server Engine (`server.ts`)**: A consolidated Node.js / Express backend running on port 3000 (`0.0.0.0`) handling HTTP REST APIs, static asset distribution, and WebSocket multiplexing.
- **REST & WebSocket Endpoints**:
  - `GET /api/health`: Health status and runtime configuration (reports `database: "in_memory"`).
  - `GET /api/workflows`: Catalog of supported DevOps workflows.
  - `GET /api/agent/operations`: Catalog of CLI agent operations.
  - `GET /api/sessions`: Historic workflow session records.
  - `GET /api/agent/context` & `/api/agent/intelligence`: Real-time and cached Project Intelligence snapshots.
  - `POST /api/workflows/plan`: Generates workflow execution plans requiring approval.
  - `POST /api/runs`: Executes approved workflows.
  - `POST /api/agent/runs`: Executes specialized agent operations (`inspect`, `dockerize`, `kubernetes`, `cicd`, `plan`, `blueprint`).
  - `POST /api/agent/console`: Handles simulated console commands.
  - `POST /api/agent/runs/:run_id/clarification`: Accepts user-provided evidence for retries.
  - `WS /ws/runs/:run_id` & `WS /ws/agent-runs/:run_id`: Real-time workflow event streaming.
  - `WS /ws/terminal`: Interactive shell execution with PTY streaming.
  - `WS /ws/chat`: Real-time AI chat with Google GenAI streaming or local fallback.
- **Data Persistence**: Active run states and Project Intelligence snapshots are maintained in-memory (`Map`), while workflow session logs are persisted to `sessions/history.json`.
- **Target Storage Boundary**: Relational database integration (PostgreSQL / Cloud SQL) is planned for durable multi-session persistence.

## Component Boundaries & Separation

### 1. AI Chat
- Operates over dedicated WebSocket `/ws/chat`.
- Integrated with the official `@google/genai` TypeScript SDK using `gemini-2.5-flash` when `GEMINI_API_KEY` is configured in the environment.
- Falls back to a deterministic, high-signal local rule-based engineering mentor (`local-mentor`) when no API key is set.
- Strictly informational and advisory; has **no direct shell execution access** and cannot mutate the filesystem or execute arbitrary commands.

### 2. Interactive Terminal Engine
- Operates over dedicated WebSocket `/ws/terminal`.
- Spawns an interactive local shell process (`/bin/bash` or `/bin/sh`, configurable via `SOHAIL_STUDIO_SHELL`) with `xterm-256color`.
- Connects stdin, stdout, and stderr directly to xterm.js via WebSocket frames.
- Supports user-initiated SIGINT interrupts via the `stop` action and cleanly issues SIGKILL upon socket disconnection.
- Strictly isolated from the AI Chat; Chat cannot inject commands into the terminal session.

### 3. Deep Inspector & Project Intelligence
- Implemented natively via `inspectTargetDirectory()` in `server.ts`.
- Traverses the target project directory (up to 6 levels deep), strictly excluding generated/cache folders (`.git`, `node_modules`, `.next`, `dist`, `build`, `.venv`, `venv`, `__pycache__`).
- Extracts deterministic evidence with file-level provenance:
  - Programming languages (`.ts`, `.js`, `.py`, `.go`, `.rs`, `.java`, `.html`, `.css`, etc.).
  - Framework detection from `package.json` dependencies (Express, React, Next.js, Vite, Tailwind CSS).
  - Infrastructure artifacts (Dockerfiles, Compose files, Kubernetes manifests, GitHub Actions / Jenkinsfiles).
  - Configuration signals (`.env*` files).
  - Application port assignments (e.g., port 3000 for web services).
- Generates a normalized Schema v4 Project Intelligence snapshot (`files`, `components`, `languages`, `frameworks`, `runtimes`, `package_managers`, `ports`, `docker`, `kubernetes`, `ci_cd`, `evidence`, `verified_patterns`).
- Snapshots are cached in-memory and accessed by downstream workflow planners.

### 4. Workflow Planning & Execution
- Multi-step workflows (`inspect-project`, `dockerize-project`, `kubernetes`, `cicd`, `documentation`, `create-project`, `debug-error`, `ai-chat`).
- **Human-in-the-Loop Approval**: `POST /api/workflows/plan` outputs plan steps with `requires_approval: true`. Execution via `POST /api/runs` strictly requires `approved: true`.
- Emits structured events (`command`, `output`, `complete`, `inspection_persisted`, `closed`) over WebSockets to provide visible progress.
- Completed runs record output summaries to `sessions/history.json`.

## Security Boundaries
- **No Unrestricted Execution in Chat**: Chat cannot run shell commands, delete files, or apply infrastructure changes.
- **PTY Isolation**: Terminal execution is confined to explicit user interaction.
- **Sanitized Secrets**: The Deep Inspector records the presence of `.env` files and variable names (e.g., `PORT`, `GEMINI_API_KEY`) but never stores or exposes secret values.
- **Exact Vector Execution**: Internal process spawns use explicit binary paths and argument arrays rather than raw `shell=True` strings.

## Current Limitations
- **Storage Layer**: Database persistence is currently in-memory (`Map` structures in `server.ts`) with local JSON logging (`sessions/history.json`). External PostgreSQL integration is not yet connected.
- **Local Ollama Inference**: Local Ollama execution is inactive in the sandboxed container runtime; AI capabilities rely on server-side Google Gemini API (`gemini-2.5-flash`) or the local fallback mentor.
- **Container Generation**: Workflow executions output verified plans and Docker/Kubernetes configurations, but direct Docker daemon execution/builds require an external Docker host.
- **Model Command Selection**: Downstream automated generators must be constrained by deterministic validation to ensure production scripts (e.g., `preview`) are selected rather than development servers (e.g., `dev`).

