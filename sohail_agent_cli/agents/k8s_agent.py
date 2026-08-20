"""Kubernetes agent for generating K8s manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sohail_agent_cli.agents.base_agent import AgentResult, BaseAgent
from sohail_agent_cli.analyzers import StackType
from sohail_agent_cli.generators import K8sConfig, K8sGenerator


class K8sAgent(BaseAgent):
    """Agent that generates Kubernetes manifests."""

    def __init__(self, dry_run: bool = False, verbose: bool = False) -> None:
        super().__init__(
            name="k8s_agent",
            description="Generates Kubernetes deployment, service, kustomization, and optional ingress",
            dry_run=dry_run,
            verbose=verbose,
        )
        self.generator = K8sGenerator()

    async def execute(
        self,
        path: Path,
        app_name: str | None = None,
        port: int | None = None,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute K8s generation."""
        self.info(f"Generating Kubernetes manifests for: {path}")

        # Analyze repository
        analysis = await self.analyze_repo(path)
        stack_context = analysis.stack
        stack = stack_context.primary

        self.info(f"Detected stack: {stack.value}")

        # Optional flags
        namespace = kwargs.get("namespace", "default")
        replicas = kwargs.get("replicas", 1)
        ingress_enabled = kwargs.get("ingress", False)
        ingress_host = kwargs.get("host", "")
        selected_names = kwargs.get("components") or []
        selected_components = [component for component in stack_context_components(analysis) if not selected_names or component.name in selected_names]
        if selected_names and not selected_components:
            return AgentResult.failure("No requested components were found in the inspected repository")

        if selected_components:
            k8s_dir = path / "k8s"
            if not self.dry_run:
                k8s_dir.mkdir(exist_ok=True)
            files_created: list[Path] = []
            files_skipped: list[Path] = []
            for component in selected_components:
                component_port = port or (component.ports[0] if component.ports else self.generator._get_default_port(component.stack.primary))
                env_vars = self.generator._get_env_vars(component.stack.primary, component.path)
                config = K8sConfig(
                    app_name=component.name.lower().replace("_", "-"),
                    image=f"{component.name.lower()}:latest",
                    port=component_port,
                    replicas=replicas,
                    namespace=namespace,
                    ingress_enabled=False,
                    ingress_host="",
                    health_path=self.generator._get_health_path(component.stack.primary),
                    env_vars=env_vars,
                )
                manifests = {
                    f"{component.name}-deployment.yaml": self.generator._generate_deployment(config),
                    f"{component.name}-service.yaml": self.generator._generate_service(config),
                }
                for filename, content in manifests.items():
                    success, msg, is_dry_run = await self.write_file(k8s_dir / filename, content, overwrite=overwrite)
                    if success:
                        self.info(msg) if is_dry_run else self.success(msg)
                        files_created.append(k8s_dir / filename)
                    else:
                        self.warning(msg)
                        files_skipped.append(k8s_dir / filename)
            return AgentResult(
                success=True,
                message="Kubernetes manifests generated for selected components",
                files_created=files_created,
                files_skipped=files_skipped,
                data={"components": [component.to_dict() for component in selected_components], "files_created": len(files_created), "files_skipped": len(files_skipped)},
            )

        # App name
        resolved_app_name = app_name or path.name.lower().replace(" ", "-").replace("_", "-")

        # Port
        resolved_port = port or stack_context.port or self.generator._get_default_port(stack)
        env_vars = self.generator._get_env_vars(stack, path)
        if stack == StackType.JAVA:
            env_vars["SERVER_PORT"] = str(resolved_port)

        # Build config once
        config = K8sConfig(
            app_name=resolved_app_name,
            image=f"{resolved_app_name}:latest",
            port=resolved_port,
            replicas=replicas,
            namespace=namespace,
            ingress_enabled=ingress_enabled,
            ingress_host=ingress_host,
            health_path=self.generator._get_health_path(stack),
            env_vars=env_vars,
        )

        # Generate manifests
        deployment = self.generator._generate_deployment(config)
        service = self.generator._generate_service(config)
        kustomization = self.generator._generate_kustomization(config)
        namespace_yaml = self.generator.generate_namespace(config)

        ingress_yaml = None
        if ingress_enabled:
            ingress_yaml = self.generator.generate_ingress(config)

        # Create k8s directory
        k8s_dir = path / "k8s"
        if not self.dry_run:
            k8s_dir.mkdir(exist_ok=True)

        files_created = []
        files_skipped = []

        async def write_manifest(file_path: Path, content: str) -> None:
            success, msg, is_dry_run = await self.write_file(
                file_path,
                content,
                overwrite=overwrite,
            )
            if success:
                if is_dry_run:
                    self.info(msg)
                else:
                    self.success(msg)
                files_created.append(file_path)
            else:
                self.warning(msg)
                files_skipped.append(file_path)

        # Core manifests
        await write_manifest(k8s_dir / "deployment.yaml", deployment)
        await write_manifest(k8s_dir / "service.yaml", service)
        await write_manifest(k8s_dir / "kustomization.yaml", kustomization)
        await write_manifest(k8s_dir / "namespace.yaml", namespace_yaml)

        # Optional ingress
        if ingress_yaml:
            await write_manifest(k8s_dir / "ingress.yaml", ingress_yaml)

        return AgentResult.success(
            message="Kubernetes manifests generated in k8s/",
            files_created=files_created,
            data={
                "stack": stack.value,
                "app_name": resolved_app_name,
                "namespace": namespace,
                "replicas": replicas,
                "ingress_enabled": ingress_enabled,
                "files_created": len(files_created),
                "files_skipped": len(files_skipped),
            },
        )


def stack_context_components(analysis: Any) -> list[Any]:
    """Keep component selection local to the analyzed shared context."""
    return list(getattr(analysis, "components", []))
        
