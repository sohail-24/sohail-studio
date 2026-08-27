# Phase 1, Step 1.1: Runtime Dependency Intelligence Architecture Analysis

## 1. Worktree status at start and end
- At start: Clean working tree on branch `jules-10152548329846354651-7f4c60ef`.
- At end: Clean working tree. No files were modified.

## 2. Repository areas inspected
- `sohail_agent_cli/inspection/` (`deep_inspector.py`, `models.py`)
- `core/storage/` (`database.py`, `project_intelligence.py`)
- `core/cli_bridge.py`
- `sohail_agent_cli/dockerize/` (`context_builder.py`, `compose_context.py`, `evidence_gap.py`, `infrastructure_policy.py`)
- `sohail_agent_cli/main.py`
- `backend/main.py`

## 3. Current Deep Inspector lifecycle
The entry point for inspection is `DeepInspector.inspect()` in `sohail_agent_cli/inspection/deep_inspector.py`. The lifecycle involves:
- Walking the project directory and classifying files.
- Reading specific files (e.g., `package.json`, `.env`, `docker-compose.yml`, `kubernetes` YAMLs) to extract structural facts.
- Determining the project stack by finding markers (e.g., in `_language_and_frameworks`).
- Facts are stored in lists on the `ProjectIntelligence` model, such as `databases`, `runtimes`, `ports`, `dependencies`, and `environment_variables`.
- Loose strings (e.g., "mongodb", "postgres") are simply added to the `databases: list[str]` array.
- The `Evidence` object captures generic file-level facts.

## 4. Current Project Intelligence schema and data flow
The single normalized project context is `ProjectIntelligence` in `sohail_agent_cli/inspection/models.py`.
- It currently stores detected databases as a flat list of strings (`databases: list[str]`).
- It has `services` and `relationships` lists, but these are currently untyped `list[dict[str, Any]]` and loosely constructed.
- There is no structured, canonical `RuntimeDependency` model connecting a component, a specific technology, and its verified evidence.

## 5. Current evidence/provenance model
- `Evidence` dataclass tracks `source_file`, `evidence_type`, `key`, `value`, and `confidence`.
- The current implementation tracks the fact that a database was mentioned (`evidence_type="database"`, `key="database"`, `value="MongoDB"`, `confidence="medium"`).
- It tracks environment variables and secrets (like `MONGO_URI`).
- However, it does not currently group this evidence into a specific "runtime dependency" requirement for a specific component.

## 6. Current persistence flow
- `core/storage/project_intelligence.py` uses SQLAlchemy to persist the `ProjectIntelligence` model to PostgreSQL.
- Each `ProjectIntelligence` list (e.g., `runtimes`, `commands`, `ports`, `evidence`, `dependencies`) has a dedicated table (e.g., `project_runtimes`, `project_commands`, `project_ports`, `project_evidence`, `project_dependencies`).
- The `databases` list is merely serialized into the `summary` JSON column in `inspection_runs`. It does not have its own table.

## 7. Current retrieval/API flow
- When `Dockerize` (or any other command) runs, it uses `ProjectIntelligenceRepository.load_latest(path)`.
- This reconstructs the `ProjectIntelligence` model exactly as it was persisted in the database.
- The repository relies entirely on this snapshot.

## 8. Current Dockerize consumption flow
- `DockerContextBuilder.build()` (in `sohail_agent_cli/dockerize/context_builder.py`) loads the `ProjectIntelligence`.
- It constructs a `DockerContext` holding an `infrastructure` dict.
- `infrastructure["databases"]` is populated directly from `intelligence.databases` (the list of strings).
- `ComposeContextBuilder.build()` (in `sohail_agent_cli/dockerize/compose_context.py`) reads these strings and generates `data_services` by running each string through `evaluate_infrastructure_candidate()`.
- Because the evidence is just a string without specific context (like an exact image or connection parameters), `evaluate_infrastructure_candidate()` often flags it as `DETECTION_ONLY` or `NEEDS_EVIDENCE` based on policies in `infrastructure_policy.py`.

## 9. Current database/runtime dependency detection findings
- Loose string detection in `_language_and_frameworks`: If "mongoose" or "mongodb" is in a file, "MongoDB" is added to `databases`.
- Connections URIs in `.env` are picked up as environment variables, but they are not linked to the database detection.
- This loose string is passed all the way to `Dockerize`, which lacks the rich evidence (like which component needs it, or what environment variables configure it) to confidently generate a Compose service.

## 10. UI/output detection findings
- In `sohail_agent_cli/main.py`, `cmd_inspect` prints the detected databases: `console.print(f"[bold]Databases:[/bold] {', '.join(intelligence.databases) or 'none detected'}")`.
- This output relies purely on the loosely detected list of strings.

## 11. Exact point(s) where relevant intelligence is currently lost or not represented
- **During Inspection:** We detect a "database" string and an "environment variable" string, but we never create a structured object (e.g., `RuntimeDependency`) that says "Component A requires Database B, evidenced by file C and environment variable D".
- **In the Model:** `ProjectIntelligence` only has `databases: list[str]`.
- **In Persistence:** `databases` is stuffed into the `summary` JSON, losing its identity as a first-class relational concept.

## 12. Recommended minimal insertion point for Phase 1 Step 1.2
To eventually support structured Runtime Dependency Intelligence, we should:
1.  **Extend `sohail_agent_cli/inspection/models.py`:** Create a `RuntimeDependency` dataclass and add `runtime_dependencies: list[RuntimeDependency]` to `ProjectIntelligence`. This model should track the component, the dependency (e.g., "MongoDB"), and link to evidence.
2.  **Update `ProjectIntelligenceRepository`:** Modify `core/storage/project_intelligence.py` to add a new SQLAlchemy table (e.g., `project_runtime_dependencies`) to persist these structured objects.
3.  **Update `DeepInspector`:** Modify `sohail_agent_cli/inspection/deep_inspector.py` to extract `RuntimeDependency` objects when relevant evidence is found, rather than just appending strings to `intelligence.databases`.

This insertion point is correct because it maintains the evidence-bound architecture: Deep Inspector collects the structured evidence, it is persisted immutably in PostgreSQL, and then retrieved cleanly for downstream consumers like Dockerize, without bypassing any layers.

## 13. Exact files likely to require modification in Step 1.2
- `sohail_agent_cli/inspection/models.py`
- `sohail_agent_cli/inspection/deep_inspector.py`
- `core/storage/project_intelligence.py`

## 14. Files that should NOT need modification
- `core/cli_bridge.py`
- `sohail_agent_cli/dockerize/compose_context.py` (Dockerize consumption will be updated in a later phase)
- `backend/main.py`
- `dashboard/*`

## 15. Security findings regarding .env / DATABASE_URL / secrets
- Sohail Studio's persistence database is configured via `DATABASE_URL` parsed by `StorageConfig.from_env()`.
- Credentials are NOT exposed or printed in the codebase.
- In `DeepInspector`, secrets from target repositories (like `MONGO_URI`) are correctly labeled as `sensitive` and handled as `Evidence(..., evidence_type="secret", ...)`.

## 16. Risks or architectural constraints for the next step
- When we add a new table (`project_runtime_dependencies`) in `core/storage/project_intelligence.py`, we must eventually run Alembic migrations.
- We must ensure we don't break the existing `intelligence.databases` list prematurely before Dockerize is updated to use the new `RuntimeDependency` models.

## 17. Confirmation that NO files were modified
Confirmed via `git status`. Working tree is clean.
