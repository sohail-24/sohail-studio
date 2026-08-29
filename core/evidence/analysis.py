"""Strict, technology-neutral AI evidence analysis and safe acquisition."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sohail_agent_cli.inspection import DeepInspector, ProjectIntelligence
from sohail_agent_cli.inspection.setup import ProjectSetupBuilder
from sohail_agent_cli.providers import BaseProvider, GenerationRequest

from .models import (
    CandidateHypothesis,
    ClarificationQuestion,
    EvidenceAnalysis,
    EvidenceAnalysisStatus,
    EvidenceGap,
    EvidenceReference,
    EvidenceRelationship,
    InspectionTarget,
    PROTECTED_DIRECTORIES,
)


DOCKER_EVIDENCE_FILENAMES = frozenset({
    ".env", ".env.example", ".env.sample", ".env.template",
    "Makefile", "Procfile", "pyproject.toml", "requirements.txt",
    "Pipfile", "Pipfile.lock", "poetry.lock", "package.json",
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
    "go.mod", "Cargo.toml", "rust-toolchain", "rust-toolchain.toml",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "settings.gradle.kts", ".nvmrc", ".python-version",
})
DOCKER_EVIDENCE_SUFFIXES = frozenset({".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".sh"})
DOCKER_EVIDENCE_DIRECTORIES = frozenset({
    "docker", "deploy", "deployment", "deployments", "infra", "infrastructure",
    "k8s", "kubernetes", "manifests", "ops", "eks-manifests",
})
DOCKER_ENTRYPOINT_FILENAMES = frozenset({
    "app.py", "main.py", "run.py", "server.py", "wsgi.py", "manage.py",
    "index.js", "index.ts", "main.js", "main.ts", "server.js", "server.ts",
})


class EvidenceAnalysisError(ValueError):
    """Raised when the analysis provider returns an unsafe/invalid contract."""

    def __init__(self, message: str, *, response_received: bool = False) -> None:
        super().__init__(message)
        self.response_received = response_received


ANALYSIS_SYSTEM_PROMPT = """You are an evidence analysis assistant for a local engineering tool.
Analyze only the supplied repository evidence and the typed evidence gap.
Your response is analysis, never accepted Project Intelligence. Do not invent
facts, commands, runtimes, ports, services, or files. Never emit shell commands
or absolute paths. Return one JSON object only.

