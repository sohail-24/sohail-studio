# Sohail Studio Documentation V2

## 1. SYSTEM PURPOSE & OPERATIONAL OVERVIEW
Sohail Studio is a local-first DevOps AI Control Plane and engineering workspace. Built as a high-performance full-stack Node.js 22 application with TypeScript, it provides developers with an integrated environment for repository inspection, workflow planning, interactive terminal operations, and real-time AI architectural guidance.

The system serves the dashboard assets and JSON APIs from a single Express server running on port 3000 (`0.0.0.0:3000`), multiplexing HTTP REST endpoints with WebSocket connections for low-latency terminal and run event streaming.

---

## 2. SUBSYSTEM ARCHITECTURAL SPECIFICATIONS

### 2.1 Dashboard & 3D Knowledge Canvas (`dashboard/`)
- **Frontend Core**: Lightweight, dependency-free vanilla JavaScript (`app.js`) driving a reactive state store and DOM rendering tree.
- **3D Visualization Engine**: Three.js (`three.min.js`, `GLTFLoader.js`) renders the Sohail avatar alongside an interactive 3D knowledge sphere representing discovered stack nodes and engineering capabilities.
- **Terminal Emulator**: xterm.js (`vendor/xterm.min.js`, `vendor/xterm.css`) providing full 256-color ANSI terminal rendering, keyboard capture, and mouse-wheel scrolling.
- **State Synchronization**: WebSocket event handlers bind live socket messages directly into the UI state, updating run outputs, terminal buffers, and chat streams without page reloads.

### 2.2 Deep Inspector & Project Intelligence Engine
- **Scanner Algorithm**: Deterministic directory walker (`inspectTargetDirectory` in `server.ts`) operating to a maximum recursion depth of 6.
- **Exclusion Filters**: Automatically prunes non-source directories: `.git`, `node_modules`, `.next`, `dist`, `build`, `.venv`, `venv`, `__pycache__`.
- **Classification Pipeline**:
  - *Languages*: Identified by file extension (`.ts`, `.js`, `.py`, `.go`, `.rs`, `.java`, `.html`, `.css`, `.json`, `.yaml`).
  - *Frameworks*: Extracted from `package.json` dependencies (Express, React, Next.js, Vite, Tailwind CSS).
  - *Infrastructure Signals*: Categorized via file pattern matching (`Dockerfile*`, `*compose*.yml`, `*.k8s.yaml`, `.github/workflows/*`).
  - *Port Detection*: Associates components with network ports (e.g., port 3000 for web services).
  - *Secret Sanitization*: Detects `.env*` configurations to register environment variable names (e.g., `PORT`, `GEMINI_API_KEY`) without inspecting or retaining sensitive values.
- **Snapshot Caching**: Normalized results are cached in memory (`storedIntelligence` Map) and indexed by resolved filesystem path.

### 2.3 Workflow Planning & Execution Engine
- **Catalog**:
  - `inspect-project`: Comprehensive stack and artifact discovery.
  - `create-project`: Guided architecture scaffolding brief.
  - `dockerize-project`: Multi-stage Docker containerization plan.
  - `kubernetes`: Production deployment and service manifest preparation.
  - `cicd`: Automated continuous delivery pipeline design.
  - `documentation`: System and API documentation synthesizer.
  - `debug-error`: Systematic error diagnostics and remediation.
  - `ai-chat`: Consultative engineering mentor session.
- **Approval Gate**: All workflows require plan generation (`POST /api/workflows/plan`) which outputs `requires_approval: true`. Execution (`POST /api/runs`) strictly enforces `approved: true`.
- **Event Bus**: Structured events are published to connected WebSocket subscribers over `/ws/runs/:run_id` and `/ws/agent-runs/:run_id`.
- **Session Recorder**: Completed runs automatically serialize outputs and exit codes to `sessions/history.json`.

### 2.4 Interactive Terminal Engine
- **Endpoint**: `/ws/terminal?cwd=<path>`
- **PTY Process Lifecycle**:
  - Spawns an interactive login shell (`/bin/bash -i` or `/bin/sh -i`, or custom via `SOHAIL_STUDIO_SHELL`).
  - Configures environment: `TERM=xterm-256color`, `PWD=<cwd>`, `SOHAIL_STUDIO_ROOT=<root>`.
  - Streams binary and UTF-8 chunks between process stdio and the WebSocket connection.
- **Control Signals**:
  - User `action: "stop"` dispatches `SIGINT` to interrupt running foreground commands.
  - Socket close event automatically issues `SIGKILL` to prevent orphaned background processes.
- **Isolation Guarantee**: The terminal operates independently from the AI chat layer; chat models cannot access or manipulate the terminal process.

### 2.5 AI Engineering Mentor Engine
- **Endpoint**: `/ws/chat`
- **Dual-Mode Inference**:
  1. *Gemini Streaming Mode*: When `GEMINI_API_KEY` is set, calls `@google/genai` with model `gemini-2.5-flash` using `generateContentStream`.
  2. *Deterministic Local Mode*: When no API key is provided, activates a rule-based engineering mentor (`local-mentor`) that detects intent (Docker, Kubernetes, CI/CD, Architecture) and streams structured Markdown guidance.
- **Conversation State**: Maintains a rolling context window of user and assistant interactions.
- **Safety Boundary**: The mentor engine is strictly advisory and cannot execute commands or mutate files.

---

## 3. DATA SCHEMAS & API SPECIFICATIONS

