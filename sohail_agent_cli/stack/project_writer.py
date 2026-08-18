"""Write-target preparation for StackGenerator V1."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from .models import StackWriteTarget


class StackProjectWriter:
    """
    Resolve generated stack files to safe output targets.

    This class does not perform filesystem writes. The agent owns writes through
    BaseAgent/FileWorker so dry-run and overwrite behavior remain consistent
    with the existing project style.
    """

    def prepare(
        self,
        output_directory: Path,
        files: OrderedDict[Path, str],
    ) -> list[StackWriteTarget]:
        """Resolve relative generated paths against the output directory."""
        output_directory = output_directory.resolve()
        targets: list[StackWriteTarget] = []
        for relative_path, content in files.items():
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError(f"Stack output path must be relative: {relative_path}")
            targets.append(
                StackWriteTarget(
                    relative_path=relative_path,
                    target_path=output_directory / relative_path,
                    content=content,
                )
            )
        return targets

    @staticmethod
    def conflicts(
        targets: list[StackWriteTarget],
        overwrite: bool,
    ) -> list[Path]:
        """Return targets that would conflict with existing files."""
        if overwrite:
            return []
        return [target.target_path for target in targets if target.target_path.exists()]
