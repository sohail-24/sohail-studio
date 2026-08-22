"""DevOps-model decision and evidence-bound Docker artifact rendering."""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from typing import Any

from sohail_agent_cli.providers import GenerationRequest, OllamaProvider

from .context_builder import DockerContext


class DockerDecisionError(ValueError):
    """Raised when Ollama does not return a safe structured decision."""


@dataclass(frozen=True)
class DockerDecision:
    status: str
    components: list[dict[str, Any]]
    compose: dict[str, Any]
    raw: dict[str, Any]


SYSTEM_PROMPT = """You are Sohail Studio's local DevOps engineering decision engine.
You receive focused Project Intelligence from a real local repository.
The user message contains a FOCUSED_DOCKER_PROJECT_INTELLIGENCE object. If it
contains components or evidence, treat those facts as supplied; do not claim
that the object is absent. If a safe decision is impossible, name the exact
missing or conflicting fact and its source.
Do not invent facts. Do not assume missing files, frameworks, runtimes, ports,
commands, databases, or services. When evidence is missing or contradictory,
return status NEEDS_EVIDENCE with a concise reason. Return JSON only using:
{"status":"ready|NEEDS_EVIDENCE","reason":"...","components":[],"compose":{}}.
Each component decision must use the supplied component name and evidence.
For ready decisions, each component should include base_image, working_directory,
package_manager, install_command, optional build_command, start_command, and
port, including the supplied component name. The compose object must contain a
services array. Compose services must include name, component, build_context,
port, and target_port and may include only evidence-supported environment or
dependency references.
Return a decision, not file contents and do not modify files."""


