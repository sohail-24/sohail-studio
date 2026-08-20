"""Main entry point for Sohail-Agent-CLI."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Awaitable, Callable

from rich.console import Console

from sohail_agent_cli.agents import (
    BootstrapAgent,
    BlueprintAgent,
    CicdAgent,
    DockerAgent,
    DocsAgent,
    InterviewAgent,
    K8sAgent,
    PlanningAgent,
    PlanningAgentV2,
    RepoInspectorAgent,
    SpecificationAgent,
    StackAgent,
)
from sohail_agent_cli.bootstrap.validator import PlanningValidationError
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
        choices=["frontend", "backend"],
        default=None,
        help="Component to containerize; may be repeated",
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
    
    agent = RepoInspectorAgent(
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    result = await agent.execute(path)
    
    return 0 if result.success else 1


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
    result = await agent.execute(
        path,
        port=args.port,
        overwrite=args.overwrite,
        components=args.component,
        compose_action=args.compose_action,
        compose=args.compose,
    )
    
    return 0 if result.success else 1


async def cmd_k8s(args: argparse.Namespace) -> int:
    """Execute the k8s command."""
    path = Path(args.path).resolve()
    
    if not path.exists():
        console.print(f"[red]Error: Path does not exist: {path}[/red]")
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
    )
    
    return 0 if result.success else 1


async def cmd_cicd(args: argparse.Namespace) -> int:
    """Execute the cicd command."""
    path = Path(args.path).resolve()
    
    if not path.exists():
        console.print(f"[red]Error: Path does not exist: {path}[/red]")
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
    )
    
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
