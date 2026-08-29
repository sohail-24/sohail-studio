"""Deterministic repository inspection and normalized project intelligence."""

from .deep_inspector import DeepInspector, InspectionError
from .models import (
    CURRENT_INTELLIGENCE_SCHEMA_VERSION,
    DiscoveredFile,
    Evidence,
    EvidenceSourceType,
    ProjectIntelligence,
)
from .persisted_analysis import repo_analysis_from_intelligence
from .setup import ProjectSetupBuilder

__all__ = [
    "DeepInspector",
    "CURRENT_INTELLIGENCE_SCHEMA_VERSION",
    "DiscoveredFile",
    "Evidence",
    "EvidenceSourceType",
    "InspectionError",
    "ProjectIntelligence",
    "ProjectSetupBuilder",
    "repo_analysis_from_intelligence",
]
