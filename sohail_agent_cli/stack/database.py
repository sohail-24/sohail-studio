"""Database stack skeletons."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path


class DatabaseSkeletons:
    """Create database-only technology skeletons."""

    def generate(self, technology: str | None) -> OrderedDict[Path, str]:
        """Generate database files for a normalized technology name."""
        files: OrderedDict[Path, str] = OrderedDict()
        if technology == "postgresql":
            files[Path("database/schema.sql")] = """-- PostgreSQL schema skeleton.
-- Add application tables during feature implementation.
"""
        return files
