# Sohail Studio Architecture V2

## Purpose
Sohail Studio is a local-first DevOps AI Control Plane and engineering workspace. Operating within a modern Node.js 22 full-stack environment, it integrates an interactive 3-column workspace combining an AI Chat Mentor, a 3D Canvas / Workflow Inspector, and an interactive Raw PTY Terminal.

---

## 1. CURRENT IMPLEMENTED ARCHITECTURE

### 1.1 High-Level Architecture
- **Client Workspace (`dashboard/`)**:
  - Rendered via vanilla JavaScript (`app.js`), responsive CSS layout (`styles.css`), and an HTML shell (`index.html`).
  - Interactive 3D scene powered by Three.js (`three.min.js`, `GLTFLoader.js`) visualizing the Sohail avatar and engineering knowledge sphere.
  - Complete terminal emulator interface powered by xterm.js (`vendor/xterm.min.js`, `vendor/xterm.css`).
  - Real-time reactivity via WebSocket event listeners for runs, terminal sessions, and chat interactions.
- **Server Engine (`server.ts`)**:
  - Single Express + WebSocket server binding to port 3000 (`0.0.0.0:3000`).
  - Dispatches REST endpoints (`/api/health`, `/api/workflows`, `/api/sessions`, `/api/agent/*`) and upgrades WebSockets (`/ws/*`).
- **Interactive Terminal Engine**:
  - Operates over `/ws/terminal` with configurable working directory (`cwd`).
  - Spawns a real interactive pseudo-terminal process (`/bin/bash -i` or `/bin/sh -i`, or custom via `SOHAIL_STUDIO_SHELL`) with `xterm-256color`.
  - Implements two-way streaming, user SIGINT (`stop` action), and graceful SIGKILL teardown on disconnection.
- **Deep Inspector**:
  - Implemented in `inspectTargetDirectory()` in `server.ts`.
  - Deterministically scans directories up to depth 6, excluding build caches and dependency folders (`node_modules`, `.git`, `dist`, etc.).
  - Extracts languages, manifest dependencies, ports, and configuration signals with file-level provenance.
- **Project Intelligence Model**:
  - Normalized Schema v4 object capturing `files`, `components`, `languages`, `frameworks`, `runtimes`, `package_managers`, `ports`, `docker`, `kubernetes`, `ci_cd`, `environment_variables`, and `evidence`.
  - Maintained in an in-memory repository (`storedIntelligence` Map in `server.ts`).
- **Workflow & Agent Execution**:
  - Supports workflows: `inspect-project`, `create-project`, `dockerize-project`, `kubernetes`, `cicd`, `documentation`, `debug-error`, `ai-chat`.
  - Supports agent operations: `inspect`, `dockerize`, `kubernetes`, `cicd`, `plan`, `blueprint`.
  - Requires explicit user approval (`approved: true`) before initiating execution runs.
  - Real-time progress streamed over `/ws/runs/:run_id` and `/ws/agent-runs/:run_id`.
- **AI Mentoring Engine**:
  - Operates over `/ws/chat`.
  - Dual-mode: uses Google GenAI TypeScript SDK (`@google/genai` with `gemini-2.5-flash`) when `GEMINI_API_KEY` is present; falls back to an intelligent, rule-based engineering mentor (`local-mentor`) when no key is set.

---

## 2. EVIDENCE FLOW & DETERMINISTIC DERIVATION

The operational data flow follows a strict, evidence-bound hierarchy:

```text
REAL TARGET FILESYSTEM
        ↓
Deep Inspector (Deterministic File Scan & Manifest Parsing)
        ↓
Evidence Classification & Provenance Tagging
        ↓
Normalized Project Intelligence Snapshot (Schema v4)
        ↓
In-Memory Intelligence Cache (`storedIntelligence`)
        ↓
Workflow / Agent Planning (`/api/workflows/plan`)
        ↓
Human Approval Checkpoint (`approved: true` enforcement)
        ↓
Execution Engine (`executeWorkflowRun` / `executeAgentOperation`)
        ↓
Real-Time Event Stream (WebSocket frames to UI)
        ↓
Session History Storage (`sessions/history.json`)
```