Required field: status, whose value is inspect_more, ask_user, or blocked.
When status is inspect_more, inspection_targets is required and must be a list.
Each inspection target must contain only a relative_path; expected_evidence_type,
rationale, and component are optional metadata. clarification_questions is an
optional list. Do not emit fields outside this contract. Omit optional sections
when they are not needed."""


class EvidenceAnalysisEngine:
    """Call Ollama only for bounded analysis of an already-detected gap."""

    def __init__(self, provider: BaseProvider, model: str) -> None:
        self.provider = provider
        self.model = model

    async def analyze(self, gap: EvidenceGap, context: dict[str, Any]) -> EvidenceAnalysis:
        prompt = (
            "EVIDENCE_GAP:\n"
            + json.dumps(gap.to_dict(), sort_keys=True, separators=(",", ":"))
            + "\nCURRENT_PROJECT_EVIDENCE:\n"
            + json.dumps(context, sort_keys=True, separators=(",", ":"))
        )
        result = await self.provider.generate(
            GenerationRequest(
                prompt=prompt,
                system=ANALYSIS_SYSTEM_PROMPT,
                model=self.model,
                temperature=0,
                options={"format": "json", "num_ctx": 8192, "num_predict": 1024},
                think=False,
            )
        )
        if result.error:
            raise EvidenceAnalysisError(result.error)
        try:
            return self._parse_json(result.text)
        except EvidenceAnalysisError as exc:
            raise EvidenceAnalysisError(str(exc), response_received=True) from exc

    @classmethod
    def _parse_json(cls, text: str) -> EvidenceAnalysis:
        payload = cls._extract_json(text)
        required = {
            "status", "inspection_targets", "findings", "evidence_relationships",
            "clarification_questions", "candidate_hypotheses", "unsupported_assumptions",
        }
        if "status" not in payload:
            raise EvidenceAnalysisError("analysis response missing field(s): status")
        unexpected = sorted(set(payload) - required)
        if unexpected:
            raise EvidenceAnalysisError(
                f"analysis response has unexpected field(s): {', '.join(unexpected)}"
            )
        try:
            status = EvidenceAnalysisStatus(payload["status"])
        except ValueError as exc:
            raise EvidenceAnalysisError(
                "analysis status must be inspect_more, ask_user, or blocked"
            ) from exc
        diagnostics: list[dict[str, Any]] = []
        if status is EvidenceAnalysisStatus.INSPECT_MORE and "inspection_targets" not in payload:
            raise EvidenceAnalysisError("analysis response missing field(s): inspection_targets")
        target_items = payload.get("inspection_targets", [])
        if not isinstance(target_items, list):
            if status is EvidenceAnalysisStatus.INSPECT_MORE:
                raise EvidenceAnalysisError("analysis field inspection_targets must be a list")
            diagnostics.append({
                "field": "inspection_targets",
                "reason": "optional field must be a list for a non-inspection analysis",
            })
            target_items = []

        optional_fields = (
            "findings", "evidence_relationships", "clarification_questions",
            "candidate_hypotheses", "unsupported_assumptions",
        )
        optional_values: dict[str, list[Any]] = {}
        omitted_optional = [field for field in optional_fields if field not in payload]
        if omitted_optional:
            diagnostics.append({
                "field": "optional_sections",
                "reason": f"omitted optional field(s): {', '.join(omitted_optional)}",
            })
        for field in optional_fields:
            value = payload.get(field, [])
            if not isinstance(value, list):
                diagnostics.append({"field": field, "reason": "optional field must be a list"})
                value = []
            optional_values[field] = value
        rejected_targets: list[dict[str, Any]] = []
        targets: list[InspectionTarget] = []
        for index, item in enumerate(target_items):
            try:
                targets.append(cls._target(item))
            except (KeyError, TypeError, ValueError) as exc:
                rejected_targets.append({"index": index, "reason": str(exc)})
        relationships: list[EvidenceRelationship] = []
        for index, item in enumerate(optional_values["evidence_relationships"]):
            try:
                relationships.append(cls._relationship(item))
                if isinstance(item, dict) and (
                    "description" not in item or not isinstance(item.get("description"), str)
                ):
                    diagnostics.append({
                        "field": "evidence_relationships",
                        "index": index,
                        "reason": "optional description omitted or invalid",
                    })
            except (KeyError, TypeError, ValueError) as exc:
                diagnostics.append({
                    "field": "evidence_relationships", "index": index, "reason": str(exc),
                })
        questions = cls._optional_items(
            optional_values["clarification_questions"], "clarification_questions",
            cls._question, diagnostics,
        )
        hypotheses = cls._optional_items(
            optional_values["candidate_hypotheses"], "candidate_hypotheses",
            cls._hypothesis, diagnostics,
        )
        findings = cls._optional_strings(optional_values["findings"], "findings", diagnostics)
        unsupported = cls._optional_strings(
            optional_values["unsupported_assumptions"], "unsupported_assumptions", diagnostics,
        )
        return EvidenceAnalysis(
            status=status,
            findings=findings,
            evidence_relationships=tuple(relationships),
            inspection_targets=tuple(targets),
            rejected_inspection_targets=tuple(rejected_targets),
            clarification_questions=tuple(questions),
            candidate_hypotheses=tuple(hypotheses),
            unsupported_assumptions=unsupported,
            diagnostics=tuple(diagnostics),
        )

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Extract the first JSON object; schema validation remains authoritative."""

        value = str(text).strip().lstrip("\ufeff")
        decoder = json.JSONDecoder()
        for index, character in enumerate(value):
            if character != "{":
                continue
            try:
                payload, _end = decoder.raw_decode(value, index)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise EvidenceAnalysisError("analysis response does not contain a JSON object")

    @staticmethod
    def _optional_items(
        items: list[Any], field: str, parser: Any, diagnostics: list[dict[str, Any]],
    ) -> list[Any]:
        accepted: list[Any] = []
        for index, item in enumerate(items):
            try:
                accepted.append(parser(item))
            except (KeyError, TypeError, ValueError) as exc:
                diagnostics.append({"field": field, "index": index, "reason": str(exc)})
        return accepted

    @staticmethod
    def _optional_strings(
        items: list[Any], field: str, diagnostics: list[dict[str, Any]],
    ) -> tuple[str, ...]:
        accepted: list[str] = []
        for index, item in enumerate(items):
            if isinstance(item, str) and item.strip():
                accepted.append(item)
            else:
                diagnostics.append({
                    "field": field, "index": index, "reason": "entry must be a non-empty string",
                })
        return tuple(accepted)

    @staticmethod
    def _strings(items: list[Any], field: str) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in items):
            raise ValueError(f"{field} entries must be non-empty strings")
        return items

    @staticmethod
    def _reference(item: Any) -> EvidenceReference:
        if not isinstance(item, dict):
            raise TypeError("evidence reference must be an object")
        return EvidenceReference(
            source_file=str(item["source_file"]), evidence_type=str(item["evidence_type"]),
            key=str(item["key"]), confidence=str(item.get("confidence", "low")),
            line_number=item.get("line_number"), origin="AI_ANALYSIS",
        )

    @classmethod
    def _target(cls, item: Any) -> InspectionTarget:
        if not isinstance(item, dict):
            raise TypeError("inspection target must be an object")
        required = {"relative_path"}
        allowed = required | {"expected_evidence_type", "rationale", "component"}
        missing = sorted(required - item.keys())
        unexpected = sorted(set(item) - allowed)
        if missing:
            raise ValueError(f"inspection target missing field(s): {', '.join(missing)}")
        if unexpected:
            raise ValueError(f"inspection target has unexpected field(s): {', '.join(unexpected)}")
        if not isinstance(item["relative_path"], str) or not item["relative_path"].strip():
            raise TypeError("inspection target relative_path must be a non-empty string")
        if item.get("component") is not None and (
            not isinstance(item["component"], str) or not item["component"].strip()
        ):
            raise TypeError("inspection target component must be a string or null")
        return InspectionTarget(
            relative_path=item["relative_path"],
            expected_evidence_type=(
                item.get("expected_evidence_type", "")
                if isinstance(item.get("expected_evidence_type", ""), str)
                else ""
            ),
            rationale=(
                item.get("rationale", "")
                if isinstance(item.get("rationale", ""), str)
                else ""
            ),
            component=item.get("component"),
        )

    @classmethod
    def _relationship(cls, item: Any) -> EvidenceRelationship:
        if not isinstance(item, dict):
            raise TypeError("evidence relationship must be an object")
        references = item.get("references", [])
        if not isinstance(references, list):
            raise TypeError("evidence relationship references must be a list")
        description = item.get("description", "")
        if not isinstance(description, str):
            description = ""
        return EvidenceRelationship(
            description=description,
            references=tuple(cls._reference(ref) for ref in references),
        )

    @staticmethod
    def _question(item: Any) -> ClarificationQuestion:
        if not isinstance(item, dict):
            raise TypeError("clarification question must be an object")
        return ClarificationQuestion(
            question=str(item["question"]), requirement=str(item["requirement"]), component=item.get("component")
        )

    @classmethod
    def _hypothesis(cls, item: Any) -> CandidateHypothesis:
        if not isinstance(item, dict):
            raise TypeError("candidate hypothesis must be an object")
        return CandidateHypothesis(
            statement=str(item["statement"]), confidence=str(item["confidence"]),
            supporting_evidence=tuple(cls._reference(ref) for ref in item.get("supporting_evidence", [])),
            unsupported_assumptions=tuple(cls._strings(item.get("unsupported_assumptions", []), "unsupported_assumptions")),
        )


