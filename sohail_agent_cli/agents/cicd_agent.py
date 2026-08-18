"""CI/CD agent for generating GitHub Actions workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sohail_agent_cli.agents.base_agent import AgentResult, BaseAgent
from sohail_agent_cli.generators import CicdGenerator


class CicdAgent(BaseAgent):
    """Agent that generates CI/CD workflows."""
    
    def __init__(self, dry_run: bool = False, verbose: bool = False) -> None:
        super().__init__(
            name="cicd_agent",
            description="Generates GitHub Actions workflows",
            dry_run=dry_run,
            verbose=verbose,
        )
        self.generator = CicdGenerator()
    
    async def execute(
        self,
        path: Path,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute CI/CD generation."""
        self.info(f"Generating CI/CD workflows for: {path}")
        
        # Analyze repository
        analysis = await self.analyze_repo(path)
        stack = analysis.stack.primary
        
        self.info(f"Detected stack: {stack.value}")
        
        # Generate workflows
        ci, docker, release = self.generator.generate(
            stack=stack,
            project_path=path,
            has_docker=analysis.has_docker,
        )
        
        # Create .github/workflows directory
        workflows_dir = path / ".github" / "workflows"
        if not self.dry_run:
            workflows_dir.mkdir(parents=True, exist_ok=True)
        
        # Write files
        files_created = []
        files_skipped = []
        
        # ci.yml
        ci_path = workflows_dir / "ci.yml"
        success, msg, is_dry_run = await self.write_file(
            ci_path,
            ci,
            overwrite=overwrite,
        )
        if success:
            if is_dry_run:
                self.info(msg)
            else:
                self.success(msg)
            files_created.append(ci_path)
        else:
            self.warning(msg)
            files_skipped.append(ci_path)
        
        # docker.yml (only if Dockerfile exists)
        if docker:
            docker_path = workflows_dir / "docker.yml"
            success, msg, is_dry_run = await self.write_file(
                docker_path,
                docker,
                overwrite=overwrite,
            )
            if success:
                if is_dry_run:
                    self.info(msg)
                else:
                    self.success(msg)
                files_created.append(docker_path)
            else:
                self.warning(msg)
                files_skipped.append(docker_path)
        
        # release.yml
        release_path = workflows_dir / "release.yml"
        success, msg, is_dry_run = await self.write_file(
            release_path,
            release,
            overwrite=overwrite,
        )
        if success:
            if is_dry_run:
                self.info(msg)
            else:
                self.success(msg)
            files_created.append(release_path)
        else:
            self.warning(msg)
            files_skipped.append(release_path)
        
        return AgentResult.success(
            message=f"CI/CD workflows generated in .github/workflows/",
            files_created=files_created,
            data={
                "stack": stack.value,
                "files_created": len(files_created),
                "files_skipped": len(files_skipped),
            },
        )
