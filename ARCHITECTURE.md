# Sohail Studio Architecture

## Purpose
Sohail Studio is a self-contained local-first AI engineering workspace. The application uses a single Python environment (`.venv`), avoiding the need for a separate CLI installation. It integrates a 3-column UI providing Chat, Workspace, and Terminal elements.

## High-Level Architecture
- **Browser UI** initiates workflows and handles interactions via HTTP REST and WebSockets.
- **FastAPI** generates workflow plans requiring manual approval and serves the static dashboard (`dashboard/`).
- **AI Control Plane** serves as an explicit, read-only boundary for the AI Chat to observe local state safely.
- **Sohail-Agent-CLI** (`sohail_agent_cli/`) acts as the underlying execution bridge.
- **Terminal** uses an isolated PTY socket (`/ws/terminal`), independent from the AI Chat.
- **Local Filesystem** updates and **Ollama** runs inferences directly locally.
- **Sessions** stores JSON logs of completed workflows (`sessions/`).

## Chat Architecture
The Chat provides conversational AI access through Ollama via `/api/chat` using the model `devops-qwen`.
It processes both standard knowledge queries and context-aware queries concerning the local workspace.

For Normal knowledge questions:
```text
User → Chat → Ollama → Answer
```

For Local-environment questions (Phase 2):
```text
User → Chat → Control Plane → Read-only local information → Ollama → Answer
```

## AI Control Plane
The Control Plane is a critical security and capability layer introduced in Phase 2. It dictates whether local information is required, safely fetching it without allowing arbitrary shell access or destructive actions. It adds very minimal latency (~4.8 ms overhead).

## Read-Only Capabilities
The AI Control Plane is explicitly restricted to these safe local tools:
- Local time/date (`local_time`)
- Filesystem/project inspection (`project_files`)
- Present Working Directory (`pwd`)
- Safe folder search (`ls` and `project_files`)
- Docker read-only inspection (`docker_read`)
- Git read-only inspection (`git_read`)
- Kubernetes read-only inspection (`kubernetes_read`)

Multi-part requests can route sequentially to multiple tools before the model provides a final answer.

## Terminal Architecture
The Terminal operates completely isolated from the Chat and Control Plane to prevent unintended operations and maintain a strict security boundary.
```text
Terminal → WebSocket → Real local PTY → Shell → Real terminal output
```

## Ollama Integration
Sohail Studio relies completely on local inference via Ollama. It does not use external cloud models.
The active local model is **`devops-qwen`** (based on Qwen3 4B Q4_K_M).

## PostgreSQL storage foundation
The storage boundary uses PostgreSQL hosted by Neon. It is configured only
through the environment variable `DATABASE_URL`; credentials are never stored
in source or returned by health checks.

## Phase 4B: Deep Inspector and Project Intelligence
The existing Sohail-Agent `inspect` operation recursively discovers the
current repository, excludes generated/cache directories and secret-bearing
files, classifies discovered files, and extracts deterministic engineering
evidence with source-file provenance. Components
are reported only when manifests and source/configuration evidence show an
independently runnable or deployable unit. It does not call Ollama and does not store
source contents.

Each successful inspection creates a new inspection run. The normalized
Project Intelligence snapshot and evidence are persisted through the existing Neon PostgreSQL
storage layer. Port candidates retain their source and conflicts rather than
being silently merged.

The inspector never stores `.env` secrets, private keys, credentials, tokens,
or raw source contents.

Dockerize now retrieves the latest successful Project Intelligence snapshot
through the existing storage repository, scopes it to the selected components,
and sends only that focused context to `devops-qwen`. Ollama
returns a structured decision; Sohail-Agent applies deterministic validation of runtime, commands, paths, services, and
ports before rendering any Dockerfiles or Compose services. Missing or conflicting evidence fails safely
with `NEEDS_EVIDENCE`.

Docker runtime selection uses a strict evidence policy. A base image is
accepted only when its runtime is supported by Project Intelligence. For
Node.js, an explicit project runtime fact such as `.nvmrc` or manifest runtime
metadata must authorize the matching
`node:<version>` image. Dependency versions, the developer machine's Node
version, README assumptions, `latest`, and internal
defaults are never runtime evidence. The LLM does not directly write files; it only proposes decisions which are verified by deterministic validation.

## Safety Rules
- Chat has **no unrestricted shell access**.
- Chat **cannot** perform any state-mutating or destructive actions (e.g., `rm`, `mkdir`, `docker stop`, `git reset`, `kubectl apply`).
- If asked to perform an action, Chat can only explain the necessary steps.
- **No evidence = NEEDS_EVIDENCE**. Facts cannot be invented by the LLM.

## Current Phase Status
- **Phase 1 (Complete):** Local Ollama foundation, Chat interface, separated PTY Terminal.
- **Phase 2 (Complete):** AI Control Plane with read-only tools, safe local context querying, mult-question routing.
- **Phase 4B (Dockerize):** Implemented inspection, Project Intelligence, Neon persistence, and deterministic validation. Currently safely blocking artifact generation on unsupported frontend commands until prompt refinement is completed.
