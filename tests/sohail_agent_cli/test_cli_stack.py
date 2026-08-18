import argparse
from pathlib import Path

import pytest

from sohail_agent_cli import main
from sohail_agent_cli.agents.base_agent import AgentResult


def test_stack_parser_defaults():
    args = main.create_parser().parse_args(["stack"])
    assert args.command == "stack"
    assert args.plan_dir == "./project-plan"
    assert args.output == "."


def test_stack_parser_accepts_options():
    args = main.create_parser().parse_args(
        ["stack", "--plan-dir", "./plans/shopfront", "--output", "./generated"]
    )
    assert args.plan_dir == "./plans/shopfront"
    assert args.output == "./generated"


@pytest.mark.asyncio
async def test_cmd_stack_uses_direct_agent_dispatch(monkeypatch, tmp_path):
    calls = {}

    class FakeStackAgent:
        def __init__(self, dry_run, verbose):
            calls["init"] = {"dry_run": dry_run, "verbose": verbose}

        async def execute(self, plan_dir, **kwargs):
            calls["execute"] = {"plan_dir": plan_dir, **kwargs}
            return AgentResult.success("ok")

    monkeypatch.setattr(main, "StackAgent", FakeStackAgent)
    args = argparse.Namespace(
        plan_dir=str(tmp_path / "project-plan"),
        output=str(tmp_path / "generated"),
        dry_run=True,
        verbose=False,
        overwrite=False,
        ollama=False,
    )
    exit_code = await main.cmd_stack(args)
    assert exit_code == 0
    assert calls["init"] == {"dry_run": True, "verbose": False}
    assert calls["execute"]["plan_dir"] == Path(args.plan_dir)
    assert calls["execute"]["output_dir"] == Path(args.output)


@pytest.mark.asyncio
async def test_cmd_stack_rejects_ollama(monkeypatch):
    monkeypatch.setattr(
        main,
        "StackAgent",
        lambda *_args, **_kwargs: pytest.fail("StackAgent should not be constructed"),
    )
    args = argparse.Namespace(
        plan_dir="./project-plan",
        output=".",
        dry_run=False,
        verbose=False,
        overwrite=False,
        ollama=True,
    )
    assert await main.cmd_stack(args) == 1


def test_stack_is_not_part_of_all_command():
    source = Path(main.__file__).read_text(encoding="utf-8")
    all_block = source[source.index("async def cmd_all"):source.index("async def main_async")]
    assert "cmd_stack" not in all_block
