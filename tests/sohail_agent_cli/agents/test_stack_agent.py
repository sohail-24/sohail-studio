from pathlib import Path

import pytest

from sohail_agent_cli.agents import StackAgent


def write_plan(root: Path) -> Path:
    plan = root / "project-plan"
    decisions = plan / "decisions"
    decisions.mkdir(parents=True)
    for filename in ("REQUIREMENTS.md", "ARCHITECTURE.md", "TASK.md"):
        (plan / filename).write_text(f"# {filename}\n", encoding="utf-8")
    for index, (topic, choice) in enumerate(
        (("frontend", "React"), ("backend", "FastAPI"), ("database", "PostgreSQL")),
        start=1,
    ):
        (decisions / f"{index:03d}_{topic}.md").write_text(
            f"# DEC-{index:03d}\n\n## Decision\n\n{choice}\n\n## Rationale\n\n- Selected.\n",
            encoding="utf-8",
        )
    return plan


@pytest.mark.asyncio
async def test_stack_agent_writes_stack_skeleton(tmp_path):
    output = tmp_path / "generated"
    result = await StackAgent().execute(
        write_plan(tmp_path),
        output_dir=output,
    )
    assert result.success
    assert (output / "frontend" / "package.json").exists()
    assert (output / "backend" / "main.py").exists()
    assert (output / "database" / "schema.sql").exists()


@pytest.mark.asyncio
async def test_stack_agent_dry_run_writes_nothing(tmp_path):
    output = tmp_path / "generated"
    result = await StackAgent(dry_run=True).execute(
        write_plan(tmp_path),
        output_dir=output,
    )
    assert result.success
    assert result.data["dry_run"] is True
    assert not output.exists()


@pytest.mark.asyncio
async def test_stack_agent_blocks_existing_files_without_overwrite(tmp_path):
    output = tmp_path / "generated"
    existing = output / "backend" / "main.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("human content", encoding="utf-8")

    result = await StackAgent().execute(
        write_plan(tmp_path),
        output_dir=output,
    )
    assert not result.success
    assert existing.read_text(encoding="utf-8") == "human content"


@pytest.mark.asyncio
async def test_stack_agent_overwrites_when_requested(tmp_path):
    output = tmp_path / "generated"
    existing = output / "backend" / "main.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("human content", encoding="utf-8")

    result = await StackAgent().execute(
        write_plan(tmp_path),
        output_dir=output,
        overwrite=True,
    )
    assert result.success
    assert "human content" not in existing.read_text(encoding="utf-8")
