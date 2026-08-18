from sohail_agent_cli.ai.models import AIRequest
from sohail_agent_cli.ai.router import AIRouter


def test_router_selects_prompt_for_known_task():
    routed = AIRouter().route(AIRequest(task="generate_documentation"))
    assert routed.prompt_name == "documentation"


def test_router_preserves_explicit_prompt():
    routed = AIRouter().route(
        AIRequest(task="generate_documentation", prompt_name="planning")
    )
    assert routed.prompt_name == "planning"
