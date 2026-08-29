# Sohail Studio Documentation V2

## Project Overview

Sohail Studio is a local-first DevOps AI Control Plane and AI engineering workspace. There is no separate CLI installation required. The project runs entirely on one Python environment (`.venv`), seamlessly integrating a dashboard, a secure AI Chat module, an AI Control Plane, a Raw PTY Terminal, and a dedicated Sohail-Agent execution CLI which leverages strict evidence-bound decision models for DevOps tasks.

## System Purpose

Sohail Studio exists to provide an integrated, local workspace where developers can interact with AI for coding and DevOps tasks while maintaining strict safety, evidence, and execution boundaries. It guarantees that AI models act as advisors and proposers, while deterministic logic and real project evidence serve as the final authority.

## Running the Project

- **Setup:** Run `python3 -m venv .venv` and then `.venv/bin/python -m pip install -e .` to setup the single environment. Use `.venv/bin/python -m pip install -e '.[dev]'` for test dependencies. Database migrations are applied using Alembic.
- **Execution:** Start the server using `.venv/bin/uvicorn backend.main:app --reload`. Access the studio via `http://127.0.0.1:8000`.
- The local Ollama endpoint must be running and available (default `http://127.0.0.1:11434`) with the configured `devops-qwen` model. Environment variable `DATABASE_URL` must point to the Neon PostgreSQL instance.

## Chat & AI Control Plane

The Chat uses `devops-qwen` strictly via local Ollama inference.
- Normal knowledge questions are answered natively without executing local commands.
- When local environment context is required, the AI Control Plane safely aggregates data using explicitly allowed read-only capabilities (e.g., `pwd`, `ls`, Docker/Git/Kubernetes status). It strictly prevents execution of state-mutating commands by avoiding `shell=True`.

## Raw PTY Terminal

The raw Terminal is a dedicated, real local PTY shell (e.g., `zsh` or `bash`). It operates completely separately from the AI Chat and Sohail-Agent workflows, providing unrestricted local execution capabilities natively loaded with the `.venv` context.

## Sohail-Agent Workflows & Project Inspection

Sohail-Agent acts as a separate DevOps CLI, distinct from the LLM chat mode. It runs guided workflows bridged natively by `core/cli_bridge.py` using strict explicit argument structures.

- **Inspect**: Uses Deep Inspector (`sohail_agent_cli/inspection/`) to build project context, identify stacks, and extract deterministic evidence from the real filesystem.
- **Dockerize**: A guided workflow to generate Docker configurations. It relies on the Dockerize Context Builder to supply the model with focused evidence, and a deterministic validator (`sohail_agent_cli/dockerize/validation.py`) to verify the model's structured decision before artifact generation.

## Project Intelligence & Persistence

Project Intelligence is the normalized, persisted intelligence model of the project. Deep Inspector feeds into this model, which is persisted in PostgreSQL (configured via `DATABASE_URL` in `core/storage/database.py`). This serves as the single source of truth and is hydrated via the API for downstream workflows like Dockerize. Raw inspection summaries do not bypass this persistence layer.

## Evidence Model & Rules

Authoritative evidence is required for all DevOps decisions. Non-authoritative sources (like dependency versions or machine-local versions) are rejected.
- **Runtime Evidence:** Exact authoritative evidence is required (e.g., `.nvmrc` stating `20`, or `package.json` `engines.node`). Broad documentation ranges (e.g., "Node.js v14 or higher") or developer machine versions do not authorize an exact Docker base image.
- **Port Evidence:** Application ports must be evidence-backed. For example, a Kubernetes `containerPort` can establish application-port evidence only when a matching Service `targetPort` exists. Service ports alone are not application-port evidence.
- **Command Evidence:** Docker start commands must be evidence-backed. The exact component `start` script is preferred. If absent, an appropriate exact `preview` script (e.g., `vite preview`) may be accepted based on policy. A frontend `dev` command (like `vite`) is not automatically a Docker production start command.

## LLM Role & Deterministic Validation

The local model `devops-qwen` proposes structured engineering decisions. It is **not the final authority**.
The **Deterministic Validation** layer is the final safety and evidence boundary. It ensures that the LLM's proposals strictly match the authoritative evidence. If evidence is missing or the model invents facts (e.g., inferring a port or command), validation fails safely with `NEEDS_EVIDENCE`. Artifact generation (e.g., writing Dockerfiles) only occurs after deterministic validation succeeds.

## Real Test Project Context

The system is currently tested against real project structures using `pytest` (`tests/sohail_agent_cli/` and `tests/`). Tests rigorously enforce deterministic validations and control plane capabilities.

## Current Limitations

- **Current Limitation:** In the Dockerize workflow, the model sometimes incorrectly proposes a development command (e.g., `start_command: vite` for the frontend) despite evidence supporting `preview: vite preview`. The deterministic validator successfully blocks this, correctly resulting in a safe failure rather than invalid artifact generation. This limitation in the model's decision-making requires future prompt/contract refinement.

## Safety Rules & Separation

- **Strict Boundary**: There is complete architectural separation between the Chat, the unrestricted Raw PTY Terminal, and the guided Sohail-Agent CLI workflows.
- **No Unrestricted Execution in Chat**: Chat cannot invoke destructive tasks.
- **Manual Approval Required**: All plans generated by the Sohail-Agent require explicit manual user approval prior to execution.
- **No Evidence = NEEDS_EVIDENCE**: The system will not fall back to assumptions or model inference if facts are missing.

---

## FUTURE ENGINEERING ROADMAP

The upcoming phases focus on building a robust, evidence-backed production infrastructure derivation engine. The core direction is: **first understand and classify real runtime intelligence, then derive deterministic contracts, then render and validate production artifacts.**

### Phase 1: Runtime Dependency Intelligence & Evidence Classification
- Deepen the Deep Inspector to not only identify components but to accurately classify every discovered fact.
- Move from "database technology detected" to understanding whether it implies a managed service, an internal connection string, or necessitates a new container service.
- Expand `EvidenceReference` and `VerifiedEngineeringPattern` capabilities to cover external and interrelated service dependencies securely.

### Phase 2: Compose Contract & Service Relationship Derivation
- Introduce a canonical, deterministic artifact contract that acts as the bridge between evidence/policies and raw file generation.
- Map out service relationships based strictly on evidence (e.g., if a frontend explicitly calls a backend port defined in env vars).
- Model-assisted, but strictly bounded, resolution of dependencies and routing policies. Missing requirements yield a safe `NEEDS_EVIDENCE`.

### Phase 3: Production Docker Compose Generation & Validation
- Implement full generation of production-ready `docker-compose.yml` and related configuration files based directly on the canonical contracts.
- Strictly separate the generation step from the validation step; validate the in-memory contracts fully before rendering, and validate rendered properties before any filesystem write occurs.

### Future Improvements
- **Dockerfile Strategy Contracts:** Improve specific Dockerfile derivation based on deep inspection (e.g., multi-stage builds automatically enabled when build evidence is detected).
- **Runtime Command/CMD Validation:** Stronger mappings of development vs. production commands derived from package manifests.
- **Environment & Secret Boundaries:** Rigorous identification of sensitive evidence, ensuring secrets are structurally separated from configuration values.
- **Network/Volume Authorization:** Deriving valid Docker network and volume topologies from explicit connection evidence.
- **Existing Artifact Handling:** Safe ingestion and validation of existing Dockerfiles/Compose files without blindly copying potentially stale or malicious configurations.
- **Real Local Verification Strategy:** Expanding local dry-run tests to actually perform safe sandbox compilations or verifications where appropriate.
