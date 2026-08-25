"""Technology-neutral evidence contracts and safety boundaries."""

from .analysis import (
    AcquisitionResult,
    EvidenceAcquisitionService,
    EvidenceAnalysisEngine,
    EvidenceAnalysisError,
)
from .clarification import ClarificationRequest, ClarificationRequestError, UserProvidedEvidence
from .models import (
    ACCEPTED_EVIDENCE_ORIGINS,
    CandidateHypothesis,
    ClarificationQuestion,
    EvidenceAnalysis,
    EvidenceAnalysisStatus,
    EvidenceGap,
    EvidenceOrigin,
    EvidenceReference,
    EvidenceRelationship,
    InspectionTarget,
    is_accepted_evidence_origin,
)
from .patterns import (
    VerifiedEngineeringPattern,
    VerifiedEngineeringPatternRecognizer,
    recognize_verified_patterns,
)

__all__ = [
    "ACCEPTED_EVIDENCE_ORIGINS",
    "CandidateHypothesis",
    "ClarificationQuestion",
    "EvidenceAnalysis",
    "EvidenceAnalysisStatus",
    "EvidenceGap",
    "EvidenceOrigin",
    "EvidenceReference",
    "EvidenceRelationship",
    "InspectionTarget",
    "is_accepted_evidence_origin",
    "AcquisitionResult",
    "EvidenceAcquisitionService",
    "EvidenceAnalysisEngine",
    "EvidenceAnalysisError",
    "ClarificationRequest",
    "ClarificationRequestError",
    "UserProvidedEvidence",
    "VerifiedEngineeringPattern",
    "VerifiedEngineeringPatternRecognizer",
    "recognize_verified_patterns",
]
