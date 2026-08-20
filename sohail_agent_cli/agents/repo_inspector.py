"""Repository inspector agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.table import Table

from sohail_agent_cli.agents.base_agent import AgentResult, BaseAgent
from sohail_agent_cli.analyzers import DeploymentReadinessAnalyzer


class RepoInspectorAgent(BaseAgent):
    """Agent that inspects and analyzes repositories."""
    
    def __init__(self, dry_run: bool = False, verbose: bool = False) -> None:
        super().__init__(
            name="repo_inspector",
            description="Inspects repository structure and detects stack",
            dry_run=dry_run,
            verbose=verbose,
        )
        self.readiness_analyzer = DeploymentReadinessAnalyzer()
    
    async def execute(self, path: Path, **kwargs: Any) -> AgentResult:
        """Execute repository inspection."""
        self.info(f"Inspecting repository: {path}")
        
        # Analyze repository
        analysis = await self.analyze_repo(path)
        
        # Calculate deployment readiness
        readiness = self.readiness_analyzer.analyze(analysis)
        
        # Print results
        self._print_results(analysis, readiness)
        
        return AgentResult.success(
            message=f"Repository inspection complete. Readiness: {readiness.score}/100 (Grade: {readiness.grade})",
            data={
                "analysis": analysis.to_dict(),
                "readiness": readiness.to_dict(),
            },
        )
    
    def _print_results(self, analysis, readiness) -> None:
        """Print inspection results."""
        from rich.console import Console
        console = Console()
        
        # Stack info
        console.print(f"\n[bold cyan]Repository:[/bold cyan] {analysis.name}")
        console.print(f"[bold cyan]Path:[/bold cyan] {analysis.path}")
        console.print(f"[bold cyan]Primary Stack:[/bold cyan] {analysis.stack.primary.value}")
        console.print(f"[bold cyan]Build System:[/bold cyan] {analysis.stack.build_system}")
        console.print(f"[bold cyan]Framework:[/bold cyan] {analysis.stack.framework}")
        console.print(f"[bold cyan]Runtime:[/bold cyan] {analysis.stack.runtime}")
        if analysis.stack.port:
            console.print(f"[bold cyan]Detected Port:[/bold cyan] {analysis.stack.port}")
        
        if analysis.stack.secondary:
            console.print(f"[bold cyan]Secondary:[/bold cyan] {', '.join(s.value for s in analysis.stack.secondary)}")
        
        console.print(f"[bold cyan]Confidence:[/bold cyan] {analysis.stack.confidence:.0%}")
        
        # DevOps files table
        table = Table(title="DevOps Files Status")
        table.add_column("File", style="cyan")
        table.add_column("Status", style="green")
        
        table.add_row("Dockerfile", "✅" if analysis.has_docker else "❌")
        table.add_row("docker-compose.yml", "✅" if analysis.has_docker_compose else "❌")
        table.add_row("Tests", "✅" if analysis.has_tests else "❌")
        table.add_row("CI/CD", "✅" if analysis.has_ci_cd else "❌")
        table.add_row("README", "✅" if analysis.has_readme else "❌")
        table.add_row("Kubernetes", "✅" if analysis.has_k8s else "❌")
        table.add_row("Helm", "✅" if analysis.has_helm else "❌")
        table.add_row("Terraform", "✅" if analysis.has_terraform else "❌")
        table.add_row("Makefile", "✅" if analysis.has_makefile else "❌")
        table.add_row(".env.example", "✅" if analysis.has_env_example else "❌")
        
        console.print(table)

        if analysis.important_files:
            console.print("\n[bold]Important Files:[/bold]")
            console.print("  " + ", ".join(analysis.important_files))
        if analysis.ci_cd_files:
            console.print(f"[bold]CI/CD Configuration:[/bold] {', '.join(analysis.ci_cd_files)}")
        if analysis.components:
            console.print("\n[bold cyan]Detected Components:[/bold cyan]")
            for component in analysis.components:
                details = [component.stack.primary.value, component.package_manager]
                if component.framework != "unknown":
                    details.append(component.framework)
                if component.ports:
                    details.append(f"ports {', '.join(str(port) for port in component.ports)}")
                console.print(f"  • {component.name}/: {' · '.join(details)}")
                if component.important_files:
                    console.print(f"    Files: {', '.join(component.important_files)}")
                if component.source_dirs:
                    console.print(f"    Sources: {', '.join(f'{source}/' for source in component.source_dirs)}")
        
        # Readiness score
        score_color = "green" if readiness.score >= 80 else "yellow" if readiness.score >= 60 else "red"
        console.print(f"\n[bold]Deployment Readiness:[/bold] [{score_color}]{readiness.score}/100[/{score_color}] (Grade: {readiness.grade})")
        
        # Gaps
        if readiness.gaps:
            console.print("\n[yellow]Gaps:[/yellow]")
            for gap in readiness.gaps:
                console.print(f"  • {gap}")
        
        # Recommendations
        if readiness.recommendations:
            console.print("\n[cyan]Recommendations:[/cyan]")
            for rec in readiness.recommendations[:5]:
                console.print(f"  • {rec}")
        
        # Entry points
        if analysis.entry_points:
            console.print("\n[bold]Entry Points:[/bold]")
            for ep in analysis.entry_points:
                console.print(f"  • {ep}")
        
        # Dependencies
        if analysis.dependencies:
            console.print(f"\n[bold]Key Dependencies:[/bold] {', '.join(analysis.dependencies[:5])}")
