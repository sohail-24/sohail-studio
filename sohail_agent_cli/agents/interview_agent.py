"""Interview agent for generating interview notes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sohail_agent_cli.agents.base_agent import AgentResult, BaseAgent
from sohail_agent_cli.providers import OllamaProvider, ProviderConfig, GenerationRequest


class InterviewAgent(BaseAgent):
    """Agent that generates interview-ready project summaries."""
    
    def __init__(
        self,
        dry_run: bool = False,
        verbose: bool = False,
        use_ollama: bool = False,
    ) -> None:
        super().__init__(
            name="interview_agent",
            description="Generates INTERVIEW_NOTES.md with talking points",
            dry_run=dry_run,
            verbose=verbose,
        )
        self.use_ollama = use_ollama
        self.ollama: OllamaProvider | None = None
        
        if use_ollama:
            self.ollama = OllamaProvider(ProviderConfig())
    
    async def execute(
        self,
        path: Path,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute interview notes generation."""
        self.info(f"Generating interview notes for: {path}")
        
        # Analyze repository
        analysis = await self.analyze_repo(path)
        
        # Generate interview notes
        if self.use_ollama and self.ollama:
            notes = await self._generate_with_ollama(analysis)
        else:
            notes = self._generate_template(analysis)
        
        # Write file
        notes_path = path / "INTERVIEW_NOTES.md"
        success, msg, is_dry_run = await self.write_file(
            notes_path,
            notes,
            overwrite=overwrite,
        )

        files_created = []
        files_skipped = []

        if success:
            if is_dry_run:
                self.info(msg)
            else:
                self.success(msg)
            files_created.append(notes_path)
        else:
            self.warning(msg)
            files_skipped.append(notes_path)
        
        return AgentResult.success(
            message="Interview notes generated",
            files_created=files_created,
            data={
                "files_created": len(files_created),
                "files_skipped": len(files_skipped),
                "ollama_enhanced": self.use_ollama,
            },
        )
    
    def _generate_template(self, analysis) -> str:
        """Generate interview notes from template."""
        name = analysis.name
        stack = analysis.stack.primary.value
        deps = analysis.dependencies[:5]
        entry_points = analysis.entry_points[:2]
        
        lines = [
            f"# Interview Notes: {name}",
            "",
            "## 30-Second Pitch",
            "",
            f'"{name} is a {stack} project',
        ]
        
        if deps:
            lines[-1] += f" built with {', '.join(deps[:3])}"
        
        if analysis.has_docker:
            lines[-1] += ", containerized with Docker"
        
        if analysis.has_k8s:
            lines[-1] += ", deployed on Kubernetes"
        
        lines[-1] += '."'
        lines.append("")
        
        # Architecture
        lines.extend([
            "## Architecture",
            "",
            f"- **Stack:** {stack}",
            f"- **Entry Points:** {', '.join(entry_points) if entry_points else 'N/A'}",
        ])
        
        if analysis.has_docker:
            lines.append("- **Containerization:** Docker")
        if analysis.has_k8s:
            lines.append("- **Orchestration:** Kubernetes")
        if analysis.has_ci_cd:
            lines.append("- **CI/CD:** GitHub Actions")
        
        lines.append("")
        
        # Key talking points
        lines.extend([
            "## Key Talking Points",
            "",
            "### Technical Highlights",
            "",
        ])
        
        if analysis.has_docker:
            lines.extend([
                "- **Containerization:** Implemented Docker for consistent deployments",
                "  - Multi-stage builds for optimized images",
                "  - Proper layer caching for faster builds",
                "",
            ])
        
        if analysis.has_k8s:
            lines.extend([
                "- **Kubernetes:** Production-ready K8s manifests",
                "  - ConfigMaps and Secrets for configuration",
                "  - Resource limits and health checks",
                "  - Kustomize for environment management",
                "",
            ])
        
        if analysis.has_ci_cd:
            lines.extend([
                "- **CI/CD:** Automated pipeline with GitHub Actions",
                "  - Automated testing on every PR",
                "  - Docker image building and publishing",
                "  - Automated releases on tag push",
                "",
            ])
        
        # Common questions
        lines.extend([
            "## Common Interview Questions",
            "",
            "### Q: Tell me about this project",
            "",
            f'"{name} is a {stack} project that solves [problem]. '
            'It features [key features], and I implemented [technical highlights] '
            'to ensure [benefits]."',
            "",
            "### Q: Why did you choose this tech stack?",
            "",
            f'"I chose {stack} because [reasons]. '
            'It provides [benefits] and is well-suited for [use case]."',
            "",
            "### Q: How did you handle deployment?",
            "",
        ])
        
        if analysis.has_docker and analysis.has_k8s:
            lines.append(
                '"I containerized the application with Docker and deployed it on Kubernetes. '
                'This approach provides scalability, resilience, and consistency across '
                'environments. I also set up CI/CD pipelines to automate the deployment process."'
            )
        elif analysis.has_docker:
            lines.append(
                '"I containerized the application with Docker to ensure consistency '
                'across development and production environments. The Dockerfile uses '
                'multi-stage builds to create optimized production images."'
            )
        else:
            lines.append(
                '"The project is designed to be deployed [describe approach]. '
                'I focused on [deployment considerations]."'
            )
        
        lines.extend([
            "",
            "## Tips",
            "",
            "- Practice explaining this project out loud",
            "- Focus on problems solved and impact",
            "- Be ready to discuss technical decisions",
            "- Have specific examples ready",
            "",
        ])
        
        return "\n".join(lines)
    
    async def _generate_with_ollama(self, analysis) -> str:
        """Generate interview notes with Ollama."""
        if not self.ollama:
            return self._generate_template(analysis)
        
        try:
            is_healthy = await self.ollama.health_check()
            if not is_healthy:
                self.warning("Ollama not available, using template")
                return self._generate_template(analysis)
            
            self.info("Generating interview notes with Ollama...")
            
            prompt = f"""Generate professional interview notes for this project:

Project: {analysis.name}
Stack: {analysis.stack.primary.value}
Dependencies: {', '.join(analysis.dependencies[:5])}
Has Docker: {analysis.has_docker}
Has K8s: {analysis.has_k8s}
Has CI/CD: {analysis.has_ci_cd}

Create an INTERVIEW_NOTES.md with:
1. 30-second pitch
2. Architecture explanation
3. Technical highlights
4. Common interview questions and answers
5. Talking points

Make it professional and interview-ready."""
            
            request = GenerationRequest(
                prompt=prompt,
                temperature=0.7,
            )
            
            result = await self.ollama.generate(request)
            
            if result.success and result.text:
                self.success("Interview notes generated with Ollama")
                return result.text
            
        except Exception as e:
            self.warning(f"Ollama generation failed: {e}")
        
        return self._generate_template(analysis)
