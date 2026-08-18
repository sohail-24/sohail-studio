import argparse
from pathlib import Path

import pytest

from sohail_agent_cli import main
from sohail_agent_cli.agents.base_agent import AgentResult


def test_plan_parser_defaults():
    args = main.create_parser().parse_args(["plan", "Build ecommerce platform"])
    assert args.command == "plan"
    assert args.goal == "Build ecommerce platform"
    assert args.project_name is None
    assert args.output == "./project-plan"


def test_plan_parser_accepts_command_specific_options():
    args = main.create_parser().parse_args(
        [
            "plan",
            "Build ecommerce platform",
            "--project-name",
            "Shopfront",
            "--output",
            "./plans/shopfront",
        ]
    )
    assert args.project_name == "Shopfront"
    assert args.output == "./plans/shopfront"


def test_existing_commands_still_parse():
    parser = main.create_parser()
    for command in ("inspect", "dockerize", "k8s", "cicd", "docs", "interview", "all"):
        args = parser.parse_args([command])
        assert args.command == command


def test_global_dry_run_remains_before_subcommand():
    args = main.create_parser().parse_args(
        ["--dry-run", "plan", "Build ecommerce platform"]
    )
    assert args.dry_run is True


@pytest.mark.asyncio
async def test_cmd_plan_uses_direct_agent_dispatch(monkeypatch, tmp_path):
    calls = {}

    class FakePlanningAgent:
        def __init__(self, dry_run, verbose):
            calls["init"] = {"dry_run": dry_run, "verbose": verbose}

        async def execute(self, path, **kwargs):
            calls["execute"] = {"path": path, **kwargs}
            return AgentResult.success("ok")

    monkeypatch.setattr(main, "PlanningAgent", FakePlanningAgent)
    args = argparse.Namespace(
        goal="Build ecommerce platform",
        project_name="Shopfront",
        output=str(tmp_path / "plan"),
        dry_run=True,
        verbose=False,
        overwrite=False,
        ollama=False,
    )
    exit_code = await main.cmd_plan(args)
    assert exit_code == 0
    assert calls["init"] == {"dry_run": True, "verbose": False}
    assert calls["execute"]["path"] == Path(args.output)
    assert calls["execute"]["goal"] == args.goal


@pytest.mark.asyncio
async def test_cmd_plan_rejects_ollama(monkeypatch):
    monkeypatch.setattr(
        main,
        "PlanningAgent",
        lambda *_args, **_kwargs: pytest.fail("PlanningAgent should not be constructed"),
    )
    args = argparse.Namespace(
        goal="Build ecommerce platform",
        project_name=None,
        output="./project-plan",
        dry_run=False,
        verbose=False,
        overwrite=False,
        ollama=True,
    )
    assert await main.cmd_plan(args) == 1


def test_plan_is_not_part_of_all_command(monkeypatch):
    parser = main.create_parser()
    args = parser.parse_args(["all"])
    assert not hasattr(args, "goal")
    source = Path(main.__file__).read_text(encoding="utf-8")
    all_block = source[source.index("async def cmd_all"):source.index("async def main_async")]
    assert "cmd_plan" not in all_block
