# Sohail Studio Documentation

## Project Overview
Sohail Studio is a self-contained local-first AI engineering workspace. There is no separate CLI installation required. The project runs entirely on one Python environment (`.venv`), and seamlessly integrates a dashboard, a secure AI Chat module, an AI Control Plane, and a raw PTY Terminal.

## Running the Project
- **Setup:** Run `python3 -m venv .venv` and then `.venv/bin/python -m pip install -e .` to setup the single environment. Use `.venv/bin/python -m pip install -e '.[dev]'` for test dependencies.
- **Execution:** Start the server using `.venv/bin/uvicorn backend.main:app --reload`. Access the studio via `http://127.0.0.1:8000`. Ollama must be running locally to process AI generations.

## Chat
The Chat workspace serves two main behaviors using the stable local model `devops-qwen`:
1. **Normal Knowledge Questions:** Answers technical and factual queries using standard Ollama generation (e.g., "What is Docker?").
2. **Local-Environment Questions:** Understands when local context is needed and calls the Control Plane (e.g., "show pwd", "find my folder named sms").

## Control Plane
Introduced in Phase 2, the Control Plane ensures Chat can inspect local resources safely. It intercepts requests for local environment insight, runs explicitly allowed read-only capabilities, and packages the result for Ollama. The Control Plane runs purely read-only commands without a shell (`shell=False`) and is very lightweight (~4.8 ms overhead).

## Terminal
The raw Terminal is architecturally isolated from the Chat. It operates via `/ws/terminal` connecting directly to a real local PTY. The terminal loads `.venv` natively (no manual source required). This allows users full execution rights while keeping Chat safely restricted.

## Ollama
Ollama is the local inference engine driving all AI generation. The active local model is `devops-qwen` (Qwen3 4B Q4_K_M). There is no cloud LLM or AWS component.

## PostgreSQL storage foundation
The storage boundary uses PostgreSQL hosted by Neon. It is configured only
through the environment variable `DATABASE_URL`; credentials are never stored
in source or returned by health checks.

## Phase 4B: Deep Inspector and Project Intelligence
The existing Sohail-Agent `inspect` operation recursively discovers the
current repository, excludes generated/cache directories and secret-bearing
files, classifies discovered files, and extracts deterministic engineering
evidence with source-file provenance. It does not call Ollama and does not store
source contents.

Each successful inspection creates a new inspection run. The normalized
Project Intelligence snapshot and evidence are persisted through the existing Neon PostgreSQL
storage layer. The inspector never stores `.env` secrets, private keys, credentials, tokens,
or raw source contents.

Dockerize retrieves the latest successful Project Intelligence snapshot
through the existing storage repository, scopes it to the selected components,
and sends only that focused context to `devops-qwen`. Ollama
returns a structured decision; Sohail-Agent applies deterministic validation on runtime, commands, paths, services, and
ports before reporting success. Missing or conflicting evidence fails safely
with `NEEDS_EVIDENCE`.

Docker runtime selection uses a strict evidence policy. A base image is
accepted only when its runtime is supported by Project Intelligence. For
Node.js, an explicit project runtime fact such as `.nvmrc` or manifest runtime
metadata must authorize the matching
`node:<version>` image. Dependency versions, the developer machine's Node
version, README assumptions, `latest`, and internal
defaults are never runtime evidence. The deterministic validator remains the final authority. Arbitrary invented commands or inferred ports are rejected.

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
- **No evidence = NEEDS_EVIDENCE**. Facts cannot be invented by the LLM.

## Testing
Run tests locally using `pytest`. Current validations include tests for safe Control Plane routing, Multi-question routing, read-only verifications, terminal PTY availability, chat safety bounds, and Dockerize deterministic validation (currently 217 passed).

## Current Status
- **Phase 1 (Complete):** Local Ollama foundation, Chat interface, separated PTY Terminal.
- **Phase 2 (Complete):** AI Control Plane with read-only tools, safe local context querying, mult-question routing.
- **Phase 4B (Dockerize):** Implemented inspection, Project Intelligence, Neon persistence, and deterministic validation. Currently safely blocking artifact generation on unsupported frontend commands until prompt refinement is completed.
