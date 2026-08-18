from pathlib import Path

from sohail_agent_cli.generators import StackGenerator


def write_plan(root: Path, frontend: str = "React", backend: str = "FastAPI", database: str = "PostgreSQL") -> Path:
    plan = root / "project-plan"
    decisions = plan / "decisions"
    decisions.mkdir(parents=True)
    for filename in ("REQUIREMENTS.md", "ARCHITECTURE.md", "TASK.md"):
        (plan / filename).write_text(f"# {filename}\n", encoding="utf-8")
    for index, (topic, choice) in enumerate(
        (("frontend", frontend), ("backend", backend), ("database", database)),
        start=1,
    ):
        (decisions / f"{index:03d}_{topic}.md").write_text(
            f"# DEC-{index:03d}\n\n## Decision\n\n{choice}\n\n## Rationale\n\n- Selected.\n",
            encoding="utf-8",
        )
    return plan


def test_stack_generator_creates_react_fastapi_postgresql_skeleton(tmp_path):
    result = StackGenerator().generate(write_plan(tmp_path))
    paths = [path.as_posix() for path in result.files]
    assert "frontend/package.json" in paths
    assert "frontend/vite.config.ts" in paths
    assert "frontend/src/main.tsx" in paths
    assert "backend/main.py" in paths
    assert "backend/requirements.txt" in paths
    assert "backend/routers/.gitkeep" in paths
    assert "backend/models/.gitkeep" in paths
    assert "database/schema.sql" in paths
    assert "products" not in "\n".join(result.files.values()).lower()
    assert "auth" not in "\n".join(result.files.values()).lower()


def test_stack_generator_creates_node_skeleton(tmp_path):
    result = StackGenerator().generate(write_plan(tmp_path, backend="Node.js"))
    paths = [path.as_posix() for path in result.files]
    assert "backend/package.json" in paths
    assert "backend/src/server.js" in paths
    assert "backend/routes/.gitkeep" in paths
    assert "backend/controllers/.gitkeep" in paths
    assert "backend/middleware/.gitkeep" in paths


def test_stack_generator_creates_django_skeleton(tmp_path):
    result = StackGenerator().generate(write_plan(tmp_path, backend="Django"))
    paths = [path.as_posix() for path in result.files]
    assert "backend/manage.py" in paths
    assert "backend/requirements.txt" in paths
    assert "backend/app/settings.py" in paths


def test_stack_generator_creates_go_skeleton(tmp_path):
    result = StackGenerator().generate(write_plan(tmp_path, backend="Go"))
    paths = [path.as_posix() for path in result.files]
    assert "backend/go.mod" in paths
    assert "backend/cmd/server/main.go" in paths
    assert "backend/internal/.gitkeep" in paths
