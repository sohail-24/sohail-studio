# Sohail Studio Architecture

Sohail Studio is a self-contained local-first AI engineering workspace.

- The application uses a single Python environment (`.venv`).
- There is no standalone external CLI dependency.
- The engineering engine is integrated directly via `sohail_agent_cli/`.
- All execution requires explicit user approval.
- The UI strictly limits itself to three columns.

## Phase 1 Architecture

The core architecture separates the conversational AI from the execution environment:

```text
Sohail Studio
      |
      +---- Chat
      |       |
      |       +---- OllamaProvider
      |       |
      |       +---- Ollama HTTP /api/chat
      |       |
      |       +---- devops-qwen:latest
      |
      +---- Terminal
      |       |
      |       +---- Real local shell PTY
      |
      +---- Inspect
      |
      +---- Workflow
```

### Chat and Ollama Output

Chat currently uses the existing Ollama HTTP provider and streaming `/api/chat` path. Chat is for conversational AI only.
The system previously used an Ollama PTY for Chat, but Phase 1 moved Chat to the existing HTTP Ollama provider.

The clean streaming architecture is as follows:

```text
User
  ↓
Sohail Studio Chat
  ↓
OllamaProvider
  ↓
Ollama /api/chat
  ↓
devops-qwen:latest
  ↓
streaming response
  ↓
Sohail Studio
```

### Terminal

The Terminal is the execution interface for actual local commands. It uses a real local PTY/shell via WebSocket (`/ws/terminal`).
The shell automatically loads the `.venv` environment from the Studio root without manual activation.

### Chat Safety Boundary

Chat and Terminal are intentionally separate. The AI may explain commands, but Chat itself does not execute those commands.
Terminal is the separate execution environment. This separation is an important architectural security boundary.
Chat messages must NOT execute local shell commands.

## System Flow

- **Browser UI** initiates workflows via HTTP REST.
- **FastAPI** generates workflow plans requiring manual approval.
- **CliBridge** builds safe execution commands from approved plans.
- **Sohail-Agent-CLI** (`sohail_agent_cli/`) executes the logic.
- **Local Filesystem** updates and **Ollama** runs inferences directly.

## Project Structure

- `backend/` serves the UI, plans workflows, and streams execution via WebSockets.
- `core/cli_bridge.py` wraps `sohail_agent_cli/` execution securely without `shell=True`.
- `sohail_agent_cli/` handles agents, generation, and orchestration.
- `dashboard/` contains the static UI (HTML, CSS, JS) and layout.
- `settings/` controls environment paths and preferred shells.
- `sessions/` locally stores JSON logs of completed workflows.
- `.venv/` is the sole Python environment handling both FastAPI and CLI operations.

## Future / Planned

The planned architecture aims to safely obtain real local context instead of asking Ollama to guess:

```text
                    SOHAIL STUDIO
                         |
                         v
                  AI CONTROL PLANE
                         |
             +-----------+-----------+
             |           |           |
             v           v           v
          Ollama      Read Tools   Knowledge
                         |
                    +----+----+
                    |    |    |
                   time files docker
```

Future read-only tools are NOT implemented in Phase 1 and will eventually include time/date, filesystem/project inspection, Docker, Git, Kubernetes, system information, and project knowledge.
