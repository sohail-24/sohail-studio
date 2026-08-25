"""DevOps-model decision and evidence-bound Docker artifact rendering."""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from typing import Any, Callable

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
    repair_attempted: bool = False


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
The reason field is mandatory and MUST be a non-empty explanation grounded in
the supplied evidence. Never return an empty string, null, or omit reason.
For example, a safe evidence outcome is:
{"status":"NEEDS_EVIDENCE","reason":"backend has no evidence-backed production start command.","components":[],"compose":{}}.
Each component decision must use the supplied component name and evidence.
For ready decisions, each component should include base_image, working_directory,
package_manager, install_command, optional build_command, start_command, and
port, including the supplied component name. The compose object must contain a
services array. Compose services must include name, component, build_context,
port, and target_port and may include only evidence-supported environment or
dependency references. The component's start_command must match the exact
command from its literal start script. A dev or preview script is not production
start evidence and must never be selected as start_command. If no explicit
production start strategy exists for a component, return NEEDS_EVIDENCE.
When the supplied context contains a verified pattern for a component, include
that pattern's pattern_id as deployment_pattern. A static_frontend pattern
permits a safe static-content server command after the exact build command and
port remain evidence-bound; do not treat the pattern as permission to invent
runtime versions, ports, environment variables, or dependencies.
The supplied artifact_plan is authoritative: generate or upgrade only those
artifacts, preserve keep actions, and exclude skip actions. Do not emit decisions
for skipped components.
Return a decision, not file contents and do not modify files."""

REPAIR_SYSTEM_PROMPT = """You repair one invalid JSON Docker decision for Sohail Studio.
Return JSON only. Preserve all valid fields and values from the original response.
Repair schema/formatting only; do not add project facts, runtime versions, ports,
commands, services, dependencies, or environment variables. Every response must
contain status, reason, components, and compose. reason must be a concise,
non-empty string grounded only in the original response or the supplied
validation error. If the original response cannot safely be repaired, return:
{"status":"NEEDS_EVIDENCE","reason":"The Docker decision could not be safely repaired from the supplied evidence.","components":[],"compose":{}}."""


class DockerDecisionEngine:
    """Ask the configured local DevOps model and reject unsupported claims."""

    def __init__(
        self,
        provider: OllamaProvider,
        model: str,
        *,
        on_repair: Callable[[], None] | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.on_repair = on_repair

    async def decide(self, context: DockerContext) -> DockerDecision:
        preflight = self._preflight(context)
        if preflight is not None:
            return preflight
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
        repair_attempted = False
        try:
            payload = self._parse_json(result.text)
        except (TypeError, ValueError) as exc:
            repair_attempted = True
            if self.on_repair is not None:
                self.on_repair()
            try:
                repaired = await self.provider.generate(
                    self._repair_request(result.text, str(exc), context.prompt())
                )
                if repaired.error:
                    raise DockerDecisionError(repaired.error)
                payload = self._parse_json(repaired.text)
            except (TypeError, ValueError, DockerDecisionError) as repair_exc:
                raise DockerDecisionError(
                    "Ollama returned an invalid Docker decision schema after one "
                    f"bounded repair attempt: {repair_exc}"
                ) from repair_exc
        decision = DockerDecision(
            status=payload["status"],
            components=payload["components"],
            compose=payload["compose"],
            raw=payload,
            repair_attempted=repair_attempted,
        )
        if decision.status == "NEEDS_EVIDENCE":
            return decision
        try:
            self._validate_decision(decision, context)
        except DockerDecisionError as exc:
            # A schema-valid model response is still only a proposal. Any
            # unsupported infrastructure claim becomes an explicit evidence
            # request before the rendering layer can see the decision.
            reason = str(exc)
            return DockerDecision(
                status="NEEDS_EVIDENCE",
                components=[],
                compose={},
                raw={
                    "status": "NEEDS_EVIDENCE",
                    "reason": reason,
                    "components": [],
                    "compose": {},
                },
                repair_attempted=repair_attempted,
            )
        return decision

    def _repair_request(
        self,
        response: str,
        error: str,
        context_prompt: str,
    ) -> GenerationRequest:
        """Create the single bounded repair request without repository access."""
        original = str(response or "")[:12000]
        supplied_context = str(context_prompt or "")[:12000]
        prompt = (
            "Repair only this structured Docker decision. Do not request or infer "
            "new repository evidence.\n\n"
            f"VALIDATION_ERROR: {error}\n\n"
            "REQUIRED_SHAPE:\n"
            '{"status":"ready|NEEDS_EVIDENCE","reason":"non-empty explanation",'
            '"components":[],"compose":{}}\n\n'
            f"ORIGINAL_RESPONSE:\n{original}\n\n"
            f"SUPPLIED_CONTEXT_FOR_GROUNDING_ONLY:\n{supplied_context}"
        )
        return GenerationRequest(
            prompt=prompt,
            system=REPAIR_SYSTEM_PROMPT,
            model=self.model,
            temperature=0,
            options={
                "format": "json",
                "num_ctx": 16384,
                "num_predict": 1024,
            },
            think=False,
        )

    @staticmethod
    def _preflight(context: DockerContext) -> DockerDecision | None:
        """Stop before Ollama when production-start evidence is absent."""
        patterns = {
            str(item.get("component")): item
            for item in context.verified_patterns
            if item.get("origin") == "VERIFIED_INFERENCE"
        }
        missing = [
            str(component.get("name"))
            for component in context.components
            if not any(
                item.get("name") == "start" and str(item.get("command") or "").strip()
                for item in component.get("commands", [])
            ) and str(component.get("name")) not in patterns
        ]
        if not missing:
            return None
        names = ", ".join(missing)
        reason = (
            f"{names} lacks evidence-backed production start command; "
            "development and preview commands cannot be used as Docker start commands"
        )
        return DockerDecision(
            status="NEEDS_EVIDENCE",
            components=[],
            compose={},
            raw={
                "status": "NEEDS_EVIDENCE",
                "reason": reason,
                "components": [],
                "compose": {},
            },
        )

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
            pattern = next(
                (
                    item for item in context.verified_patterns
                    if item.get("component") == name
                    and item.get("origin") == "VERIFIED_INFERENCE"
                ),
                None,
            )
            if pattern is not None:
                if component.get("deployment_pattern") != pattern.get("pattern_id"):
                    raise DockerDecisionError(
                        f"Docker decision did not preserve the verified pattern for {name}"
                    )
                self._validate_verified_pattern(name, component, source, pattern)
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
                if command_name == "start" and pattern is not None:
                    continue
                if allowed:
                    manager = str(source.get("package_manager") or "npm")
                    allowed |= {
                        f"{manager} run {command_name}",
                        f"{manager} {command_name}" if command_name == "start" and manager == "npm" else "",
                    }
                    allowed.discard("")
                if command_text not in allowed:
                    raise DockerDecisionError(f"Docker decision invented {command_name} command for {name}")
            self._validate_runtime(name, component, source)
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
    def _validate_verified_pattern(
        name: str,
        component: dict[str, Any],
        source: dict[str, Any],
        pattern: dict[str, Any],
    ) -> None:
        """Validate model details against a deterministic pattern policy."""
        if pattern.get("category") != "static_frontend":
            raise DockerDecisionError(f"Unsupported verified pattern for {name}")
        policy = pattern.get("policy") or {}
        build_command = component.get("build_command")
        build_text = " ".join(build_command) if isinstance(build_command, list) else str(build_command or "")
        if build_text != str(policy.get("build_command") or ""):
            raise DockerDecisionError(f"Docker decision changed the verified build command for {name}")
        start = component.get("start_command")
        start_text = " ".join(start) if isinstance(start, list) else str(start or "")
        if not start_text.strip() or any(token in start_text for token in (";", "&&", "||", "|", "`", "$")):
            raise DockerDecisionError(f"Docker decision supplied an unsafe static server command for {name}")
        tokens = start if isinstance(start, list) else shlex.split(start_text)
        if not tokens:
            raise DockerDecisionError(f"Docker decision supplied an empty static server command for {name}")
        if any(".." in str(token) or str(token).startswith("/") for token in tokens):
            raise DockerDecisionError(f"Docker decision supplied a traversal-shaped static serving path for {name}")
        family = " ".join(str(token) for token in tokens[:2])
        allowed_families = set(policy.get("allowed_start_command_families") or [])
        if str(tokens[0]) not in allowed_families and family not in allowed_families:
            raise DockerDecisionError(f"Docker decision supplied an unsupported static server for {name}")
        expected_port = policy.get("port")
        if component.get("port") != expected_port:
            raise DockerDecisionError(f"Docker decision changed the verified application port for {name}")
        if not any(
            item.get("port") == expected_port
            and item.get("port_type") == "application"
            and not item.get("conflict")
            for item in source.get("ports", [])
        ):
            raise DockerDecisionError(f"Verified pattern port evidence is no longer available for {name}")

    @staticmethod
    def _validate_runtime(name: str, component: dict[str, Any], source: dict[str, Any]) -> None:
        """Require every Docker runtime claim to be supported by evidence.

        In particular, a Node base image is never selected from model
        knowledge, dependency versions, machine state, README assumptions, or
        an internal default. Only an explicit Project Intelligence runtime
        fact can authorize its major version.
        """
        runtimes = [item for item in source.get("runtimes", []) if item.get("runtime") == "Node.js"]
        base_image = str(component.get("base_image", ""))
        if not base_image:
            raise DockerDecisionError(f"Docker decision did not provide a base image for {name}")
        if not base_image.startswith("node:"):
            return
        runtime = next(
            (
                item for item in runtimes
                if re.fullmatch(r"v?\d+(?:\.\d+){0,2}", str(item.get("version", "")).strip())
            ),
            None,
        )
        if runtime is None:
            if runtimes:
                candidate = runtimes[0]
                version = str(candidate.get("version", "")).strip() or "unknown"
                source_file = str(candidate.get("source_file", "unknown source"))
                raise DockerDecisionError(
                    "An exact Node.js runtime version is required to select a Node base image, "
                    f"but Project Intelligence only contains the non-authoritative range "
                    f"'Node.js {version}' from {source_file}."
                )
            raise DockerDecisionError(
                f"An exact Node.js runtime version is required for {name}; "
                "Project Intelligence contains no authoritative Node.js runtime evidence."
            )
        runtime_version = str(runtime.get("version", "")).strip()
        detected = re.fullmatch(r"v?(\d+(?:\.\d+){0,2})", runtime_version)
        selected = re.fullmatch(r"node:(\d+(?:\.\d+){0,2})(?:-.+)?", base_image)
        if not detected:
            raise DockerDecisionError(f"Node.js runtime evidence is not an explicit version for {name}; confirmation is required")
        if not selected or detected.group(1) != selected.group(1):
            raise DockerDecisionError(f"Docker decision changed the detected Node.js runtime for {name}")

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