### Evidence Provenance Rules
1. **Repository Truth**: Files discovered on disk (e.g., `package.json`, `server.ts`, `.env.example`) constitute primary evidence.
2. **Deterministic Extraction**: Classifications (e.g., language identification, framework detection) derive strictly from file extensions and manifest dependency keys.
3. **No Phantom Facts**: Runtimes, ports, and package managers must cite explicit source files (e.g., port 3000 assigned because of web server evidence, Node.js 22 assigned from package manifest).
4. **Secret Sanitization**: Environment variable presence is tracked for infrastructure modeling, but secret values are never read or stored.

---

## 3. SECURITY & SEPARATION MODEL

- **Three Independent Execution Planes**:
  1. *AI Chat Plane*: Read-only and conversational. Has zero access to shell execution, filesystem modification, or process management.
  2. *Interactive Terminal Plane*: User-driven, unmediated interactive shell with raw terminal capabilities. Cannot be triggered or manipulated by AI Chat.
  3. *Workflow / Agent Plane*: Structured, deterministic operations that strictly require explicit user approval (`approved: true`) to execute.
- **Process Spawning Safety**: System processes are spawned with explicit binary and argument vectors, avoiding arbitrary shell string injection (`shell=True`).
- **Data Isolation**: API responses never output raw environment credentials or internal system secrets.

---

## 4. CURRENT LIMITATIONS / BLOCKERS

- **In-Memory Storage**: Current database persistence relies on server-side `Map` structures and JSON files (`sessions/history.json`). External SQL persistence (PostgreSQL / Cloud SQL) is planned for future multi-instance deployments.
- **Ollama Client Inactivity**: Local Ollama inference is not active in the current cloud sandbox; AI capabilities rely on server-side Google Gemini streaming or the deterministic fallback mentor.
- **Container Sandbox**: The server runs in an isolated container environment; native Docker daemon commands (e.g., `docker build`, `docker run`) cannot be executed locally without an external remote Docker socket.
- **Command Selection Contract**: When generating Docker and CI/CD configurations, production preview commands (e.g., `vite preview`) must be explicitly prioritized over development commands (e.g., `vite dev`).

---

## 5. TARGET ARCHITECTURE / FUTURE PHASES

The long-term target architecture expands Sohail Studio into a distributed DevOps orchestrator:

```text
REAL LOCAL REPOSITORY
        ↓
Deep Deterministic Inspector
        ↓
Cloud SQL (PostgreSQL) Persisted Project Intelligence
        ↓
Evidence Classification Engine
        ↓
Deterministic Runtime & Dependency Derivation
        ↓
Verified Engineering Patterns & Policy Engine
        ↓
Model-Assisted Configuration Synthesis (Bounded Gemini API)
        ↓
Canonical Infrastructure Artifact Contract
        ↓
Multi-Stage Dockerfile / Compose / K8s Manifest Generation
        ↓
Strict Pre-Write Validation Gate
        ↓
Validated Filesystem Output / Remote Sandbox Verification
```

---

## 6. PHASED ENGINEERING ROADMAP

### Phase 1: Persistent Cloud Database Foundation
- Provision Cloud SQL (PostgreSQL) storage layer to replace transient in-memory `Map` storage.
- Implement structured relational schemas for Projects, Runs, Intelligence Snapshots, and Evidence Provenance records.
- Support multi-session audit logging and team collaboration.

### Phase 2: Advanced Dependency Intelligence & Service Graph Derivation
- Deepen file inspection to analyze multi-service repositories and monorepos.
- Derive cross-service dependencies, internal network links, and service-to-service communication paths from environment variables and connection strings.
- Separate database technology detection from container authorization (e.g., distinguishing an external managed DB from a local container service).

### Phase 3: Production Docker & Compose Synthesis with Strict Validation
- Synthesize production-ready multi-stage Dockerfiles optimized for layer caching, minimal base images (Alpine/distroless), and non-root execution.
- Deterministically render `docker-compose.yml` topologies with explicit health checks, networks, and named volumes.
- Implement pre-render and pre-write validation gates to reject any artifact that introduces unverified ports, commands, or credentials.

### Phase 4: Kubernetes & CI/CD Pipeline Synthesis
- Generate production-grade Kubernetes manifests (Deployments, ClusterIP Services, ConfigMaps, Ingress, and resource limit specifications).
- Synthesize automated CI/CD workflows (GitHub Actions, GitLab CI) with lint, test, container packaging, and automated security scans.
- Support live sandbox validation against target cluster APIs.

