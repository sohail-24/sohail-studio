import argparse
from pathlib import Path

import pytest

from sohail_agent_cli import main
from sohail_agent_cli.agents.base_agent import AgentResult


def test_blueprint_parser_defaults():
    args = main.create_parser().parse_args(["blueprint"])

    assert args.command == "blueprint"
    assert args.plan_dir == "./project-plan"
    assert args.spec_dir == "./specifications"
    assert args.output == "./blueprints"


def test_blueprint_parser_accepts_options():
    args = main.create_parser().parse_args(
        [
            "blueprint",
            "--plan-dir",
            "./plans/shopfront",
            "--spec-dir",
            "./specs/shopfront",
            "--output",
            "./blueprints/shopfront",
        ]
    )

    assert args.plan_dir == "./plans/shopfront"
    assert args.spec_dir == "./specs/shopfront"
    assert args.output == "./blueprints/shopfront"


@pytest.mark.asyncio
async def test_cmd_blueprint_uses_direct_agent_dispatch(monkeypatch, tmp_path):
    calls = {}

    class FakeBlueprintAgent:
        def __init__(self, dry_run, verbose):
            calls["init"] = {"dry_run": dry_run, "verbose": verbose}

        async def execute(self, plan_dir, **kwargs):
            calls["execute"] = {"plan_dir": plan_dir, **kwargs}
            return AgentResult.success("ok")

    monkeypatch.setattr(main, "BlueprintAgent", FakeBlueprintAgent)
    args = argparse.Namespace(
        plan_dir=str(tmp_path / "project-plan"),
        spec_dir=str(tmp_path / "specifications"),
        output=str(tmp_path / "blueprints"),
        dry_run=True,
        verbose=False,
        overwrite=False,
        ollama=False,
    )

    exit_code = await main.cmd_blueprint(args)

    assert exit_code == 0
    assert calls["init"] == {"dry_run": True, "verbose": False}
    assert calls["execute"]["plan_dir"] == Path(args.plan_dir)
    assert calls["execute"]["spec_dir"] == Path(args.spec_dir)
    assert calls["execute"]["output_dir"] == Path(args.output)


def test_blueprint_is_not_part_of_all_command():
    source = Path(main.__file__).read_text(encoding="utf-8")
    all_block = source[
        source.index("async def cmd_all"):source.index("async def run_command_safely")
    ]

    assert "cmd_blueprint" not in all_block
