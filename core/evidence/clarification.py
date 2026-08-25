"""Typed, policy-neutral contracts for bounded user clarification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import EvidenceOrigin, EvidenceReference


class ClarificationRequestError(ValueError):
    """Raised when a clarification request would be ambiguous or unsafe."""


@dataclass(frozen=True)
class ClarificationRequest:
    """One precise proposition for which a workflow needs user input."""

    request_id: str
    workflow: str
    gap_id: str
    root_path: str
    component: str | None
    requirement: str
    question: str
    expected_answer_type: str
    allowed_answers: tuple[str, ...] = ()
    candidate_values: tuple[str, ...] = ()
    reason: str = ""
    proposition: str = ""
    evidence_references: tuple[EvidenceReference, ...] = ()
    status: str = "pending"
    issued_at: str = ""

    def __post_init__(self) -> None:
        required = (
            "request_id", "workflow", "gap_id", "root_path", "requirement",
            "question", "expected_answer_type", "proposition",
        )
        for field_name in required:
            if not str(getattr(self, field_name)).strip():
                raise ClarificationRequestError(f"ClarificationRequest.{field_name} is required")
        if self.question.strip().lower() in {"should i continue?", "should we continue?"}:
            raise ClarificationRequestError("Clarification question must identify a proposition")
        if self.expected_answer_type not in {"yes_no", "select", "text"}:
            raise ClarificationRequestError("Unsupported clarification answer type")
        if self.expected_answer_type in {"yes_no", "select"} and not self.allowed_answers:
            raise ClarificationRequestError("Choice clarification requires allowed answers")
        if any(item.origin is EvidenceOrigin.AI_ANALYSIS for item in self.evidence_references):
            raise ClarificationRequestError("Clarification references cannot come from AI_ANALYSIS")
        if self.status not in {"pending", "answered", "accepted", "rejected"}:
            raise ClarificationRequestError("Unsupported clarification status")
        object.__setattr__(self, "issued_at", self.issued_at or datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ClarificationRequest":
        references = tuple(
            item if isinstance(item, EvidenceReference) else EvidenceReference(
                source_file=str(item["source_file"]),
                evidence_type=str(item["evidence_type"]),
                key=str(item["key"]),
                confidence=str(item.get("confidence") or "low"),
                line_number=item.get("line_number"),
                origin=item.get("origin", EvidenceOrigin.REPOSITORY_EVIDENCE),
            )
            for item in value.get("evidence_references", [])
        )
        return cls(
            request_id=str(value.get("request_id") or ""),
            workflow=str(value.get("workflow") or ""),
            gap_id=str(value.get("gap_id") or ""),
            root_path=str(value.get("root_path") or ""),
            component=value.get("component"),
            requirement=str(value.get("requirement") or ""),
            question=str(value.get("question") or ""),
            expected_answer_type=str(value.get("expected_answer_type") or ""),
            allowed_answers=tuple(str(item) for item in value.get("allowed_answers", [])),
            candidate_values=tuple(str(item) for item in value.get("candidate_values", [])),
            reason=str(value.get("reason") or ""),
            proposition=str(value.get("proposition") or ""),
            evidence_references=references,
            status=str(value.get("status") or "pending"),
            issued_at=str(value.get("issued_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "workflow": self.workflow,
            "gap_id": self.gap_id,
            "root_path": self.root_path,
            "component": self.component,
            "requirement": self.requirement,
            "question": self.question,
            "expected_answer_type": self.expected_answer_type,
            "allowed_answers": list(self.allowed_answers),
            "candidate_values": list(self.candidate_values),
            "reason": self.reason,
            "proposition": self.proposition,
            "evidence_references": [item.to_dict() for item in self.evidence_references],
            "status": self.status,
            "issued_at": self.issued_at,
        }


@dataclass(frozen=True)
class UserProvidedEvidence:
    """A user answer bound to the exact clarification proposition."""

    request_id: str
    workflow: str
    gap_id: str
    root_path: str
    component: str | None
    proposition: str
    confirmed_value: str
    answer: str
    answer_type: str
    evidence_type: str = "user_clarification"
    key: str = "clarification"
    provided_at: str = ""
    origin: EvidenceOrigin = EvidenceOrigin.USER_PROVIDED_EVIDENCE

    def __post_init__(self) -> None:
        for field_name in (
            "request_id", "workflow", "gap_id", "root_path", "proposition",
            "confirmed_value", "answer", "answer_type", "evidence_type", "key",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ClarificationRequestError(f"UserProvidedEvidence.{field_name} is required")
        if EvidenceOrigin(self.origin) is not EvidenceOrigin.USER_PROVIDED_EVIDENCE:
            raise ClarificationRequestError("User evidence must retain USER_PROVIDED_EVIDENCE origin")
        object.__setattr__(self, "provided_at", self.provided_at or datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "UserProvidedEvidence":
        return cls(
            request_id=str(value.get("request_id") or ""),
            workflow=str(value.get("workflow") or ""),
            gap_id=str(value.get("gap_id") or ""),
            root_path=str(value.get("root_path") or ""),
            component=value.get("component"),
            proposition=str(value.get("proposition") or ""),
            confirmed_value=str(value.get("confirmed_value") or ""),
            answer=str(value.get("answer") or ""),
            answer_type=str(value.get("answer_type") or ""),
            evidence_type=str(value.get("evidence_type") or ""),
            key=str(value.get("key") or ""),
            provided_at=str(value.get("provided_at") or ""),
            origin=value.get("origin", EvidenceOrigin.USER_PROVIDED_EVIDENCE),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "workflow": self.workflow,
            "gap_id": self.gap_id,
            "root_path": self.root_path,
            "component": self.component,
            "proposition": self.proposition,
            "confirmed_value": self.confirmed_value,
            "answer": self.answer,
            "answer_type": self.answer_type,
            "evidence_type": self.evidence_type,
            "key": self.key,
            "provided_at": self.provided_at,
            "origin": EvidenceOrigin(self.origin).value,
        }
