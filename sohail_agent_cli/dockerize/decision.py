"""DevOps-model decision and evidence-bound Docker artifact rendering."""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, replace
from typing import Any, Callable

from sohail_agent_cli.providers import GenerationRequest, OllamaProvider

from .context_builder import DockerContext
from .platform_policy import policy_for_component, policy_value


DOCKER_DECISION_OUTPUT_TOKENS = 2048
DOCKER_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "reason", "components", "compose"],
    "properties": {
        "status": {"type": "string", "enum": ["ready", "NEEDS_EVIDENCE"]},
        "reason": {"type": "string", "minLength": 1},
        "components": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "name", "base_image", "working_directory", "package_manager",
                    "install_command", "build_command", "start_command", "port",
                ],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "base_image": {"type": "string", "minLength": 1},
                    "working_directory": {"type": "string", "minLength": 1},
                    "package_manager": {"type": "string"},
                    "install_command": {"type": "string"},
                    "build_command": {"type": "string"},
                    "start_command": {
                        "anyOf": [
                            {"type": "string", "minLength": 1},
                            {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        ]
                    },
                    "port": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    "deployment_pattern": {"type": "string", "minLength": 1},
                },
                "additionalProperties": True,
            },
        },
        "compose": {
            "type": "object",
            "properties": {
                "services": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["name", "component", "build_context", "port", "target_port"],
                        "properties": {
                            "name": {"type": "string", "minLength": 1},
                            "component": {"type": "string", "minLength": 1},
                            "build_context": {"type": "string"},
                            "port": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                            "target_port": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                            "environment": {"type": "array", "items": {"type": "string"}},
                            "depends_on": {"type": "array", "items": {"type": "string"}},
                        },
                        "additionalProperties": True,
                    },
                },
            },
            "additionalProperties": True,
        },
    },
}


class DockerDecisionError(ValueError):
    """Raised when Ollama does not return a safe structured decision."""


