"""Technology-neutral contracts for evidence gaps and evidence analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PureWindowsPath
from typing import Any


class EvidenceOrigin(str, Enum):
    """Where a fact came from; AI analysis is never accepted evidence."""

    REPOSITORY_EVIDENCE = "REPOSITORY_EVIDENCE"
    USER_PROVIDED_EVIDENCE = "USER_PROVIDED_EVIDENCE"
    VERIFIED_INFERENCE = "VERIFIED_INFERENCE"
    AI_ANALYSIS = "AI_ANALYSIS"


ACCEPTED_EVIDENCE_ORIGINS = frozenset(
    {
        EvidenceOrigin.REPOSITORY_EVIDENCE,
        EvidenceOrigin.USER_PROVIDED_EVIDENCE,
        EvidenceOrigin.VERIFIED_INFERENCE,
    }
)


def is_accepted_evidence_origin(origin: EvidenceOrigin | str) -> bool:
    """Return whether an origin may affect deterministic generation."""

    try:
        normalized = EvidenceOrigin(origin)
    except ValueError:
        return False
    return normalized in ACCEPTED_EVIDENCE_ORIGINS


@dataclass(frozen=True)
class EvidenceReference:
    """A small provenance pointer, never a copy of arbitrary file content."""

    source_file: str
    evidence_type: str
    key: str
    confidence: str
    line_number: int | None = None
    origin: EvidenceOrigin = EvidenceOrigin.REPOSITORY_EVIDENCE

    def __post_init__(self) -> None:
        if not self.source_file.strip():
            raise ValueError("EvidenceReference.source_file is required")
        if not self.evidence_type.strip() or not self.key.strip():
            raise ValueError("EvidenceReference.evidence_type and key are required")
        object.__setattr__(self, "origin", EvidenceOrigin(self.origin))

    @classmethod
    def from_evidence(cls, evidence: Any) -> "EvidenceReference":
        """Create a reference from the existing inspector Evidence model."""

        return cls(
            source_file=str(evidence.source_file),
            evidence_type=str(evidence.evidence_type),
            key=str(evidence.key),
            confidence=str(evidence.confidence),
            line_number=evidence.line_number,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "evidence_type": self.evidence_type,
            "key": self.key,
            "confidence": self.confidence,
            "line_number": self.line_number,
            "origin": self.origin.value,
        }


@dataclass(frozen=True)
class EvidenceGap:
    """A deterministic description of why a workflow cannot safely proceed."""

    workflow: str
    project: str
    root_path: str
    requirement: str
    reason: str
    missing_evidence: str
    component: str | None = None
    observed_evidence: tuple[EvidenceReference, ...] = ()
    deterministic_constraints: tuple[str, ...] = ()
    allowed_decisions: tuple[str, ...] = ()
    forbidden_decisions: tuple[str, ...] = ()
    clarification_type: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("workflow", "project", "root_path", "requirement", "reason", "missing_evidence"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"EvidenceGap.{field_name} is required")
        if any(not is_accepted_evidence_origin(item.origin) for item in self.observed_evidence):
            raise ValueError("EvidenceGap observed_evidence cannot contain AI_ANALYSIS")

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow": self.workflow,
            "project": self.project,
            "root_path": self.root_path,
            "component": self.component,
            "clarification_type": self.clarification_type,
            "requirement": self.requirement,
            "reason": self.reason,
            "missing_evidence": self.missing_evidence,
            "observed_evidence": [item.to_dict() for item in self.observed_evidence],
            "deterministic_constraints": list(self.deterministic_constraints),
            "allowed_decisions": list(self.allowed_decisions),
            "forbidden_decisions": list(self.forbidden_decisions),
        }


PROTECTED_DIRECTORIES = frozenset(
    {
        ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
        ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", "dist", "build",
        "coverage", "htmlcov", ".next", "target", "vendor", "tmp", "temp", ".tox",
    }
)
PROTECTED_SECRET_NAMES = frozenset(
    {".env", ".env.local", ".env.production", ".env.development", ".env.test", "credentials"}
)
PROTECTED_SECRET_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".pkcs12"})
SAFE_ENV_NAMES = frozenset({".env.example", ".env.sample", ".env.template"})


@dataclass(frozen=True)
class InspectionTarget:
    """A safe relative repository target; it intentionally has no command field."""

    relative_path: str
    expected_evidence_type: str = ""
    rationale: str = ""
    component: str | None = None

    def validate(self, project_root: Path) -> Path:
        """Validate and resolve an existing, in-root, non-secret target."""

        raw = self.relative_path.strip()
        if not raw or "\x00" in raw or "\n" in raw or "\r" in raw:
            raise ValueError("Inspection target must be a non-empty relative path")
        windows_path = PureWindowsPath(raw)
        relative = Path(raw)
        if relative.is_absolute() or windows_path.is_absolute() or windows_path.drive:
            raise ValueError("Inspection target must be relative to the project root")
        if ".." in relative.parts:
            raise ValueError("Inspection target cannot contain path traversal")
        if relative == Path("."):
            raise ValueError("Inspection target must identify a file or bounded directory")
        if any(operator in raw for operator in (";", "&&", "||", "|", ">", "<", "`", "$(", "'", '"')):
            raise ValueError("Inspection targets cannot contain shell commands")

        root = Path(project_root).expanduser().resolve(strict=False)
        unresolved = root / relative
        candidate = unresolved.resolve(strict=False)
        if candidate != root and root not in candidate.parents:
            raise ValueError("Inspection target must remain inside the project root")
        if any(part.lower() in PROTECTED_DIRECTORIES for part in relative.parts):
            raise ValueError("Inspection target is inside an excluded directory")
        filename = candidate.name.lower()
        if (
            filename in PROTECTED_SECRET_NAMES
            or (filename.startswith(".env.") and filename not in SAFE_ENV_NAMES)
            or candidate.suffix.lower() in PROTECTED_SECRET_SUFFIXES
        ):
            raise ValueError("Inspection target may contain secrets and cannot be inspected")
        if not candidate.exists():
            raise ValueError(f"Inspection target does not exist: {self.relative_path}")
        if unresolved.is_symlink() or not (candidate.is_file() or candidate.is_dir()):
            raise ValueError("Inspection target must be a regular file or directory")
        return candidate

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "expected_evidence_type": self.expected_evidence_type,
            "rationale": self.rationale,
            "component": self.component,
        }


class EvidenceAnalysisStatus(str, Enum):
    INSPECT_MORE = "inspect_more"
    ASK_USER = "ask_user"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class EvidenceRelationship:
    description: str
    references: tuple[EvidenceReference, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "references": [item.to_dict() for item in self.references],
        }


@dataclass(frozen=True)
class ClarificationQuestion:
    question: str
    requirement: str
    component: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "requirement": self.requirement,
            "component": self.component,
        }


@dataclass(frozen=True)
class CandidateHypothesis:
    statement: str
    confidence: str
    supporting_evidence: tuple[EvidenceReference, ...] = ()
    unsupported_assumptions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "confidence": self.confidence,
            "supporting_evidence": [item.to_dict() for item in self.supporting_evidence],
            "unsupported_assumptions": list(self.unsupported_assumptions),
        }


@dataclass(frozen=True)
class EvidenceAnalysis:
    """AI analysis only; it is never an accepted Project Intelligence snapshot."""

    status: EvidenceAnalysisStatus
    findings: tuple[str, ...] = ()
    evidence_relationships: tuple[EvidenceRelationship, ...] = ()
    inspection_targets: tuple[InspectionTarget, ...] = ()
    rejected_inspection_targets: tuple[dict[str, Any], ...] = ()
    clarification_questions: tuple[ClarificationQuestion, ...] = ()
    candidate_hypotheses: tuple[CandidateHypothesis, ...] = ()
    unsupported_assumptions: tuple[str, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()
    origin: EvidenceOrigin = EvidenceOrigin.AI_ANALYSIS

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", EvidenceAnalysisStatus(self.status))
        object.__setattr__(self, "origin", EvidenceOrigin(self.origin))
        if self.origin is not EvidenceOrigin.AI_ANALYSIS:
            raise ValueError("EvidenceAnalysis must remain AI_ANALYSIS")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "findings": list(self.findings),
            "evidence_relationships": [item.to_dict() for item in self.evidence_relationships],
            "inspection_targets": [item.to_dict() for item in self.inspection_targets],
            "rejected_inspection_targets": [dict(item) for item in self.rejected_inspection_targets],
            "clarification_questions": [item.to_dict() for item in self.clarification_questions],
            "candidate_hypotheses": [item.to_dict() for item in self.candidate_hypotheses],
            "unsupported_assumptions": list(self.unsupported_assumptions),
            "diagnostics": [dict(item) for item in self.diagnostics],
            "origin": self.origin.value,
        }
