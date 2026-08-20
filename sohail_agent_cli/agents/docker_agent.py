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
        components: list[str] | None = None,
        compose: bool = True,
        compose_action: str = "keep",
        **kwargs: Any,
    ) -> AgentResult:
        """Execute Docker generation."""
        self.info(f"Generating Docker configuration for: {path}")
        
        # Analyze repository
        analysis = await self.analyze_repo(path)
        stack = analysis.stack.primary
        
        self.info(f"Detected stack: {stack.value}")
        
        selected_components = [
            component for component in analysis.components
            if not components or component.name in components
        ]
        if components and not selected_components:
            return AgentResult.failure("No requested components were found in the inspected repository")

        # Generate component Dockerfiles from each component's own inspection context.
        if selected_components:
            files_created: list[Path] = []
            files_skipped: list[Path] = []
            compose_services: list[tuple[str, int]] = []
            for component in selected_components:
                dockerfile, dockerignore, _ = self.generator.generate(
                    stack=component.stack,
                    project_path=component.path,
                    port=component.ports[0] if component.ports else None,
                    stack_context=component.stack,
                )
                for filename, content in (("Dockerfile", dockerfile), (".dockerignore", dockerignore)):
                    success, msg, is_dry_run = await self.write_file(
                        component.path / filename,
                        content,
                        overwrite=overwrite,
                    )
                    if success:
                        self.info(msg) if is_dry_run else self.success(msg)
                        files_created.append(component.path / filename)
                    else:
                        self.warning(msg)
                        files_skipped.append(component.path / filename)
                compose_services.append((component.name, component.ports[0] if component.ports else 3000))

            if compose and compose_action != "keep":
                compose_path = path / "docker-compose.yml"
                compose_content = self._component_compose(compose_services)
                success, msg, is_dry_run = await self.write_file(
                    compose_path,
                    compose_content,
                    overwrite=overwrite,
                )
                if success:
                    self.info(msg) if is_dry_run else self.success(msg)
                    files_created.append(compose_path)
                else:
                    self.warning(msg)
                    files_skipped.append(compose_path)
            return AgentResult(
                success=True,
                message=f"Docker configuration generated for {', '.join(component.name for component in selected_components)}",
                files_created=files_created,
                files_skipped=files_skipped,
                data={"components": [component.to_dict() for component in selected_components], "files_created": len(files_created), "files_skipped": len(files_skipped)},
            )

        # Generate root-level Docker files when no independently buildable components exist.
        dockerfile, dockerignore, docker_compose = self.generator.generate(
            stack=analysis.stack,
            project_path=path,
            port=port,
            stack_context=analysis.stack,
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

    @staticmethod
    def _component_compose(services: list[tuple[str, int]]) -> str:
        lines = ["services:"]
        for name, port in services:
            lines.extend([
                f"  {name}:",
                f"    build: ./{name}",
                f"    ports:",
                f"      - \"{port}:{port}\"",
            ])
        return "\n".join(lines) + "\n"
