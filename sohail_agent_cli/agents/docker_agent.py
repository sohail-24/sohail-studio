"""Project-Intelligence driven Docker generation agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.config import load_config
from core.storage.project_intelligence import ProjectIntelligenceRepository
from sohail_agent_cli.agents.base_agent import AgentResult, BaseAgent
from sohail_agent_cli.dockerize import (
    DockerContextBuilder,
    DockerContextError,
    DockerDecisionEngine,
    DockerDecisionError,
    DockerValidationError,
    validate_docker_result,
)
from sohail_agent_cli.providers import BaseProvider, OllamaProvider, ProviderConfig


class DockerAgent(BaseAgent):
    """Ask the local DevOps model, then execute and validate its decision."""

    def __init__(
        self,
        dry_run: bool = False,
        verbose: bool = False,
        *,
        repository: ProjectIntelligenceRepository | None = None,
        provider: BaseProvider | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(
            name="docker_agent",
            description="Builds Docker artifacts from persisted Project Intelligence",
            dry_run=dry_run,
            verbose=verbose,
        )
        settings_path = Path(__file__).resolve().parents[2] / "settings" / "default.json"
        config = load_config(settings_path)
        self.model = model or config.devops_model
        self.provider = provider or OllamaProvider(
            ProviderConfig(base_url=config.ollama_base_url, default_model=self.model)
        )
        self.repository = repository

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
        root = path.expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return AgentResult.failure(f"Target folder does not exist: {root}")
        repository = self.repository
        close_storage = False
        try:
            if repository is None:
                repository = ProjectIntelligenceRepository.from_env()
                close_storage = True
            context = DockerContextBuilder(repository).build(root, components)
            self.info(
                f"Docker context: {context.project['name']} · root {context.project['root_path']} · "
                f"selected {', '.join(context.project['selected_components'])} · "
                f"components {len(context.components)} · evidence {len(context.evidence)} · "
                f"model {self.model}"
            )
            decision = await DockerDecisionEngine(self.provider, self.model).decide(context)
            if decision.status != "ready":
                reason = decision.raw.get("reason") or "The DevOps model requires more repository evidence"
                return AgentResult.failure(f"Docker decision requires evidence: {reason}")
            if compose and not (decision.compose.get("services") or []):
                return AgentResult.failure("Docker decision did not define Compose services for the selected components")

            artifacts: dict[Path, str] = {}
            files_created: list[Path] = []
            files_skipped: list[Path] = []
            for component in decision.components:
                intelligence = next(item for item in context.components if item["name"] == component["name"])
                component_root = root / str(intelligence.get("path") or ".")
                dockerfile_path = component_root / "Dockerfile"
                dockerfile = DockerDecisionEngine.render_dockerfile(component)
                artifacts[dockerfile_path] = dockerfile
                await self._write_generated(
                    dockerfile_path, dockerfile, overwrite, files_created, files_skipped,
                )
                if dockerfile_path not in files_created and dockerfile_path.exists():
                    artifacts[dockerfile_path] = dockerfile_path.read_text(encoding="utf-8")
                dockerignore_path = component_root / ".dockerignore"
                dockerignore = DockerDecisionEngine.render_dockerignore()
                artifacts[dockerignore_path] = dockerignore
                await self._write_generated(
                    dockerignore_path, dockerignore, overwrite, files_created, files_skipped,
                )
                if dockerignore_path not in files_created and dockerignore_path.exists():
                    artifacts[dockerignore_path] = dockerignore_path.read_text(encoding="utf-8")

            compose_path = root / "docker-compose.yml"
            compose_exists = compose_path.exists()
            generate_compose = compose and (
                not compose_exists or compose_action in {"improve", "generate"}
            )
            if generate_compose:
                compose_content = DockerDecisionEngine.render_compose(decision)
                artifacts[compose_path] = compose_content
                await self._write_generated(
                    compose_path, compose_content, overwrite, files_created, files_skipped,
                )
                if compose_path not in files_created and compose_path.exists():
                    artifacts[compose_path] = compose_path.read_text(encoding="utf-8")
            elif compose and compose_exists:
                artifacts[compose_path] = compose_path.read_text(encoding="utf-8")

            validation = validate_docker_result(
                root,
                context,
                decision,
                artifacts,
                compose_expected=generate_compose,
            )
            for created in files_created:
                self.success(f"{'Would write' if self.dry_run else 'Wrote'} {created}")
            for skipped in files_skipped:
                self.warning(f"Skipped existing file (use overwrite): {skipped}")
            return AgentResult(
                success=True,
                message="Docker artifacts validated successfully",
                files_created=files_created,
                files_skipped=files_skipped,
                data={
                    "model": self.model,
                    "context": context.to_dict(),
                    "decision": decision.raw,
                    "validation": validation,
                    "files_created": len(files_created),
                    "files_skipped": len(files_skipped),
                },
            )
        except (DockerContextError, DockerDecisionError, DockerValidationError) as exc:
            return AgentResult.failure(str(exc))
        finally:
            if close_storage and repository is not None:
                repository.storage.close()

    async def _write_generated(
        self,
        path: Path,
        content: str,
        overwrite: bool,
        files_created: list[Path],
        files_skipped: list[Path],
    ) -> None:
        success, _message, _is_dry_run = await self.write_file(path, content, overwrite=overwrite)
        if success:
            files_created.append(path)
        else:
            files_skipped.append(path)
