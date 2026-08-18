# Sohail Studio Documentation

Sohail Studio is a local-first AI engineering workspace.

- There is no separate CLI installation.
- The project runs entirely on one environment (`.venv`).
- The dashboard, raw PTY terminal, and embedded `sohail-agent` operate in harmony.

## Installation

- Run `python3 -m venv .venv` to set up the single environment.
- Run `.venv/bin/python -m pip install -e .` to install the studio and integrated CLI.
- Run `.venv/bin/python -m pip install -e '.[dev]'` for local test dependencies.

## Execution

- Start the server using `.venv/bin/uvicorn backend.main:app --reload`.
- Access the local studio interface via `http://127.0.0.1:8000`.
- The workspace requires Ollama running locally for AI generation capabilities.

## Embedded Terminal

- The embedded terminal operates through `/ws/terminal`.
- The terminal environment automatically maps `VIRTUAL_ENV` to `.venv`.
- The embedded terminal requires no manual `source` activation.
- Access the integrated commands directly via `sohail-agent --help`.

## Interface Layout

- **Left Panel**: Contains the recent task list and programmatic 3D AI Mentor.
- **Center Canvas**: Serves as the primary workspace for planning and execution logs.
- **Right Panel**: Houses the rotating Engineering Knowledge Sphere and the raw Terminal.

## Supported Workflows

The current CLI-backed interface workflows are:

- **Inspect Project**: Reads codebase context and stores project state (`inspect`).
- **Dockerize Project**: Configures minimal, environment-specific Docker artifacts (`dockerize`).
- **Kubernetes**: Deploys localized manifests into a clustered setup (`k8s`).
- **CI/CD**: Generates automated pipelines tailored to project needs (`cicd`).
- **Generate Documentation**: Authors relevant project documentation based on the codebase (`docs`).

All other visual placeholders, such as "Create New Project" or "Debug Error", do not map to executable commands currently.

## Workflow Execution Steps

1. Select the local target folder and the desired workflow.
2. Request a workflow plan from the dashboard.
3. Review the proposed steps manually.
4. Click to approve the execution.
5. The application securely triggers the command in the integrated `.venv`.
6. Watch real-time command output and CLI results.
7. Logs are permanently kept in the `sessions/` directory.
