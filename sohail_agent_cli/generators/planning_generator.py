"""Deterministic Markdown generator for PlanningAgent V1."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Iterable

from sohail_agent_cli.planning.models import DecisionRecord, PlanningContext, Requirement, TaskItem


class PlanningGenerator:
    """Render a validated planning context into a planning-package file map."""

    def generate(self, context: PlanningContext) -> OrderedDict[Path, str]:
        """Generate all PlanningAgent V1 artifacts without filesystem access."""
        context.validate()
        files: OrderedDict[Path, str] = OrderedDict()
        for decision in context.decisions:
            files[decision.filename] = self._render_decision(context, decision)
        files[Path("REQUIREMENTS.md")] = self._render_requirements(context)
        files[Path("ARCHITECTURE.md")] = self._render_architecture(context)
        files[Path("TASK.md")] = self._render_tasks(context)
        self._validate_file_map(files)
        return files

    def _render_requirements(self, context: PlanningContext) -> str:
        brief = context.brief
        lines = self._front_matter(
            context,
            document="requirements",
            status="draft",
        )
        lines.extend(
            [
                "# Requirements",
                "",
                "## Project Goal",
                "",
                brief.goal,
                "",
                "## Target Users",
                "",
                *self._bullets(brief.target_users),
                "",
                "## Functional Requirements",
                "",
            ]
        )
        lines.extend(
            self._render_requirement_group(
                requirement
                for requirement in context.requirements
                if requirement.category == "functional"
            )
        )
        lines.extend(["## Non-Functional Requirements", ""])
        lines.extend(
            self._render_requirement_group(
                requirement
                for requirement in context.requirements
                if requirement.category == "non_functional"
            )
        )
        lines.extend(["## Constraints", ""])
        constraints = [
            requirement
            for requirement in context.requirements
            if requirement.category == "constraint"
        ]
        if constraints:
            lines.extend(self._render_requirement_group(constraints))
        else:
            lines.extend(["No explicit first-release constraints were confirmed.", ""])
        lines.extend(["## Assumptions", "", *self._bullets(context.assumptions), ""])
        lines.extend(["## Out of Scope", ""])
        lines.extend(
            self._bullets(brief.out_of_scope)
            if brief.out_of_scope
            else ["- No explicit out-of-scope items were provided."]
        )
        lines.extend(["", "## Open Questions", ""])
        lines.extend(
            [
                f"- **{question.question_id}:** {question.text}"
                for question in context.open_questions
            ]
            or ["- No open questions were recorded."]
        )
        return self._finish(lines)

    def _render_requirement_group(
        self,
        requirements: Iterable[Requirement],
    ) -> list[str]:
        lines: list[str] = []
        for requirement in requirements:
            lines.extend(
                [
                    f"### {requirement.requirement_id} — {requirement.title}",
                    "",
                    f"- **Priority:** {requirement.priority}",
                    f"- **Status:** {requirement.status}",
                    f"- **Source:** {requirement.source}",
                    f"- **Requirement:** {requirement.statement}",
                    f"- **Acceptance:** {requirement.acceptance}",
                ]
            )
            if requirement.decision_ids:
                lines.append(
                    f"- **Related Decisions:** {', '.join(requirement.decision_ids)}"
                )
            lines.append("")
        return lines

    def _render_architecture(self, context: PlanningContext) -> str:
        brief = context.brief
        decision_index = [
            f"- [{decision.decision_id} — {decision.title}]({decision.filename.as_posix()})"
            for decision in context.decisions
        ]
        lines = self._front_matter(context, document="architecture", status="draft")
        lines.extend(
            [
                "# Architecture",
                "",
                "## Architecture Summary",
                "",
                (
                    f"{brief.name} is planned as a {self._category_label(brief.category)} "
                    f"for {self._join_words(brief.target_users)}. The design below reflects "
                    "confirmed choices and keeps unresolved choices explicit."
                ),
                "",
                "## Goals and Non-Goals",
                "",
                "### Goals",
                "",
                *self._bullets(brief.first_release_scope),
                "",
                "### Non-Goals",
                "",
                *(
                    self._bullets(brief.out_of_scope)
                    if brief.out_of_scope
                    else ["- No explicit non-goals were provided."]
                ),
                "",
                "## System Context",
                "",
                f"- **Primary users:** {self._join_words(brief.target_users)}",
                (
                    "- **System boundary:** the components listed below and their "
                    "confirmed integrations."
                ),
                (
                    "- **External systems:** none are assumed unless explicitly "
                    "recorded in a decision."
                ),
                "",
                "## Major Components",
                "",
            ]
        )
        for component in context.architecture_components:
            lines.extend(
                [
                    f"### {component.name}",
                    "",
                    *self._bullets(component.responsibilities),
                ]
            )
            if component.decision_ids:
                lines.extend(
                    ["", f"Related decisions: {', '.join(component.decision_ids)}"]
                )
            lines.append("")
        lines.extend(
            [
                "## Component Responsibilities",
                "",
                "Each component owns only the responsibilities listed above. Cross-component "
                "behavior should use explicit interfaces rather than shared hidden state.",
                "",
                "## Data Flow",
                "",
                "1. A target user initiates a confirmed first-release flow.",
                "2. The user-facing boundary validates and forwards the request when applicable.",
                "3. The application boundary applies business rules.",
                (
                    "4. Confirmed persistence or external systems are used through "
                    "explicit boundaries."
                ),
                "5. The outcome is returned without exposing sensitive configuration.",
                "",
                "## Data Model Overview",
                "",
                self._database_overview(context),
                "",
                "## Authentication and Authorization",
                "",
                context.authentication_summary,
                "",
                "## Deployment View",
                "",
                context.deployment_summary,
                "",
                "## Reliability and Observability",
                "",
                "- Critical failures should be visible to operators.",
                "- Logs must not expose credentials or sensitive tokens.",
                "- Exact availability, backup, and recovery targets remain requirements decisions.",
                "",
                "## Security and Privacy",
                "",
                "- Production secrets must be supplied through runtime configuration.",
                "- Access checks must follow the confirmed authentication decision.",
                "- Data retention and regulatory obligations are not assumed.",
                "",
                "## Architecture Decisions",
                "",
                *(decision_index or ["- No architecture decisions were confirmed."]),
                "",
                "## Assumptions and Open Questions",
                "",
                "### Assumptions",
                "",
                *self._bullets(context.assumptions),
                "",
                "### Open Questions",
                "",
                *(
                    [
                        f"- **{question.question_id}:** {question.text}"
                        for question in context.open_questions
                    ]
                    or ["- No open questions were recorded."]
                ),
            ]
        )
        return self._finish(lines)

    def _render_tasks(self, context: PlanningContext) -> str:
        lines = self._front_matter(context, document="tasks", status="active")
        lines.extend(
            [
                "# Task Plan",
                "",
                "## Status Definitions",
                "",
                "- `proposed` — valid work that is not ready to begin.",
                "- `ready` — work with confirmed prerequisites.",
                "- `blocked` — work waiting on a decision or dependency.",
                "- `in_progress` — reserved for human or verified execution updates.",
                "- `done` — reserved for human or verified execution updates.",
                "- `cancelled` — reserved for human updates.",
                "",
                "## Priority Definitions",
                "",
                "- `P0` — required for the first usable release.",
                "- `P1` — important after the core path works.",
                "- `P2` — valuable but deferrable.",
                "- `P3` — optional.",
                "",
                "## Task Summary",
                "",
                "| ID | Task | Status | Priority | Depends On | Owner |",
                "|---|---|---|---|---|---|",
            ]
        )
        for task in context.tasks:
            dependencies = ", ".join(task.dependencies) if task.dependencies else "—"
            lines.append(
                f"| {task.task_id} | {task.title} | {task.status} | "
                f"{task.priority} | {dependencies} | {task.owner} |"
            )
        lines.append("")
        for task in context.tasks:
            lines.extend(self._render_task(task))
        return self._finish(lines)

    def _render_task(self, task: TaskItem) -> list[str]:
        return [
            f"## {task.task_id} — {task.title}",
            "",
            f"- **Status:** {task.status}",
            f"- **Priority:** {task.priority}",
            f"- **Owner:** {task.owner}",
            f"- **Dependencies:** {', '.join(task.dependencies) if task.dependencies else 'none'}",
            (
                f"- **Requirements:** "
                f"{', '.join(task.requirement_ids) if task.requirement_ids else 'none'}"
            ),
            f"- **Decisions:** {', '.join(task.decision_ids) if task.decision_ids else 'none'}",
            "",
            "### Objective",
            "",
            task.objective,
            "",
            "### Acceptance Criteria",
            "",
            *self._bullets(task.acceptance_criteria),
            "",
            "### Notes",
            "",
            *(self._bullets(task.notes) if task.notes else ["- No additional notes."]),
            "",
        ]

    def _render_decision(
        self,
        context: PlanningContext,
        decision: DecisionRecord,
    ) -> str:
        lines = [
            "---",
            f"planning_schema: {context.schema_version}",
            f"id: {decision.decision_id}",
            f"title: {decision.title}",
            f"status: {decision.status}",
            f"date: {context.brief.planning_date.isoformat()}",
            "supersedes: null",
            "superseded_by: null",
            "---",
            "",
            f"# {decision.decision_id} — {decision.title}",
            "",
            "## Context",
            "",
            decision.context,
            "",
            "## Decision",
            "",
            decision.choice,
            "",
            "## Rationale",
            "",
            *self._bullets(decision.rationale),
            "",
            "## Alternatives Considered",
            "",
            *(
                self._bullets(decision.alternatives)
                if decision.alternatives
                else ["- No alternatives were recorded."]
            ),
            "",
            "## Consequences",
            "",
            "### Positive",
            "",
            *self._bullets(decision.positive_consequences),
            "",
            "### Negative",
            "",
            *self._bullets(decision.negative_consequences),
            "",
            "## Related Requirements",
            "",
            *(
                self._bullets(decision.related_requirement_ids)
                if decision.related_requirement_ids
                else ["- None linked in the initial plan."]
            ),
            "",
            "## Related Tasks",
            "",
            *(
                self._bullets(decision.related_task_ids)
                if decision.related_task_ids
                else ["- None linked in the initial plan."]
            ),
            "",
            "## Open Questions",
            "",
            *(
                self._bullets(decision.open_question_ids)
                if decision.open_question_ids
                else ["- No decision-specific open questions."]
            ),
        ]
        return self._finish(lines)

    @staticmethod
    def _front_matter(
        context: PlanningContext,
        document: str,
        status: str,
    ) -> list[str]:
        return [
            "---",
            f"planning_schema: {context.schema_version}",
            f"project: {context.brief.name}",
            f"document: {document}",
            f"status: {status}",
            f"updated: {context.brief.planning_date.isoformat()}",
            "---",
            "",
        ]

    @staticmethod
    def _bullets(values: Iterable[str]) -> list[str]:
        return [f"- {value}" for value in values]

    @staticmethod
    def _join_words(values: list[str]) -> str:
        if not values:
            return "unspecified users"
        if len(values) == 1:
            return values[0]
        if len(values) == 2:
            return f"{values[0]} and {values[1]}"
        return ", ".join(values[:-1]) + f", and {values[-1]}"

    @staticmethod
    def _category_label(category: str) -> str:
        return {
            "web_application": "web application",
            "api_service": "API or service",
            "cli_tool": "command-line tool",
            "generic_software": "software project",
        }.get(category, "software project")

    @staticmethod
    def _database_overview(context: PlanningContext) -> str:
        database_decision = next(
            (decision for decision in context.decisions if decision.topic == "database"),
            None,
        )
        if database_decision is None:
            return (
                "The primary data store and detailed entity relationships are not yet decided. "
                "Resolve the database open question before persistence implementation."
            )
        if database_decision.choice.lower() == "none":
            return "No primary database is required for the first release."
        return (
            f"The confirmed primary data-store direction is {database_decision.choice}. "
            "Detailed entities and relationships must be defined during implementation."
        )

    @staticmethod
    def _finish(lines: list[str]) -> str:
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _validate_file_map(files: OrderedDict[Path, str]) -> None:
        if not files:
            raise ValueError("PlanningGenerator produced no files")
        for path, content in files.items():
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Planning output path must be relative: {path}")
            if not content.strip():
                raise ValueError(f"Planning output is empty: {path}")
            if not content.endswith("\n"):
                raise ValueError(f"Planning output needs a trailing newline: {path}")
            if any(token in content for token in ("{{", "}}", "[problem]", "Feature 1")):
                raise ValueError(f"Unresolved template content in {path}")
