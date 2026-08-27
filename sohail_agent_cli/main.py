"""Main entry point for Sohail-Agent-CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from rich.console import Console
from rich.panel import Panel

from core.cli_bridge import (
    CONTROLLED_NEEDS_CLARIFICATION_EXIT_CODE,
    CONTROLLED_NEEDS_EVIDENCE_EXIT_CODE,
)
from core.storage.project_intelligence import ProjectIntelligenceRepository
from sohail_agent_cli.agents import (
    BlueprintAgent,
    BootstrapAgent,
    CicdAgent,
    DockerAgent,
    DocsAgent,
    InterviewAgent,
    K8sAgent,
    PlanningAgent,
    PlanningAgentV2,
    SpecificationAgent,
    StackAgent,
)
from sohail_agent_cli.bootstrap.validator import PlanningValidationError
from sohail_agent_cli.inspection import DeepInspector
from sohail_agent_cli.stack.loader import StackPlanError

console = Console()

CommandHandler = Callable[[argparse.Namespace], Awaitable[int]]
EXPECTED_CLI_EXCEPTIONS = (
    FileNotFoundError,
    PermissionError,
    ValueError,
    PlanningValidationError,
    StackPlanError,
)


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="sohail-agent",
        description="Sohail-Agent-CLI: A local AI engineering assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sohail-agent inspect ./my-project
  sohail-agent dockerize ./my-project
  sohail-agent k8s ./my-project
  sohail-agent cicd ./my-project
  sohail-agent docs ./my-project
  sohail-agent interview ./my-project
  sohail-agent plan "Build an ecommerce platform"
  sohail-agent plan-v2
  sohail-agent stack --plan-dir ./project-plan --output ./my-project
  sohail-agent specification --plan-dir ./project-plan --output ./specifications
  sohail-agent blueprint --plan-dir ./project-plan --spec-dir ./specifications --output ./blueprints
  sohail-agent all ./my-project
        """,
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 2.0.0",
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files",
    )
    
    parser.add_argument(
        "--ollama",
        action="store_true",
        help="Use Ollama for AI-enhanced generation (docs, interview)",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # inspect command
    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect repository structure and stack",
    )
    inspect_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to repository (default: current directory)",
    )
    
    # dockerize command
    dockerize_parser = subparsers.add_parser(
        "dockerize",
        help="Generate Docker configuration",
    )
    dockerize_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to repository (default: current directory)",
    )
    dockerize_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to expose",
    )
    dockerize_parser.add_argument(
        "--component",
        action="append",
        default=None,
        help="Evidence-discovered component to containerize; may be repeated",
    )
    dockerize_parser.add_argument(
        "--compose-action",
        choices=["analyze", "improve", "generate", "keep"],
        default="keep",
        help="How to handle repository Docker Compose configuration",
    )
    dockerize_parser.add_argument(
        "--no-compose",
        dest="compose",
        action="store_false",
        default=True,
        help="Do not create or update Docker Compose configuration",
    )
    dockerize_parser.add_argument(
        "--clarification-response",
        default="",
        help="Validated user-provided evidence for one bounded clarification retry",
    )
    dockerize_parser.add_argument(
        "--inspection-run-id",
        default="",
        help="Canonical persisted inspection run to reuse",
    )
    dockerize_parser.add_argument(
        "--docker-plan",
        default="",
        help="Internal artifact plan produced by the Terminal Dockerize workflow",
    )
    
    # k8s command
    k8s_parser = subparsers.add_parser(
        "k8s",
        help="Generate Kubernetes manifests",
    )
    k8s_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to repository (default: current directory)",
    )
    k8s_parser.add_argument(
        "--app-name",
        type=str,
        default=None,
        help="Application name",
    )
    k8s_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to expose",
    )
    k8s_parser.add_argument(
        "--component",
        action="append",
        choices=["frontend", "backend"],
        default=None,
        help="Component to target; may be repeated",
    )
    k8s_parser.add_argument(
        "--organization",
        choices=["automatic", "single", "separate"],
        default="automatic",
        help="Manifest organization strategy",
    )
    k8s_parser.add_argument(
        "--inspection-run-id",
        default="",
        help="Canonical persisted inspection run to reuse",
    )
    
    # cicd command
    cicd_parser = subparsers.add_parser(
        "cicd",
        help="Generate CI/CD workflows",
    )
    cicd_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to repository (default: current directory)",
    )
    cicd_parser.add_argument(
        "--action",
        choices=["analyze", "improve", "generate", "keep"],
        default="analyze",
        help="How to handle existing CI/CD configuration",
    )
    cicd_parser.add_argument(
        "--platform",
        choices=["jenkins", "github-actions", "both"],
        default="jenkins",
        help="CI/CD platform for generated workflows",
    )
    cicd_parser.add_argument(
        "--inspection-run-id",
        default="",
        help="Canonical persisted inspection run to reuse",
    )
    
    # docs command
    docs_parser = subparsers.add_parser(
        "docs",
        help="Generate project documentation",
    )
    docs_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to repository (default: current directory)",
    )
    
    # interview command
    interview_parser = subparsers.add_parser(
        "interview",
        help="Generate interview notes",
    )
    interview_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to repository (default: current directory)",
    )

    # plan command
    plan_parser = subparsers.add_parser(
        "plan",
        help="Create a persistent project planning package",
    )
    plan_parser.add_argument(
        "goal",
        help="Project goal to clarify and plan",
    )
    plan_parser.add_argument(
        "--project-name",
        type=str,
        default=None,
        help="Project display name",
    )
    plan_parser.add_argument(
        "--output",
        type=str,
        default="./project-plan",
        help="Planning package directory (default: ./project-plan)",
    )

    # plan-v2 command
    plan_v2_parser = subparsers.add_parser(
        "plan-v2",
        help="Create a planning package with the Engineering Decision Engine",
    )
    plan_v2_parser.add_argument(
        "--goal",
        type=str,
        default=None,
        help="Project goal to prefill before interactive decisions",
    )
    plan_v2_parser.add_argument(
        "--project-name",
        type=str,
        default=None,
        help="Project display name to prefill before interactive decisions",
    )
    plan_v2_parser.add_argument(
        "--output",
        type=str,
        default="./project-plan",
        help="Planning package directory (default: ./project-plan)",
    )

        # bootstrap command
    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Generate a professional project scaffold from a planning package",
    )

    bootstrap_parser.add_argument(
        "--plan-dir",
        type=str,
        default="./project-plan",
        help="Planning package directory (default: ./project-plan)",
    )

    bootstrap_parser.add_argument(
        "--output",
        type=str,
        default=".",
        help="Output project directory (default: current directory)",
    )

    # stack command
    stack_parser = subparsers.add_parser(
        "stack",
        help="Generate technology stack skeletons from a planning package",
    )
    stack_parser.add_argument(
        "--plan-dir",
        type=str,
        default="./project-plan",
        help="Planning package directory (default: ./project-plan)",
    )
    stack_parser.add_argument(
        "--output",
        type=str,
        default=".",
        help="Output project directory (default: current directory)",
    )

    # specification command
    specification_parser = subparsers.add_parser(
        "specification",
        help="Generate structured specification files from a planning package",
    )
    specification_parser.add_argument(
        "--plan-dir",
        type=str,
        default="./project-plan",
        help="Planning package directory (default: ./project-plan)",
    )
    specification_parser.add_argument(
        "--output",
        type=str,
        default="./specifications",
        help="Specification output directory (default: ./specifications)",
    )

    # blueprint command
    blueprint_parser = subparsers.add_parser(
        "blueprint",
        help="Generate implementation blueprint files from planning and specification packages",
    )
    blueprint_parser.add_argument(
        "--plan-dir",
        type=str,
        default="./project-plan",
        help="Planning package directory (default: ./project-plan)",
    )
    blueprint_parser.add_argument(
        "--spec-dir",
        type=str,
        default="./specifications",
        help="Specification package directory (default: ./specifications)",
    )
    blueprint_parser.add_argument(
        "--output",
        type=str,
        default="./blueprints",
        help="Blueprint output directory (default: ./blueprints)",
    )
    
    # all command
    all_parser = subparsers.add_parser(
        "all",
        help="Run all agents on the project",
    )
    all_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to repository (default: current directory)",
    )
    
    return parser


