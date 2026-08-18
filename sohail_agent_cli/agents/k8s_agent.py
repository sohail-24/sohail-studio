"""Kubernetes agent for generating K8s manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sohail_agent_cli.agents.base_agent import AgentResult, BaseAgent
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
        stack = analysis.stack.primary

        self.info(f"Detected stack: {stack.value}")

        # Optional flags
        namespace = kwargs.get("namespace", "default")
        replicas = kwargs.get("replicas", 1)
        ingress_enabled = kwargs.get("ingress", False)
        ingress_host = kwargs.get("host", "")

        # App name
        resolved_app_name = app_name or path.name.lower().replace(" ", "-").replace("_", "-")

        # Port
        resolved_port = port or self.generator._get_default_port(stack)

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
            env_vars=self.generator._get_env_vars(stack, path),
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
        