class DockerDecisionEngine:
    """Ask the configured local DevOps model and reject unsupported claims."""

    def __init__(self, provider: OllamaProvider, model: str) -> None:
        self.provider = provider
        self.model = model

    async def decide(self, context: DockerContext) -> DockerDecision:
        result = await self.provider.generate(
            GenerationRequest(
                prompt=context.prompt(),
                system=SYSTEM_PROMPT,
                model=self.model,
                temperature=0,
                options={
                    "format": "json",
                    "num_ctx": 16384,
                    "num_predict": 1024,
                },
                think=False,
            )
        )
        if result.error:
            raise DockerDecisionError(result.error)
        try:
            payload = self._parse_json(result.text)
        except (TypeError, ValueError) as exc:
            raise DockerDecisionError(
                f"Ollama returned an invalid Docker decision schema: {exc}"
            ) from exc
        decision = DockerDecision(
            status=payload["status"],
            components=payload["components"],
            compose=payload["compose"],
            raw=payload,
        )
        if decision.status == "NEEDS_EVIDENCE":
            return decision
        self._validate_decision(decision, context)
        return decision

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        value = text.strip()
        if value.startswith("```"):
            value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE | re.DOTALL).strip()
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"response is not valid JSON: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise ValueError("decision must be a JSON object")
        required = {"status", "reason", "components", "compose"}
        missing = sorted(required - data.keys())
        if missing:
            raise ValueError(f"missing required field(s): {', '.join(missing)}")
        unexpected = sorted(set(data) - required)
        if unexpected:
            raise ValueError(f"unexpected field(s): {', '.join(unexpected)}")
        if data["status"] not in {"ready", "NEEDS_EVIDENCE"}:
            raise ValueError("status must be 'ready' or 'NEEDS_EVIDENCE'")
        if not isinstance(data["reason"], str) or not data["reason"].strip():
            raise ValueError("reason must be a non-empty string")
        if not isinstance(data["components"], list):
            raise ValueError("components must be a list")
        if any(not isinstance(item, dict) for item in data["components"]):
            raise ValueError("components items must be objects")
        if not isinstance(data["compose"], dict):
            raise ValueError("compose must be an object")
        return data

    @staticmethod
    def _commands_for(component: dict[str, Any], name: str) -> set[str]:
        return {
            str(item.get("command")) for item in component.get("commands", [])
            if item.get("name") == name and item.get("command")
        }

    def _validate_decision(self, decision: DockerDecision, context: DockerContext) -> None:
        expected = {str(item["name"]): item for item in context.components}
        actual = {str(item.get("name")): item for item in decision.components}
        if set(actual) != set(expected):
            raise DockerDecisionError("Ollama returned Docker components different from the selected evidence")
        for name, component in actual.items():
            source = expected[name]
            package_manager = source.get("package_manager")
            if package_manager and component.get("package_manager") not in {None, package_manager}:
                raise DockerDecisionError(f"Docker decision changed the detected package manager for {name}")
            if any(
                item.get("conflict") and item.get("port_type") == "application"
                for item in source.get("ports", [])
            ):
                raise DockerDecisionError(f"Port evidence conflicts for {name}; Docker decision requires confirmation")
            ports = [item for item in source.get("ports", []) if item.get("port_type") == "application" and not item.get("conflict")]
            requested_port = component.get("port")
            if ports and requested_port is None:
                raise DockerDecisionError(f"Docker decision omitted the detected application port for {name}")
            if requested_port is not None and not ports:
                raise DockerDecisionError(f"Docker decision invented a port for {name}; no port evidence exists")
            if requested_port is not None and ports and requested_port not in {item.get("port") for item in ports}:
                raise DockerDecisionError(f"Docker decision invented port {requested_port} for {name}")
            for command_name, key in (("start", "start_command"), ("build", "build_command"), ("dev", "dev_command")):
                command = component.get(key)
                if not command:
                    continue
                command_text = " ".join(command) if isinstance(command, list) else str(command)
                allowed = self._commands_for(source, command_name)
                if allowed:
                    manager = str(source.get("package_manager") or "npm")
                    allowed |= {
                        f"{manager} run {command_name}",
                        f"{manager} {command_name}" if command_name == "start" and manager == "npm" else "",
                    }
                    allowed.discard("")
                if command_text not in allowed:
                    raise DockerDecisionError(f"Docker decision invented {command_name} command for {name}")
            runtime = next((item for item in source.get("runtimes", []) if item.get("runtime") == "Node.js"), None)
            base_image = str(component.get("base_image", ""))
            if base_image.startswith("node:") and runtime is None:
                raise DockerDecisionError(f"Node.js runtime evidence is missing for {name}; confirmation is required")
            if runtime and base_image.startswith("node:"):
                detected = re.search(r"\d+", str(runtime.get("version", "")))
                selected = re.search(r"node:(\d+)", base_image)
                if detected and selected and detected.group(0) != selected.group(1):
                    raise DockerDecisionError(f"Docker decision changed the detected Node.js runtime for {name}")
        services = decision.compose.get("services") or []
        if not isinstance(services, list):
            raise DockerDecisionError("Docker Compose services must be a list")
        for service in services:
            component_name = service.get("component")
            if component_name not in expected or service.get("name") != component_name:
                raise DockerDecisionError("Docker decision invented a Compose service")
            expected_path = str(expected[component_name].get("path") or ".")
            expected_context = "." if expected_path == "." else f"./{expected_path}"
            if service.get("build_context") not in {None, expected_context}:
                raise DockerDecisionError("Docker decision changed the evidence-backed Compose build context")
            component_ports = [
                item for item in expected[component_name].get("ports", [])
                if item.get("port_type") == "application" and not item.get("conflict")
            ]
            service_port = service.get("port")
            target_port = service.get("target_port", service_port)
            if component_ports and (service_port, target_port) not in {
                (item.get("port"), item.get("port")) for item in component_ports
            }:
                raise DockerDecisionError("Docker Compose port is inconsistent with Project Intelligence")
            allowed_environment = {
                str(item.get("name") or item.get("key"))
                for item in expected[component_name].get("environment", [])
            }
            if any(str(item) not in allowed_environment for item in service.get("environment") or []):
                raise DockerDecisionError("Docker decision invented a Compose environment variable")
            if any(item not in expected for item in service.get("depends_on") or []):
                raise DockerDecisionError("Docker decision invented a Compose dependency")

    @staticmethod
    def render_dockerfile(component: dict[str, Any]) -> str:
        base_image = str(component.get("base_image") or "")
        if not base_image:
            raise DockerDecisionError(f"Docker decision did not provide a base image for {component.get('name')}")
        workdir = str(component.get("working_directory") or "/app")
        install = component.get("install_command")
        build = component.get("build_command")
        start = component.get("start_command")
        lines = [f"FROM {base_image}", f"WORKDIR {workdir}"]
        if install:
            lines.extend(["COPY package*.json ./", f"RUN {install}"])
        else:
            raise DockerDecisionError(f"Docker decision did not provide an install command for {component.get('name')}")
        lines.append("COPY . .")
        if build:
            lines.append(f"RUN {build}")
        if component.get("port") is not None:
            lines.append(f"EXPOSE {int(component['port'])}")
        if start:
            command = start if isinstance(start, list) else shlex.split(str(start))
            lines.append("CMD " + json.dumps(command))
        return "\n".join(lines) + "\n"

    @staticmethod
    def render_dockerignore() -> str:
        return "node_modules\n.venv\n__pycache__\n.git\n.env\n.env.*\n!.env.example\n"

    @staticmethod
    def render_compose(decision: DockerDecision) -> str:
        lines = ["services:"]
        for service in decision.compose.get("services") or []:
            name = str(service["name"])
            component = str(service["component"])
            build_context = str(service.get("build_context") or f"./{component}")
            lines.extend([f"  {name}:", f"    build: {build_context}"])
            port = service.get("port")
            target = service.get("target_port", port)
            if port is not None and target is not None:
                lines.extend(["    ports:", f'      - "{int(port)}:{int(target)}"'])
            environment = service.get("environment") or []
            if environment:
                lines.append("    environment:")
                for variable in environment:
                    lines.append(f"      - {variable}")
            depends_on = service.get("depends_on") or []
            if depends_on:
                lines.append("    depends_on:")
                lines.extend(f"      - {dependency}" for dependency in depends_on)
        return "\n".join(lines) + "\n"
