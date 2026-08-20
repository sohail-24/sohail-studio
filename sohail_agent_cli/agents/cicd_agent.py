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
        action: str = "analyze",
        platform: str = "jenkins",
        **kwargs: Any,
    ) -> AgentResult:
        """Execute CI/CD generation."""
        self.info(f"Generating CI/CD workflows for: {path}")
        
        # Analyze repository
        analysis = await self.analyze_repo(path)
        stack = analysis.stack.primary
        
        self.info(f"Detected stack: {stack.value}")
        if analysis.ci_cd_files:
            self.info(f"Existing CI/CD configuration detected: {', '.join(analysis.ci_cd_files)}")
            if action in {"analyze", "keep"}:
                self.info("Existing CI/CD configuration preserved by user choice")
                return AgentResult.success(
                    message="Existing CI/CD configuration analyzed and preserved",
                    data={"ci_cd_files": analysis.ci_cd_files, "action": action, "platform": platform},
                )
        files_created: list[Path] = []
        files_skipped: list[Path] = []
        if platform in {"jenkins", "both"}:
            jenkins_path = path / "Jenkinsfile"
            success, msg, is_dry_run = await self.write_file(
                jenkins_path,
                self._generate_jenkinsfile(analysis),
                overwrite=overwrite,
            )
            if success:
                self.info(msg) if is_dry_run else self.success(msg)
                files_created.append(jenkins_path)
            else:
                self.warning(msg)
                files_skipped.append(jenkins_path)
            if platform == "jenkins":
                return AgentResult(
                    success=True,
                    message="Jenkins pipeline handled through the selected safety policy",
                    files_created=files_created,
                    files_skipped=files_skipped,
                    data={"platform": platform, "action": action, "files_created": len(files_created), "files_skipped": len(files_skipped)},
                )

        # Generate workflows
        ci, docker, release = self.generator.generate(
            stack=analysis.stack,
            project_path=path,
            has_docker=analysis.has_docker,
            stack_context=analysis.stack,
        )
        
        # Create .github/workflows directory
        workflows_dir = path / ".github" / "workflows"
        if not self.dry_run:
            workflows_dir.mkdir(parents=True, exist_ok=True)
        
        # Write files
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
                "platform": platform,
                "action": action,
                "files_created": len(files_created),
                "files_skipped": len(files_skipped),
            },
        )

    @staticmethod
    def _generate_jenkinsfile(analysis: Any) -> str:
        """Generate a reviewable Jenkins pipeline from detected components."""
        stages = ["        stage('Checkout') { steps { checkout scm } }"]
        for component in analysis.components:
            if component.package_manager == "npm":
                stages.append(
                    f"        stage('{component.name} install/build') {{ steps {{ dir('{component.name}') {{ sh 'npm ci'; "
                    + ("sh 'npm run build'" if "build" in component.scripts else "echo 'No build script detected'")
                    + " }} } }"
                )
        return "pipeline {\n  agent any\n  stages {\n" + "\n".join(stages) + "\n  }\n}\n"
