# Sohail Studio Documentation

Sohail Studio is a local-first AI engineering workspace. It combines a browser dashboard, a raw local terminal, workflow planning and approval, and the integrated Sohail-Agent-CLI implementation in one project.

## Requirements

- macOS or another local Unix-like environment with a usable shell and PTY support.
- Python 3.11 or newer.
- The dependencies declared in `pyproject.toml` or `requirements.txt`.
- Ollama installed locally for Ollama-backed generation. Studio does not install or start the Ollama service.

No separate CLI checkout, CLI virtual environment, cloud service, or hosted asset is required for normal Studio operation.

## Installation

From the Sohail Studio project root:

```bash
python3 -m venv .venv                 # only when .venv does not exist
.venv/bin/python -m pip install -e .
```

For development and tests:

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

The editable install places the `sohail-agent` console entry point in the same `.venv` used by FastAPI and the embedded terminal.

## Running Studio

Start the local backend from the project root:

```bash
.venv/bin/uvicorn backend.main:app --reload
```

Then open <http://127.0.0.1:8000>. Bind only to loopback for local use.

## Embedded terminal

The Terminal page connects to `WS /ws/terminal`. The backend creates a PTY and starts the configured shell at the Studio project root by default. A caller can still supply an explicit `cwd` query parameter for a selected local target, including `workspace/`.

The PTY receives its environment directly from Studio:

- `PATH` has `sohail-studio/.venv/bin` first.
- `VIRTUAL_ENV` points to `sohail-studio/.venv`.
- `PWD` is the selected terminal working directory.
- `SOHAIL_STUDIO_ROOT` identifies the Studio root.
- `PYTHONPATH` includes the Studio root.

Therefore the embedded terminal immediately supports:

```bash
pwd
which python
which sohail-agent
sohail-agent --help
ollama list
```

No manual `source .venv/bin/activate`, directory switch, or shell startup-file change is required.

## Integrated CLI

The project entry point is configured as:

```text
sohail-agent = sohail_agent_cli.main:main
```

Use it from the Studio environment:

```bash
.venv/bin/sohail-agent --help
.venv/bin/sohail-agent --version
```

Available commands:

```text
inspect
dockerize
k8s
cicd
docs
interview
plan
plan-v2
bootstrap
stack
specification
blueprint
all
```

Global options are `--version`, `--verbose`, `--dry-run`, `--overwrite`, and `--ollama`.

## Workflows

The five current CLI-backed Studio workflows map to the integrated CLI as follows:

| UI workflow | CLI command |
| --- | --- |
| Inspect Project | `inspect` |
| Dockerize Project | `dockerize` |
| Kubernetes | `k8s` |
| CI/CD | `cicd` |
| Generate Documentation | `docs` |

The lifecycle is:

1. Select a workflow and local target.
2. Request a plan.
3. Review the proposed steps.
4. Approve the plan explicitly.
5. Start the CLI-backed run.
6. Watch command, output, process, completion, and error events.
7. Review the persisted run in Sessions.

Create New Project, Debug Error, and AI Chat remain visible placeholders and are not silently executed.

## HTTP API

- `GET /` — serves the dashboard.
- `GET /api/health` — reports local health and integrated CLI availability.
- `GET /api/workflows` — returns the workflow catalog.
- `GET /api/sessions` — returns recent locally persisted runs.
- `POST /api/workflows/plan` — validates a workflow and creates its approval plan.
- `POST /api/runs` — starts a run only when `approved` is `true` and the target exists.
- `GET /api/runs/{run_id}` — returns buffered run state and events.

Example plan request:

```json
{
  "workflow": "inspect-project",
  "target": "/path/to/local/project",
  "provider": "",
  "model": ""
}
```

Run requests additionally support `approved`, `dry_run`, and `overwrite`.

## WebSockets

### `WS /ws/runs/{run_id}`

Streams the real CLI run. Events include:

- `command` — the structured command preview and purpose.
- `output` — CLI stdout/stderr output.
- `process` — child process information.
- `complete` — success/failure and exit code.
- `error` — an execution or validation error.
- `closed` — the run stream has finished.

### `WS /ws/terminal`

Provides the raw PTY. Input messages can be plain text or JSON with `action: "input"`; a `stop` action sends SIGINT to the shell process.

## Configuration

`settings/default.json` contains the current local defaults:

```json
{
  "terminal_cwd": ".",
  "venv_path": ".venv",
  "shell": "/bin/bash",
  "local_only": true
}
```

`SOHAIL_STUDIO_SHELL` can override the PTY shell. The CLI and workflows preserve these local AI settings:

- `SOHAIL_AI_PROVIDER`
- `SOHAIL_AI_MODEL`
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`

Provider/model fields supplied in a workflow request are passed to the CLI process as environment variables. Ollama remains an external local service; do not run another Ollama server if the existing service is already running.

## Storage and project layout

```text
backend/            FastAPI application and workflow execution
core/               CliBridge and session store
dashboard/          Static UI and local assets
terminal/           Terminal integration boundary
settings/           Runtime defaults
sohail_agent_cli/   Integrated CLI source
tests/              Studio and integrated CLI tests
sessions/           Local run JSON records
workspace/          Available local workspace directory
logs/               Local log directory
.venv/              Single Python environment
```

Sessions and logs are local. The CLI writes generated files only to the approved target and according to its flags.

## Security model

- Studio is local-first and intended for loopback use.
- Plan review and explicit approval are required before workflow execution.
- Workflow IDs are allowlisted in `core/cli_bridge.py`.
- Workflow commands use structured argument lists with `asyncio.create_subprocess_exec`; workflow execution does not use `shell=True`.
- User values are passed as arguments or environment variables rather than concatenated into shell strings.
- The command preview is streamed before process output.
- Run state remains in local session storage.
- The raw PTY is a local WebSocket bridge, not a remote hosted shell.

## Testing

Run the integrated suite from the project root:

```bash
.venv/bin/python -m pytest -q
```

The Phase 4 baseline is 146 passing tests. Safe CLI checks include:

```bash
.venv/bin/sohail-agent --help
.venv/bin/sohail-agent --version
.venv/bin/sohail-agent --dry-run inspect .
```
