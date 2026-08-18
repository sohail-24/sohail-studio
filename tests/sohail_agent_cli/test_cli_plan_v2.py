import argparse
from pathlib import Path

import pytest

from sohail_agent_cli import main
from sohail_agent_cli.agents.base_agent import AgentResult


def test_plan_v2_parser_defaults():
    args = main.create_parser().parse_args(["plan-v2"])

    assert args.command == "plan-v2"
    assert args.goal is None
    assert args.project_name is None
    assert args.output == "./project-plan"


def test_plan_v2_parser_accepts_options():
    args = main.create_parser().parse_args(
        [
            "plan-v2",
            "--goal",
            "Build ecommerce platform",
            "--project-name",
            "Shopfront",
            "--output",
            "./plans/shopfront",
        ]
    )

    assert args.goal == "Build ecommerce platform"
    assert args.project_name == "Shopfront"
    assert args.output == "./plans/shopfront"


@pytest.mark.asyncio
async def test_cmd_plan_v2_uses_direct_agent_dispatch(monkeypatch, tmp_path):
    calls = {}

    class FakePlanningAgentV2:
        def __init__(self, dry_run, verbose):
            calls["init"] = {"dry_run": dry_run, "verbose": verbose}

        async def execute(self, path, **kwargs):
            calls["execute"] = {"path": path, **kwargs}
            return AgentResult.success("ok")

    monkeypatch.setattr(main, "PlanningAgentV2", FakePlanningAgentV2)
    args = argparse.Namespace(
        goal="Build ecommerce platform",
        project_name="Shopfront",
        output=str(tmp_path / "plan"),
        dry_run=True,
        verbose=False,
        overwrite=False,
        ollama=False,
    )

    exit_code = await main.cmd_plan_v2(args)

    assert exit_code == 0
    assert calls["init"] == {"dry_run": True, "verbose": False}
    assert calls["execute"]["path"] == Path(args.output)
    assert calls["execute"]["goal"] == args.goal
    assert calls["execute"]["project_name"] == args.project_name


@pytest.mark.asyncio
async def test_cmd_plan_v2_rejects_ollama(monkeypatch):
    monkeypatch.setattr(
        main,
        "PlanningAgentV2",
        lambda *_args, **_kwargs: pytest.fail("PlanningAgentV2 should not be built"),
    )
    args = argparse.Namespace(
        goal=None,
        project_name=None,
        output="./project-plan",
        dry_run=False,
        verbose=False,
        overwrite=False,
        ollama=True,
    )

    assert await main.cmd_plan_v2(args) == 1


def test_plan_v2_is_not_part_of_all_command():
    source = Path(main.__file__).read_text(encoding="utf-8")
    all_block = source[source.index("async def cmd_all"):source.index("async def main_async")]

    assert "cmd_plan_v2" not in all_block
