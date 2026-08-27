"""Small deterministic eligibility contract for Compose infrastructure candidates."""

from __future__ import annotations

from typing import Any

from sohail_agent_cli.inspection.models import EvidenceSourceType

DETECTED = "DETECTED"
DETECTION_ONLY = "DETECTION_ONLY"
ELIGIBLE = "ELIGIBLE"
NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
UNSUPPORTED = "UNSUPPORTED"

SUPPORTED_INFRASTRUCTURE = {"MongoDB", "PostgreSQL", "MySQL"}
INFRASTRUCTURE_EVIDENCE_POLICY_V1 = {
    "policy_id": "compose-infrastructure-evidence-v1",
    "policy_version": "1",
    "source_type": EvidenceSourceType.APPROVED_PLATFORM_POLICY,
    "model_inference": False,
    "supported_types": sorted(SUPPORTED_INFRASTRUCTURE),
    "rule_id": "compose.infrastructure.explicit-service-metadata.v1",
}


def evaluate_infrastructure_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Evaluate persisted candidate metadata without supplying missing values."""
    technology = str(candidate.get("service_type") or candidate.get("technology") or "").strip()
    result = {
        **dict(candidate),
        "technology": technology or None,
        "policy": dict(INFRASTRUCTURE_EVIDENCE_POLICY_V1),
        "source_type": str(candidate.get("source_type") or EvidenceSourceType.EXPLICIT),
        "model_inference": bool(candidate.get("model_inference", False)),
    }
    if technology not in SUPPORTED_INFRASTRUCTURE:
        result.update({
            "eligibility": UNSUPPORTED,
            "missing_requirements": [],
            "unsupported_reason": "Infrastructure technology is outside the Step 4C supported set",
            "authorized_fields": [],
        })
        return result

    image = str(candidate.get("image") or "").strip()
    image_source = str(candidate.get("image_source_type") or result["source_type"])
    if image.endswith(":latest") or image == "latest":
        result.update({
            "eligibility": NEEDS_EVIDENCE,
            "missing_requirements": ["exact non-latest infrastructure image"],
            "unsupported_reason": "The :latest image tag is not an authorized fallback",
            "authorized_fields": [],
        })
        return result
    if image and image_source == EvidenceSourceType.MODEL_PROPOSED:
        result.update({
            "eligibility": NEEDS_EVIDENCE,
            "missing_requirements": ["authoritative infrastructure image"],
            "unsupported_reason": "Model-proposed infrastructure images are not authoritative",
            "authorized_fields": [],
        })
        return result

    forbidden_values = {
        key for key in (
            "username", "password", "credentials", "secret",
            "volume", "volumes", "healthcheck",
        )
        if candidate.get(key)
    }
    if forbidden_values:
        result.update({
            "eligibility": UNSUPPORTED,
            "missing_requirements": [],
            "unsupported_reason": (
                "Credentials, volumes, and health checks are not authorized "
                "by this foundation"
            ),
            "rejected_fields": sorted(forbidden_values),
            "authorized_fields": [],
        })
        return result

    missing = [
        field for field in ("service_name", "image")
        if not str(candidate.get(field) or "").strip()
    ]
    if missing:
        result.update({
            "eligibility": DETECTION_ONLY,
            "missing_requirements": missing,
            "unsupported_reason": "Technology was detected without exact service metadata",
            "authorized_fields": [],
        })
        return result

    if image_source not in {
        EvidenceSourceType.EXPLICIT,
        EvidenceSourceType.DERIVED_DETERMINISTIC,
        EvidenceSourceType.APPROVED_PLATFORM_POLICY,
    } or result["source_type"] not in {
        EvidenceSourceType.EXPLICIT,
        EvidenceSourceType.DERIVED_DETERMINISTIC,
        EvidenceSourceType.APPROVED_PLATFORM_POLICY,
    } or result["model_inference"]:
        result.update({
            "eligibility": NEEDS_EVIDENCE,
            "missing_requirements": ["authoritative infrastructure metadata"],
            "unsupported_reason": "Infrastructure metadata is not authoritative",
            "authorized_fields": [],
        })
        return result

    result.update({
        "eligibility": ELIGIBLE,
        "missing_requirements": [],
        "unsupported_reason": None,
        "authorized_fields": ["service_name", "technology", "image"],
    })
    return result
