from sohail_agent_cli.ai.models import AIStructuredOutput
from sohail_agent_cli.specification.models import Specification, SpecificationOutput


def test_specification_maps_ai_metadata_to_sections():
    output = AIStructuredOutput(
        kind="specification",
        title="Shopfront Specification",
        summary="A commerce platform.",
        items=("browse products",),
        metadata={
            "product_spec": "Product overview.",
            "features": ["Browse products", "Manage cart"],
            "data_model": {"Product": "Catalog item"},
            "api_spec": ["GET /products"],
            "non_functional": ["No secrets in source control"],
        },
    )

    specification = Specification.from_ai_output(output)

    assert specification.title == "Shopfront Specification"
    assert specification.features == ("Browse products", "Manage cart")
    assert "Product" in specification.data_model
    assert "- GET /products" in specification.api_spec
    assert specification.non_functional == ("No secrets in source control",)


def test_empty_specification_output_reports_empty():
    assert SpecificationOutput().is_empty
