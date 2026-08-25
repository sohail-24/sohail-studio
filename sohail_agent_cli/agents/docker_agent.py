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
from sohail_agent_cli.providers import BaseProvider, OllamaProvider, ProviderConfig


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
            ProviderConfig(base_url=config.ollama_base_url, default_model=self.model)
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
            for attempt in range(2):
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
                self.info(f"Asking {self.model} for a bounded Docker decision")
                self.info(
                    f"Docker context: {context.project['name']} · root {context.project['root_path']} · "
                    f"selected {', '.join(context.project['selected_components'])} · "
                    f"components {len(context.components)} · evidence {len(context.evidence)} · "
                    f"model {self.model}"
                )
                decision = await decision_engine.decide(context)
                if decision.repair_attempted:
                    self.info("Revalidating bounded repaired Docker decision")
                if decision.status == "ready":
                    break
                if docker_plan is not None:
                    self.info(
                        "Dockerize evidence acquisition not started: "
                        "the explicit plan is bound to the persisted inspection snapshot"
                    )
                    break
                if attempt == 1:
                    self.info("Dockerize retry not started: retry limit reached")
                    break
                gap_result = await self._acquire_evidence_once(
                    root, context, decision, repository, acquisition_service,
                    emit_stage_events=using_default_acquisition,
                    allow_clarification=not bool(user_evidence),
                )
                acquisition_details.append(gap_result)
                if not gap_result["accepted_evidence_added"]:
                    clarification = gap_result.get("clarification_request")
                    if clarification is not None:
                        clarification_data = (
                            clarification.to_dict()
                            if hasattr(clarification, "to_dict")
                            else clarification
                        )
                        return AgentResult.controlled(
                            "NEEDS_CLARIFICATION",
                            f"Clarification required: {clarification_data['question']}",
                            data={
                                "decision": decision.raw,
                                "evidence_acquisition": acquisition_details,
                                "clarification_request": clarification_data,
                            },
                        )
                    self.info(
                        "Dockerize retry not started: no new deterministic evidence was accepted"
                    )
                    break
                self.info("Retrying Dockerize once with refreshed Project Intelligence")
            assert decision is not None
            if decision.status != "ready":
                reason = decision.raw.get("reason") or "The DevOps model requires more repository evidence"
                return AgentResult.controlled(
                    "NEEDS_EVIDENCE",
                    f"Docker decision requires evidence: {reason}",
                    data={
                        "decision": decision.raw,
                        "model": self.model,
                        "evidence_acquisition": acquisition_details,
                    },
                )
            if compose and not (decision.compose.get("services") or []):
                return AgentResult.failure("Docker decision did not define Compose services for the selected components")

            artifacts: dict[Path, str] = {}
            files_created: list[Path] = []
            files_skipped: list[Path] = []
            for component in decision.components:
                intelligence = next(item for item in context.components if item["name"] == component["name"])
                component_action = (
                    artifact_plan["dockerfiles"].get(component["name"])
                    if artifact_plan is not None else "generate"
                )
                dockerfile_path = self._dockerfile_path(root, intelligence)
                dockerfile = DockerDecisionEngine.render_dockerfile(component)
                if component_action == "keep":
                    artifacts[dockerfile_path] = dockerfile_path.read_text(encoding="utf-8")
                    files_skipped.append(dockerfile_path)
                    continue
                artifacts[dockerfile_path] = dockerfile
                await self._write_generated(
                    dockerfile_path, dockerfile,
                    overwrite or component_action == "upgrade",
                    files_created, files_skipped,
                )
                if dockerfile_path not in files_created and dockerfile_path.exists():
                    artifacts[dockerfile_path] = dockerfile_path.read_text(encoding="utf-8")
                dockerignore_path = dockerfile_path.parent / ".dockerignore"
                dockerignore = DockerDecisionEngine.render_dockerignore()
                artifacts[dockerignore_path] = dockerignore
                await self._write_generated(
                    dockerignore_path, dockerignore,
                    overwrite or component_action == "upgrade",
                    files_created, files_skipped,
                )
                if dockerignore_path not in files_created and dockerignore_path.exists():
                    artifacts[dockerignore_path] = dockerignore_path.read_text(encoding="utf-8")

            compose_path = self._compose_path(root, context)
            compose_exists = compose_path.exists()
            planned_compose = artifact_plan["compose"] if artifact_plan is not None else None
            generate_compose = compose and (
                (planned_compose in {"generate", "upgrade"}) if planned_compose is not None
                else (not compose_exists or compose_action in {"improve", "generate"})
            )
            if generate_compose:
                compose_content = DockerDecisionEngine.render_compose(decision)
                artifacts[compose_path] = compose_content
                await self._write_generated(
                    compose_path, compose_content,
                    overwrite or planned_compose == "upgrade",
                    files_created, files_skipped,
                )
                if compose_path not in files_created and compose_path.exists():
                    artifacts[compose_path] = compose_path.read_text(encoding="utf-8")
            elif compose and compose_exists:
                artifacts[compose_path] = compose_path.read_text(encoding="utf-8")

            validation = validate_docker_result(
                root,
                context,
                decision,
                artifacts,
                compose_expected=generate_compose,
                compose_path=compose_path,
            )
            self.info("Docker artifacts validated against persisted evidence")
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
                    "files_created": len(files_created),
                    "files_skipped": len(files_skipped),
                    "docker_plan": artifact_plan,
                },
            )
        except (DockerContextError, DockerDecisionError, DockerValidationError) as exc:
            return AgentResult.failure(str(exc))
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
