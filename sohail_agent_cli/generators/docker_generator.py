"""Docker file generator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sohail_agent_cli.analyzers import StackType


@dataclass
class DockerConfig:
    """Configuration for Docker generation."""

    base_image: str
    workdir: str = "/app"
    port: int = 8000
    cmd: list[str] | None = None
    expose_ports: list[int] | None = None
    env_vars: dict[str, str] | None = None
    build_deps: list[str] | None = None
    run_deps: list[str] | None = None
    python_version: str | None = None
    node_version: str | None = None
    use_gunicorn: bool = False
    settings_module: str | None = None


class DockerGenerator:
    """Generator for Docker configuration files."""

    def __init__(self) -> None:
        self.templates: dict[StackType, callable] = {
            StackType.PYTHON: self._generate_python,
            StackType.DJANGO: self._generate_django,
            StackType.FASTAPI: self._generate_fastapi,
            StackType.FLASK: self._generate_flask,
            StackType.NODE: self._generate_node,
            StackType.REACT: self._generate_react,
            StackType.NEXTJS: self._generate_nextjs,
            StackType.VUE: self._generate_node,
            StackType.GO: self._generate_go,
            StackType.RUST: self._generate_rust,
        }

    def generate(
        self,
        stack: StackType,
        project_path: Path,
        port: int | None = None,
    ) -> tuple[str, str, str]:
        """
        Generate Docker files.

        Returns:
            Tuple of (dockerfile, dockerignore, docker_compose)
        """
        generator = self.templates.get(stack, self._generate_python)
        config = generator(project_path, port)

        dockerfile = self._render_dockerfile(config, stack)
        dockerignore = self._render_dockerignore(stack)
        docker_compose = self._render_docker_compose(config, stack)

        return dockerfile, dockerignore, docker_compose

    def _generate_python(self, path: Path, port: int | None = None) -> DockerConfig:
        """Generate config for generic Python."""
        python_version = self._detect_python_version(path)
        entry_point = self._find_python_entry(path)

        cmd = ["python", entry_point] if entry_point else ["python", "main.py"]

        return DockerConfig(
            base_image=f"python:{python_version}-slim",
            port=port or 8000,
            cmd=cmd,
            python_version=python_version,
        )

    def _generate_django(self, path: Path, port: int | None = None) -> DockerConfig:
        """Generate config for Django."""
        python_version = self._detect_python_version(path)
        settings_module = self._detect_django_settings(path)

        return DockerConfig(
            base_image=f"python:{python_version}-slim",
            port=port or 8000,
            cmd=["python", "manage.py", "runserver", "0.0.0.0:8000"],
            python_version=python_version,
            build_deps=["gcc", "libpq-dev"],
            env_vars={
                "PYTHONUNBUFFERED": "1",
                **(
                    {"DJANGO_SETTINGS_MODULE": settings_module}
                    if settings_module
                    else {}
                ),
            },
            settings_module=settings_module,
        )

    def _generate_fastapi(self, path: Path, port: int | None = None) -> DockerConfig:
        """Generate config for FastAPI."""
        python_version = self._detect_python_version(path)

        app_module = "main:app"
        if (path / "app" / "main.py").exists():
            app_module = "app.main:app"
        elif (path / "src" / "main.py").exists():
            app_module = "src.main:app"

        return DockerConfig(
            base_image=f"python:{python_version}-slim",
            port=port or 8000,
            cmd=["uvicorn", app_module, "--host", "0.0.0.0", "--port", "8000"],
            python_version=python_version,
            env_vars={"PYTHONUNBUFFERED": "1"},
        )

    def _generate_flask(self, path: Path, port: int | None = None) -> DockerConfig:
        """Generate config for Flask."""
        python_version = self._detect_python_version(path)

        return DockerConfig(
            base_image=f"python:{python_version}-slim",
            port=port or 5000,
            cmd=["flask", "run", "--host=0.0.0.0"],
            python_version=python_version,
            env_vars={
                "FLASK_APP": "app.py",
                "PYTHONUNBUFFERED": "1",
            },
        )

    def _generate_node(self, path: Path, port: int | None = None) -> DockerConfig:
        """Generate config for Node.js."""
        node_version = "20"

        entry = "index.js"
        for candidate in ["server.js", "app.js", "index.js", "main.js"]:
            if (path / candidate).exists():
                entry = candidate
                break

        return DockerConfig(
            base_image=f"node:{node_version}-alpine",
            port=port or 3000,
            cmd=["node", entry],
            node_version=node_version,
        )

    def _generate_react(self, path: Path, port: int | None = None) -> DockerConfig:
        """Generate config for React."""
        node_version = "20"

        return DockerConfig(
            base_image=f"node:{node_version}-alpine",
            port=port or 80,
            cmd=["serve", "-s", "build", "-l", "80"],
            node_version=node_version,
        )

    def _generate_nextjs(self, path: Path, port: int | None = None) -> DockerConfig:
        """Generate config for Next.js."""
        node_version = "20"

        return DockerConfig(
            base_image=f"node:{node_version}-alpine",
            port=port or 3000,
            cmd=["npm", "start"],
            node_version=node_version,
        )

    def _generate_go(self, path: Path, port: int | None = None) -> DockerConfig:
        """Generate config for Go."""
        return DockerConfig(
            base_image="golang:1.21-alpine",
            port=port or 8080,
            cmd=["./app"],
        )

    def _generate_rust(self, path: Path, port: int | None = None) -> DockerConfig:
        """Generate config for Rust."""
        return DockerConfig(
            base_image="rust:1.75-slim",
            port=port or 8080,
            cmd=["./app"],
        )

    def _detect_python_version(self, path: Path) -> str:
        """Detect Python version from pyproject.toml if possible."""
        python_version = "3.11"
        pyproject = path / "pyproject.toml"

        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if "requires-python" in line and ">=" in line:
                        version = line.split(">=")[1].strip().strip('"\' ')
                        if version:
                            return version
            except Exception:
                pass

        return python_version

    def _detect_django_settings(self, path: Path) -> str | None:
        """Try to detect Django settings module."""
        candidates = [
            "config.settings",
            "config.settings.dev",
            "config.settings.prod",
            "project.settings",
            "app.settings",
        ]

        for candidate in candidates:
            parts = candidate.split(".")
            file_path = path.joinpath(*parts[:-1], f"{parts[-1]}.py")
            if file_path.exists():
                return candidate

        if (path / "config" / "settings").is_dir():
            if (path / "config" / "settings" / "dev.py").exists():
                return "config.settings.dev"
            if (path / "config" / "settings" / "base.py").exists():
                return "config.settings.base"

        return None

    def _find_python_entry(self, path: Path) -> str | None:
        """Find Python entry point."""
        candidates = ["main.py", "app.py", "server.py", "run.py"]

        for candidate in candidates:
            if (path / candidate).exists():
                return candidate

        for subdir in path.iterdir():
            if subdir.is_dir() and (subdir / "__main__.py").exists():
                return subdir.name

        return None

    def _render_dockerfile(self, config: DockerConfig, stack: StackType) -> str:
        """Render Dockerfile content."""

        # 🔥 SPECIAL DJANGO PRODUCTION MODE
        if stack == StackType.DJANGO:
            python_version = config.python_version or "3.12"
            settings = config.settings_module or "config.settings.prod"

            return f"""FROM python:{python_version}-slim

    ENV PYTHONDONTWRITEBYTECODE=1
    ENV PYTHONUNBUFFERED=1

    WORKDIR /app

    # Install system dependencies
    RUN apt-get update && apt-get install -y \\
        build-essential \\
        libpq-dev \\
        netcat-openbsd \\
        && rm -rf /var/lib/apt/lists/*

    # Copy requirements
    COPY requirements /app/requirements

    RUN pip install --upgrade pip
    RUN pip install -r requirements/prod.txt

    # Copy project
    COPY . .

    # Django settings
    ENV DJANGO_SETTINGS_MODULE={settings}

    # Create required directories
    RUN mkdir -p /app/logs
    RUN mkdir -p /app/media

    # Collect static files
    RUN python manage.py collectstatic --noinput

    EXPOSE {config.port}

    # Production server
    CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:{config.port}"]
    """
        # 🔥 DEFAULT (ALL OTHER STACKS)
        lines = [f"FROM {config.base_image}", ""]

        if stack in (
            StackType.PYTHON,
            StackType.FASTAPI,
            StackType.FLASK,
        ):
            lines.extend(
                [
                    "ENV PYTHONDONTWRITEBYTECODE=1",
                    "ENV PYTHONUNBUFFERED=1",
                    "",
                ]
            )

        lines.extend(
            [
                f"WORKDIR {config.workdir}",
                "",
            ]
        )

        if stack in (
            StackType.PYTHON,
            StackType.FASTAPI,
            StackType.FLASK,
        ):
            lines.extend(
                [
                    "COPY requirements.txt .",
                    "RUN pip install --upgrade pip && pip install -r requirements.txt",
                    "",
                ]
            )

        lines.extend(
            [
                "COPY . .",
                "",
            ]
        )

        if config.env_vars:
            for key, value in config.env_vars.items():
                lines.append(f"ENV {key}={value}")
            lines.append("")

        lines.append(f"EXPOSE {config.port}")
        lines.append("")

        if config.cmd:
            cmd_rendered = ", ".join(f'"{part}"' for part in config.cmd)
            lines.append(f"CMD [{cmd_rendered}]")

        return "\n".join(lines)




        """Render Dockerfile content."""
        lines = [f"FROM {config.base_image}", ""]

        if stack in (
            StackType.PYTHON,
            StackType.DJANGO,
            StackType.FASTAPI,
            StackType.FLASK,
        ):
            lines.extend(
                [
                    "# Set Python environment variables",
                    "ENV PYTHONDONTWRITEBYTECODE=1",
                    "ENV PYTHONUNBUFFERED=1",
                    "",
                ]
            )

        if config.build_deps and stack in (
            StackType.PYTHON,
            StackType.DJANGO,
            StackType.FASTAPI,
            StackType.FLASK,
        ):
            lines.extend(
                [
                    "# Install build dependencies",
                    "RUN apt-get update && apt-get install -y \\",
                ]
            )
            for dep in config.build_deps:
                lines.append(f"    {dep} \\")
            lines.extend(
                [
                    "    && rm -rf /var/lib/apt/lists/*",
                    "",
                ]
            )

        lines.extend(
            [
                f"WORKDIR {config.workdir}",
                "",
            ]
        )

        if stack in (
            StackType.PYTHON,
            StackType.DJANGO,
            StackType.FASTAPI,
            StackType.FLASK,
        ):
            lines.extend(
                [
                    "# Install Python dependencies",
                    "COPY requirements.txt requirements.txt",
                    "COPY requirements/ requirements/",
                    "COPY pyproject.toml pyproject.toml",
                    "RUN pip install --upgrade pip && \\",
                    "    pip install --no-cache-dir -r requirements.txt 2>/dev/null || \\",
                    "    pip install --no-cache-dir -r requirements/base.txt 2>/dev/null || \\",
                    "    pip install --no-cache-dir -e . 2>/dev/null || \\",
                    "    echo 'No installable Python dependency file found'",
                    "",
                ]
            )
        elif stack in (StackType.NODE, StackType.REACT, StackType.NEXTJS, StackType.VUE):
            lines.extend(
                [
                    "# Install Node.js dependencies",
                    "COPY package*.json ./",
                    "RUN npm ci",
                    "",
                ]
            )
        elif stack == StackType.GO:
            lines.extend(
                [
                    "# Download Go dependencies",
                    "COPY go.mod go.sum ./",
                    "RUN go mod download",
                    "",
                ]
            )
        elif stack == StackType.RUST:
            lines.extend(
                [
                    "# Download Rust dependencies",
                    "COPY Cargo.toml Cargo.lock ./",
                    "RUN mkdir src && echo 'fn main() {}' > src/main.rs",
                    "RUN cargo build --release && rm -rf src",
                    "",
                ]
            )

        if stack == StackType.REACT:
            return self._render_react_multistage(config)

        lines.extend(
            [
                "# Copy application code",
                "COPY . .",
                "",
            ]
        )

        if stack == StackType.GO:
            lines.extend(
                [
                    "# Build the application",
                    "RUN CGO_ENABLED=0 GOOS=linux go build -o app .",
                    "",
                ]
            )
        elif stack == StackType.RUST:
            lines.extend(
                [
                    "# Build the application",
                    "RUN cargo build --release",
                    "RUN cp target/release/* ./app 2>/dev/null || true",
                    "",
                ]
            )

        if config.env_vars:
            lines.append("# Environment variables")
            for key, value in config.env_vars.items():
                lines.append(f"ENV {key}={value}")
            lines.append("")

        lines.extend(
            [
                f"EXPOSE {config.port}",
                "",
            ]
        )

        if config.cmd:
            cmd_rendered = ", ".join(f'"{part}"' for part in config.cmd)
            lines.append(f"CMD [{cmd_rendered}]")

        return "\n".join(lines)

    def _render_react_multistage(self, config: DockerConfig) -> str:
        """Render multi-stage Dockerfile for React."""
        node_version = config.node_version or "20"

        return f"""# Build stage
FROM node:{node_version}-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# Production stage
FROM node:{node_version}-alpine

WORKDIR /app

RUN npm install -g serve

COPY --from=builder /app/build ./build

EXPOSE 80

CMD ["serve", "-s", "build", "-l", "80"]
"""

    def _render_dockerignore(self, stack: StackType) -> str:
        """Render .dockerignore content."""
        common = [
            "# Git",
            ".git",
            ".gitignore",
            "",
            "# IDE",
            ".idea",
            ".vscode",
            "*.swp",
            "*.swo",
            "",
            "# OS",
            ".DS_Store",
            "Thumbs.db",
            "",
            "# Environment",
            ".env",
            ".env.local",
            ".env.*.local",
            "",
            "# Tests",
            "tests/",
            "test/",
            "__tests__/",
            "*.test.js",
            "*.test.ts",
            "*.spec.js",
            "*.spec.ts",
            "",
            "# Documentation",
            "docs/",
            "",
        ]

        stack_specific = []

        if stack in (
            StackType.PYTHON,
            StackType.DJANGO,
            StackType.FASTAPI,
            StackType.FLASK,
        ):
            stack_specific = [
                "# Python",
                "__pycache__/",
                "*.py[cod]",
                "*$py.class",
                "*.so",
                ".Python",
                "build/",
                "develop-eggs/",
                "dist/",
                "downloads/",
                "eggs/",
                ".eggs/",
                "lib/",
                "lib64/",
                "parts/",
                "sdist/",
                "var/",
                "wheels/",
                "*.egg-info/",
                ".installed.cfg",
                "*.egg",
                ".venv/",
                "venv/",
                "ENV/",
                ".pytest_cache/",
                ".coverage",
                "htmlcov/",
                ".tox/",
                "db.sqlite3",
                "media/",
                "staticfiles/",
                "",
            ]
        elif stack in (StackType.NODE, StackType.REACT, StackType.NEXTJS, StackType.VUE):
            stack_specific = [
                "# Node.js",
                "node_modules/",
                "npm-debug.log*",
                "yarn-debug.log*",
                "yarn-error.log*",
                ".npm",
                ".yarn",
                "coverage/",
                ".nyc_output/",
                ".next/",
                "out/",
                "build/",
                "dist/",
                "",
            ]
        elif stack == StackType.GO:
            stack_specific = [
                "# Go",
                "*.exe",
                "*.exe~",
                "*.dll",
                "*.so",
                "*.dylib",
                "*.test",
                "*.out",
                "vendor/",
                "",
            ]
        elif stack == StackType.RUST:
            stack_specific = [
                "# Rust",
                "target/",
                "Cargo.lock",
                "**/*.rs.bk",
                "*.pdb",
                "",
            ]

        return "\n".join(common + stack_specific)

    def _render_docker_compose(self, config: DockerConfig, stack: StackType) -> str:
        """Render docker-compose.yml content."""
        port = config.port

        lines = [
            'version: "3.8"',
            "",
            "services:",
            "  app:",
            "    build: .",
            f"    ports:",
            f'      - "{port}:{port}"',
        ]

        if stack == StackType.DJANGO:
            lines.extend(
                [
                    "    command: python manage.py runserver 0.0.0.0:8000",
                    "    volumes:",
                    "      - .:/app",
                    "    environment:",
                    "      - PYTHONUNBUFFERED=1",
                ]
            )
            if config.settings_module:
                lines.append(f"      - DJANGO_SETTINGS_MODULE={config.settings_module}")
        else:
            lines.extend(
                [
                    "    environment:",
                ]
            )
            if stack in (
                StackType.PYTHON,
                StackType.FASTAPI,
                StackType.FLASK,
            ):
                lines.append("      - PYTHONUNBUFFERED=1")
            elif stack in (StackType.NODE, StackType.REACT, StackType.NEXTJS):
                lines.append("      - NODE_ENV=production")

        if config.env_vars:
            for key, value in config.env_vars.items():
                if key not in {"PYTHONUNBUFFERED", "DJANGO_SETTINGS_MODULE"}:
                    lines.append(f"      - {key}={value}")

        lines.extend(
            [
                "    restart: unless-stopped",
                "",
                "  # Uncomment to add a database",
                "  # db:",
                "  #   image: postgres:15-alpine",
                "  #   environment:",
                "  #     POSTGRES_USER: user",
                "  #     POSTGRES_PASSWORD: password",
                "  #     POSTGRES_DB: app",
                "  #   volumes:",
                "  #     - postgres_data:/var/lib/postgresql/data",
                "  #   restart: unless-stopped",
                "",
                "# volumes:",
                "#   postgres_data:",
            ]
        )

        return "\n".join(lines)