@dataclass(frozen=True)
class DockerDecision:
    status: str
    components: list[dict[str, Any]]
    compose: dict[str, Any]
    raw: dict[str, Any]
    repair_attempted: bool = False
    model_called: bool = False


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
package_manager, install_command, build_command when the evidence or verified
pattern requires a build, start_command, and
port, including the supplied component name. The compose object must contain a
services array. Compose services must include name, component, build_context,
port, and target_port and may include only evidence-supported environment or
dependency references. The component's start_command must match the exact
command from its literal start script or the exact DERIVED_DETERMINISTIC launch
command supplied in the component artifact evidence. A dev or preview script is
not production start evidence and must never be selected as start_command. If no
explicit or deterministically derived production start strategy exists for a
component, return NEEDS_EVIDENCE.
When the supplied context contains a verified pattern for a component, include
that pattern's pattern_id verbatim as deployment_pattern; this field is
required and omission is invalid. A static_frontend pattern
permits a safe static-content server command after the exact build command and
port remain evidence-bound; do not treat the pattern as permission to invent
runtime versions, ports, environment variables, or dependencies.
For a static_frontend component, put deployment_pattern and build_command on
that component object, never on a Compose service. The build_command must match
the verified pattern policy exactly. The start_command must use an allowed
static-serving family from that policy; never use dev, preview, vite dev, or
vite preview as a production Docker start command. Use the exact Node runtime
as the build image and include an evidence-compatible package install command;
do not use a runtime-only image such as nginx as the build image.
The supplied artifact_plan is authoritative: generate or upgrade only those
artifacts, preserve keep actions, and exclude skip actions. Do not emit decisions
for skipped components.
For every component whose supplied ports contain a non-conflicting port with
port_type application, copy that exact integer to component.port. The matching
Compose service must copy that same integer to both port and target_port. Do
not omit an evidence-backed application port and do not use documented or
service-only ports in its place.
Return a decision, not file contents and do not modify files."""

REPAIR_SYSTEM_PROMPT = """You repair one invalid JSON Docker decision for Sohail Studio.
Return JSON only. Preserve all valid fields and values from the original response.
Repair schema/formatting only; do not add project facts, runtime versions, ports,
commands, services, dependencies, or environment variables. Every response must
contain status, reason, components, and compose. reason must be a concise,
non-empty string grounded only in the original response or the supplied
validation error. For every supplied component with a non-conflicting
application port, copy the exact port into the component and into the matching
Compose service's port and target_port. Do not omit an evidence-backed
application port. Use each component's evidence-backed path as the Compose
build_context, expressed as a relative ./path. For a verified static_frontend
component, keep deployment_pattern and build_command inside its component
object, use the exact verified build command, use the exact Node runtime as the
build image, include the package install command, and use an allowed static
server instead of dev or preview. For every entry in verified_patterns, copy
its pattern_id verbatim to the matching component's deployment_pattern before
returning ready. If the original response cannot safely be repaired, return:
{"status":"NEEDS_EVIDENCE","reason":"The Docker decision could not be safely repaired from the supplied evidence.","components":[],"compose":{}}."""


class DockerDecisionEngine:
    """Ask the configured local DevOps model and reject unsupported claims."""

    def __init__(
        self,
        provider: OllamaProvider,
        model: str,
        *,
        on_repair: Callable[[], None] | None = None,
        on_model_call: Callable[[], None] | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.on_repair = on_repair
        self.on_model_call = on_model_call

    async def decide(self, context: DockerContext) -> DockerDecision:
        preflight = self._preflight(context)
        if preflight is not None:
            return preflight
        if self.on_model_call is not None:
            self.on_model_call()
        result = await self.provider.generate(
            GenerationRequest(
                prompt=context.prompt(),
                system=SYSTEM_PROMPT,
                model=self.model,
                temperature=0,
                options={
                    "format": DOCKER_DECISION_SCHEMA,
                    "num_ctx": 16384,
                    "num_predict": DOCKER_DECISION_OUTPUT_TOKENS,
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
            payload = await self._repair_payload(result.text, str(exc), context.prompt())
        payload = self._normalize_evidence_bound_fields(payload, context)
        decision = DockerDecision(
            status=payload["status"],
            components=payload["components"],
            compose=payload["compose"],
            raw=payload,
            repair_attempted=repair_attempted,
            model_called=True,
        )
        if decision.status == "NEEDS_EVIDENCE":
            return decision
        try:
            self._validate_decision(decision, context)
        except DockerDecisionError as exc:
            if not repair_attempted:
                repair_attempted = True
                try:
                    repair_context = context
                    repair_scope = ""
                    expected_names = {str(item["name"]) for item in context.components}
                    actual_names = {str(item.get("name")) for item in decision.components}
                    if actual_names < expected_names:
                        missing_names = sorted(expected_names - actual_names)
                        repair_context = self._scope_context(context, missing_names)
                        repair_scope = (
                            "The original response omitted these required component names: "
                            + ", ".join(missing_names)
                            + ". Return decisions for those missing names from the supplied context."
                        )
                    payload = await self._repair_payload(
                        result.text,
                        str(exc),
                        repair_context.prompt(),
                        repair_scope=repair_scope,
                    )
                except DockerDecisionError as repair_exc:
                    return self._needs_evidence(
                        str(exc),
                        repair_attempted=True,
                        proposed=decision.raw,
                    )
                payload = self._merge_scope_repair(decision.raw, payload, context)
                payload = self._normalize_evidence_bound_fields(payload, context)
                repaired_decision = DockerDecision(
                    status=payload["status"],
                    components=payload["components"],
                    compose=payload["compose"],
                    raw=payload,
                    repair_attempted=True,
                    model_called=True,
                )
                if repaired_decision.status == "NEEDS_EVIDENCE":
                    return repaired_decision
                try:
                    self._validate_decision(repaired_decision, context)
                except DockerDecisionError as repaired_error:
                    return self._needs_evidence(
                        str(exc),
                        repair_attempted=True,
                        proposed=repaired_decision.raw,
                    )
                return repaired_decision
            # A schema-valid model response is still only a proposal. Any
            # unsupported infrastructure claim becomes an explicit evidence
            # request before the rendering layer can see the decision.
            return self._needs_evidence(
                str(exc), repair_attempted=repair_attempted, proposed=decision.raw,
            )
        return decision

    async def _repair_payload(
        self,
        response: str,
        error: str,
        context_prompt: str,
        repair_scope: str = "",
    ) -> dict[str, Any]:
        """Perform exactly one bounded repair of the model's structured output."""
        if self.on_repair is not None:
            self.on_repair()
        repaired = await self.provider.generate(
            self._repair_request(response, error, context_prompt, repair_scope=repair_scope)
        )
        if repaired.error:
            raise DockerDecisionError(repaired.error)
        try:
            return self._parse_json(repaired.text)
        except (TypeError, ValueError) as exc:
            raise DockerDecisionError(
                "Ollama returned an invalid Docker decision schema after one "
                f"bounded repair attempt: {exc}"
            ) from exc

    @staticmethod
    def _needs_evidence(
        reason: str,
        *,
        repair_attempted: bool,
        proposed: dict[str, Any] | None = None,
    ) -> DockerDecision:
        model_proposed = {
            "components": [dict(item) for item in (proposed or {}).get("components", []) if isinstance(item, dict)],
            "compose": (proposed or {}).get("compose") if isinstance((proposed or {}).get("compose"), dict) else {},
        }
        return DockerDecision(
            status="NEEDS_EVIDENCE",
            components=[],
            compose={},
            raw={
                "status": "NEEDS_EVIDENCE",
                "reason": reason,
                "components": [],
                "compose": {},
                "model_proposed": model_proposed,
            },
            repair_attempted=repair_attempted,
            model_called=True,
        )

    @staticmethod
    def _normalize_evidence_bound_fields(
        payload: dict[str, Any],
        context: DockerContext,
    ) -> dict[str, Any]:
        """Copy only deterministic pattern identity omitted by the model.

        A verified pattern is already an accepted Project Intelligence fact. If
        the model omits that identity while returning a ready decision, adding
        the exact persisted pattern_id is safe normalization, not inference.
        Any conflicting non-empty value remains untouched and is rejected by
        the strict validator.
        """
        if payload.get("status") != "ready":
            return payload
        normalized = dict(payload)
        components = [
            dict(item) for item in payload.get("components", [])
            if isinstance(item, dict)
        ]
        by_name = {str(item.get("name")): item for item in components}
        changed = False
        for pattern in context.verified_patterns:
            name = str(pattern.get("component") or "")
            pattern_id = str(pattern.get("pattern_id") or "")
            component = by_name.get(name)
            if component is None or not pattern_id:
                continue
            if not str(component.get("deployment_pattern") or "").strip():
                component["deployment_pattern"] = pattern_id
                changed = True
        if changed:
            normalized["components"] = components
        return normalized

    def _repair_request(
        self,
        response: str,
        error: str,
        context_prompt: str,
        repair_scope: str = "",
    ) -> GenerationRequest:
        """Create the single bounded repair request without repository access."""
        original = str(response or "")[:12000]
        supplied_context = self._bound_context_for_repair(context_prompt)
        prompt = (
            "Repair only this structured Docker decision. Do not request or infer "
            "new repository evidence.\n\n"
            f"VALIDATION_ERROR: {error}\n\n"
            f"REPAIR_SCOPE: {repair_scope or 'Repair the complete structured response without changing its evidence scope.'}\n\n"
            "REQUIRED_SHAPE:\n"
            '{"status":"ready|NEEDS_EVIDENCE","reason":"non-empty explanation",'
            '"components":[],"compose":{}}\n\n'
            f"ORIGINAL_RESPONSE:\n{original}\n\n"
            "Before returning a ready response, check every component in the supplied context:\n"
            "preserve its exact name; copy any non-conflicting port_type=application\n"
            "port into component.port and into its Compose service's port and target_port;\n"
            "copy its component path into build_context as a relative ./path; preserve\n"
            "each verified_patterns.pattern_id verbatim as deployment_pattern on its\n"
            "matching component, and preserve exact policy commands. If a required fact cannot\n"
            "be copied from the supplied context, return NEEDS_EVIDENCE.\n\n"
            f"SUPPLIED_CONTEXT_FOR_GROUNDING_ONLY:\n{supplied_context}"
        )
        return GenerationRequest(
            prompt=prompt,
            system=REPAIR_SYSTEM_PROMPT,
            model=self.model,
            temperature=0,
            options={
                "format": DOCKER_DECISION_SCHEMA,
                "num_ctx": 16384,
                "num_predict": DOCKER_DECISION_OUTPUT_TOKENS,
            },
            think=False,
        )

    @staticmethod
    def _bound_context_for_repair(context_prompt: str, limit: int = 22000) -> str:
        """Keep the complete focused context within the bounded model request."""
        value = str(context_prompt or "")
        if len(value) <= limit:
            return value
        half = (limit - 80) // 2
        return value[:half] + "\n...[bounded context middle omitted]...\n" + value[-half:]

    @staticmethod
    def _scope_context(context: DockerContext, names: list[str]) -> DockerContext:
        selected = [item for item in context.components if str(item.get("name")) in names]
        project = dict(context.project)
        project["selected_components"] = names
        patterns = [
            item for item in context.verified_patterns
            if str(item.get("component")) in names
        ]
        plan = dict(context.artifact_plan or {})
        if isinstance(plan.get("dockerfiles"), dict):
            plan["dockerfiles"] = {
                name: action for name, action in plan["dockerfiles"].items()
                if name in names
            }
        return replace(
            context,
            project=project,
            components=selected,
            verified_patterns=patterns,
            artifact_plan=plan,
        )

    @staticmethod
    def _merge_scope_repair(
        original: dict[str, Any],
        repaired: dict[str, Any],
        context: DockerContext,
    ) -> dict[str, Any]:
        expected_names = {str(item["name"]) for item in context.components}
        ordered_names = [str(item["name"]) for item in context.components]
        original_components = [
            item for item in original.get("components", [])
            if isinstance(item, dict)
        ]
        repaired_components = [
            item for item in repaired.get("components", [])
            if isinstance(item, dict)
        ]
        repaired_names = {str(item.get("name")) for item in repaired_components}
        if repaired_names == expected_names:
            components = repaired_components
        else:
            by_name = {str(item.get("name")): item for item in original_components}
            for item in repaired_components:
                name = str(item.get("name"))
                if name in expected_names:
                    by_name[name] = item
            components = [by_name[name] for name in ordered_names if name in by_name]
        original_compose = original.get("compose") if isinstance(original.get("compose"), dict) else {}
        repaired_compose = repaired.get("compose") if isinstance(repaired.get("compose"), dict) else {}
        original_services = [item for item in original_compose.get("services", []) if isinstance(item, dict)]
        repaired_services = [item for item in repaired_compose.get("services", []) if isinstance(item, dict)]
        services_by_name = {
            str(item.get("name")): item for item in original_services + repaired_services
            if str(item.get("component")) in expected_names
        }
        return {
            **repaired,
            "components": components,
            "compose": {**original_compose, **repaired_compose, "services": list(services_by_name.values())},
        }

    @staticmethod
    def _explicit_deployment_facts(
        source: dict[str, Any], field: str, value_key: str,
    ) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in source.get(field, [])
            if item.get("source_type", "EXPLICIT_EVIDENCE") == "EXPLICIT_EVIDENCE"
            and item.get("model_inference") is False
            and str(item.get(value_key) or "").strip()
        ]

    @staticmethod
    def _authorized_deployment_facts(
        context: DockerContext,
        source: dict[str, Any],
        component_name: str,
        field: str,
        value_key: str,
    ) -> list[dict[str, Any]]:
        explicit = DockerDecisionEngine._explicit_deployment_facts(source, field, value_key)
        policy = policy_for_component(context.platform_policies, component_name)
        policy_field = "base_image" if field == "base_images" else "working_directory"
        approved = policy_value(policy, policy_field)
        return explicit + ([approved] if approved is not None else [])

    @staticmethod
    def _preflight(context: DockerContext) -> DockerDecision | None:
        """Stop before Ollama when any mandatory Docker fact is unauthorized.

        This gate deliberately consumes only the already-built DockerContext.
        There is no repository access, convention fallback, or model proposal
        path here.  A platform-policy source can be added as a separate,
        explicitly persisted authority later; no such policy is currently
        present, so only explicit repository facts are accepted for deployment
        layout values.
        """
        patterns = {
            str(item.get("component")): item
            for item in context.verified_patterns
            if item.get("origin") == "VERIFIED_INFERENCE"
        }
        boundaries: list[dict[str, Any]] = []
        missing: list[str] = []

        for component in context.components:
            name = str(component.get("name"))
            explicit_start = [
                item for item in component.get("commands", [])
                if item.get("name") == "start" and str(item.get("command") or "").strip()
            ]
            derived = [
                item for item in component.get("artifacts", [])
                if item.get("executable") is True
                and item.get("source_type") == "DERIVED_DETERMINISTIC"
                and item.get("model_inference") is False
                and item.get("rule_id")
                and item.get("derived_from")
                and item.get("launch_command")
            ]
            unsupported = component.get("deployment_evidence") or {}
            policy = policy_for_component(context.platform_policies, name)
            base_images = DockerDecisionEngine._explicit_deployment_facts(component, "base_images", "image")
            working_directories = DockerDecisionEngine._explicit_deployment_facts(component, "working_directories", "path")
            policy_base_image = policy_value(policy, "base_image")
            policy_working_directory = policy_value(policy, "working_directory")
            explicit_base_values = {str(item.get("image")) for item in base_images}
            explicit_workdir_values = {str(item.get("path")) for item in working_directories}
            base_conflict = (
                len(explicit_base_values) > 1
                or bool(policy_base_image and explicit_base_values
                        and explicit_base_values != {str(policy_base_image.get("value"))})
            )
            workdir_conflict = (
                len(explicit_workdir_values) > 1
                or bool(policy_working_directory and explicit_workdir_values
                        and explicit_workdir_values != {str(policy_working_directory.get("value"))})
            )
            start_authorized = bool(explicit_start or derived or name in patterns)
            base_authorized = bool(base_images or policy_base_image) and not base_conflict
            workdir_authorized = bool(working_directories or policy_working_directory) and not workdir_conflict
            boundaries.append({
                "component": name,
                "explicit": explicit_start,
                "derived_deterministic": derived,
                "base_image": {
                    "requirement": "Exact Docker base image",
                    "explicit": base_images,
                    "derived_deterministic": [],
                    "approved_platform_policy": [policy_base_image] if policy_base_image else [],
                    "unsupported": None if base_authorized else {
                        "status": "CONFLICT" if base_conflict else "UNSUPPORTED",
                        "reason": (
                            "Explicit repository base image conflicts with the applicable platform policy"
                            if base_conflict else
                            "No exact repository base image or applicable approved deterministic platform policy is persisted"
                        ),
                    },
                    "authorized_source": "EXPLICIT_EVIDENCE" if base_images else (
                        "APPROVED_PLATFORM_POLICY" if policy_base_image else "UNSUPPORTED"
                    ),
                    "authorized": base_authorized,
                },
                "working_directory": {
                    "requirement": "Exact working directory",
                    "explicit": working_directories,
                    "derived_deterministic": [],
                    "approved_platform_policy": [policy_working_directory] if policy_working_directory else [],
                    "unsupported": None if workdir_authorized else {
                        "status": "CONFLICT" if workdir_conflict else "UNSUPPORTED",
                        "reason": (
                            "Explicit repository working directory conflicts with the applicable platform policy"
                            if workdir_conflict else
                            "No exact repository working directory or applicable approved deterministic platform policy is persisted"
                        ),
                    },
                    "authorized_source": "EXPLICIT_EVIDENCE" if working_directories else (
                        "APPROVED_PLATFORM_POLICY" if policy_working_directory else "UNSUPPORTED"
                    ),
                    "authorized": workdir_authorized,
                },
                "unsupported": unsupported if unsupported.get("status") == "UNSUPPORTED" else None,
            })
            if not start_authorized:
                missing.append(f"{name}: exact production start command")
            if not base_authorized:
                missing.append(f"{name}: exact Docker base image" if not base_conflict else f"{name}: conflicting Docker base image evidence")
            if not workdir_authorized:
                missing.append(f"{name}: exact working directory" if not workdir_conflict else f"{name}: conflicting working directory evidence")
        if not missing:
            return None
        requirements = "; ".join(missing)
        reason = (
            "Missing authoritative Docker requirements: "
            f"{requirements}. Model proposals, implicit defaults, and development or preview commands are not authorized."
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
                "stage": "deterministic Docker requirement preflight",
                "model_called": False,
                "repair_attempted": False,
                "missing_requirements": missing,
                "evidence_boundary": boundaries,
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
            working_directory = str(component.get("working_directory") or "").strip()
            allowed_working_directories = {
                str(item.get("path") or item.get("value") or "")
                for item in self._authorized_deployment_facts(
                    context, source, name, "working_directories", "path"
                )
            }
            if working_directory not in allowed_working_directories:
                raise DockerDecisionError(
                    f"Docker decision proposed working directory '{working_directory}' for {name}, but it is not an authorized repository or platform-policy value"
                )
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
                if command_name == "build" and source.get("package_manager") == "maven":
                    allowed |= self._commands_for(source, "package")
                if command_name == "start":
                    derived_starts = {
                        " ".join(str(token) for token in item.get("launch_command", []))
                        for item in source.get("artifacts", [])
                        if item.get("executable") is True
                        and item.get("source_type") == "DERIVED_DETERMINISTIC"
                        and item.get("model_inference") is False
                    }
                    if derived_starts:
                        if command_text not in derived_starts:
                            raise DockerDecisionError(
                                f"Docker decision changed derived production start command for {name}"
                            )
                        continue
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
            self._validate_runtime(name, component, source, context)
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
        base_image = str(component.get("base_image") or "")
        if not base_image.startswith("node:"):
            raise DockerDecisionError(
                f"Static frontend pattern requires a Node.js build image for {name}"
            )
        if not str(component.get("install_command") or "").strip():
            raise DockerDecisionError(
                f"Static frontend pattern requires an evidence-compatible package install command for {name}"
            )
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
    def _validate_runtime(
        name: str,
        component: dict[str, Any],
        source: dict[str, Any],
        context: DockerContext,
    ) -> None:
        """Require every Docker runtime claim to be supported by evidence.

        In particular, a Node base image is never selected from model
        knowledge, dependency versions, machine state, README assumptions, or
        an internal default. Only an explicit Project Intelligence runtime
        fact can authorize its major version.
        """
        base_image = str(component.get("base_image", ""))
        if not base_image:
            raise DockerDecisionError(f"Docker decision did not provide a base image for {name}")
        allowed_images = {
            str(item.get("image") or item.get("value") or "")
            for item in DockerDecisionEngine._authorized_deployment_facts(
                context, source, name, "base_images", "image"
            )
        }
        if base_image not in allowed_images:
            raise DockerDecisionError(
                f"Docker decision proposed base image '{base_image}' for {name}, but it is not an authorized repository or platform-policy value"
            )
        runtimes = [item for item in source.get("runtimes", []) if item.get("runtime") == "Node.js"]
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
        if component.get("package_manager") == "maven" or component.get("language") == "Java":
            return DockerDecisionEngine._render_maven_dockerfile(component)
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
    def _render_maven_dockerfile(component: dict[str, Any]) -> str:
        """Render the Maven strategy; this is intentionally not the Node template."""
        base_image = str(component.get("base_image") or "")
        if not base_image:
            raise DockerDecisionError(f"Docker decision did not provide a base image for {component.get('name')}")
        artifacts = [
            item for item in component.get("artifacts", [])
            if item.get("executable") is True
            and item.get("source_type") == "DERIVED_DETERMINISTIC"
            and item.get("model_inference") is False
        ]
        if len(artifacts) != 1:
            raise DockerDecisionError(
                f"Maven component {component.get('name')} has no uniquely proven executable artifact"
            )
        build = str(component.get("build_command") or "").strip()
        if build != "mvn package":
            raise DockerDecisionError(
                f"Maven component {component.get('name')} lacks the exact supported package command"
            )
        artifact = str(artifacts[0].get("path") or "").strip()
        start = component.get("start_command")
        command = start if isinstance(start, list) else shlex.split(str(start or ""))
        if command != ["java", "-jar", artifact]:
            raise DockerDecisionError(
                f"Maven component {component.get('name')} changed its derived launch command"
            )
        policy = component.get("platform_policy")
        build_policy = policy_value(policy, "build_image")
        if build_policy is None:
            raise DockerDecisionError(
                f"Maven component {component.get('name')} lacks an approved platform build image"
            )
        build_image = str(build_policy["value"])
        workdir = str(component.get("working_directory") or "")
        if not workdir:
            raise DockerDecisionError(
                f"Maven component {component.get('name')} lacks an authorized working directory"
            )
        if artifact.startswith("/") or ".." in artifact.split("/"):
            raise DockerDecisionError(
                f"Maven component {component.get('name')} has an unsafe derived artifact path"
            )
        artifact_in_build = f"{workdir.rstrip('/')}/{artifact}"
        lines = [
            f"FROM {build_image} AS build",
            f"WORKDIR {workdir}",
            "COPY . .",
            f"RUN {build}",
            f"FROM {base_image}",
            f"WORKDIR {workdir}",
            f"COPY --from=build {artifact_in_build} {artifact_in_build}",
        ]
        if component.get("port") is not None:
            lines.append(f"EXPOSE {int(component['port'])}")
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
