"""Deterministic repository inspection and normalized project intelligence."""

from .deep_inspector import DeepInspector, InspectionError
from .models import DiscoveredFile, Evidence, ProjectIntelligence

__all__ = [
    "DeepInspector",
    "DiscoveredFile",
    "Evidence",
    "InspectionError",
    "ProjectIntelligence",
]
