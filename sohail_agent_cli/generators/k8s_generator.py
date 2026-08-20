"""Kubernetes manifest generator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from sohail_agent_cli.analyzers import StackType


@dataclass
class K8sConfig:
    """Configuration for K8s generation."""

    app_name: str
    image: str
    port: int = 8000
    replicas: int = 1
    namespace: str = "default"
    service_type: str = "ClusterIP"
    ingress_enabled: bool = False
    ingress_host: str = ""
    health_path: str = "/"
    env_vars: dict[str, str] | None = None


class K8sGenerator:
    """Generator for Kubernetes manifests."""

    def generate(
        self,
        stack: StackType,
        project_path: Path,
        app_name: str | None = None,
        port: int | None = None,
    ) -> tuple[str, str, str]:
        """
        Generate K8s manifests.

        Returns:
            Tuple of (deployment, service, kustomization)
        """
        if app_name is None:
            app_name = self._slugify(project_path.name)

        default_port = self._get_default_port(stack)
        port = port or default_port

        config = K8sConfig(
            app_name=app_name,
            image=f"{app_name}:latest",
            port=port,
            health_path=self._get_health_path(stack),
            env_vars=self._get_env_vars(stack, project_path),
        )

        deployment = self._generate_deployment(config)
        service = self._generate_service(config)
        kustomization = self._generate_kustomization(config)

        return deployment, service, kustomization

    def _get_default_port(self, stack: StackType) -> int:
        """Get default port for stack."""
        ports = {
            StackType.DJANGO: 8000,
            StackType.FASTAPI: 8000,
            StackType.FLASK: 5000,
            StackType.NODE: 3000,
            StackType.REACT: 80,
            StackType.NEXTJS: 3000,
            StackType.VUE: 80,
            StackType.GO: 8080,
            StackType.RUST: 8080,
            StackType.PYTHON: 8000,
            StackType.JAVA: 8080,
        }
        return ports.get(stack, 8080)

    def _get_health_path(self, stack: StackType) -> str:
        """Get default health check path."""
        if stack in (StackType.REACT, StackType.VUE, StackType.NEXTJS):
            return "/"
        return "/"

    def _get_env_vars(self, stack: StackType, project_path: Path) -> dict[str, str]:
        """Infer useful environment variables based on stack and repo."""
        env = {}

        if stack in (
            StackType.PYTHON,
            StackType.DJANGO,
            StackType.FASTAPI,
            StackType.FLASK,
        ):
            env["PYTHONUNBUFFERED"] = "1"

        if stack == StackType.DJANGO:
            settings_module = self._detect_django_settings(project_path)
            if settings_module:
                env["DJANGO_SETTINGS_MODULE"] = settings_module

        if stack in (StackType.NODE, StackType.REACT, StackType.NEXTJS, StackType.VUE):
            env["NODE_ENV"] = "production"

        return env

    def _detect_django_settings(self, path: Path) -> str | None:
        """Try to detect Django settings module."""
        candidates = [
            "config.settings.prod",
            "config.settings.base",
            "config.settings",
            "project.settings",
            "app.settings",
        ]

        for candidate in candidates:
            parts = candidate.split(".")
            file_path = path.joinpath(*parts[:-1], f"{parts[-1]}.py")
            if file_path.exists():
                return candidate

        if (path / "config" / "settings").is_dir():
            if (path / "config" / "settings" / "prod.py").exists():
                return "config.settings.prod"
            if (path / "config" / "settings" / "base.py").exists():
                return "config.settings.base"

        return None

    def _slugify(self, text: str) -> str:
        """Convert text to k8s-friendly name."""
        return text.lower().replace(" ", "-").replace("_", "-")

    def _generate_deployment(self, config: K8sConfig) -> str:
        """Generate deployment.yaml."""
        env_list = [{"name": "PORT", "value": str(config.port)}]

        if config.env_vars:
            for key, value in config.env_vars.items():
                env_list.append({"name": key, "value": value})

        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": config.app_name,
                "namespace": config.namespace,
                "labels": {
                    "app": config.app_name,
                    "managed-by": "sohail-agent-cli",
                },
            },
            "spec": {
                "replicas": config.replicas,
                "selector": {
                    "matchLabels": {
                        "app": config.app_name,
                    },
                },
                "template": {
                    "metadata": {
                        "labels": {
                            "app": config.app_name,
                        },
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": config.app_name,
                                "image": config.image,
                                "imagePullPolicy": "IfNotPresent",
                                "ports": [
                                    {
                                        "containerPort": config.port,
                                    },
                                ],
                                "env": env_list,
                                "resources": {
                                    "requests": {
                                        "memory": "128Mi",
                                        "cpu": "100m",
                                    },
                                    "limits": {
                                        "memory": "512Mi",
                                        "cpu": "500m",
                                    },
                                },
                                "readinessProbe": {
                                    "httpGet": {
                                        "path": config.health_path,
                                        "port": config.port,
                                    },
                                    "initialDelaySeconds": 5,
                                    "periodSeconds": 10,
                                    "timeoutSeconds": 2,
                                    "failureThreshold": 3,
                                },
                                "livenessProbe": {
                                    "httpGet": {
                                        "path": config.health_path,
                                        "port": config.port,
                                    },
                                    "initialDelaySeconds": 15,
                                    "periodSeconds": 20,
                                    "timeoutSeconds": 2,
                                    "failureThreshold": 3,
                                },
                            },
                        ],
                    },
                },
            },
        }

        return yaml.dump(deployment, default_flow_style=False, sort_keys=False)

    def _generate_service(self, config: K8sConfig) -> str:
        """Generate service.yaml."""
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": config.app_name,
                "namespace": config.namespace,
                "labels": {
                    "app": config.app_name,
                    "managed-by": "sohail-agent-cli",
                },
            },
            "spec": {
                "type": config.service_type,
                "ports": [
                    {
                        "port": config.port,
                        "targetPort": config.port,
                        "protocol": "TCP",
                        "name": "http",
                    },
                ],
                "selector": {
                    "app": config.app_name,
                },
            },
        }

        return yaml.dump(service, default_flow_style=False, sort_keys=False)

    def _generate_kustomization(self, config: K8sConfig) -> str:
        """Generate kustomization.yaml."""
        resources = [
            "deployment.yaml",
            "service.yaml",
        ]

        if config.ingress_enabled:
            resources.append("ingress.yaml")

        kustomization = {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "namespace": config.namespace,
            "resources": resources,
            "commonLabels": {
                "app": config.app_name,
                "managed-by": "sohail-agent-cli",
            },
            "images": [
                {
                    "name": config.image,
                    "newTag": "latest",
                },
            ],
        }

        return yaml.dump(kustomization, default_flow_style=False, sort_keys=False)

    def generate_namespace(self, config: K8sConfig) -> str:
        """Generate namespace.yaml."""
        namespace = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": config.namespace,
                "labels": {
                    "managed-by": "sohail-agent-cli",
                },
            },
        }

        return yaml.dump(namespace, default_flow_style=False, sort_keys=False)

    def generate_ingress(self, config: K8sConfig) -> str:
        """Generate optional ingress.yaml."""
        host = config.ingress_host or f"{config.app_name}.example.com"

        ingress = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": config.app_name,
                "namespace": config.namespace,
                "annotations": {
                    "nginx.ingress.kubernetes.io/rewrite-target": "/",
                },
                "labels": {
                    "managed-by": "sohail-agent-cli",
                },
            },
            "spec": {
                "rules": [
                    {
                        "host": host,
                        "http": {
                            "paths": [
                                {
                                    "path": "/",
                                    "pathType": "Prefix",
                                    "backend": {
                                        "service": {
                                            "name": config.app_name,
                                            "port": {
                                                "number": config.port,
                                            },
                                        },
                                    },
                                },
                            ],
                        },
                    },
                ],
            },
        }

        return yaml.dump(ingress, default_flow_style=False, sort_keys=False)

    def generate_configmap(self, config: K8sConfig, data: dict[str, str]) -> str:
        """Generate optional configmap.yaml."""
        configmap = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": f"{config.app_name}-config",
                "namespace": config.namespace,
                "labels": {
                    "managed-by": "sohail-agent-cli",
                },
            },
            "data": data,
        }

        return yaml.dump(configmap, default_flow_style=False, sort_keys=False)
