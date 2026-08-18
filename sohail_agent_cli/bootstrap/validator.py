"""Bootstrap planning package validator."""

from __future__ import annotations

from pathlib import Path


class PlanningValidationError(Exception):
    """Raised when a planning package is invalid."""


class PlanningValidator:
    """
    Validates a PlanningAgent package before bootstrapping.

    Expected structure:

    project-plan/
        REQUIREMENTS.md
        ARCHITECTURE.md
        TASK.md
        decisions/
    """

    REQUIRED_FILES = (
        "REQUIREMENTS.md",
        "ARCHITECTURE.md",
        "TASK.md",
    )

    def validate(self, plan_directory: Path) -> None:
        """
        Validate a planning package.

        Raises:
            PlanningValidationError:
                If the planning package is invalid.
        """

        plan_directory = plan_directory.resolve()

        if not plan_directory.exists():
            raise PlanningValidationError(
                f"Planning package not found: {plan_directory}"
            )

        if not plan_directory.is_dir():
            raise PlanningValidationError(
                f"Expected a directory: {plan_directory}"
            )

        self._validate_required_files(plan_directory)
        self._validate_decisions_directory(plan_directory)

    def _validate_required_files(
        self,
        plan_directory: Path,
    ) -> None:
        """Validate required markdown files."""

        for filename in self.REQUIRED_FILES:
            file_path = plan_directory / filename

            if not file_path.exists():
                raise PlanningValidationError(
                    f"Missing required file: {filename}"
                )

            if not file_path.is_file():
                raise PlanningValidationError(
                    f"Expected file: {filename}"
                )

    @staticmethod
    def _validate_decisions_directory(
        plan_directory: Path,
    ) -> None:
        """Validate decisions directory."""

        decisions = plan_directory / "decisions"

        if not decisions.exists():
            raise PlanningValidationError(
                "Missing decisions directory."
            )

        if not decisions.is_dir():
            raise PlanningValidationError(
                "decisions exists but is not a directory."
            )