async def cmd_inspect(args: argparse.Namespace) -> int:
    """Execute the inspect command."""
    path = Path(args.path).resolve()
    
    if not path.exists():
        console.print(f"[red]Error: Path does not exist: {path}[/red]")
        return 1
    
    console.print("[cyan][Running][/cyan] Starting complete repository inspection...")
    intelligence = DeepInspector().inspect(
        path,
        progress=lambda message: console.print(f"[cyan][Running][/cyan] {message}..."),
    )
    runtime_summary = ", ".join(
        f"{item['runtime']} {item['version']}" for item in intelligence.runtimes
    ) or "none detected"
    port_summary = ", ".join(
        f"{item.get('component', 'project')}.{item.get('port_type', 'application')}="
        f"{'conflict' if item.get('conflict') else item.get('port')}"
        for item in intelligence.ports
    ) or "none detected"
    console.print(f"\n[bold cyan]Inspection complete:[/bold cyan] {intelligence.name}")
    console.print(f"[bold]Files:[/bold] {len(intelligence.files)} · [bold]Evidence:[/bold] {len(intelligence.evidence)}")
    console.print(f"[bold]Components:[/bold] {', '.join(item['name'] for item in intelligence.components) or 'none detected'}")
    console.print(f"[bold]Languages:[/bold] {', '.join(intelligence.languages) or 'none detected'}")
    console.print(f"[bold]Runtimes:[/bold] {runtime_summary}")
    console.print(f"[bold]Package managers:[/bold] {', '.join(intelligence.package_managers) or 'none detected'}")
    console.print(f"[bold]Databases:[/bold] {', '.join(intelligence.databases) or 'none detected'}")
    console.print(f"[bold]Ports:[/bold] {port_summary}")
    console.print(f"[bold]Docker:[/bold] {'detected' if intelligence.has_docker or intelligence.has_docker_compose else 'not detected'}")
    console.print(f"[bold]Kubernetes:[/bold] {'detected' if intelligence.kubernetes.get('files') else 'not detected'}")
    console.print(f"[bold]CI/CD:[/bold] {', '.join(intelligence.ci_cd.get('platforms', [])) or 'not detected'}")
    counts = intelligence.evidence_counts
    console.print(f"[bold]Confidence:[/bold] high {counts['high']} · medium {counts['medium']} · low {counts['low']}")
    if args.dry_run:
        console.print("[yellow]Dry run: inspection was not persisted.[/yellow]")
        return 0

    console.print("[cyan][Running][/cyan] Persisting inspection intelligence in PostgreSQL...")
    repository = ProjectIntelligenceRepository.from_env()
    try:
        persisted = repository.persist(intelligence)
    finally:
        repository.storage.close()
    console.print(f"[bold green]Stored in PostgreSQL:[/bold green] inspection run {persisted.run_id}")
    console.print("[bold green][Completed] Inspection complete.[/bold green]")
    return 0


