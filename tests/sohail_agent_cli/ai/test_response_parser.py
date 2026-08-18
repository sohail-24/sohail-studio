from sohail_agent_cli.ai.models import AIStructuredOutput
from sohail_agent_cli.ai.response_parser import AIResponseParser


def test_response_parser_returns_dataclass():
    output = AIResponseParser().parse_structured_output(
        {
            "kind": "feature",
            "title": "Feature slices",
            "summary": "Small slices.",
            "items": ["slice one", "slice two"],
            "metadata": {"confidence": "medium"},
        }
    )
    assert isinstance(output, AIStructuredOutput)
    assert output.items == ("slice one", "slice two")
    assert output.metadata["confidence"] == "medium"
