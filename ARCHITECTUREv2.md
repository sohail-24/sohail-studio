# Sohail Studio Architecture V2

## Purpose

Sohail Studio is a local-first DevOps AI Control Plane and engineering workspace. It uses a single Python environment (`.venv`) and integrates a 3-column UI providing Chat, Workspace Canvas, and an Engineering Knowledge Sphere / Terminal Execution Engine.

## High-Level Architecture

The architecture distinctly separates operations to maintain strict safety and evidence boundaries:

- **Browser UI**: Initiates workflows via HTTP REST and WebSockets.
- **FastAPI**: Manages backend operations, serves the static dashboard (`dashboard/`), and streams execution outputs.
- **AI Control Plane**: An explicit, read-only boundary for the AI Chat to observe local state safely.
- **Sohail-Agent**: Operates as a separate, dedicated DevOps CLI (`sohail_agent_cli/`), NOT an LLM chat mode.
- **Terminal**: Uses an isolated PTY socket (`/ws/terminal`), providing a real local shell environment independent from the AI Chat.
- **Project Inspection**: Deep Inspector extracts deterministic engineering evidence from the real filesystem.
- **Project Intelligence**: Persisted source of truth in Neon PostgreSQL, accessed via API.
- **Model Decision-Making**: `devops-qwen` proposes decisions based on focused evidence.
- **Deterministic Validation**: The final safety and evidence boundary that enforces rules before any artifact generation.
- **Artifact Generation**: Renders final Dockerfiles or Compose files only after successful validation.

## Dockerize Workflow Architecture

The current Dockerize flow follows a strict, evidence-bound path:

1. **REAL FILESYSTEM**
2. ↓ **Deep Inspector**
3. ↓ **Evidence**
4. ↓ **Project Intelligence**
5. ↓ **Neon PostgreSQL**
6. ↓ **Dockerize Context Builder**
7. ↓ **Focused Evidence**
8. ↓ **devops-qwen** (proposes Structured Docker Decision)
9. ↓ **Deterministic Engineering Validation** (final authority)
10. ↓ **Docker Artifact Generation**

The LLM is **not the final authority** and does not directly control filesystem writes. Artifact generation only occurs after deterministic validation succeeds.

## AI Control Plane (Chat Phase 2)

The Control Plane ensures safe, read-only local environment querying. It intercepts requests for local insight, explicitly limiting execution to safe tools (e.g., `pwd`, `ls`, Docker/Git/Kubernetes read-only status) without shell injection risks (`shell=False`). It operates distinctly from standard chat and terminal actions.

## Chat & Ollama (Chat Phase 1)

The Chat is driven by local inference via **Ollama**, utilizing the **`devops-qwen`** model (based on Qwen3 4B Q4_K_M) with a 16384 context window on the running server (`http://127.0.0.1:11434`). It processes standard knowledge queries and context-aware queries concerning the local workspace, completely separate from the execution engine.

## Sohail-Agent Execution

Sohail-Agent is an integrated CLI (`sohail_agent_cli/`) bridged via `core/cli_bridge.py`. It provides structured, guided workflows:

- **Inspect**: Repository context building via Deep Inspector, identifying stacks, and extracting deterministic evidence.
- **Dockerize**: Guided Docker configuration through strict evidence-bound model proposals and deterministic validation.
- **Kubernetes**: (Planned/Future) Generating Kubernetes manifests.
- **CI/CD**: (Planned/Future) Analyzing and generating CI/CD pipelines.
- **Plan & Blueprint**: (Planned/Future) Automated planning and structured blueprint generation.

All Sohail-Agent actions require manual user approval before execution.

## Strict Evidence-Bound Decision Model

A foundational architectural rule is: **No evidence = NEEDS_EVIDENCE**

Dockerize uses strict evidence-bound behavior. The model may propose engineering decisions, but it cannot invent missing facts.
- Inferred runtime versions are **not acceptable**.
- Inferred ports are **not acceptable**.
- Inferred commands are **not acceptable**.
- Model defaults are **not acceptable**.
- Arbitrary model output is **not trusted**.
- `status=ready` alone is **not sufficient**.
- Raw inspection summaries **cannot bypass** Project Intelligence.
- Validation **cannot be skipped**.

The deterministic validator remains the final authority before artifact generation.

## Project Intelligence and Persistence

Neon PostgreSQL is the persistence source of truth for Project Intelligence. The current system uses a working `DATABASE_URL`.
The working API path for retrieval is:
`GET /api/agent/context?target=<project>`

Deep Inspector feeds Project Intelligence, which is persisted in Neon, then retrieved via API to the Dockerize Context Builder. Dockerize consumes this persisted evidence rather than inventing project facts.

## Terminal Architecture

The Terminal operates completely isolated from the Chat and Control Plane to prevent unintended operations.
It is a raw PTY terminal providing a real local shell environment (such as `zsh`) with full user execution rights.

## Security Boundaries & Separation

- **Separation**: Chat provides reasoning, Raw PTY provides unrestricted shell access, and Sohail-Agent executes guided DevOps workflows. They are strictly isolated.
- Chat **cannot** invoke arbitrary shell execution or state-mutating actions (e.g., `rm -rf`, `docker run`).
- CLI Bridge strictly protects against shell injection by using explicit argument lists (`argv`) rather than `shell=True`.
- No fake Project Intelligence or Ollama inference for missing facts.

## Testing & Current State

The current test state reflects successful integration of the deterministic validation layer:
- **217** total tests passed.
- **48** focused Inspector/Dockerize tests passed.
- **30** Dockerize workflow tests passed.

**Current Limitation (Safe Blocker):**
The model can still choose an unsupported development command (e.g., proposing `vite` as a start command when the evidence only supports a production-style `vite preview` for frontend). The deterministic validator correctly and safely rejects this proposal. This demonstrates the architecture working as intended, but highlights a limitation where artifact generation is safely blocked until the model decision contract/prompt is improved. Real Dockerfiles/Compose generation for the frontend has not yet succeeded due to this safe block.

## Future Architecture

Planned future phases include extending the evidence-bound model to Kubernetes, CI/CD, and Blueprint capabilities, as well as refining the model prompt to correctly select evidence-backed frontend commands.
