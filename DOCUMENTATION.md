# Sohail Studio Documentation

## Project Overview
Sohail Studio is a local-first AI engineering workspace. There is no separate CLI installation required. The project runs entirely on one Python environment (`.venv`), and seamlessly integrates a dashboard, a secure AI Chat module, an AI Control Plane, and a raw PTY Terminal.

## Running the Project
- **Setup:** Run `python3 -m venv .venv` and then `.venv/bin/python -m pip install -e .` to setup the single environment. Use `.venv/bin/python -m pip install -e '.[dev]'` for test dependencies.
- **Execution:** Start the server using `.venv/bin/uvicorn backend.main:app --reload`. Access the studio via `http://127.0.0.1:8000`. Ollama must be running locally to process AI generations.

## Chat
The Chat workspace serves two main behaviors using the stable local model `devops-qwen:v1`:
1. **Normal Knowledge Questions:** Answers technical and factual queries using standard Ollama generation (e.g., "What is Docker?").
2. **Local-Environment Questions:** Understands when local context is needed and calls the Control Plane (e.g., "show pwd", "find my folder named sms").

## Control Plane
Introduced in Phase 2, the Control Plane ensures Chat can inspect local resources safely. It intercepts requests for local environment insight, runs explicitly allowed read-only capabilities, and packages the result for Ollama. The Control Plane runs purely read-only commands without a shell (`shell=False`) and is very lightweight (~4.8 ms overhead).

## Terminal
The raw Terminal is architecturally isolated from the Chat. It operates via `/ws/terminal` connecting directly to a real local PTY. The terminal loads `.venv` natively (no manual source required). This allows users full execution rights while keeping Chat safely restricted.

## Ollama
Ollama is the local inference engine driving all AI generation.
Create the stable tag once from the existing development model with:

```bash
ollama cp devops-qwen:latest devops-qwen:v1
```

Both local tags remain available. Chat uses `CHAT_MODEL=devops-qwen:v1`, while
the future DevOps generation layer is reserved as `DEVOPS_MODEL=devops-qwen:latest`.
There is no cloud LLM or AWS component.

## PostgreSQL storage foundation
The storage boundary uses PostgreSQL hosted by Neon. It is configured only
through the environment variable `DATABASE_URL`; credentials are never stored
in source or returned by health checks. The minimum schema is applied with the
reproducible Alembic migration command:

```bash
DATABASE_URL='postgresql://...?...sslmode=require' .venv/bin/python -m core.storage.migrate
```

The backend health endpoint at `/api/health` reports only `database:
connected`, `unavailable`, or `not_configured`. Existing JSON session files are
preserved and are not migrated by this foundation.

## Phase 4B: Deep Inspector and Project Intelligence
The existing Sohail-Agent `inspect` operation now recursively discovers the
current repository, excludes generated/cache directories and secret-bearing
files, classifies discovered files, and extracts deterministic engineering
evidence with source-file provenance and high/medium/low confidence. Components
are reported only when manifests and source/configuration evidence show an
independently runnable or deployable unit; workspace and metadata-only roots
are not promoted to applications. It does not call Ollama and does not store
source contents.

Each successful inspection creates a new inspection run. The normalized
Project Intelligence snapshot and its file metadata, components, runtimes,
dependencies, commands, component-aware ports, Docker, Kubernetes, CI/CD,
documentation, and evidence are persisted through the existing Neon PostgreSQL
storage layer. Port candidates retain their source and conflicts rather than
being silently merged. Local `.env` files are inspected for configuration
shape, but sensitive values are stored only as `REDACTED`.
Re-inspection preserves prior runs and advances the project's current snapshot.

After the already-applied storage foundation migration, apply the Phase 4B
migration with:

```bash
DATABASE_URL='postgresql://...?...sslmode=require' .venv/bin/python -m core.storage.migrate
```

The inspector never stores `.env` secrets, private keys, credentials, tokens,
or raw source contents. Dockerize targets come from detected components, and
the UI distinguishes an existing Compose file from a request to generate one.
The JSON session store remains unchanged.

Dockerize now retrieves the latest successful Project Intelligence snapshot
through the existing storage repository, scopes it to the selected components,
and sends only that context to `DEVOPS_MODEL` (`devops-qwen:latest`). Ollama
returns a structured decision; Sohail-Agent renders the selected Dockerfiles
and Compose services, then validates runtime, commands, paths, services, and
ports before reporting success. Missing or conflicting evidence fails safely
with `NEEDS_EVIDENCE`. Dry runs never write files, and existing files require
the existing overwrite policy.

Docker runtime selection uses a strict evidence policy. A base image is
accepted only when its runtime is supported by Project Intelligence. For
Node.js, an explicit project runtime fact such as `.nvmrc`, manifest runtime
metadata, or an existing Dockerfile base image must authorize the matching
`node:<version>` image. Dependency versions, the developer machine's Node
version, Kubernetes Service ports, README assumptions, `latest`, and internal
defaults are never runtime evidence. If Ollama returns `ready` with an
unsupported or missing runtime claim, deterministic validation converts the
proposal to `NEEDS_EVIDENCE`; no Dockerfile or Compose artifact is rendered.

## Supported Read-Only Operations
The AI Control Plane supports the following read-only CLI abstractions for Chat:
- `pwd`
- `ls`
- Safe filesystem and folder search
- Local time and date extraction
- Read-only Docker status (e.g., `docker ps`, `docker info`)
- Read-only Git state (e.g., `git status`, `git log`)
- Read-only Kubernetes cluster state (`kubectl get pods`, etc.)

## Safety Rules
- Chat has **no unrestricted shell access**.
- Chat **cannot** perform any state-mutating or destructive actions (e.g., `rm`, `mkdir`, `docker stop`, `git reset`, `kubectl apply`).
- If asked to perform an action, Chat can only explain the necessary steps.

## Testing
Run tests locally using `pytest`. Current validations included tests for safe Control Plane routing, Multi-question routing, read-only verifications, terminal PTY availability, and chat safety bounds. All 20 focused test cases from Phase 2 have successfully passed.

## Current Status
- **Phase 1 (Complete):** Local Ollama foundation, Chat interface, separated PTY Terminal.
- **Phase 2 (Complete):** AI Control Plane with read-only tools, safe local context querying, mult-question routing.
