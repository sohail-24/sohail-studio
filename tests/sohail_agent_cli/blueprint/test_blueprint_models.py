from sohail_agent_cli.ai.models import AIStructuredOutput
from sohail_agent_cli.blueprint.models import Blueprint, BlueprintOutput


def test_blueprint_maps_ai_metadata_to_sections():
    output = AIStructuredOutput(
        kind="blueprint",
        title="Shopfront Blueprint",
        summary="A commerce implementation blueprint.",
        items=("build API",),
        metadata={
            "system_design": "Layered service design.",
            "backend_architecture": {"API": "FastAPI service"},
            "frontend_architecture": "React application.",
            "database_design": "PostgreSQL schema.",
            "api_flow": ["GET /products", "POST /orders"],
            "implementation_plan": "Build vertical slices.",
            "folder_structure": "src/, tests/",
            "dependencies": ["fastapi", "react"],
        },
    )

    blueprint = Blueprint.from_ai_output(output)

    assert blueprint.title == "Shopfront Blueprint"
    assert "API" in blueprint.backend_architecture
    assert "- GET /products" in blueprint.api_flow
    assert "- fastapi" in blueprint.dependencies
    assert blueprint.source_items == ("build API",)


def test_empty_blueprint_output_reports_empty():
    assert BlueprintOutput().is_empty
