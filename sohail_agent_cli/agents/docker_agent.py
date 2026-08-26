"""Project-Intelligence driven Docker generation agent."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.config import load_config
from core.evidence import (
    ClarificationRequestError,
    EvidenceAcquisitionService,
    EvidenceAnalysisEngine,
    EvidenceAnalysisError,
    UserProvidedEvidence,
)
from core.storage.project_intelligence import ProjectIntelligenceRepository
from sohail_agent_cli.agents.base_agent import AgentResult, BaseAgent
from sohail_agent_cli.dockerize import (
    DockerClarificationPolicy,
    DockerContextBuilder,
    DockerContextError,
    DockerDecisionEngine,
    DockerDecisionError,
    DockerEvidenceGapAdapter,
    DockerValidationError,
    validate_docker_result,
)
from sohail_agent_cli.dockerize.platform_policy import policy_for_component, policy_value
from sohail_agent_cli.providers import BaseProvider, OllamaProvider, ProviderConfig


DOCKER_OLLAMA_TIMEOUT_SECONDS = 120.0


def _evidence_diagnostic(context: Any, reason: str) -> dict[str, Any]:
    """Describe the evidence boundary without acquiring new repository facts."""

    requirements: list[dict[str, Any]] = []
    for component in context.components:
        name = str(component.get("name") or "component")
        runtimes = list(component.get("runtimes") or [])
        commands = list(component.get("commands") or [])
        application_ports = [
            item for item in component.get("ports", [])
            if item.get("port_type") == "application"
        ]
        start_commands = [
            item for item in commands
            if item.get("name") == "start" and str(item.get("command") or "").strip()
        ]
        derived_artifacts = [
            item for item in component.get("artifacts", [])
            if item.get("source_type") == "DERIVED_DETERMINISTIC"
            and item.get("model_inference") is False
        ]
        policy = policy_for_component(context.platform_policies, name)
        policy_base = policy_value(policy, "base_image")
        policy_workdir = policy_value(policy, "working_directory")
        unsupported = component.get("deployment_evidence") or {}
        build_commands = [
            item for item in commands
            if item.get("name") in {"build", "package"}
            and str(item.get("command") or "").strip()
        ]
        requirements.extend([
            {
                "component": name,
                "requirement": "Application/component identity",
                "source": component.get("evidence") or [],
                "value": name,
                "repository_truth": "FOUND" if name else "NOT FOUND",
                "inspector": "EXTRACTED" if name else "NOT EXTRACTED",
                "persisted": "PERSISTED",
                "docker_context": "INCLUDED",
                "validation": "NOT RUN (decision blocked)" if not name else "PENDING",
            },
            {
                "component": name,
                "requirement": "Exact runtime version",
                "source": [item.get("source_file") for item in runtimes],
                "value": [
                    {"runtime": item.get("runtime"), "version": item.get("version")}
                    for item in runtimes
                ],
                "repository_truth": "FOUND" if runtimes else "NOT FOUND",
                "inspector": "EXTRACTED" if runtimes else "NOT EXTRACTED",
                "persisted": "PERSISTED" if runtimes else "NOT PERSISTED",
                "docker_context": "INCLUDED" if runtimes else "NOT INCLUDED",
                "validation": "NOT RUN (decision blocked)",
            },
            {
                "component": name,
                "requirement": "Build command",
                "source": [item.get("source_file") for item in build_commands],
                "value": [item.get("command") for item in build_commands],
                "repository_truth": "FOUND" if build_commands else "NOT FOUND",
                "inspector": "EXTRACTED" if build_commands else "NOT EXTRACTED",
                "persisted": "PERSISTED" if build_commands else "NOT PERSISTED",
                "docker_context": "INCLUDED" if build_commands else "NOT INCLUDED",
                "validation": "NOT RUN (decision blocked)",
            },
            {
                "component": name,
                "requirement": "Production start command",
                "explicit_evidence": [dict(item) for item in start_commands],
                "derived_deterministic": [dict(item) for item in derived_artifacts],
                "unsupported": unsupported if unsupported.get("status") == "UNSUPPORTED" else None,
                "source": [item.get("source_file") for item in start_commands]
                + [ref.get("source_file") for item in derived_artifacts for ref in item.get("derived_from", [])],
                "value": [item.get("command") for item in start_commands]
                + [item.get("launch_command") for item in derived_artifacts],
                "repository_truth": "FOUND" if start_commands or derived_artifacts else "NOT PROVEN",
                "inspector": "EXTRACTED" if start_commands or derived_artifacts else "NOT EXTRACTED",
                "persisted": "PERSISTED" if start_commands or derived_artifacts else "NOT PERSISTED",
                "docker_context": "INCLUDED" if start_commands or derived_artifacts else "NOT INCLUDED",
                "validation": "NOT RUN (decision blocked)",
                "rejection": (
                    "No explicit or deterministic production start strategy was classified; model inference is not accepted."
                    if not start_commands and not derived_artifacts else ""
                ),
            },
            {
                "component": name,
                "requirement": "Application port",
                "source": [item.get("source_file") for item in application_ports],
                "value": [item.get("port") for item in application_ports],
                "repository_truth": "FOUND" if application_ports else "NOT FOUND",
                "inspector": "EXTRACTED" if application_ports else "NOT EXTRACTED",
                "persisted": "PERSISTED" if application_ports else "NOT PERSISTED",
                "docker_context": "INCLUDED" if application_ports else "NOT INCLUDED",
                "validation": "NOT RUN (decision blocked)",
            },
            {
                "component": name,
                "requirement": "Exact Docker base image",
                "explicit_evidence": [dict(item) for item in component.get("base_images", []) if item.get("source_type", "EXPLICIT_EVIDENCE") == "EXPLICIT_EVIDENCE"],
                "derived_deterministic": [],
                "approved_platform_policy": [policy_base] if policy_base else [],
                "unsupported": {"status": "UNSUPPORTED", "reason": "No exact base image evidence or applicable approved platform policy exists"} if not component.get("base_images") and not policy_base else None,
                "source": [item.get("source_file") for item in component.get("base_images", [])],
                "value": [item.get("image") for item in component.get("base_images", [])] + ([policy_base.get("value")] if policy_base else []),
                "repository_truth": "FOUND" if component.get("base_images") else "NOT IN REPOSITORY",
                "inspector": "EXTRACTED" if component.get("base_images") else "NOT EXTRACTED",
                "persisted": "PERSISTED" if component.get("base_images") else ("POLICY REGISTRY" if policy_base else "NOT PERSISTED"),
                "docker_context": "INCLUDED" if component.get("base_images") or policy_base else "NOT INCLUDED",
                "validation": "NOT RUN (decision blocked)",
            },
            {
                "component": name,
                "requirement": "Exact working directory",
                "explicit_evidence": [dict(item) for item in component.get("working_directories", []) if item.get("source_type", "EXPLICIT_EVIDENCE") == "EXPLICIT_EVIDENCE"],
                "derived_deterministic": [],
                "approved_platform_policy": [policy_workdir] if policy_workdir else [],
                "unsupported": {"status": "UNSUPPORTED", "reason": "No exact working directory evidence or applicable approved platform policy exists"} if not component.get("working_directories") and not policy_workdir else None,
                "source": [item.get("source_file") for item in component.get("working_directories", [])],
                "value": [item.get("path") for item in component.get("working_directories", [])] + ([policy_workdir.get("value")] if policy_workdir else []),
                "repository_truth": "FOUND" if component.get("working_directories") else "NOT IN REPOSITORY",
                "inspector": "EXTRACTED" if component.get("working_directories") else "NOT EXTRACTED",
                "persisted": "PERSISTED" if component.get("working_directories") else ("POLICY REGISTRY" if policy_workdir else "NOT PERSISTED"),
                "docker_context": "INCLUDED" if component.get("working_directories") or policy_workdir else "NOT INCLUDED",
                "validation": "NOT RUN (decision blocked)",
            },
        ])
    if "working directory" in reason.lower():
        recommendation = "Persist an exact authoritative WORKDIR or approved deterministic platform policy; Dockerize will not default to /app."
    elif "base image" in reason.lower():
        recommendation = "Persist an exact base image or approve a documented deterministic platform policy; Ollama cannot choose one."
    else:
        recommendation = "Run Inspect after adding or explicitly documenting the missing production start strategy; do not supply a model-generated default."
    return {
        "stage": "Evidence-bound decision validation",
        "reason": reason,
        "inspection_run_id": context.project.get("inspection_run_id"),
        "repository_scan_during_dockerize": "NO",
        "requirements": requirements,
        "platform_policies": context.platform_policies,
        "evidence_available": context.evidence,
        "evidence_rejected": [],
        "recommended_next_action": recommendation,
    }


class DockerAgent(BaseAgent):
    """Ask the local DevOps model, then execute and validate its decision."""

    def __init__(
        self,
        dry_run: bool = False,
        verbose: bool = False,
        *,
        repository: ProjectIntelligenceRepository | None = None,
        provider: BaseProvider | None = None,
        model: str | None = None,
        acquisition_service: EvidenceAcquisitionService | None = None,
    ) -> None:
        super().__init__(
            name="docker_agent",
            description="Builds Docker artifacts from persisted Project Intelligence",
            dry_run=dry_run,
            verbose=verbose,
        )
        settings_path = Path(__file__).resolve().parents[2] / "settings" / "default.json"
        config = load_config(settings_path)
        self.model = model or config.devops_model
        self.provider = provider or OllamaProvider(
            ProviderConfig(
                base_url=config.ollama_base_url,
                default_model=self.model,
                timeout=DOCKER_OLLAMA_TIMEOUT_SECONDS,
            )
        )
        self.repository = repository
        self.acquisition_service = acquisition_service

    async def execute(
        self,
        path: Path,
        port: int | None = None,
        overwrite: bool = False,
        components: list[str] | None = None,
        compose: bool = True,
        compose_action: str = "keep",
        user_evidence: str | None = None,
        inspection_run_id: str | None = None,
        docker_plan: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AgentResult:
        root = path.expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return AgentResult.failure(f"Target folder does not exist: {root}")
        if self.dry_run:
            self.info("[DRY RUN] Render and validate only; no filesystem writes will be performed")
        repository = self.repository
        close_storage = False
        try:
            if repository is None:
                repository = ProjectIntelligenceRepository.from_env()
                close_storage = True
            context_builder = DockerContextBuilder(repository)
            decision_engine = DockerDecisionEngine(
                self.provider,
                self.model,
                on_model_call=lambda: self.info(f"Asking {self.model} for a bounded Docker decision"),
                on_repair=lambda: self.warning(
                    "Model output format invalid; performing one bounded repair"
                ),
            )
            using_default_acquisition = self.acquisition_service is None
            acquisition_service = self.acquisition_service or EvidenceAcquisitionService(repository)
            if user_evidence:
                try:
                    accepted_user_evidence = UserProvidedEvidence.from_dict(json.loads(user_evidence))
                    if accepted_user_evidence.root_path != str(root) or accepted_user_evidence.component is None:
                        raise ClarificationRequestError("User evidence scope does not match the selected project")
                    DockerClarificationPolicy.validate_user_evidence(accepted_user_evidence)
                    intelligence = repository.load_latest(str(root))
                    if intelligence is None:
                        raise DockerContextError("Project Intelligence is required before user evidence can be accepted")
                    if accepted_user_evidence.component not in {
                        str(item.get("name")) for item in intelligence.components
                    }:
                        raise ClarificationRequestError("User evidence component was not discovered")
                    if not any(
                        item.get("request_id") == accepted_user_evidence.request_id
                        for item in intelligence.user_evidence
                    ):
                        intelligence.user_evidence.append(accepted_user_evidence.to_dict())
                        repository.persist(intelligence)
                    self.info("Validating user-provided evidence")
                    self.info("User-provided evidence accepted")
                except (json.JSONDecodeError, TypeError, ValueError, ClarificationRequestError) as exc:
                    self.info(f"User-provided evidence rejected: {exc}")
                    return AgentResult.controlled(
                        "NEEDS_EVIDENCE",
                        f"User-provided evidence was rejected: {exc}",
                    )
            acquisition_details: list[dict[str, Any]] = []
            decision = None
            selected_components = components
            if docker_plan is not None and not selected_components:
                selected_components = list((docker_plan.get("dockerfiles") or {}).keys())
            # Dockerize is intentionally a single-snapshot workflow.  A model
            # decision gap is reported; repository evidence can only change by
            # running Inspect explicitly before Dockerize.
            for attempt in range(1):
                context = context_builder.build(
                    root,
                    selected_components,
                    expected_inspection_run_id=inspection_run_id if attempt == 0 else None,
                )
                artifact_plan = self._normalize_docker_plan(root, context, docker_plan)
                if artifact_plan is not None:
                    context = replace(context, artifact_plan=artifact_plan)
                    has_generation = any(
                        action in {"generate", "upgrade"}
                        for action in artifact_plan["dockerfiles"].values()
                    ) or artifact_plan["compose"] in {"generate", "upgrade"}
                    if not has_generation:
                        kept = [
                            self._dockerfile_path(root, item)
                            for item in context.components
                            if artifact_plan["dockerfiles"].get(item["name"]) == "keep"
                        ]
                        if artifact_plan["compose"] == "keep":
                            kept.append(self._compose_path(root, context))
                        return AgentResult(
                            success=True,
                            message="Existing Docker configuration kept",
                            files_skipped=kept,
                            data={
                                "inspection_run_id": context.project.get("inspection_run_id"),
                                "docker_plan": artifact_plan,
                                "planned_actions": [
                                    {"action": "keep", "path": str(path)} for path in kept
                                ],
                                "dry_run": self.dry_run,
                                "context": context.to_dict(),
                            },
                        )
                    active_components = [
                        name for name in context.project["selected_components"]
                        if artifact_plan["dockerfiles"].get(name) != "skip"
                    ]
                    if not active_components:
                        if artifact_plan["compose"] in {"generate", "upgrade"}:
                            raise DockerContextError(
                                "Docker Compose cannot be generated without a selected component"
                            )
                        kept = [
                            self._dockerfile_path(root, item)
                            for item in context.components
                            if artifact_plan["dockerfiles"].get(item["name"]) == "keep"
                        ]
                        compose_path = self._compose_path(root, context)
                        if artifact_plan["compose"] == "keep":
                            kept.append(compose_path)
                        return AgentResult(
                            success=True,
                            message="Existing Docker configuration kept",
                            files_skipped=kept,
                            data={
                                "inspection_run_id": context.project.get("inspection_run_id"),
                                "docker_plan": artifact_plan,
                                "planned_actions": [
                                    {"action": "keep", "path": str(path)} for path in kept
                                ],
                                "dry_run": self.dry_run,
                                "context": context.to_dict(),
                            },
                        )
                    if active_components != context.project["selected_components"]:
                        context = context_builder.build(
                            root,
                            active_components,
                            expected_inspection_run_id=inspection_run_id if attempt == 0 else None,
                        )
                        context = replace(context, artifact_plan=artifact_plan)
                self.info(
                    f"Using persisted Project Intelligence: inspection run "
                    f"{context.project.get('inspection_run_id') or 'stored snapshot'}"
                )
                if artifact_plan is not None:
                    selected_artifacts = [
                        f"{name} Dockerfile ({action})"
                        for name, action in artifact_plan["dockerfiles"].items()
                        if action != "skip"
                    ]
                    if artifact_plan["compose"] != "skip":
                        selected_artifacts.append(f"Docker Compose ({artifact_plan['compose']})")
                    self.info(
                        "Selected Docker artifacts: "
                        + (", ".join(selected_artifacts) or "none")
                    )
                self.info(
                    f"Docker context: {context.project['name']} · root {context.project['root_path']} · "
                    f"selected {', '.join(context.project['selected_components'])} · "
                    f"components {len(context.components)} · evidence {len(context.evidence)} · "
                    f"model {self.model}"
                )
                self.info("Running deterministic Docker requirement preflight")
                decision = await decision_engine.decide(context)
                self.info(
                    "Ollama decision received"
                    if decision.model_called
                    else "Deterministic evidence preflight blocked before Ollama"
                )
                if not decision.model_called:
                    self.warning("Missing authoritative Docker requirements")
                    self.info("Ollama was not called")
                if decision.repair_attempted:
                    self.info("Revalidating bounded repaired Docker decision")
                if decision.status == "ready":
                    self.info("Docker decision validated against persisted evidence")
                    break
                self.info(
                    "Dockerize evidence acquisition not started: "
                    "the workflow is bound to the persisted inspection snapshot"
                )
                break
            assert decision is not None
            if decision.status != "ready":
                reason = decision.raw.get("reason") or "The DevOps model requires more repository evidence"
                diagnostic = _evidence_diagnostic(context, reason)
                if decision.raw.get("stage") == "deterministic Docker requirement preflight":
                    diagnostic["stage"] = decision.raw["stage"]
                    diagnostic["preflight"] = decision.raw.get("evidence_boundary", [])
                    diagnostic["missing_requirements"] = decision.raw.get("missing_requirements", [])
                diagnostic["model_proposed"] = (
                    decision.raw.get("model_proposed")
                    or {
                        "components": decision.raw.get("components", []),
                        "compose": decision.raw.get("compose", {}),
                    }
                    if decision.model_called
                    else None
                )
                return AgentResult.controlled(
                    "NEEDS_EVIDENCE",
                    f"Docker decision requires evidence: {reason}",
                    data={
                        "decision": decision.raw,
                        "model": self.model,
                        "evidence_acquisition": acquisition_details,
                        "inspection_run_id": context.project.get("inspection_run_id"),
                        "context": context.to_dict(),
                        "diagnostic": diagnostic,
                        "repair_attempts": int(decision.repair_attempted),
                        "model_called": decision.model_called,
                        "dry_run": self.dry_run,
                    },
                )
            if compose and not (decision.compose.get("services") or []):
                return AgentResult.failure("Docker decision did not define Compose services for the selected components")

            artifacts: dict[Path, str] = {}
            files_created: list[Path] = []
            files_skipped: list[Path] = []
            pending_writes: list[tuple[Path, str, bool]] = []
            planned_actions: list[dict[str, str]] = []
            self.info("Rendering selected Docker artifacts")
            for component in decision.components:
                intelligence = next(item for item in context.components if item["name"] == component["name"])
                component_action = (
                    artifact_plan["dockerfiles"].get(component["name"])
                    if artifact_plan is not None else "generate"
                )
                dockerfile_path = self._dockerfile_path(root, intelligence)
                # Rendering receives the model's bounded decision together with
                # persisted deterministic strategy facts.  The model cannot
                # add or replace artifact identity while the renderer remains
                # independent of repository access.
                render_component = {
                    **component,
                    "artifacts": list(intelligence.get("artifacts") or []),
                    "deployment_evidence": dict(intelligence.get("deployment_evidence") or {}),
                    "language": intelligence.get("language"),
                    "platform_policy": policy_for_component(
                        context.platform_policies, str(component.get("name"))
                    ),
                }
                dockerfile = DockerDecisionEngine.render_dockerfile(render_component)
                if component_action == "keep":
                    artifacts[dockerfile_path] = dockerfile_path.read_text(encoding="utf-8")
                    files_skipped.append(dockerfile_path)
                    planned_actions.append({"action": "keep", "path": str(dockerfile_path)})
                    continue
                dockerfile_overwrite = overwrite or component_action == "upgrade"
                if dockerfile_path.exists() and not dockerfile_overwrite:
                    artifacts[dockerfile_path] = dockerfile_path.read_text(encoding="utf-8")
                    files_skipped.append(dockerfile_path)
                    planned_actions.append({"action": "keep", "path": str(dockerfile_path)})
                else:
                    artifacts[dockerfile_path] = dockerfile
                    pending_writes.append((dockerfile_path, dockerfile, dockerfile_overwrite))
                    planned_actions.append({"action": component_action, "path": str(dockerfile_path)})
                dockerignore_path = dockerfile_path.parent / ".dockerignore"
                dockerignore = DockerDecisionEngine.render_dockerignore()
                dockerignore_overwrite = overwrite or component_action == "upgrade"
                if dockerignore_path.exists() and not dockerignore_overwrite:
                    artifacts[dockerignore_path] = dockerignore_path.read_text(encoding="utf-8")
                    files_skipped.append(dockerignore_path)
                    planned_actions.append({"action": "keep", "path": str(dockerignore_path)})
                else:
                    artifacts[dockerignore_path] = dockerignore
                    pending_writes.append((dockerignore_path, dockerignore, dockerignore_overwrite))
                    planned_actions.append({"action": component_action, "path": str(dockerignore_path)})

            compose_path = self._compose_path(root, context)
            compose_exists = compose_path.exists()
            planned_compose = artifact_plan["compose"] if artifact_plan is not None else None
            generate_compose = compose and (
                (planned_compose in {"generate", "upgrade"}) if planned_compose is not None
                else (not compose_exists or compose_action in {"improve", "generate"})
            )
            if generate_compose:
                compose_content = DockerDecisionEngine.render_compose(decision)
                compose_overwrite = overwrite or planned_compose == "upgrade"
                if compose_path.exists() and not compose_overwrite:
                    artifacts[compose_path] = compose_path.read_text(encoding="utf-8")
                    files_skipped.append(compose_path)
                    planned_actions.append({"action": "keep", "path": str(compose_path)})
                else:
                    artifacts[compose_path] = compose_content
                    pending_writes.append((compose_path, compose_content, compose_overwrite))
                    planned_actions.append({"action": planned_compose or "generate", "path": str(compose_path)})
            elif compose and compose_exists:
                artifacts[compose_path] = compose_path.read_text(encoding="utf-8")
                planned_actions.append({"action": "keep", "path": str(compose_path)})

            self.info("Validating rendered Docker artifacts")
            validation = validate_docker_result(
                root,
                context,
                decision,
                artifacts,
                compose_expected=generate_compose,
                compose_path=compose_path,
            )
            self.info("Docker artifacts validated against persisted evidence")
            if self.dry_run:
                self.info("[DRY RUN] No files were written or modified")
            else:
                for write_path, content, write_overwrite in pending_writes:
                    await self._write_generated(
                        write_path, content, write_overwrite,
                        files_created, files_skipped,
                    )
            for created in files_created:
                self.success(f"{'Would write' if self.dry_run else 'Wrote'} {created}")
            for skipped in files_skipped:
                self.warning(f"Skipped existing file (use overwrite): {skipped}")
            return AgentResult(
                success=True,
                message="Docker artifacts validated successfully",
                files_created=files_created,
                files_skipped=files_skipped,
                data={
                    "model": self.model,
                    "context": context.to_dict(),
                    "decision": decision.raw,
                    "validation": validation,
                    "inspection_run_id": context.project.get("inspection_run_id"),
                    "rendered_artifacts": [
                        {"path": str(path), "content": content}
                        for path, content in artifacts.items()
                    ],
                    "repair_attempts": int(decision.repair_attempted),
                    "model_called": decision.model_called,
                    "files_created": len(files_created),
                    "files_skipped": len(files_skipped),
                    "docker_plan": artifact_plan,
                    "planned_actions": planned_actions,
                    "dry_run": self.dry_run,
                },
            )
        except (DockerContextError, DockerDecisionError, DockerValidationError) as exc:
            if isinstance(exc, DockerContextError):
                stage = "Persisted Docker context"
            elif isinstance(exc, DockerDecisionError):
                stage = "Ollama Docker decision"
            else:
                stage = "Docker artifact validation"
            return AgentResult.failure(str(exc), data={"stage": stage})
        finally:
            if close_storage and repository is not None:
                repository.storage.close()

    @staticmethod
    def _dockerfile_path(root: Path, component: dict[str, Any]) -> Path:
        stored = [str(item) for item in component.get("dockerfiles", []) if str(item).strip()]
        if stored:
            return root / stored[0]
        return root / str(component.get("path") or ".") / "Dockerfile"

    @staticmethod
    def _compose_path(root: Path, context: Any) -> Path:
        stored = [
            str(item) for item in context.infrastructure.get("compose_files", [])
            if str(item).strip()
        ]
        return root / stored[0] if stored else root / "docker-compose.yml"

    @classmethod
    def _normalize_docker_plan(
        cls,
        root: Path,
        context: Any,
        docker_plan: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if docker_plan is None:
            return None
        dockerfiles = docker_plan.get("dockerfiles")
        compose = docker_plan.get("compose", "skip")
        allowed = {"generate", "upgrade", "keep", "skip"}
        if not isinstance(dockerfiles, dict) or compose not in allowed:
            raise DockerContextError("Docker plan must define dockerfiles and a valid Compose action")
        names = {str(item["name"]) for item in context.components}
        unknown = set(dockerfiles) - names
        if unknown:
            raise DockerContextError(f"Docker plan contains undiscovered components: {', '.join(sorted(unknown))}")
        normalized: dict[str, str] = {}
        for component in context.components:
            name = str(component["name"])
            action = dockerfiles.get(name, "skip")
            if action not in allowed:
                raise DockerContextError(f"Invalid Dockerfile action for {name}: {action}")
            path = cls._dockerfile_path(root, component)
            if action == "keep" and not path.exists():
                raise DockerContextError(
                    f"Stored Dockerfile for {name} is unavailable; re-inspect explicitly before keeping it"
                )
            if action == "upgrade" and not path.exists():
                raise DockerContextError(
                    f"Cannot upgrade missing Dockerfile for {name}; choose generate instead"
                )
            if action == "generate" and path.exists():
                raise DockerContextError(
                    f"Dockerfile for {name} already exists; choose keep or upgrade explicitly"
                )
            normalized[name] = action
        compose_path = cls._compose_path(root, context)
        if compose == "keep" and not compose_path.exists():
            raise DockerContextError(
                "Stored Docker Compose configuration is unavailable; re-inspect explicitly before keeping it"
            )
        if compose == "upgrade" and not compose_path.exists():
            raise DockerContextError(
                "Cannot upgrade missing Docker Compose configuration; choose generate instead"
            )
        if compose == "generate" and compose_path.exists():
            raise DockerContextError(
                "Docker Compose already exists; choose keep or upgrade explicitly"
            )
        return {"dockerfiles": normalized, "compose": compose}

    async def _acquire_evidence_once(
        self,
        root: Path,
        context: Any,
        decision: Any,
        repository: ProjectIntelligenceRepository,
        acquisition_service: EvidenceAcquisitionService,
        emit_stage_events: bool = True,
        allow_clarification: bool = True,
    ) -> dict[str, Any]:
        """Run one bounded analysis/acquisition cycle; never accepts model facts."""

        self.info("Evidence analysis: analyzing the deterministic Docker evidence gap")
        missing = [
            str(item.get("name"))
            for item in context.components
            if not any(
                command.get("name") == "start" and str(command.get("command") or "").strip()
                for command in item.get("commands", [])
            )
        ]
        affected = missing or list(context.project.get("selected_components") or [])
        intelligence = repository.load_latest(str(root))
        if intelligence is None:
            raise DockerContextError("Project Intelligence disappeared before evidence analysis")
        analyses: list[dict[str, Any]] = []
        accepted_added = False
        total_added = 0
        targets_inspected: list[str] = []
        rejected_targets: list[dict[str, str]] = []
        clarification_request: dict[str, Any] | None = None
        for component_name in affected:
            gap = DockerEvidenceGapAdapter.from_context(
                context,
                component_name,
                reason=decision.raw.get("reason"),
            )
            try:
                analysis = await EvidenceAnalysisEngine(self.provider, self.model).analyze(
                    gap, context.to_dict(),
                )
            except EvidenceAnalysisError as exc:
                if exc.response_received:
                    self.info("Evidence analysis response received")
                self.info(f"Evidence analysis parsing failed: {exc}")
                analyses.append({"status": "blocked", "error": str(exc)})
                continue
            analyses.append(analysis.to_dict())
            parse_quality = "partially valid" if (
                analysis.diagnostics or analysis.rejected_inspection_targets
            ) else "valid"
            self.info(f"Evidence analysis response received: {parse_quality}")
            self.info(
                "Evidence analysis parsed: "
                f"{len(analysis.inspection_targets)} valid target(s), "
                f"{len(analysis.rejected_inspection_targets)} malformed target(s) rejected"
            )
            for rejected in analysis.rejected_inspection_targets:
                self.info(
                    f"Rejected malformed proposal {rejected.get('index', '?')}: "
                    f"{rejected.get('reason', 'invalid inspection target')}"
                )
            for diagnostic in analysis.diagnostics:
                location = diagnostic.get("field", "analysis")
                if "index" in diagnostic:
                    location = f"{location}[{diagnostic['index']}]"
                self.info(
                    f"Evidence analysis diagnostic ({location}): "
                    f"{diagnostic.get('reason', 'optional analysis item ignored')}"
                )
            if analysis.status.value != "inspect_more":
                self.info(
                    "Deterministic target validation not started: "
                    "analysis did not request inspection"
                )
                continue
            if not analysis.inspection_targets and emit_stage_events:
                self.info(
                    "Deterministic target validation not started: "
                    "no valid inspection proposals"
                )
                continue
            acquire_kwargs: dict[str, Any] = {}
            if emit_stage_events:
                acquire_kwargs = {
                    "on_validation_start": lambda: self.info(
                        "Validating proposed repository targets"
                    ),
                    "on_validation_complete": lambda approved, rejected: self.info(
                        f"Deterministic target validation complete: "
                        f"{approved} safe target(s) approved, "
                        f"{len(rejected)} rejected"
                    ),
                    "on_acquisition_start": lambda count: self.info(
                        f"Acquisition started: inspecting {count} approved target(s)"
                    ),
                    "on_inspection_complete": lambda: self.info(
                        "Deterministic evidence inspection completed"
                    ),
                }
            acquired = acquisition_service.acquire(
                root, intelligence, gap, analysis, **acquire_kwargs
            )
            if (
                allow_clarification
                and clarification_request is None
                and acquired.validated_target_count > 0
                and not acquired.accepted_evidence_added
            ):
                clarification_request = DockerClarificationPolicy.build_request(gap)
            targets_inspected.extend(acquired.inspected_targets)
            rejected_targets.extend(acquired.rejected_targets)
            accepted_added = accepted_added or acquired.accepted_evidence_added
            total_added += acquired.added_evidence_count
            if acquired.refreshed is not None:
                intelligence = acquired.refreshed
            if acquired.validated_target_count:
                if acquired.accepted_evidence_added:
                    self.info(
                        f"Accepted deterministic evidence added: "
                        f"{acquired.added_evidence_count} fact(s)"
                    )
                    self.info("Project Intelligence snapshot refreshed")
                else:
                    self.info("No new deterministic evidence accepted")
                    self.info("Project Intelligence snapshot not refreshed")
            elif acquired.rejected_targets:
                self.info("No proposed target passed deterministic validation")
        return {
            "accepted_evidence_added": accepted_added,
            "added_evidence_count": total_added,
            "inspected_targets": targets_inspected,
            "rejected_targets": rejected_targets,
            "analyses": analyses,
            "clarification_request": clarification_request,
        }

    async def _write_generated(
        self,
        path: Path,
        content: str,
        overwrite: bool,
        files_created: list[Path],
        files_skipped: list[Path],
    ) -> None:
        success, _message, _is_dry_run = await self.write_file(path, content, overwrite=overwrite)
        if success:
            files_created.append(path)
        else:
            files_skipped.append(path)