@dataclass(frozen=True)
class AcquisitionResult:
    inspected_targets: tuple[str, ...] = ()
    rejected_targets: tuple[dict[str, str], ...] = ()
    accepted_evidence_added: bool = False
    added_evidence_count: int = 0
    validated_target_count: int = 0
    verification_performed: bool = False
    refreshed: ProjectIntelligence | None = None
    scope: str = ""
    requested_requirements: tuple[str, ...] = ()
    candidate_targets: tuple[str, ...] = ()
    evidence_found: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "inspected_targets": list(self.inspected_targets),
            "rejected_targets": [dict(item) for item in self.rejected_targets],
            "accepted_evidence_added": self.accepted_evidence_added,
            "added_evidence_count": self.added_evidence_count,
            "validated_target_count": self.validated_target_count,
            "verification_performed": self.verification_performed,
            "scope": self.scope,
            "requested_requirements": list(self.requested_requirements),
            "candidate_targets": list(self.candidate_targets),
            "evidence_found": [dict(item) for item in self.evidence_found],
        }


class EvidenceAcquisitionService:
    """Validate model proposals, inspect only safe existing targets, and persist facts."""

    def __init__(self, repository: Any, inspector: DeepInspector | None = None, max_targets: int = 16) -> None:
        self.repository = repository
        self.inspector = inspector or DeepInspector()
        self.max_targets = max_targets

    def acquire_docker_evidence(
        self,
        root: Path,
        intelligence: ProjectIntelligence,
        context: Any,
        missing_requirements: list[str] | tuple[str, ...],
    ) -> AcquisitionResult:
        """Inspect a bounded, deterministic set of current Docker evidence.

        This path intentionally does not call an AI provider or the full
        inspector.  It inventories only current files whose names, locations,
        or persisted entrypoint records can answer unresolved Docker facts,
        then reuses ``inspect_targets`` for safe extraction and provenance.
        """

        root = Path(root).expanduser().resolve()
        requirements = tuple(str(item) for item in missing_requirements if str(item).strip())
        targets = self._docker_targets(root, context)
        if not targets:
            return AcquisitionResult(
                verification_performed=True,
                scope="docker",
                requested_requirements=requirements,
            )

        partial = self.inspector.inspect_targets(root, targets)
        evidence_found = tuple(
            {
                key: value
                for key, value in item.to_dict().items()
                if key in {"source_file", "evidence_type", "key", "confidence", "line_number", "source_type", "rule_id"}
            }
            for item in partial.evidence
        )
        merged = self._merge(intelligence, partial)
        merged.project_setup = ProjectSetupBuilder.build(merged)
        before = {self._evidence_key(item) for item in intelligence.evidence}
        after = {self._evidence_key(item) for item in merged.evidence}
        added = len(after - before)
        if added:
            self.repository.persist(merged)
        return AcquisitionResult(
            inspected_targets=tuple(path.relative_to(root).as_posix() for path in targets),
            accepted_evidence_added=bool(added),
            added_evidence_count=added,
            validated_target_count=len(targets),
            verification_performed=True,
            refreshed=merged if added else intelligence,
            scope="docker",
            requested_requirements=requirements,
            candidate_targets=tuple(path.relative_to(root).as_posix() for path in targets),
            evidence_found=evidence_found,
        )

    def _docker_targets(self, root: Path, context: Any) -> list[Path]:
        """Select current files by deterministic Docker evidence relevance."""

        entrypoints = {
            str(item.get("source_file"))
            for component in getattr(context, "components", []) or []
            for item in component.get("entrypoints", []) or []
            if item.get("source_file")
        }
        candidates: list[Path] = []
        for path in root.rglob("*"):
            if not path.is_file() or any(part in PROTECTED_DIRECTORIES for part in path.relative_to(root).parts):
                continue
            relative = path.relative_to(root).as_posix()
            name = path.name
            lower_name = name.lower()
            parent_names = {part.lower() for part in path.relative_to(root).parts[:-1]}
            relevant = (
                relative in entrypoints
                or name in DOCKER_EVIDENCE_FILENAMES
                or name.startswith("Dockerfile.")
                or lower_name.startswith("readme")
                or (name in DOCKER_ENTRYPOINT_FILENAMES)
                or (path.suffix.lower() in DOCKER_EVIDENCE_SUFFIXES and parent_names.intersection(DOCKER_EVIDENCE_DIRECTORIES))
            )
            if relevant:
                candidates.append(path)
        return sorted(candidates, key=lambda path: path.relative_to(root).as_posix())[: self.max_targets]

    def acquire(
        self,
        root: Path,
        intelligence: ProjectIntelligence,
        gap: EvidenceGap,
        analysis: EvidenceAnalysis,
        on_validation_start: Any | None = None,
        on_validation_complete: Any | None = None,
        on_acquisition_start: Any | None = None,
        on_inspection_complete: Any | None = None,
        on_verification_start: Any | None = None,
    ) -> AcquisitionResult:
        accepted: list[Path] = []
        rejected: list[dict[str, str]] = []
        inspected: list[str] = []
        if on_validation_start is not None:
            on_validation_start()
        for target in analysis.inspection_targets[: self.max_targets]:
            if target.component and target.component != gap.component:
                rejected.append({"target": target.relative_path, "reason": "target component does not match the gap"})
                continue
            try:
                resolved = target.validate(root)
            except ValueError as exc:
                rejected.append({"target": target.relative_path, "reason": str(exc)})
                continue
            accepted.append(resolved)
            inspected.append(target.relative_path)
        if on_validation_complete is not None:
            on_validation_complete(len(accepted), tuple(rejected))
        if not accepted:
            return AcquisitionResult(tuple(inspected), tuple(rejected))
        if on_acquisition_start is not None:
            on_acquisition_start(len(accepted))
        partial = self.inspector.inspect_targets(root, accepted)
        if on_inspection_complete is not None:
            on_inspection_complete()
        elif on_verification_start is not None:
            on_verification_start()
        merged = self._merge(intelligence, partial)
        before = {self._evidence_key(item) for item in intelligence.evidence}
        after = {self._evidence_key(item) for item in merged.evidence}
        added = len(after - before)
        if added == 0:
            return AcquisitionResult(
                tuple(inspected), tuple(rejected), False, 0, len(accepted), True, intelligence,
            )
        self.repository.persist(merged)
        return AcquisitionResult(
            tuple(inspected), tuple(rejected), True, added, len(accepted), True, merged,
        )

    @staticmethod
    def _evidence_key(item: Any) -> tuple[str, str, str, str]:
        return (str(item.source_file), str(item.evidence_type), str(item.key), json.dumps(item.value, sort_keys=True))

    @classmethod
    def _merge(cls, base: ProjectIntelligence, partial: ProjectIntelligence) -> ProjectIntelligence:
        merged = replace(base)
        for field in ("files", "evidence", "dependencies", "commands", "ports", "services", "runtimes", "environment_variables"):
            values = list(getattr(base, field))
            seen = {json.dumps(item.to_dict() if hasattr(item, "to_dict") else item, sort_keys=True, default=str) for item in values}
            for item in getattr(partial, field):
                marker = json.dumps(item.to_dict() if hasattr(item, "to_dict") else item, sort_keys=True, default=str)
                if marker not in seen:
                    values.append(item)
                    seen.add(marker)
            setattr(merged, field, values)
        for field in ("languages", "frameworks", "package_managers", "databases", "warnings"):
            setattr(merged, field, list(dict.fromkeys([*getattr(base, field), *getattr(partial, field)])))
        existing_components = {str(item.get("name")): dict(item) for item in base.components}
        for component in partial.components:
            existing = existing_components.setdefault(str(component.get("name")), {})
            for key, value in component.items():
                if isinstance(value, list) and isinstance(existing.get(key), list):
                    existing[key] = cls._merge_list_values(existing[key], value)
                elif key not in existing or not existing[key]:
                    existing[key] = value
        merged.components = list(existing_components.values())
        for field in ("docker", "kubernetes", "ci_cd", "documentation"):
            current = dict(getattr(base, field))
            for key, value in getattr(partial, field).items():
                if isinstance(value, list) and isinstance(current.get(key), list):
                    current[key] = cls._merge_list_values(current[key], value)
                elif key not in current:
                    current[key] = value
            setattr(merged, field, current)
        return merged

    @staticmethod
    def _merge_list_values(existing: list[Any], additions: list[Any]) -> list[Any]:
        """Deduplicate scalar and structured metadata without requiring hashability."""

        merged: list[Any] = []
        seen: set[str] = set()
        for item in [*existing, *additions]:
            marker = json.dumps(
                item.to_dict() if hasattr(item, "to_dict") else item,
                sort_keys=True,
                default=str,
            )
            if marker not in seen:
                merged.append(item)
                seen.add(marker)
        return merged
