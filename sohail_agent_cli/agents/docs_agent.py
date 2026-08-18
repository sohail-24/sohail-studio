"""Documentation agent for generating README and deployment docs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sohail_agent_cli.agents.base_agent import AgentResult, BaseAgent
from sohail_agent_cli.generators import ReadmeGenerator
from sohail_agent_cli.providers import OllamaProvider, ProviderConfig


class DocsAgent(BaseAgent):
    """Agent that generates project documentation."""
    
    def __init__(
        self,
        dry_run: bool = False,
        verbose: bool = False,
        use_ollama: bool = False,
    ) -> None:
        super().__init__(
            name="docs_agent",
            description="Generates README.md and DEPLOYMENT.md",
            dry_run=dry_run,
            verbose=verbose,
        )
        self.generator = ReadmeGenerator()
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
        """Execute docs generation."""
        self.info(f"Generating documentation for: {path}")
        
        # Analyze repository
        analysis = await self.analyze_repo(path)
        
        # Generate docs
        readme, deployment = self.generator.generate(
            analysis=analysis,
            include_deployment=True,
        )
        
        # Optionally enhance with Ollama
        if self.use_ollama and self.ollama:
            readme = await self._enhance_with_ollama(readme, analysis)
        
        # Write files
        files_created = []
        files_skipped = []
        
        # README.md
        readme_path = path / "README.md"
        success, msg, is_dry_run = await self.write_file(
            readme_path,
            readme,
            overwrite=overwrite,
        )
        if success:
            if is_dry_run:
                self.info(msg)
            else:
                self.success(msg)
            files_created.append(readme_path)
        else:
            self.warning(msg)
            files_skipped.append(readme_path)
        
        # DEPLOYMENT.md
        if deployment:
            deployment_path = path / "DEPLOYMENT.md"
            success, msg, is_dry_run = await self.write_file(
                deployment_path,
                deployment,
                overwrite=overwrite,
            )
            if success:
                if is_dry_run:
                    self.info(msg)
                else:
                    self.success(msg)
                files_created.append(deployment_path)
            else:
                self.warning(msg)
                files_skipped.append(deployment_path)
        
        return AgentResult.success(
            message="Documentation generated",
            files_created=files_created,
            data={
                "files_created": len(files_created),
                "files_skipped": len(files_skipped),
                "ollama_enhanced": self.use_ollama,
            },
        )
    
    async def _enhance_with_ollama(self, readme: str, analysis) -> str:
        """Enhance README with Ollama."""
        if not self.ollama:
            return readme
        
        try:
            # Check if Ollama is available
            is_healthy = await self.ollama.health_check()
            if not is_healthy:
                self.warning("Ollama not available, using default README")
                return readme
            
            self.info("Enhancing README with Ollama...")
            
            from sohail_agent_cli.providers import GenerationRequest
            
            prompt = f"""Enhance this README for a {analysis.stack.primary.value} project.
Make it more professional and engaging while keeping the structure.

Current README:
{readme[:2000]}

Provide an improved version that:
1. Has a compelling description
2. Clear installation steps
3. Better feature highlights
4. Professional tone

Return only the improved README content."""
            
            request = GenerationRequest(
                prompt=prompt,
                temperature=0.7,
            )
            
            result = await self.ollama.generate(request)
            
            if result.success and result.text:
                self.success("README enhanced with Ollama")
                return result.text
            
        except Exception as e:
            self.warning(f"Ollama enhancement failed: {e}")
        
        return readme
