import json

import pytest

from sohail_agent_cli.ai.models import ProjectContext
from sohail_agent_cli.ai.prompts import PromptBuilder, PromptCatalog


def test_prompt_catalog_exposes_versioned_templates():
    catalog = PromptCatalog()
    assert "planning" in catalog.names()
    assert catalog.get("planning").version == "v1"


def test_prompt_builder_injects_context_and_contract():
    context = ProjectContext(
        goal="Build ecommerce",
        project_name="Shopfront",
        frontend="React",
        backend="FastAPI",
        database="PostgreSQL",
    )
    template, prompt = PromptBuilder().build(
        "planning",
        context=context,
        instruction="Summarize architecture.",
    )
    payload = json.loads(prompt.split("\n\n", 1)[1])
    assert template.name == "planning"
    assert payload["context"]["frontend"] == "React"
    assert payload["instruction"] == "Summarize architecture."
    assert "response_contract" in payload


def test_prompt_catalog_rejects_unknown_template():
    with pytest.raises(KeyError):
        PromptCatalog().get("missing")
