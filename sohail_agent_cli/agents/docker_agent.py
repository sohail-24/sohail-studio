"""Docker agent for generating Docker configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sohail_agent_cli.agents.base_agent import AgentResult, BaseAgent
from sohail_agent_cli.generators import DockerGenerator


class DockerAgent(BaseAgent):
    """Agent that generates Docker configuration."""
    
    def __init__(self, dry_run: bool = False, verbose: bool = False) -> None:
        super().__init__(
            name="docker_agent",
            description="Generates Dockerfile, .dockerignore, and docker-compose.yml",
            dry_run=dry_run,
            verbose=verbose,
        )
        self.generator = DockerGenerator()
    
    async def execute(
        self,
        path: Path,
        port: int | None = None,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute Docker generation."""
        self.info(f"Generating Docker configuration for: {path}")
        
        # Analyze repository
        analysis = await self.analyze_repo(path)
        stack = analysis.stack.primary
        
        self.info(f"Detected stack: {stack.value}")
        
        # Generate Docker files
        dockerfile, dockerignore, docker_compose = self.generator.generate(
            stack=stack,
            project_path=path,
            port=port,
        )
        
        # Write files
        files_created = []
        files_skipped = []
        
        # Dockerfile
        dockerfile_path = path / "Dockerfile"
        success, msg, is_dry_run = await self.write_file(
            dockerfile_path,
            dockerfile,
            overwrite=overwrite,
        )
        if success:
            if is_dry_run:
                self.info(msg)
            else:
                self.success(msg)
            files_created.append(dockerfile_path)
        else:
            self.warning(msg)
            files_skipped.append(dockerfile_path)
        
        # .dockerignore
        dockerignore_path = path / ".dockerignore"
        success, msg, is_dry_run = await self.write_file(
            dockerignore_path,
            dockerignore,
            overwrite=overwrite,
        )
        if success:
            if is_dry_run:
                self.info(msg)
            else:
                self.success(msg)
            files_created.append(dockerignore_path)
        else:
            self.warning(msg)
            files_skipped.append(dockerignore_path)
        
        # docker-compose.yml
        compose_path = path / "docker-compose.yml"
        success, msg, is_dry_run = await self.write_file(
            compose_path,
            docker_compose,
            overwrite=overwrite,
        )
        if success:
            if is_dry_run:
                self.info(msg)
            else:
                self.success(msg)
            files_created.append(compose_path)
        else:
            self.warning(msg)
            files_skipped.append(compose_path)
        
        return AgentResult.success(
            message=f"Docker configuration generated for {stack.value}",
            files_created=files_created,
            data={
                "stack": stack.value,
                "files_created": len(files_created),
                "files_skipped": len(files_skipped),
            },
        )
