"""Deterministic repository inspection and normalized project intelligence."""

from .deep_inspector import DeepInspector, InspectionError
from .models import DiscoveredFile, Evidence, ProjectIntelligence
from .persisted_analysis import repo_analysis_from_intelligence

__all__ = [
    "DeepInspector",
    "DiscoveredFile",
    "Evidence",
    "InspectionError",
    "ProjectIntelligence",
    "repo_analysis_from_intelligence",
]