def _planned_actions(result: Any) -> list[dict[str, str]]:
    planned = list((getattr(result, "data", {}) or {}).get("planned_actions", []) or [])
    if planned:
        return planned
    return [
        {"action": "create", "path": str(path)}
        for path in list(getattr(result, "files_created", []) or [])
    ] + [
        {"action": "keep", "path": str(path)}
        for path in list(getattr(result, "files_skipped", []) or [])
    ]


def _display_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def _artifact_previews(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return selected artifact previews with their planned action."""
    previews = list(data.get("artifact_previews") or [])
    if previews:
        return previews
    actions = {
        str(item.get("path")): str(item.get("action") or "keep")
        for item in data.get("planned_actions", []) or []
    }
    return [
        {**artifact, "action": actions.get(str(artifact.get("path")), "keep")}
        for artifact in data.get("rendered_artifacts", []) or []
    ]


def _safe_command_name(value: Any) -> str:
    name = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return name or "sohail-app"


def _recommended_docker_commands(data: dict[str, Any]) -> list[str]:
    """Build terminal guidance from the selected, validated artifacts only."""
    context = data.get("context") or {}
    project = context.get("project") or {}
    root = str(project.get("root_path") or "")
    if not root:
        return []
    actions = [item for item in data.get("planned_actions", []) or [] if item.get("action") != "skip"]
    compose_paths = [
        str(item.get("path")) for item in actions
        if Path(str(item.get("path"))).name in {"docker-compose.yml", "compose.yml"}
    ]
    lines = ["Recommended Docker commands", f"Run from: {root}", ""]
    if compose_paths:
        lines.extend([
            "1. Build and start",
            "   docker compose up --build",
            "2. Run in background",
            "   docker compose up -d --build",
            "3. View status",
            "   docker compose ps",
            "4. View logs",
            "   docker compose logs -f",
            "5. Stop services",
            "   docker compose down",
        ])
        return lines

    components = {
        str(item.get("name")): item for item in context.get("components", []) or []
    }
    dockerfiles = [
        item for item in actions
        if Path(str(item.get("path"))).name.lower().startswith("dockerfile")
    ]
    if not dockerfiles:
        return []
    lines.append("Dockerfile-only project guidance:")
    for index, item in enumerate(dockerfiles, start=1):
        dockerfile = Path(str(item["path"]))
        relative_dockerfile = os.path.relpath(dockerfile, root)
        component = next(
            (
                source for source in components.values()
                if relative_dockerfile in {
                    *(str(path) for path in source.get("dockerfiles", []) or []),
                    f"{str(source.get('path') or '.').strip('./')}/Dockerfile".strip("/"),
                    "Dockerfile" if str(source.get("path") or ".") == "." else "",
                }
            ),
            {},
        )
        name = _safe_command_name(component.get("name") or dockerfile.parent.name or project.get("name"))
        component_path = str(component.get("path") or ".")
        build_context = "." if component_path in {"", "."} else f"./{component_path.strip('./')}"
        port = next(
            (
                item.get("port") for item in component.get("ports", []) or []
                if item.get("port_type") == "application" and not item.get("conflict")
            ),
            None,
        )
        lines.extend([
            f"{index}. Build {relative_dockerfile}",
            f"   docker build -t {name}:local -f {relative_dockerfile} {build_context}",
            f"{index + 1}. Run {name}:local",
            f"   docker run --rm --name {name}"
            + (f" -p {int(port)}:{int(port)}" if port is not None else "")
            + f" {name}:local",
            f"{index + 2}. View logs",
            f"   docker logs -f {name}",
            f"{index + 3}. Stop the container",
            f"   docker stop {name}",
        ])
    return lines


def _append_context_evidence(lines: list[str], context: dict[str, Any]) -> None:
    for component in context.get("components", []) or []:
        name = component.get("name", "component")
        lines.append(f"  {name}:")
        runtimes = component.get("runtimes", []) or []
        for item in runtimes:
            lines.append(
                f"    - Runtime: {item.get('runtime')} {item.get('version')} "
                f"(source: {item.get('source_file')}, confidence: {item.get('confidence')})"
            )
        for item in component.get("commands", []) or []:
            lines.append(
                f"    - Command [{item.get('name')}]: {item.get('command')} "
                f"(source: {item.get('source_file')}, confidence: {item.get('confidence')})"
            )
        for item in component.get("ports", []) or []:
            lines.append(
                f"    - Port [{item.get('port_type')}]: {item.get('port')} "
                f"(source: {item.get('source_file')}, confidence: {item.get('confidence')})"
            )
        for item in component.get("artifacts", []) or []:
            lines.append(
                f"    - Artifact [{item.get('source_type')}]: {item.get('path')} "
                f"(rule: {item.get('rule_id')}, derived from: {_display_value(item.get('derived_from') or [])})"
            )
            lines.append(f"      launch: {_display_value(item.get('launch_command') or 'none')}")
        for item in component.get("base_images", []) or []:
            lines.append(
                f"    - Base image [{item.get('source_type', 'EXPLICIT_EVIDENCE')}]: {item.get('image')} "
                f"(source: {item.get('source_file')})"
            )
        for item in component.get("working_directories", []) or []:
            lines.append(
                f"    - Working directory [{item.get('source_type', 'EXPLICIT_EVIDENCE')}]: {item.get('path')} "
                f"(source: {item.get('source_file')})"
            )
        if not runtimes and not component.get("commands") and not component.get("ports") and not component.get("artifacts"):
            lines.append("    - No Docker-relevant runtime, command, or port facts")
    for policy in context.get("platform_policies", []) or []:
        lines.append(
            f"  Platform policy [{policy.get('source_type')}]: "
            f"{policy.get('policy_id')} v{policy.get('policy_version')} "
            f"(component: {policy.get('component')}, applies: {_display_value(policy.get('applicable_reason') or [])})"
        )
        for field in ("base_image", "working_directory", "build_image"):
            value = (policy.get("values") or {}).get(field)
            if value:
                lines.append(
                    f"    - {field}: {value.get('value')} "
                    f"(source_type: {value.get('source_type')}, policy: {value.get('policy_id')} v{value.get('policy_version')})"
                )


def _print_docker_result(result: Any, *, dry_run: bool = False) -> None:
    if dry_run:
        planned = _planned_actions(result)
        data = getattr(result, "data", {}) or {}
        context = data.get("context") or {}
        decision = data.get("decision") or {}
        validation = data.get("validation") or {}
        lines = [
            "Inspection:",
            f"  Project: {context.get('project', {}).get('name', 'unknown')}",
            f"  Inspection run: {data.get('inspection_run_id') or context.get('project', {}).get('inspection_run_id', 'unknown')}",
            "  Repository scan during Dockerize: 0 (persisted snapshot reused)",
            "",
            "Evidence used:",
        ]
        _append_context_evidence(lines, context)
        lines.extend(["", "Artifact plan:"])
        if planned:
            labels = {"generate": "CREATE", "create": "CREATE", "upgrade": "UPGRADE", "keep": "KEEP", "skip": "SKIP"}
            for item in planned:
                action = labels.get(str(item.get("action", "plan")).lower(), str(item.get("action", "PLAN")).upper())
                lines.append(f"WOULD {action}: {item.get('path', '')}")
        else:
            lines.append("  No filesystem changes planned")
        lines.extend([
            "",
            "Ollama:",
            f"  Model: {data.get('model', 'devops-qwen:latest')}",
            "  Status: decision received" if data.get("model_called", True) else "  Status: not called (deterministic preflight blocked first)",
            f"  Repair attempts: {data.get('repair_attempts', 0)}",
            "",
            "Decision validation:",
            f"  [PASS] evidence-bound decision ({decision.get('status', 'unknown')})",
            f"  [PASS] artifact scope ({'authoritative plan applied' if data.get('docker_plan') is not None else 'default plan'})",
            f"  [PASS] rendered artifact validation ({validation.get('status', 'unknown')})",
            "",
            "In-memory artifacts:",
        ])
        rendered = _artifact_previews(data)
        if rendered:
            for artifact in rendered:
                lines.append(f"  [READY] {artifact.get('path', '')}")
        else:
            lines.append("  None (workflow did not reach rendering)")
        for index, artifact in enumerate(rendered, start=1):
            action = str(artifact.get("action") or "keep").lower()
            status = {
                "generate": "WOULD CREATE",
                "create": "WOULD CREATE",
                "upgrade": "WOULD UPDATE",
                "keep": "WOULD KEEP",
                "skip": "WOULD SKIP",
            }.get(action, f"WOULD {action.upper()}")
            lines.extend([
                "",
                "================================================",
                f"ARTIFACT {index} OF {len(rendered)} — {Path(str(artifact.get('path', ''))).name}",
                f"Status: {status}",
                "Authority: validated in-memory rendering",
                "================================================",
                f"Path: {artifact.get('path', '')}",
                "Preview:",
                str(artifact.get("content", "")),
            ])
        command_lines = _recommended_docker_commands(data)
        if command_lines:
            lines.extend(["", "================================================", *command_lines, "================================================"])
        lines.extend([
            "",
            "Files written: NO (count: 0)",
            "Files modified: NO (count: 0)",
            "Repository scan: 0 during Dockerize",
            f"Inspection run reused: {data.get('inspection_run_id') or context.get('project', {}).get('inspection_run_id', 'unknown')}",
        ])
        console.print(Panel("\n".join(lines), title="DRY RUN COMPLETED", border_style="yellow"))
        return
    lines = ["Created artifacts", ""]
    actions = _planned_actions(result)
    if actions:
        labels = {"generate": "CREATED", "create": "CREATED", "upgrade": "UPGRADED", "keep": "KEPT", "skip": "SKIPPED"}
        for item in actions:
            action = labels.get(str(item.get("action", "create")).lower(), str(item.get("action", "create")).upper())
            lines.append(f"{action}: {item.get('path', '')}")
    else:
        lines.append("No artifact paths reported")
    data = getattr(result, "data", {}) or {}
    written = int(data.get("files_written", len(getattr(result, "files_created", []) or [])))
    modified = list(data.get("files_modified", []) or [])
    lines.extend([
        "",
        "Validation: PASSED",
        f"Files written: {'YES' if written else 'NO'} (count: {written})",
        f"Files modified: {'YES' if modified else 'NO'}" + (f" ({', '.join(modified)})" if modified else ""),
        "Persisted intelligence: REUSED",
        "New inspection: NO",
    ])
    command_lines = _recommended_docker_commands(data)
    if command_lines:
        lines.extend(["", "================================================", *command_lines, "================================================"])
    console.print(Panel("\n".join(lines), title="DOCKERIZE COMPLETED", border_style="green"))


def _print_docker_blocked(result: Any, *, dry_run: bool, stage: str) -> None:
    title = "DRY RUN BLOCKED" if dry_run else "DOCKERIZE FAILED"
    data = getattr(result, "data", {}) or {}
    diagnostic = data.get("diagnostic") or {}
    actual_stage = str(diagnostic.get("stage") or data.get("stage") or stage)
    lines = [f"Stage: {actual_stage}", "", f"Reason: {result.message}", ""]
    if diagnostic:
        lines.extend([
            "Missing/evidence boundary:",
            f"  Repository truth in persisted snapshot: {diagnostic.get('requirements', [{}])[0].get('repository_truth', 'NOT REPRESENTED')}",
            f"  Dockerize repository scan: {diagnostic.get('repository_scan_during_dockerize', 'NO')}",
            f"  Missing authoritative requirements: {_display_value(diagnostic.get('missing_requirements') or 'none')}",
            "",
            "Evidence diagnostic:",
        ])
        for item in diagnostic.get("requirements", []) or []:
            lines.extend([
                f"  {item.get('component')}: {item.get('requirement')}",
                f"    source: {_display_value(item.get('source') or 'none')}",
                f"    value: {_display_value(item.get('value') or 'none')}",
                f"    explicit evidence: {_display_value(item.get('explicit_evidence') or 'none')}",
                f"    derived deterministic: {_display_value(item.get('derived_deterministic') or 'none')}",
                f"    approved platform policy: {_display_value(item.get('approved_platform_policy') or 'none')}",
                f"    unsupported: {_display_value(item.get('unsupported') or 'none')}",
                f"    repository truth: {item.get('repository_truth')}",
                f"    inspector: {item.get('inspector')}",
                f"    persistence: {item.get('persisted')}",
                f"    Docker context: {item.get('docker_context')}",
                f"    deterministic validation: {item.get('validation')}",
            ])
            if item.get("rejection"):
                lines.append(f"    rejected: {item['rejection']}")
        lines.extend([
            f"  Model called: {'YES' if data.get('model_called') else 'NO'}",
            f"  Repair attempted: {'YES' if data.get('repair_attempts') else 'NO'}",
            "  Ollama was not called: YES" if not data.get("model_called") else "  Ollama was not called: NO",
            "",
            "Evidence rejected: " + _display_value(diagnostic.get("evidence_rejected") or "none"),
            "Model proposed (not repository truth): " + _display_value(diagnostic.get("model_proposed") or "none"),
            "Evidence absent/unsupported: see each requirement's explicit, derived, and unsupported fields above.",
            f"Recommended next action: {diagnostic.get('recommended_next_action', 'Re-inspect after adding authoritative evidence.')}",
        ])
    lines.extend(["", "Files written: NO (count: 0)", "Files modified: NO (count: 0)"])
    console.print(Panel("\n".join(lines), title=title, border_style="yellow" if dry_run else "red"))


async def cmd_dockerize(args: argparse.Namespace) -> int:
    """Execute the dockerize command."""
    path = Path(args.path).resolve()
    
    if not path.exists():
        console.print(f"[red]Error: Path does not exist: {path}[/red]")
        return 1
    
    agent = DockerAgent(
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    try:
        raw_docker_plan = getattr(args, "docker_plan", "")
        docker_plan = json.loads(raw_docker_plan) if raw_docker_plan else None
        if docker_plan is not None and not isinstance(docker_plan, dict):
            raise ValueError("Docker plan must be an object")
    except (TypeError, json.JSONDecodeError, ValueError) as exc:
        console.print(f"[red]Dockerize failed:[/red] Invalid Docker plan: {exc}")
        return 1
    result = await agent.execute(
        path,
        port=args.port,
        overwrite=args.overwrite,
        components=args.component,
        compose_action=args.compose_action,
        compose=args.compose,
        user_evidence=getattr(args, "clarification_response", ""),
        inspection_run_id=getattr(args, "inspection_run_id", ""),
        docker_plan=docker_plan,
    )
    if result.status == "NEEDS_CLARIFICATION":
        request = result.data.get("clarification_request")
        question = request.get("question") if isinstance(request, dict) else result.message
        console.print(f"[yellow]Clarification required:[/yellow] {question}")
        if request:
            console.print(
                "SOHAIL_CLARIFICATION_REQUEST:" + json.dumps(request, separators=(",", ":")),
                markup=False,
                no_wrap=True,
                overflow="ignore",
                crop=False,
            )
        return CONTROLLED_NEEDS_CLARIFICATION_EXIT_CODE
    if result.status == "NEEDS_EVIDENCE":
        if args.dry_run:
            _print_docker_blocked(result, dry_run=True, stage="Evidence-bound decision validation")
        else:
            console.print(f"[yellow]Dockerize needs evidence:[/yellow] {result.message}")
        return CONTROLLED_NEEDS_EVIDENCE_EXIT_CODE
    if not result.success:
        if args.dry_run:
            _print_docker_blocked(result, dry_run=True, stage="Dockerize execution")
        else:
            _print_docker_blocked(result, dry_run=False, stage="Dockerize execution")
        return 1
    if not args.dry_run:
        console.print(f"[bold green]{result.message}[/bold green]")
    _print_docker_result(result, dry_run=args.dry_run)
    return 0


def _load_required_inspection(path: Path, expected_run_id: str = ""):
    """Load the canonical persisted snapshot; never fall back to a repository scan."""
    repository = ProjectIntelligenceRepository.from_env()
    try:
        intelligence = repository.load_latest(str(path))
    finally:
        repository.storage.close()
    if intelligence is None:
        console.print("[red]Project Intelligence is required; run Inspect first.[/red]")
        return None
    if expected_run_id and intelligence.inspection_run_id != expected_run_id:
        console.print(
            "[red]Stored Project Intelligence does not match the requested inspection run; "
            "re-inspect explicitly.[/red]"
        )
        return None
    console.print(
        f"[cyan][Verified][/cyan] Using persisted Project Intelligence: "
        f"inspection run {intelligence.inspection_run_id or 'stored snapshot'}"
    )
    return intelligence


async def cmd_k8s(args: argparse.Namespace) -> int:
    """Execute the k8s command."""
    path = Path(args.path).resolve()
    
    if not path.exists():
        console.print(f"[red]Error: Path does not exist: {path}[/red]")
        return 1
    
    intelligence = _load_required_inspection(path, getattr(args, "inspection_run_id", ""))
    if intelligence is None:
        return 1
    agent = K8sAgent(
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    result = await agent.execute(
        path,
        app_name=args.app_name,
        port=args.port,
        overwrite=args.overwrite,
        components=args.component,
        organization=args.organization,
        intelligence=intelligence,
    )
    
    if result.success:
        console.print(f"[bold green]{result.message}[/bold green]")
        _print_created_files(result)
    else:
        console.print(f"[red]Kubernetes failed:[/red] {result.message}")
    return 0 if result.success else 1


async def cmd_cicd(args: argparse.Namespace) -> int:
    """Execute the cicd command."""
    path = Path(args.path).resolve()
    
    if not path.exists():
        console.print(f"[red]Error: Path does not exist: {path}[/red]")
        return 1
    
    intelligence = _load_required_inspection(path, getattr(args, "inspection_run_id", ""))
    if intelligence is None:
        return 1
    agent = CicdAgent(
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    result = await agent.execute(
        path,
        overwrite=args.overwrite,
        action=args.action,
        platform=args.platform,
        intelligence=intelligence,
    )
    
    if result.success:
        console.print(f"[bold green]{result.message}[/bold green]")
        _print_created_files(result)
    else:
        console.print(f"[red]CI/CD failed:[/red] {result.message}")
    return 0 if result.success else 1


async def cmd_docs(args: argparse.Namespace) -> int:
    """Execute the docs command."""
    path = Path(args.path).resolve()
    
    if not path.exists():
        console.print(f"[red]Error: Path does not exist: {path}[/red]")
        return 1
    
    agent = DocsAgent(
        dry_run=args.dry_run,
        verbose=args.verbose,
        use_ollama=args.ollama,
    )
    result = await agent.execute(
        path,
        overwrite=args.overwrite,
    )
    
    if result.success:
        console.print(f"[bold green]{result.message}[/bold green]")
        _print_created_files(result)
    else:
        console.print(f"[red]Documentation failed:[/red] {result.message}")
    return 0 if result.success else 1


async def cmd_interview(args: argparse.Namespace) -> int:
    """Execute the interview command."""
    path = Path(args.path).resolve()
    
    if not path.exists():
        console.print(f"[red]Error: Path does not exist: {path}[/red]")
        return 1
    
    agent = InterviewAgent(
        dry_run=args.dry_run,
        verbose=args.verbose,
        use_ollama=args.ollama,
    )
    result = await agent.execute(
        path,
        overwrite=args.overwrite,
    )
    
    return 0 if result.success else 1


async def cmd_plan(args: argparse.Namespace) -> int:
    """Execute the PlanningAgent V1 command through direct dispatch."""
    if args.ollama:
        console.print(
            "[red]Error: PlanningAgent V1 does not use Ollama or other providers.[/red]"
        )
        return 1

    output_path = Path(args.output)
    agent = PlanningAgent(
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    result = await agent.execute(
        output_path,
        goal=args.goal,
        project_name=args.project_name,
        overwrite=args.overwrite,
    )
    return 0 if result.success else 1


async def cmd_plan_v2(args: argparse.Namespace) -> int:
    """Execute PlanningAgent V2 through the Engineering Decision Engine."""
    if args.ollama:
        console.print(
            "[red]Error: PlanningAgent V2 does not use Ollama or other providers.[/red]"
        )
        return 1

    agent = PlanningAgentV2(
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    result = await agent.execute(
        Path(args.output),
        goal=args.goal,
        project_name=args.project_name,
        overwrite=args.overwrite,
    )
    return 0 if result.success else 1


async def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Execute the BootstrapAgent."""

    if args.ollama:
        console.print(
            "[red]Error: BootstrapAgent V1 does not use Ollama.[/red]"
        )
        return 1

    plan_dir = Path(args.plan_dir)
    output_dir = Path(args.output)

    agent = BootstrapAgent(
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    result = await agent.execute(
        plan_dir,
        output_dir=output_dir,
        overwrite=args.overwrite,
    )

    return 0 if result.success else 1


async def cmd_stack(args: argparse.Namespace) -> int:
    """Execute the StackAgent."""
    if args.ollama:
        console.print(
            "[red]Error: StackGenerator V1 does not use Ollama or other providers.[/red]"
        )
        return 1

    agent = StackAgent(
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    result = await agent.execute(
        Path(args.plan_dir),
        output_dir=Path(args.output),
        overwrite=args.overwrite,
    )
    return 0 if result.success else 1


async def cmd_specification(args: argparse.Namespace) -> int:
    """Execute the SpecificationAgent."""
    agent = SpecificationAgent(
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    result = await agent.execute(
        Path(args.plan_dir),
        output_dir=Path(args.output),
        overwrite=args.overwrite,
    )
   
    return 0 if result.success else 1


async def cmd_blueprint(args: argparse.Namespace) -> int:
    """Execute the BlueprintAgent."""
    agent = BlueprintAgent(
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    result = await agent.execute(
        Path(args.plan_dir),
        spec_dir=Path(args.spec_dir),
        output_dir=Path(args.output),
        overwrite=args.overwrite,
    )

    return 0 if result.success else 1


async def cmd_all(args: argparse.Namespace) -> int:
    """Execute all commands."""
    path = Path(args.path).resolve()
    
    if not path.exists():
        console.print(f"[red]Error: Path does not exist: {path}[/red]")
        return 1
    
    console.print(f"\n[bold blue]Running all agents on:[/bold blue] {path}")
    
    if args.dry_run:
        console.print("[yellow]DRY RUN - No files will be modified[/yellow]")
    
    # Run inspect first
    console.print("\n" + "=" * 60)
    console.print("[bold]1. Repository Inspection[/bold]")
    console.print("=" * 60)
    await cmd_inspect(args)
    
    # Run other agents
    agents = [
        ("2. Docker Generation", cmd_dockerize),
        ("3. Kubernetes Generation", cmd_k8s),
        ("4. CI/CD Generation", cmd_cicd),
        ("5. Documentation Generation", cmd_docs),
        ("6. Interview Notes Generation", cmd_interview),
    ]
    
    for title, cmd_func in agents:
        console.print("\n" + "=" * 60)
        console.print(f"[bold]{title}[/bold]")
        console.print("=" * 60)
        try:
            await cmd_func(args)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
    
    console.print("\n" + "=" * 60)
    console.print("[bold green]All agents completed![/bold green]")
    console.print("=" * 60)
    
    return 0


async def run_command_safely(
    command_func: CommandHandler,
    args: argparse.Namespace,
) -> int:
    """Run a command and convert expected CLI failures into clean messages."""
    try:
        return await command_func(args)
    except EXPECTED_CLI_EXCEPTIONS as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1
    except Exception as exc:
        if getattr(args, "verbose", False):
            raise
        console.print(f"[red]Unexpected error:[/red] {exc}")
        console.print("[dim]Run again with --verbose to see the full traceback.[/dim]")
        return 1


async def main_async() -> int:
    """Main async entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    commands = {
        "inspect": cmd_inspect,
        "dockerize": cmd_dockerize,
        "k8s": cmd_k8s,
        "cicd": cmd_cicd,
        "docs": cmd_docs,
        "interview": cmd_interview,
        "plan": cmd_plan,
        "plan-v2": cmd_plan_v2,
        "bootstrap": cmd_bootstrap,
        "stack": cmd_stack,
        "specification": cmd_specification,
        "blueprint": cmd_blueprint,
        "all": cmd_all,
    }
    
    command_func = commands.get(args.command)
    if command_func:
        return await run_command_safely(command_func, args)
    else:
        console.print(f"[red]Unknown command: {args.command}[/red]")
        return 1


def main() -> int:
    """Main entry point."""
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        console.print("[yellow]Cancelled by user.[/yellow]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
