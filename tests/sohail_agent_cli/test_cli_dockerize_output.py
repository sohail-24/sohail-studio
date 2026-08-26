from pathlib import Path

from rich.console import Console

import sohail_agent_cli.main as cli
from sohail_agent_cli.agents.base_agent import AgentResult


def rendered_output(monkeypatch) -> str:
    output = Console(record=True, color_system=None, width=120)
    monkeypatch.setattr(cli, "console", output)
    return output


def test_dry_run_result_panel_reports_planned_actions(monkeypatch):
    output = rendered_output(monkeypatch)
    result = AgentResult(
        success=True,
        message="Docker artifacts validated successfully",
        data={
            "inspection_run_id": "inspection-123",
            "context": {
                "project": {"name": "sample", "inspection_run_id": "inspection-123"},
                "components": [{
                    "name": "backend",
                    "runtimes": [{"runtime": "Node.js", "version": "20", "source_file": ".nvmrc", "confidence": "high"}],
                    "commands": [{"name": "start", "command": "node server.js", "source_file": "package.json", "confidence": "high"}],
                    "artifacts": [{"path": "target/app.jar", "source_type": "DERIVED_DETERMINISTIC", "rule_id": "maven.executable-artifact.spring-boot.v1", "derived_from": [{"source_file": "pom.xml", "key": "artifactId/version"}], "launch_command": ["java", "-jar", "target/app.jar"]}],
                    "ports": [],
                }],
            },
            "decision": {"status": "ready"},
            "validation": {"status": "passed"},
            "rendered_artifacts": [{"path": "backend/Dockerfile", "content": 'FROM node:20\nCMD ["node","server.js"]\n'}],
            "planned_actions": [{"action": "generate", "path": "backend/Dockerfile"}],
        },
    )

    cli._print_docker_result(result, dry_run=True)

    text = output.export_text()
    assert "DRY RUN COMPLETED" in text
    assert "WOULD CREATE: backend/Dockerfile" in text
    assert "FROM node:20" in text
    assert "DERIVED_DETERMINISTIC" in text
    assert "target/app.jar" in text
    assert 'CMD ["node","server.js"]' in text
    assert "Files written: NO" in text
    assert "Files modified: NO" in text


def test_real_result_panel_reports_created_artifacts(monkeypatch):
    output = rendered_output(monkeypatch)
    result = AgentResult(
        success=True,
        message="Docker artifacts validated successfully",
        files_created=[Path("backend/Dockerfile")],
        data={"planned_actions": [{"action": "generate", "path": "backend/Dockerfile"}]},
    )

    cli._print_docker_result(result, dry_run=False)

    text = output.export_text()
    assert "DOCKERIZE COMPLETED" in text
    assert "CREATED: backend/Dockerfile" in text
    assert "Validation: PASSED" in text
    assert "Persisted intelligence: REUSED" in text
    assert "New inspection: NO" in text


def test_blocked_result_panel_reports_stage_and_no_writes(monkeypatch):
    output = rendered_output(monkeypatch)
    result = AgentResult.controlled(
        "NEEDS_EVIDENCE",
        "frontend lacks evidence-backed production start command",
        data={
            "diagnostic": {
                "stage": "Evidence-bound decision validation",
                "repository_scan_during_dockerize": "NO",
                "requirements": [{
                    "component": "frontend",
                    "requirement": "Production start command",
                    "source": ["package.json"],
                    "value": "none",
                    "repository_truth": "NOT FOUND IN PERSISTED SNAPSHOT",
                    "inspector": "NOT EXTRACTED",
                    "persisted": "NOT PERSISTED",
                    "docker_context": "NOT INCLUDED",
                    "validation": "NOT RUN (decision blocked)",
                    "rejection": "No literal production start command was classified",
                    "explicit_evidence": [],
                    "derived_deterministic": [],
                    "unsupported": {"status": "UNSUPPORTED", "reason": "not proven"},
                }],
                "evidence_rejected": [],
                "model_proposed": {"components": [{"name": "frontend", "base_image": "node:20"}], "compose": {}},
                "recommended_next_action": "Re-inspect after adding authoritative evidence.",
            },
        },
    )

    cli._print_docker_blocked(result, dry_run=True, stage="Evidence-bound decision validation")

    text = output.export_text()
    assert "DRY RUN BLOCKED" in text
    assert "Stage: Evidence-bound decision validation" in text
    assert "frontend lacks evidence-backed production start command" in text
    assert "inspector: NOT EXTRACTED" in text
    assert "Docker context: NOT INCLUDED" in text
    assert "explicit evidence: none" in text
    assert "derived deterministic: none" in text
    assert "Model proposed (not repository truth)" in text
    assert "Files written: NO" in text


def test_preflight_blocked_panel_reports_missing_requirements_and_zero_model_calls(monkeypatch):
    output = rendered_output(monkeypatch)
    result = AgentResult.controlled(
        "NEEDS_EVIDENCE",
        "Missing authoritative Docker requirements: backend: exact Docker base image; backend: exact working directory",
        data={
            "model_called": False,
            "repair_attempts": 0,
            "diagnostic": {
                "stage": "deterministic Docker requirement preflight",
                "repository_scan_during_dockerize": "NO",
                "missing_requirements": [
                    "backend: exact Docker base image",
                    "backend: exact working directory",
                ],
                "requirements": [{
                    "component": "backend",
                    "requirement": "Exact Docker base image",
                    "source": [],
                    "value": [],
                    "repository_truth": "NOT PROVEN",
                    "inspector": "NOT EXTRACTED",
                    "persisted": "NOT PERSISTED",
                    "docker_context": "NOT INCLUDED",
                    "validation": "NOT RUN (decision blocked)",
                    "explicit_evidence": [],
                    "derived_deterministic": [],
                    "unsupported": {"status": "UNSUPPORTED", "reason": "not proven"},
                }],
                "evidence_rejected": [],
                "model_proposed": {"components": [], "compose": {}},
            },
        },
    )

    cli._print_docker_blocked(result, dry_run=True, stage="Evidence-bound decision validation")

    text = output.export_text()
    assert "DRY RUN BLOCKED" in text
    assert "Stage: deterministic Docker requirement preflight" in text
    assert "Missing authoritative requirements:" in text
    assert "exact Docker base image" in text
    assert "Model called: NO" in text
    assert "Repair attempted: NO" in text
    assert "Ollama was not called: YES" in text
    assert "Files written: NO" in text
