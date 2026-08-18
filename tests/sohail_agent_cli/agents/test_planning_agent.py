from pathlib import Path

import pytest

from sohail_agent_cli.agents import PlanningAgent

ANSWERS = [
    "",
    "shoppers, store administrators",
    "browse products, manage cart, place orders",
    "marketplace sellers",
    "Next.js",
    "FastAPI",
    "PostgreSQL",
    "session",
    "yes",
    "later",
    "managed container platform",
    "security, transactional consistency",
]


def prompt_from(values):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


@pytest.mark.asyncio
async def test_successful_flow_creates_complete_package(tmp_path):
    output = tmp_path / "project-plan"
    agent = PlanningAgent(
        prompt=prompt_from(ANSWERS),
        confirm=lambda _prompt: True,
    )
    result = await agent.execute(output, goal="Build ecommerce platform")
    assert result.success
    assert (output / "TASK.md").exists()
    assert (output / "ARCHITECTURE.md").exists()
    assert (output / "REQUIREMENTS.md").exists()
    assert (output / "decisions" / "001_frontend.md").exists()
    assert result.data["failed_files"] == []


@pytest.mark.asyncio
async def test_dry_run_creates_nothing(tmp_path):
    output = tmp_path / "project-plan"
    agent = PlanningAgent(
        dry_run=True,
        prompt=prompt_from(ANSWERS),
        confirm=lambda _prompt: True,
    )
    result = await agent.execute(output, goal="Build ecommerce platform")
    assert result.success
    assert result.data["dry_run"] is True
    assert not output.exists()
    assert result.files_created == []


@pytest.mark.asyncio
async def test_user_cancellation_writes_nothing(tmp_path):
    output = tmp_path / "project-plan"
    agent = PlanningAgent(
        prompt=prompt_from(ANSWERS),
        confirm=lambda _prompt: False,
    )
    result = await agent.execute(output, goal="Build ecommerce platform")
    assert result.success
    assert result.data["cancelled"] is True
    assert not output.exists()


@pytest.mark.asyncio
async def test_invalid_goal_fails_before_prompting(tmp_path):
    agent = PlanningAgent(prompt=lambda _prompt: pytest.fail("prompt should not run"))
    result = await agent.execute(tmp_path / "plan", goal="   ")
    assert not result.success


@pytest.mark.asyncio
async def test_output_path_file_is_rejected(tmp_path):
    output = tmp_path / "project-plan"
    output.write_text("not a directory", encoding="utf-8")
    agent = PlanningAgent(prompt=lambda _prompt: pytest.fail("prompt should not run"))
    result = await agent.execute(output, goal="Build ecommerce platform")
    assert not result.success
    assert "not a directory" in result.message.lower()


@pytest.mark.asyncio
async def test_parent_traversal_output_is_rejected():
    agent = PlanningAgent(prompt=lambda _prompt: pytest.fail("prompt should not run"))
    result = await agent.execute(Path("../project-plan"), goal="Build ecommerce platform")
    assert not result.success
    assert "parent traversal" in result.message


@pytest.mark.asyncio
async def test_existing_summary_blocks_without_overwrite(tmp_path):
    output = tmp_path / "project-plan"
    output.mkdir()
    (output / "TASK.md").write_text("human content", encoding="utf-8")
    agent = PlanningAgent(
        prompt=prompt_from(ANSWERS),
        confirm=lambda _prompt: True,
    )
    result = await agent.execute(output, goal="Build ecommerce platform")
    assert not result.success
    assert (output / "TASK.md").read_text(encoding="utf-8") == "human content"
    assert not (output / "REQUIREMENTS.md").exists()


@pytest.mark.asyncio
async def test_overwrite_replaces_summaries_but_not_decisions(tmp_path):
    output = tmp_path / "project-plan"
    output.mkdir()
    for filename in ("TASK.md", "ARCHITECTURE.md", "REQUIREMENTS.md"):
        (output / filename).write_text("old", encoding="utf-8")
    agent = PlanningAgent(
        prompt=prompt_from(ANSWERS),
        confirm=lambda _prompt: True,
    )
    result = await agent.execute(
        output,
        goal="Build ecommerce platform",
        overwrite=True,
    )
    assert result.success
    assert "old" not in (output / "TASK.md").read_text(encoding="utf-8")
    assert len(result.data["overwritten_files"]) == 3


@pytest.mark.asyncio
async def test_existing_decision_is_always_protected(tmp_path):
    output = tmp_path / "project-plan"
    decision = output / "decisions" / "001_frontend.md"
    decision.parent.mkdir(parents=True)
    decision.write_text("accepted history", encoding="utf-8")
    agent = PlanningAgent(
        prompt=prompt_from(ANSWERS),
        confirm=lambda _prompt: True,
    )
    result = await agent.execute(
        output,
        goal="Build ecommerce platform",
        overwrite=True,
    )
    assert not result.success
    assert decision.read_text(encoding="utf-8") == "accepted history"
    assert not (output / "TASK.md").exists()


@pytest.mark.asyncio
async def test_invalid_choice_is_retried(tmp_path):
    answers = ANSWERS.copy()
    answers.insert(4, "Svelte")
    prompts = []
    iterator = iter(answers)

    def prompt(text):
        prompts.append(text)
        return next(iterator)

    agent = PlanningAgent(prompt=prompt, confirm=lambda _prompt: False)
    result = await agent.execute(tmp_path / "plan", goal="Build ecommerce platform")
    assert result.success
    frontend_prompts = [item for item in prompts if "Frontend approach" in item]
    assert len(frontend_prompts) == 2


@pytest.mark.asyncio
async def test_write_failure_returns_failed_result(tmp_path, monkeypatch):
    output = tmp_path / "project-plan"
    agent = PlanningAgent(
        prompt=prompt_from(ANSWERS),
        confirm=lambda _prompt: True,
    )

    async def fail_write(*_args, **_kwargs):
        return False, "simulated write failure", False

    monkeypatch.setattr(agent, "write_file", fail_write)
    result = await agent.execute(output, goal="Build ecommerce platform")
    assert not result.success
    assert result.data["failed_files"]
