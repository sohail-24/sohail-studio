# Sohail Studio Architecture V2

## Purpose

Sohail Studio is a local-first DevOps AI Control Plane and engineering workspace. It uses a single Python environment (`.venv`) and integrates a 3-column UI providing Chat, Workspace Canvas, and an Engineering Knowledge Sphere / Terminal Execution Engine.

## CURRENT IMPLEMENTED STATE

### High-Level Architecture
- **Browser UI**: Initiates workflows via HTTP REST and WebSockets.
- **FastAPI**: Manages backend operations, serves the static dashboard (`dashboard/`), and streams execution outputs.
- **AI Control Plane**: An explicit, read-only boundary for the AI Chat to observe local state safely (`core/control_plane.py`). It enforces `shell=False` to prevent destructive operations.
- **Sohail-Agent**: Operates as a separate, dedicated DevOps CLI (`sohail_agent_cli/`), NOT an LLM chat mode. It executes directly via explicitly passed argument vectors.
- **Terminal**: Uses an isolated PTY socket (`/ws/terminal`), providing a real local shell environment independent from the AI Chat.
- **Project Inspection**: Deep Inspector (`sohail_agent_cli/inspection/`) extracts deterministic engineering evidence from the real filesystem.
- **Project Intelligence**: Persisted source of truth using PostgreSQL (`core/storage/database.py`), managed via Alembic migrations.
- **Model Decision-Making**: `devops-qwen` proposes decisions based on focused evidence, integrated via `OllamaProvider`.
- **Deterministic Validation**: The final safety and evidence boundary (`sohail_agent_cli/dockerize/validation.py`) that enforces rules before any artifact generation.
- **Artifact Generation**: Renders final Dockerfiles or Compose files only after successful validation.

### Dockerize Workflow Architecture
The current Dockerize flow follows a strict, evidence-bound path:

1. **REAL FILESYSTEM**
2. ↓ **Deep Inspector**
3. ↓ **Evidence**
4. ↓ **Project Intelligence**
5. ↓ **PostgreSQL Database** (`DATABASE_URL`)
6. ↓ **Dockerize Context Builder**
7. ↓ **Focused Evidence**
8. ↓ **devops-qwen via Ollama** (proposes Structured Docker Decision)
9. ↓ **Deterministic Engineering Validation** (final authority, blocks unsupported proposals like missing commands or unverified ports)
10. ↓ **Docker Artifact Generation**

### Security Boundaries & Separation
- **Separation**: Chat provides reasoning, Raw PTY provides unrestricted shell access, and Sohail-Agent executes guided DevOps workflows. They are strictly isolated.
- Chat **cannot** invoke arbitrary shell execution or state-mutating actions.
- CLI Bridge strictly protects against shell injection by using explicit argument lists (`argv`) rather than `shell=True`.
- No fake Project Intelligence or Ollama inference for missing facts.

### Current Limitations
- **Current Limitation (Safe Blocker):** The model can still choose an unsupported development command (e.g., proposing `vite` as a start command when the evidence only supports a production-style `vite preview` for frontend). The deterministic validator (`sohail_agent_cli/dockerize/validation.py`) correctly and safely rejects this proposal. Artifact generation is safely blocked until the model decision contract/prompt is improved.

## TARGET ARCHITECTURE / FUTURE PHASES

Sohail Studio's long-term goal is:
Inspect a real local project completely, derive its real architecture and runtime requirements from evidence, then generate production-ready Dockerfiles and Docker Compose configuration without guessing or copying historical artifacts.

The future architecture should follow:
REAL LOCAL REPOSITORY
        ↓
Complete deterministic inspection
        ↓
Persisted Project Intelligence
        ↓
Evidence classification
        ↓
Deterministic architecture/runtime derivation
        ↓
Verified engineering patterns
        ↓
Approved platform/runtime policy
        ↓
Bounded model assistance only where appropriate
        ↓
Canonical authoritative artifact contract
        ↓
Production-ready Dockerfile / Compose rendering
        ↓
Strict validation
        ↓
Optional validated filesystem write

### Important Principles
- **No guessing:** Missing facts must not be invented to make an artifact look more complete (e.g., database credentials, environment variables, networks, volumes, image names).
- **Classification:** Every discovered fact must be classified according to what it actually proves (e.g., DATABASE TECHNOLOGY DETECTED is not automatically DATABASE CONTAINER SERVICE AUTHORIZED).
- **Distinctions:** The system distinguishes between Repository truth, Deterministic derivation, Verified engineering pattern, Approved platform policy, Model proposal, and Missing evidence (`NEEDS_EVIDENCE`).
- **Dependencies & Relationships:** The future Docker Compose architecture must be capable of understanding real runtime dependencies and relationships when supported by inspection evidence, rather than only producing a minimal frontend/backend Compose file.

### Phased Roadmap

*Note: Phase boundaries may be refined based on actual implementation discoveries, but the core direction remains: first understand and classify real runtime intelligence, then derive deterministic contracts, then render and validate production artifacts.*

- **Phase 1: Runtime Dependency Intelligence & Evidence Classification**
  Enhance the inspection pipeline to deeply classify discovered facts, mapping raw evidence (e.g., package dependencies, connection strings) into structured runtime dependencies without automatically authorizing them as infrastructure.
- **Phase 2: Compose Contract & Service Relationship Derivation**
  Build the deterministic engine that evaluates classified evidence against approved policies to derive a canonical artifact contract. This phase identifies true service relationships and constraints (e.g., required environment variables, network boundaries).
- **Phase 3: Production Docker Compose Generation & Validation**
  Implement the rendering of production-ready Docker Compose files based entirely on the derived contracts. This includes strict pre-render and pre-write validation, ensuring no artifacts are generated or overwritten without matching evidence.
- **Future Improvements:**
  - Robust Dockerfile strategy contracts and production artifact enhancements.
  - Runtime command/CMD validation improvements.
  - Deterministic service dependency handling.
  - Environment and secret boundaries.
  - Network/volume authorization based on verified patterns.
  - Safe handling of existing artifacts.
