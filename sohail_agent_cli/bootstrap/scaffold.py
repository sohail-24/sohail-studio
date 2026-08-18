"""Bootstrap project scaffold generator."""

from __future__ import annotations

from pathlib import Path


class ProjectScaffold:
    """
    Creates the initial project directory structure.

    This class is responsible only for creating
    directories and placeholder files.
    """

    DIRECTORIES = (
        "frontend",
        "backend",
        "docs",
        "docker",
        "kubernetes",
        "scripts",
        "tests",
        ".github",
        ".github/workflows",
    )

    FILES = (
        "README.md",
        "LICENSE",
        ".gitignore",
        ".env.example",
        "Makefile",
    )

    def create(
        self,
        output_directory: Path,
        overwrite: bool = False,
    ) -> list[Path]:
        """
        Create the project scaffold.

        Returns:
            List of created filesystem paths.
        """

        output_directory = output_directory.resolve()

        created: list[Path] = []

        created.extend(
            self._create_directories(output_directory)
        )

        created.extend(
            self._create_files(
                output_directory,
                overwrite=overwrite,
            )
        )

        return created

    def _create_directories(
        self,
        root: Path,
    ) -> list[Path]:
        """
        Create project directories.
        """

        created: list[Path] = []

        for directory in self.DIRECTORIES:
            path = root / directory
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)

        return created

    def _create_files(
        self,
        root: Path,
        overwrite: bool,
    ) -> list[Path]:
        """
        Create placeholder files.
        """

        created: list[Path] = []

        for filename in self.FILES:
            file_path = root / filename

            if file_path.exists() and not overwrite:
                continue

            file_path.touch(exist_ok=True)
            created.append(file_path)

        return created