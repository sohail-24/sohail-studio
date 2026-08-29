# Sohail Studio Architecture

## Purpose
Sohail Studio is a self-contained local-first AI engineering workspace. The application uses a single Python environment (`.venv`), avoiding the need for a separate CLI installation. It integrates a 3-column UI providing Chat, Workspace, and Terminal elements.

## High-Level Architecture
- **Browser UI** initiates workflows and handles interactions via HTTP REST and WebSockets.
- **FastAPI** generates workflow plans requiring manual approval and serves the static dashboard (`dashboard/`).
- **AI Control Plane** serves as an explicit, read-only boundary for the AI Chat to observe local state safely (`core/control_plane.py`). It strictly uses `shell=False`.
- **Sohail-Agent-CLI** (`sohail_agent_cli/`) acts as the underlying execution bridge. All CLI commands are invoked securely via exact argument lists (no `shell=True`).
- **Terminal** uses an isolated PTY socket (`/ws/terminal`), independent from the AI Chat.
- **Local Filesystem** updates and **Ollama** runs inferences directly locally.
- **Sessions** stores JSON logs of completed workflows (`sessions/`).

## Chat Architecture
The Chat provides conversational AI access through Ollama via `/api/chat` using the model `devops-qwen` via the HTTP API, not managed directly by Studio.
It processes both standard knowledge queries and context-aware queries concerning the local workspace.

## AI Control Plane
The Control Plane is a critical security and capability layer. It dictates whether local information is required, safely fetching it without allowing arbitrary shell access or destructive actions.

## Read-Only Capabilities
The AI Control Plane is explicitly restricted to safe local tools (e.g., `local_time`, `project_files`, `pwd`, `docker_read`, `git_read`, `kubernetes_read`). Multi-part requests can route sequentially to multiple tools before the model provides a final answer.

## Terminal Architecture
The Terminal operates completely isolated from the Chat and Control Plane to prevent unintended operations and maintain a strict security boundary.
```text
Terminal → WebSocket → Real local PTY → Shell → Real terminal output
```

## Ollama Integration
Sohail Studio relies completely on local inference via Ollama. It does not use external cloud models.
The active local model is **`devops-qwen`** (based on Qwen3 4B Q4_K_M). It interfaces with Ollama as an external HTTP API and does not start or manage the Ollama process.

## PostgreSQL storage foundation
The storage boundary uses PostgreSQL (e.g., hosted by Neon). It is configured only
through the environment variable `DATABASE_URL`; credentials are never stored
in source or returned by health checks. Migrations are managed via Alembic (`migrations/`).

## Deep Inspector and Project Intelligence
The Deep Inspector (`sohail_agent_cli/inspection/`) recursively discovers the
current repository, excludes generated/cache directories and secret-bearing
files, classifies discovered files, and extracts deterministic engineering
evidence with source-file provenance. Components
are reported only when manifests and source/configuration evidence show an
independently runnable or deployable unit. It does not call Ollama and does not store
source contents.

Each successful inspection creates a new inspection run. The normalized
Project Intelligence snapshot and evidence are persisted through the existing PostgreSQL
storage layer (`core/storage/project_intelligence.py`). Port candidates retain their source and conflicts rather than
being silently merged.

The inspector never stores `.env` secrets, private keys, credentials, tokens,
or raw source contents.

## Dockerize Workflow
Dockerize retrieves the latest successful Project Intelligence snapshot
through the existing storage repository, scopes it to the selected components,
and sends only that focused context to `devops-qwen` via the Context Builder. Ollama
returns a structured decision; Sohail-Agent applies deterministic validation (`sohail_agent_cli/dockerize/validation.py`) on runtime, commands, paths, services, and
ports before rendering any Dockerfiles or Compose services. Missing or conflicting evidence fails safely
with `NEEDS_EVIDENCE`.

Docker runtime selection uses a strict evidence policy. A base image is
accepted only when its runtime is supported by Project Intelligence. For
Node.js, an explicit project runtime fact such as `.nvmrc` or manifest runtime
metadata must authorize the matching
`node:<version>` image. Dependency versions, the developer machine's Node
version, README assumptions, `latest`, and internal
defaults are never runtime evidence. The LLM does not directly write files; it only proposes decisions which are verified by deterministic validation.

## Dry-run Behavior and Write Protection
The system ensures that a `dry_run` flag performs zero writes. In dry-run mode, the filesystem remains unmodified and Dockerize preflight failures or blocked generations result in zero artifact writes. The inspector never rescans the repository during the Dockerize phase; it strictly relies on the persisted Project Intelligence to protect against filesystem changes mid-operation.

## Safety Rules
- Chat has **no unrestricted shell access**.
- Chat **cannot** perform any state-mutating or destructive actions (e.g., `rm`, `mkdir`, `docker stop`, `git reset`, `kubectl apply`).
- If asked to perform an action, Chat can only explain the necessary steps.
- **No evidence = NEEDS_EVIDENCE**. Facts cannot be invented by the LLM.
- **No `shell=True` execution**: The CLI Bridge strictly executes commands securely using explicit argument lists.

## Current Limitations
- The model can sometimes propose a development command (e.g., `vite`) instead of a supported production preview command (`vite preview`). The deterministic validation layer correctly blocks this, preventing generation but causing the workflow to pause safely. True production Dockerfile generation may be blocked until the prompt contract is improved.
