"""Deterministic Dockerize policy for user-provided clarification."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.evidence import (
    ClarificationRequest,
    ClarificationRequestError,
    EvidenceGap,
    UserProvidedEvidence,
)


class DockerClarificationPolicy:
    """Allow only a narrowly defined, explicitly bound Docker fact."""

    clarification_type = "production_start_command"

    @classmethod
    def build_request(cls, gap: EvidenceGap) -> ClarificationRequest | None:
        if gap.workflow != "Dockerize" or gap.clarification_type != cls.clarification_type:
            return None
        component = gap.component or "the affected component"
        identity = json.dumps(gap.to_dict(), sort_keys=True, separators=(",", ":"))
        request_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        proposition = (
            f"The production start command for component '{component}' is exactly "
            "the command supplied in this clarification."
        )
        return ClarificationRequest(
            request_id=request_id,
            workflow=gap.workflow,
            gap_id=request_id,
            root_path=gap.root_path,
            component=gap.component,
            requirement=gap.requirement,
            question=(
                f"What exact production start command should be used for component "
                f"'{component}'?"
            ),
            expected_answer_type="text",
            reason=gap.reason,
            proposition=proposition,
            evidence_references=gap.observed_evidence,
        )

    @classmethod
    def validate_answer(cls, request: ClarificationRequest, answer: Any) -> UserProvidedEvidence:
        if request.expected_answer_type == "text":
            value = str(answer or "").strip()
            if not value:
                raise ClarificationRequestError("A non-empty production start command is required")
            if value.lower() in {"yes", "no"}:
                raise ClarificationRequestError("This clarification requires the exact command, not a yes/no response")
            cls._validate_command_text(value)
        elif request.expected_answer_type in {"yes_no", "select"}:
            value = str(answer or "").strip()
            if value not in request.allowed_answers:
                raise ClarificationRequestError("The response is not one of the allowed answers")
        else:
            raise ClarificationRequestError("Unsupported clarification answer type")
        return UserProvidedEvidence(
            request_id=request.request_id,
            workflow=request.workflow,
            gap_id=request.gap_id,
            root_path=request.root_path,
            component=request.component,
            proposition=request.proposition,
            confirmed_value=value,
            answer=value,
            answer_type=request.expected_answer_type,
            evidence_type="workflow_clarification",
            key=cls.clarification_type,
        )

    @classmethod
    def validate_user_evidence(cls, evidence: UserProvidedEvidence) -> None:
        if evidence.workflow != "Dockerize":
            raise ClarificationRequestError("User evidence belongs to an unsupported workflow")
        if evidence.answer_type == "text":
            cls._validate_command_text(evidence.confirmed_value)

    @staticmethod
    def _validate_command_text(value: str) -> None:
        if len(value) > 512 or any(ord(char) < 32 for char in value):
            raise ClarificationRequestError("The command contains unsupported control characters or is too long")
        if any(operator in value for operator in (";", "&&", "||", "|", ">", "<", "`", "$(", "'", '"')):
            raise ClarificationRequestError("Shell operators and quoted command expressions are not accepted")
