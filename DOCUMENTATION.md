# Sohail Studio Documentation

## Project Overview
Sohail Studio is a local-first AI engineering workspace. There is no separate CLI installation required. The project runs entirely on one Python environment (`.venv`), and seamlessly integrates a dashboard, a secure AI Chat module, an AI Control Plane, and a raw PTY Terminal.

## Running the Project
- **Setup:** Run `python3 -m venv .venv` and then `.venv/bin/python -m pip install -e .` to setup the single environment. Use `.venv/bin/python -m pip install -e '.[dev]'` for test dependencies.
- **Execution:** Start the server using `.venv/bin/uvicorn backend.main:app --reload`. Access the studio via `http://127.0.0.1:8000`. Ollama must be running locally to process AI generations.

## Chat
The Chat workspace serves two main behaviors using `devops-qwen:latest`:
1. **Normal Knowledge Questions:** Answers technical and factual queries using standard Ollama generation (e.g., "What is Docker?").
2. **Local-Environment Questions:** Understands when local context is needed and calls the Control Plane (e.g., "show pwd", "find my folder named sms").

## Control Plane
Introduced in Phase 2, the Control Plane ensures Chat can inspect local resources safely. It intercepts requests for local environment insight, runs explicitly allowed read-only capabilities, and packages the result for Ollama. The Control Plane runs purely read-only commands without a shell (`shell=False`) and is very lightweight (~4.8 ms overhead).

## Terminal
The raw Terminal is architecturally isolated from the Chat. It operates via `/ws/terminal` connecting directly to a real local PTY. The terminal loads `.venv` natively (no manual source required). This allows users full execution rights while keeping Chat safely restricted.

## Ollama
Ollama is the local inference engine driving all AI generation.
The configured model is `devops-qwen:latest`. There is no cloud-hosted component.

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