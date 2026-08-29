"""Deterministic project setup requirements derived from Project Intelligence."""

from __future__ import annotations

import posixpath
from pathlib import Path
from typing import Any

AVAILABLE_STATUSES = {"AVAILABLE", "AVAILABLE_REDACTED", "DEFAULT_ONLY"}
TEMPLATE_NAMES = {".env.example", ".env.sample", ".env.template"}
ENV_FILE_NAMES = TEMPLATE_NAMES | {".env"}


class ProjectSetupBuilder:
    """Project a persisted snapshot into safe, actionable setup guidance.

    This class does not read the repository and does not trust user claims. It
    only turns already persisted deterministic findings into requirements. A
    later inspection must verify any configuration supplied by a user.
    """

    @classmethod
    def build(cls, intelligence: Any) -> dict[str, Any]:
        requirements: list[dict[str, Any]] = []
        gaps = list(intelligence.evidence_gaps)
        components = {str(item.get("name")): item for item in intelligence.components}
        setup_instructions = list(
            (getattr(intelligence, "documentation", {}) or {}).get("setup_instructions") or []
        )

        # A README can prove that configuration is part of the setup contract
        # even when the source never accesses the variable using a pattern the
        # inspector understands.  Keep that documentation as a requirement,
        # but never promote its example value to runtime availability.
        variables_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for variable in intelligence.environment_variables:
            name = str(variable.get("name") or variable.get("key") or "").strip()
            if name:
                key = (str(variable.get("component") or "root"), name)
                variables_by_key[key] = dict(variable)
        for instruction in setup_instructions:
            name = str(instruction.get("name") or "").strip()
            if not name:
                continue
            component = str(instruction.get("component") or "root")
            key = (component, name)
            variable = variables_by_key.setdefault(
                key,
                {
                    "name": name,
                    "key": name,
                    "value": None,
                    "sensitive": bool(instruction.get("sensitive")),
                    "required": True,
                    "value_status": str(instruction.get("value_status") or "DOCUMENTED_PLACEHOLDER").upper(),
                    "component": component,
                    "source_file": instruction.get("source_file"),
                    "source_files": [instruction.get("source_file")],
                    "role": "runtime",
                    "confidence": "high",
                },
            )
            variable["documented_setup"] = True
            variable["required"] = bool(variable.get("required") or True)
        variables = sorted(
            variables_by_key.values(),
            key=lambda item: (str(item.get("component") or "root"), str(item.get("name") or item.get("key") or "")),
        )

        for variable in variables:
            name = str(variable.get("name") or variable.get("key") or "").strip()
            if not name:
                continue
            status = cls._status(variable)
            required = bool(variable.get("required"))
            matching_gaps = [
                gap for gap in gaps
                if gap.get("kind") == "environment_value"
                and str(gap.get("name") or "") == name
                and cls._same_component(gap, variable)
            ]
            documented = [item for item in setup_instructions if item.get("name") == name and cls._same_component(item, variable)]
            if not required and not matching_gaps and not documented:
                continue
            # Documentation keeps the configuration key discoverable, but it
            # must not keep an already satisfied current-repository value in
            # the unresolved setup list.  The dashboard's requirements are
            # blockers, not a catalog of every documented key.
            if status in AVAILABLE_STATUSES:
                continue

            component = str(variable.get("component") or "root")
            source_files = cls._sources(variable, matching_gaps)
            role = str(variable.get("role") or "runtime")
            sensitive = bool(variable.get("sensitive"))
            blocks = cls._blocking_workflows(name, role, matching_gaps)
            location = cls._location(variable, source_files, documented)
            immediate, selection_basis = cls._is_immediate(
                variable, component, components, blocks, documented, source_files,
            )
            template_value, template_value_status = cls._template_value(
                variable, documented, sensitive,
            )
            requirement = {
                "name": name,
                "component": component,
                "required": required,
                "status": "NEEDS_EVIDENCE",
                "sensitive": sensitive,
                "value_status": status,
                "value": None,
                "role": role,
                "sources": [{"source_file": source} for source in source_files],
                "blocks": blocks,
                "resolution": "USER_CONFIGURATION_REQUIRED",
                "reinspect_required": True,
                "template_placeholder": "<provide your secret value>" if sensitive else "<provide value>",
                "template_value": template_value,
                "template_value_status": template_value_status,
                "message": cls._message(name, status, source_files, sensitive),
                "confidence": cls._confidence(variable, matching_gaps),
                "priority": "immediate" if immediate else "additional",
                "selection_basis": selection_basis,
                "location": location,
            }
            requirements.append(requirement)

        templates = cls._templates(requirements)
        immediate_requirements = [item for item in requirements if item["priority"] == "immediate"]
        additional_requirements = [item for item in requirements if item["priority"] == "additional"]
        return {
            "status": "NEEDS_EVIDENCE" if requirements else "READY",
            "requirements": requirements,
            "templates": templates,
            "immediate_requirements": immediate_requirements,
            "additional_requirements": additional_requirements,
            "immediate_templates": cls._templates(immediate_requirements),
            "additional_templates": cls._templates(additional_requirements),
            "reinspect_required": bool(requirements),
            "source": "persisted_project_intelligence",
        }

    @classmethod
    def _is_immediate(
        cls,
        variable: dict[str, Any],
        component: str,
        components: dict[str, dict[str, Any]],
        blocks: list[str],
        documented: list[dict[str, Any]],
        source_files: list[str],
    ) -> tuple[bool, list[str]]:
        basis: list[str] = []
        component_is_known = component in components or component == "root"
        if blocks and component_is_known:
            basis.append("blocks a downstream workflow")
        if documented and component_is_known:
            basis.append("explicit repository setup instruction")
        if str(variable.get("role") or "") == "build_time" and component_is_known:
            basis.append("required by a build-time configuration path")
        if not basis and component_is_known and any(Path(source).name in TEMPLATE_NAMES for source in source_files):
            basis.append("required variable is listed in a repository template")
        return bool(basis), basis

    @classmethod
    def _template_value(
        cls,
        variable: dict[str, Any],
        documented: list[dict[str, Any]],
        sensitive: bool,
    ) -> tuple[str | None, str]:
        if sensitive:
            return None, "REDACTED"
        candidates: list[str] = []
        for item in documented:
            value = item.get("value")
            if value not in (None, "") and item.get("value_status") == "DOCUMENTED_VALUE":
                candidates.append(str(value))
        if str(variable.get("value_status") or "").upper() == "TEMPLATE_ONLY":
            value = variable.get("value")
            if value not in (None, "", "REDACTED") and not cls._placeholder(str(value)):
                candidates.append(str(value))
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) > 1:
            return None, "AMBIGUOUS"
        if candidates:
            return candidates[0], "EVIDENCE_BACKED_TEMPLATE_VALUE"
        return None, "PLACEHOLDER_ONLY"

    @staticmethod
    def _placeholder(value: str) -> bool:
        normalized = value.strip().lower()
        return (
            not normalized
            or normalized.startswith("<")
            or normalized.startswith("your_")
            or normalized in {"changeme", "change_me", "placeholder", "example", "todo", "replace_me"}
            or "replace-with" in normalized
            or "your-value" in normalized
        )

    @classmethod
    def _location(
        cls,
        variable: dict[str, Any],
        source_files: list[str],
        documented: list[dict[str, Any]],
    ) -> dict[str, Any]:
        candidates: dict[str, list[str]] = {}
        for item in documented:
            location = str(item.get("location") or "")
            if location:
                candidates.setdefault(location, []).append(str(item.get("source_file") or "README"))
        for source in source_files:
            path = Path(source)
            if path.name in ENV_FILE_NAMES:
                target = path.with_name(".env").as_posix() if path.name in TEMPLATE_NAMES else path.as_posix()
                candidates.setdefault(target, []).append(source)
        if len(candidates) == 1:
            path, sources = next(iter(candidates.items()))
            return {
                "status": "VERIFIED",
                "path": path,
                "sources": list(dict.fromkeys(sources)),
                "basis": "explicit repository env file, template, or setup instruction",
            }
        if len(candidates) > 1:
            return {
                "status": "AMBIGUOUS",
                "path": None,
                "candidates": [
                    {"path": path, "sources": list(dict.fromkeys(sources))}
                    for path, sources in sorted(candidates.items())
                ],
                "basis": "multiple repository env locations were found",
            }
        return {
            "status": "NEEDS_EVIDENCE",
            "path": None,
            "sources": [],
            "basis": "repository evidence does not establish an env-file location",
        }

    @staticmethod
    def _same_component(gap: dict[str, Any], variable: dict[str, Any]) -> bool:
        gap_component = str(gap.get("component") or "root")
        variable_component = str(variable.get("component") or "root")
        return gap_component == variable_component or not gap.get("component")

    @staticmethod
    def _status(variable: dict[str, Any]) -> str:
        explicit = str(variable.get("value_status") or "").upper()
        if explicit:
            return explicit
        value = variable.get("value")
        source_files = [str(item) for item in variable.get("source_files") or []]
        source_file = str(variable.get("source_file") or "")
        all_sources = source_files + ([source_file] if source_file else [])
        if any(Path(source).name in TEMPLATE_NAMES for source in all_sources):
            return "TEMPLATE_ONLY"
        if value not in (None, "", "required"):
            return "AVAILABLE_REDACTED" if variable.get("sensitive") else "AVAILABLE"
        return "NEEDS_EVIDENCE"

    @staticmethod
    def _sources(variable: dict[str, Any], gaps: list[dict[str, Any]]) -> list[str]:
        values = [
            *(str(item) for item in variable.get("source_files") or []),
            str(variable.get("source_file") or ""),
            *(str(item.get("source_file") or "") for item in gaps),
        ]
        return list(dict.fromkeys(item for item in values if item))

    @staticmethod
    def _confidence(variable: dict[str, Any], gaps: list[dict[str, Any]]) -> str:
        values = [str(variable.get("confidence") or "")]
        values.extend(str(item.get("confidence") or "") for item in gaps)
        return "high" if "high" in values else "medium" if "medium" in values else "low"

    @staticmethod
    def _message(name: str, status: str, sources: list[str], sensitive: bool) -> str:
        source_text = ", ".join(sources) if sources else "repository configuration evidence"
        if status == "TEMPLATE_ONLY":
            return f"{name} is listed in {source_text}, but a template is not a verified runtime value. Populate the component configuration and re-inspect."
        if status == "DEFAULT_ONLY":
            return f"{name} has a repository default in {source_text}; verify whether that default is valid for the requested workflow before proceeding."
        if sensitive:
            return f"{name} is referenced in {source_text}, but its sensitive value is not available to Project Intelligence. Provide it through configuration and re-inspect; the value will remain redacted."
        return f"{name} is referenced in {source_text}, but no repository value or explicit default is available. Provide the value and re-inspect."

    @staticmethod
    def _blocking_workflows(name: str, role: str, gaps: list[dict[str, Any]]) -> list[str]:
        decisions = {str(item.get("decision") or "") for item in gaps}
        if name == "PORT":
            return ["dockerfile", "compose", "kubernetes"]
        if role == "build_time" or "build_configuration" in decisions:
            return ["dockerfile", "compose", "kubernetes"]
        return []

    @classmethod
    def _templates(cls, requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for requirement in requirements:
            location = requirement.get("location") or {}
            location_key = str(location.get("path") or "")
            grouped.setdefault((str(requirement["component"]), location_key), []).append(requirement)
        templates: list[dict[str, Any]] = []
        for (component, _location_key), items in grouped.items():
            location = items[0].get("location") or {}
            location_path = str(location.get("path") or "")
            directory = posixpath.dirname(location_path) if location.get("status") == "VERIFIED" else "."
            directory = directory or "."
            lines = [f"{item['name']}={item['template_value'] or item['template_placeholder']}" for item in items]
            template_sources = [
                source["source_file"]
                for item in items
                for source in item.get("sources", [])
                if Path(str(source.get("source_file") or "")).name in TEMPLATE_NAMES
            ]
            commands: list[str] = []
            if template_sources:
                target = posixpath.basename(location_path) if location_path else ".env"
                commands.append(f"cp {posixpath.relpath(template_sources[0], directory)} {target}")
            elif location.get("status") == "VERIFIED":
                commands.append("touch .env")
            templates.append({
                "component": component,
                "directory": directory,
                "file": posixpath.basename(location_path) if location_path else ".env",
                "variables": [item["name"] for item in items],
                "content": "\n".join(lines) + "\n",
                "commands": commands,
                "location": location,
                "guidance": ([f"cd {directory}"] if directory != "." else []) + ["create the environment file with the values for these verified variables", "re-inspect the repository after configuration"],
                "safe": True,
            })
        return templates
