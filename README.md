# Sohail Studio

Sohail Studio is a local-first AI engineering workspace combining a browser dashboard, an embedded terminal, and the integrated Sohail-Agent-CLI engineering engine.

The CLI implementation lives in `sohail_agent_cli/`. Studio is self-contained: normal operation does not require a sibling CLI checkout or a second virtual environment.

## What it includes

- Node.js / Express backend with workflow planning, approval, execution, and WebSocket streaming.
- Three-column dashboard with the Workspace Canvas, AI Mentor, Engineering Knowledge Sphere, and Terminal / Execution Engine.
- Raw local PTY terminal that starts at the Studio project root.
- Integrated `sohail-agent` commands for repository inspection, generation, planning, and project scaffolding.
- Local session persistence and optional Google Gemini-backed generation.

## Install and run

From the Studio project root:

```bash
npm install
npm run dev
```

Open <http://127.0.0.1:3000>. The embedded terminal configures the same Studio environment automatically; no `source` command or directory switch is required.

## Production Build

To compile and run in production:

```bash
npm run build
npm start
```

## CLI

Available commands:

`inspect`, `dockerize`, `kubernetes`, `cicd`, `plan`, `blueprint`.

## Workflow model

Studio-backed workflows create a plan first. The user reviews and approves that plan before `CliBridge` launches an allowlisted CLI command. Output, process information, completion, and errors are streamed locally to the dashboard, and completed runs are stored in `sessions/`.

Workflow execution uses structured subprocess arguments and does not use `shell=True`.

## Project layout

```text
server.ts           Node.js / Express API, workflow runs, and WebSockets
dashboard/          Static dashboard application and browser UI
sessions/           Session history storage
settings/           Local runtime configuration defaults
test_runtime_evidence.ts  Project Intelligence and evidence-derived test suite
package.json        Package manifest and scripts
```

## Testing

Run the test suite, linter, and build checks:

```bash
npm test
npm run lint
npm run build
```