### 3.1 Project Intelligence Schema (Version 4)
```typescript
interface ProjectIntelligence {
  name: string;
  root_path: string;
  intelligence_schema_version: 4;
  inspection_run_id: string;
  inspected_at: string; // ISO 8601 timestamp
  intelligence_status: "COMPLETE" | "PARTIAL" | "FAILED";
  files: Array<{
    relative_path: string;
    classification: "source" | "manifest" | "config" | "docker" | "docker_compose" | "kubernetes" | "ci_cd";
    language: string | null;
    size: number;
    sha256: string | null;
    ignored: boolean;
  }>;
  components: Array<{
    name: string;
    path: string;
    role: "service" | "frontend" | "worker";
    framework: string;
    package_manager: string;
    runtimes?: Array<{ runtime: string; version: string }>;
    evidence: string[];
  }>;
  languages: string[];
  frameworks: string[];
  runtimes: Array<{ runtime: string; version: string }>;
  package_managers: string[];
  ports: Array<{
    component: string;
    port: number;
    port_type: "application" | "service";
    value: number;
  }>;
  has_docker: boolean;
  docker: { dockerfiles: string[] };
  has_kubernetes: boolean;
  kubernetes: { files: string[] };
  has_ci_cd: boolean;
  ci_cd: { platforms: string[] };
  ci_cd_files: string[];
  environment_variables: Array<{
    name: string;
    role: string;
    value_status: "AVAILABLE" | "NEEDS_EVIDENCE";
    required: boolean;
    source_files: string[];
  }>;
  evidence: Array<{
    source_file: string;
    evidence_type: string;
    key: string;
    value: string;
    confidence: "high" | "medium" | "low";
    extraction_method: string;
  }>;
  verified_patterns: Array<{
    pattern_id: string;
    category: string;
  }>;
}
```

### 3.2 Run State & Event Schema
```typescript
interface RunEvent {
  type: "command" | "output" | "inspection_persisted" | "user_evidence_accepted" | "retry_started" | "complete" | "closed" | "error";
  command?: string;
  message?: string;
  run_id?: string;
  status?: "running" | "completed" | "failed";
  result_status?: "SUCCESS" | "NEEDS_EVIDENCE" | "ERROR";
  exit_code?: number;
  transport?: "gemini-api" | "local-mentor";
  [key: string]: any;
}

interface RunState {
  runId: string;
  workflow: string;
  target: string;
  provider?: string;
  model?: string;
  events: RunEvent[];
  subscribers: Set<WebSocket>;
  complete: boolean;
  awaitingClarification: boolean;
  pendingClarification: any | null;
  agentRequest?: any;
}
```

---

## 4. SECURITY & SEPARATION ENFORCEMENT

| Boundary | Enforcement Mechanism | Failure Mode |
| :--- | :--- | :--- |
| **AI Chat Shell Access** | Chat socket has no execution runtime; handles only text tokens | Model advice is strictly textual; no commands can run |
| **Terminal Isolation** | PTY process is triggered only by user UI actions on `/ws/terminal` | Cannot be controlled or scripted by AI Chat |
| **Workflow Execution** | `approved: true` required on `POST /api/runs` | Unapproved runs return HTTP 400 Bad Request |
| **Process Spawning** | Node.js `spawn` with explicit argument arrays (no `shell: true`) | Prevents arbitrary shell string interpolation attacks |
| **Secret Sanitization** | Deep Inspector records only variable keys; values are not read | Zero credentials stored in memory or serialized in logs |

---

## 5. CURRENT LIMITATIONS & CONSTRAINTS

1. **Storage Persistence**: Active workflow states and Project Intelligence snapshots are maintained in server memory. Session logs are saved to `sessions/history.json`. External database integration (PostgreSQL) is designated for upcoming phases.
2. **Local Ollama Daemon**: Ollama is not active in the current sandboxed container; AI capabilities use Google Gemini streaming or the built-in local mentor.
3. **Container Daemon Access**: The server runs in a secure Linux container sandbox without root Docker socket access; live Docker builds require an external Docker daemon.

---

## 6. FUTURE ENGINEERING ROADMAP

### Phase 1: Relational Persistence Layer (Cloud SQL / PostgreSQL)
- Migrate transient in-memory run tracking and intelligence snapshots to a relational database.
- Establish schemas for Projects, Runs, Artifacts, and Evidence Provenance records.
- Support persistent audit logs and multi-session workspace recovery.

### Phase 2: Dependency Intelligence & Topology Modeling
- Expand Deep Inspector to resolve complex monorepos and multi-tier service relationships.
- Derive service-to-service communication paths from configuration files, connection strings, and client SDK references.
- Distinguish external managed dependencies from local container requirements.

### Phase 3: Production Docker & Compose Generation with Validation Gates
- Synthesize production-ready multi-stage Dockerfiles (build caching, non-root user, minimal base images).
- Generate deterministic `docker-compose.yml` topologies with strict health checks and network definitions.
- Implement pre-render and pre-write deterministic validation to block any artifact that references unverified ports or commands.

### Phase 4: Kubernetes & CI/CD Pipeline Synthesis
- Synthesize production Kubernetes manifests (Deployments, Services, ConfigMaps, Ingress, and resource budgets).
- Output automated CI/CD workflows for GitHub Actions with linting, testing, and vulnerability scanning steps.
- Enable live validation against staging clusters and sandbox registries.

