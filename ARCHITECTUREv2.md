# Sohail Studio Architecture V2

## Purpose

Sohail Studio is a self-contained local-first AI engineering workspace. The application integrates a 3-column UI providing Chat, Workspace Canvas, and an Engineering Knowledge Sphere / Terminal Execution Engine. It uses a single Python environment (`.venv`), avoiding the need for a separate CLI installation.

## High-Level Architecture

- **Browser UI** initiates workflows via HTTP REST and WebSockets.
- **FastAPI** manages the backend, serves the static dashboard (`dashboard/`), and streams execution outputs.
- **AI Control Plane** is an explicit, read-only boundary for the AI Chat to observe local state safely.
- **Sohail-Agent** operates as a separate, dedicated DevOps CLI (`sohail_agent_cli/`), NOT an LLM chat mode.
- **Terminal** uses an isolated PTY socket (`/ws/terminal`), independent from the AI Chat.
- **Local Filesystem** maintains single-source-of-truth project state; all workflows run natively on the host.

## AI Control Plane (Chat Phase 2)

Introduced in Phase 2, the Control Plane ensures safe, read-only local environment querying. It intercepts requests for local insight, explicitly limiting execution to safe tools (e.g., `pwd`, `ls`, Docker/Git/Kubernetes read-only status) without shell injection risks (`shell=False`).

## Chat & Ollama (Chat Phase 1)

The Chat is driven by local inference via **Ollama**, strictly utilizing the **`devops-qwen:latest`** model.
It operates completely separately from the execution engine, ensuring a strict boundary between conversational generation and DevOps automation.

## Sohail-Agent Execution

Sohail-Agent is an integrated CLI (`sohail_agent_cli/`) bridged via `core/cli_bridge.py`. It provides structured, guided workflows executed in a live Sohail-Agent execution/output area, separated from the Raw PTY.
Key capabilities include:

- **Inspect**: Repository context building and project-aware frontend/backend component detection.
- **Dockerize**: Guided Docker configuration and Docker Compose handling.
- **Kubernetes**: Generating Kubernetes manifests based on repository context.
- **CI/CD**: Analyzing and generating CI/CD pipelines.
- **Plan & Blueprint**: Automated planning and structured blueprint generation.

All Sohail-Agent actions require manual user approval before execution and rely on a shared project-aware repository context to serve as the single source of truth.

## Terminal Architecture

The Terminal operates completely isolated from the Chat and Control Plane to prevent unintended operations.
It is a raw PTY terminal providing a real local shell environment (such as `zsh`) with full user execution rights.

## Security Boundaries & Separation

- **Separation**: Chat provides reasoning, Raw PTY provides unrestricted shell access, and Sohail-Agent executes guided DevOps workflows. They are strictly isolated.
- Chat **cannot** invoke arbitrary shell execution or state-mutating actions (e.g., `rm -rf`, `docker run`).
- CLI Bridge strictly protects against shell injection by using explicit argument lists (`argv`) rather than `shell=True`.

## Current Phase Status

### Phase 1 — COMPLETE

- Ollama foundation and Local-first architecture complete.
- Chat UI and PTY Terminal completely separated.

### Phase 2 — COMPLETE

- AI Control Plane introduced with multi-question routing and multi-tool aggregation.
- Safety boundaries strictly enforced (no destructive commands).

## Known Limitations

- The architecture enforces a manual approval workflow for all tasks; AI-generated plans must never execute silently without user approval.
- The system exclusively relies on local inference (Ollama `devops-qwen:latest`); no external cloud models are supported.
