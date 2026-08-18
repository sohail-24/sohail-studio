import json
from pathlib import Path

import pytest

from sohail_agent_cli.agents import PlanningAgentV2
from sohail_agent_cli.planning.decision_engine.models import PlanningSelections, QuestionAnswer


def selections() -> PlanningSelections:
    return PlanningSelections.from_answers(
        (
            QuestionAnswer("Q-1", "project.name", "Shopfront"),
            QuestionAnswer("Q-2", "project.goal", "Build ecommerce platform"),
            QuestionAnswer("Q-3", "project.target_users", "shoppers, admins"),
            QuestionAnswer("Q-4", "project.project_type", "web_application"),
            QuestionAnswer("Q-5", "features.first_release_scope", "browse products"),
            QuestionAnswer("Q-6", "features.out_of_scope", "marketplace sellers"),
            QuestionAnswer("Q-7", "frontend.framework", "Next.js"),
            QuestionAnswer("Q-8", "backend.framework", "FastAPI"),
            QuestionAnswer("Q-9", "database.primary_database", "PostgreSQL"),
            QuestionAnswer("Q-10", "authentication.approach", "session"),
            QuestionAnswer("Q-11", "container.docker_required", True),
            QuestionAnswer("Q-12", "container.kubernetes", "later"),
            QuestionAnswer("Q-13", "infrastructure.deployment_target", "containers"),
            QuestionAnswer("Q-14", "monitoring.enabled", True),
            QuestionAnswer("Q-15", "security.baseline", "standard"),
            QuestionAnswer("Q-16", "testing.strategy", ("unit", "integration")),
            QuestionAnswer("Q-17", "documentation.level", "standard"),
            QuestionAnswer(
                "Q-18",
                "custom_requirements.items",
                "Generate PDF reports, Offline mode",
            ),
        )
    )


class FakeEngine:
    def __init__(self) -> None:
        self.initial_answers = None

    def run(self, initial_answers=None):
        self.initial_answers = initial_answers
        return selections()


@pytest.mark.asyncio
async def test_planning_agent_v2_writes_planning_package_and_selections(tmp_path):
    engine = FakeEngine()
    output = tmp_path / "project-plan"
    agent = PlanningAgentV2(engine=engine)

    result = await agent.execute(
        output,
        goal="Build ecommerce platform",
        project_name="Shopfront",
    )

    assert result.success
    assert engine.initial_answers["project.goal"] == "Build ecommerce platform"
    assert (output / "planning-selections.json").exists()
    assert (output / "TASK.md").exists()
    assert (output / "ARCHITECTURE.md").exists()
    assert (output / "REQUIREMENTS.md").exists()
    assert (output / "decisions" / "001_frontend.md").exists()
    data = json.loads((output / "planning-selections.json").read_text(encoding="utf-8"))
    assert data["custom_requirements"] == ["Generate PDF reports", "Offline mode"]
    assert result.data["custom_requirements"] == 2


@pytest.mark.asyncio
async def test_planning_agent_v2_dry_run_writes_nothing(tmp_path):
    output = tmp_path / "project-plan"
    agent = PlanningAgentV2(dry_run=True, engine=FakeEngine())

    result = await agent.execute(output)

    assert result.success
    assert result.data["dry_run"] is True
    assert not output.exists()


@pytest.mark.asyncio
async def test_planning_agent_v2_blocks_existing_selections_without_overwrite(tmp_path):
    output = tmp_path / "project-plan"
    output.mkdir()
    existing = output / "planning-selections.json"
    existing.write_text("human content", encoding="utf-8")
    agent = PlanningAgentV2(engine=FakeEngine())

    result = await agent.execute(output)

    assert not result.success
    assert existing.read_text(encoding="utf-8") == "human content"


@pytest.mark.asyncio
async def test_planning_agent_v2_overwrites_selections_when_requested(tmp_path):
    output = tmp_path / "project-plan"
    output.mkdir()
    existing = output / "planning-selections.json"
    existing.write_text("human content", encoding="utf-8")
    agent = PlanningAgentV2(engine=FakeEngine())

    result = await agent.execute(output, overwrite=True)

    assert result.success
    assert "human content" not in existing.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_planning_agent_v2_protects_existing_decisions(tmp_path):
    output = tmp_path / "project-plan"
    decision = output / "decisions" / "001_frontend.md"
    decision.parent.mkdir(parents=True)
    decision.write_text("accepted history", encoding="utf-8")
    agent = PlanningAgentV2(engine=FakeEngine())

    result = await agent.execute(output, overwrite=True)

    assert not result.success
    assert decision.read_text(encoding="utf-8") == "accepted history"
    assert not (output / "planning-selections.json").exists()
