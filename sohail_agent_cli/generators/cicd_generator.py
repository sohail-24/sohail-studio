"""CI/CD workflow generator."""

from __future__ import annotations

from pathlib import Path

from sohail_agent_cli.analyzers import StackType


class CicdGenerator:
    """Generator for CI/CD workflows."""

    def generate(
        self,
        stack: StackType,
        project_path: Path,
        has_docker: bool = False,
    ) -> tuple[str, str | None, str]:
        """Generate CI/CD workflows."""
        ci = self._generate_ci(stack, project_path, has_docker)
        docker = self._generate_docker() if has_docker else None
        release = self._generate_release()

        return ci, docker, release

    # -----------------------------
    # CI GENERATION
    # -----------------------------
    def _generate_ci(self, stack: StackType, project_path: Path, has_docker: bool) -> str:
        if stack == StackType.DJANGO:
            return self._generate_django_ci(project_path, has_docker)

        if stack in (StackType.PYTHON, StackType.FASTAPI, StackType.FLASK):
            return self._generate_python_ci(project_path, has_docker)

        if stack in (StackType.NODE, StackType.REACT, StackType.NEXTJS, StackType.VUE):
            return self._generate_node_ci(has_docker)

        return self._generate_generic_ci(has_docker)

    # -----------------------------
    # DJANGO CI (🔥 SMART)
    # -----------------------------
    def _generate_django_ci(self, project_path: Path, has_docker: bool) -> str:
        requirements_install = self._detect_requirements(project_path)

        docker_section = self._docker_section() if has_docker else ""

        return f"""name: CI

on:
  push:
    branches: [main, develop]
  pull_request:

jobs:
  django-ci:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd="pg_isready"
          --health-interval=10s
          --health-timeout=5s
          --health-retries=5

    env:
      DATABASE_URL: postgres://postgres:postgres@localhost:5432/test_db
      DJANGO_SETTINGS_MODULE: config.settings.dev

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          {requirements_install}

      - name: Run migrations
        run: python manage.py migrate

      - name: Collect static
        run: python manage.py collectstatic --noinput

      - name: Run tests
        run: pytest || true
{docker_section}
"""

    # -----------------------------
    # PYTHON CI
    # -----------------------------
    def _generate_python_ci(self, project_path: Path, has_docker: bool) -> str:
        requirements_install = self._detect_requirements(project_path)
        docker_section = self._docker_section() if has_docker else ""

        return f"""name: CI

on:
  push:
    branches: [main, develop]
  pull_request:

jobs:
  python-ci:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          {requirements_install}

      - name: Lint
        run: |
          pip install ruff
          ruff check . || true

      - name: Test
        run: pytest || true
{docker_section}
"""

    # -----------------------------
    # NODE CI
    # -----------------------------
    def _generate_node_ci(self, has_docker: bool) -> str:
        docker_section = self._docker_section() if has_docker else ""

        return f"""name: CI

on:
  push:
    branches: [main, develop]
  pull_request:

jobs:
  node-ci:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "20"

      - run: npm ci
      - run: npm run build || true
      - run: npm test || true
{docker_section}
"""

    # -----------------------------
    # GENERIC
    # -----------------------------
    def _generate_generic_ci(self, has_docker: bool) -> str:
        docker_section = self._docker_section() if has_docker else ""

        return f"""name: CI

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
      - run: echo "Add your build steps"
{docker_section}
"""

    # -----------------------------
    # HELPERS
    # -----------------------------
    def _detect_requirements(self, path: Path) -> str:
        """Smart requirements detection."""
        if (path / "requirements" / "prod.txt").exists():
            return "pip install -r requirements/prod.txt"
        if (path / "requirements.txt").exists():
            return "pip install -r requirements.txt"
        return "pip install -e ."

    def _docker_section(self) -> str:
        return """
      - name: Build Docker image
        run: docker build -t app:test .

      - name: Run Docker container
        run: docker run --rm app:test echo "Docker works"
"""

    # -----------------------------
    # DOCKER CD
    # -----------------------------
    def _generate_docker(self) -> str:
        return """name: Docker

on:
  push:
    branches: [main]

jobs:
  docker:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - run: docker build -t app:latest .
"""

    # -----------------------------
    # RELEASE
    # -----------------------------
    def _generate_release(self) -> str:
        return """name: Release

on:
  push:
    tags: ['v*']

jobs:
  release:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
      - run: echo "Release step"
"""