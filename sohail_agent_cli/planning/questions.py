"""Deterministic PlanningAgent V1 question catalog and normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Callable

from .models import (
    ArchitectureComponent,
    DecisionRecord,
    OpenQuestion,
    PlanningContext,
    ProjectBrief,
    Requirement,
    TaskItem,
)


@dataclass(frozen=True)
class PlanningQuestion:
    """Metadata for one deterministic planning question."""

    question_id: str
    prompt: str
    answer_type: str
    required: bool
    destination: str
    options: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    condition: Callable[[dict[str, str]], bool] | None = None
    creates_decision: bool = False
    open_question_text: str | None = None

    def applies(self, category: str, answers: dict[str, str]) -> bool:
        category_matches = not self.categories or category in self.categories
        condition_matches = self.condition(answers) if self.condition else True
        return category_matches and condition_matches

    def validate_answer(self, answer: str) -> str:
        normalized = answer.strip()
        if not normalized and self.required:
            raise ValueError("An answer is required")
        if not normalized:
            return ""
        if self.answer_type in {"choice", "yes_no"}:
            allowed = {option.lower(): option for option in self.options}
            if normalized.lower() not in allowed:
                raise ValueError(f"Choose one of: {', '.join(self.options)}")
            return allowed[normalized.lower()]
        return normalized


QUESTION_CATALOG: tuple[PlanningQuestion, ...] = (
    PlanningQuestion(
        "Q-001",
        "Project name",
        "short_text",
        True,
        "project_name",
    ),
    PlanningQuestion(
        "Q-002",
        "Target users (comma-separated)",
        "list",
        True,
        "target_users",
    ),
    PlanningQuestion(
        "Q-003",
        "First-release scope (comma-separated outcomes)",
        "list",
        True,
        "first_release_scope",
    ),
    PlanningQuestion(
        "Q-004",
        "Explicitly out of scope (comma-separated, optional)",
        "list",
        False,
        "out_of_scope",
    ),
    PlanningQuestion(
        "Q-005",
        "Frontend approach",
        "choice",
        True,
        "frontend",
        ("React", "Next.js", "Vue", "server-rendered", "none", "undecided"),
        ("web_application",),
        creates_decision=True,
        open_question_text="Which frontend approach should the project use?",
    ),
    PlanningQuestion(
        "Q-006",
        "Backend approach",
        "choice",
        True,
        "backend",
        ("FastAPI", "Django", "Flask", "Node.js", "Go", "other", "undecided"),
        ("web_application", "api_service"),
        creates_decision=True,
        open_question_text="Which backend approach should the project use?",
    ),
    PlanningQuestion(
        "Q-007",
        "Primary database",
        "choice",
        False,
        "database",
        ("PostgreSQL", "MongoDB", "SQLite", "none", "other", "undecided"),
        creates_decision=True,
        open_question_text="Which primary database should the project use?",
    ),
    PlanningQuestion(
        "Q-008",
        "Authentication approach",
        "choice",
        False,
        "authentication",
        ("session", "JWT", "external identity provider", "none", "undecided"),
        ("web_application", "api_service"),
        creates_decision=True,
        open_question_text="Which authentication approach should the project use?",
    ),
    PlanningQuestion(
        "Q-009",
        "Is Docker required?",
        "yes_no",
        True,
        "docker",
        ("yes", "no", "undecided"),
        creates_decision=True,
        open_question_text="Is Docker required for the first release?",
    ),
    PlanningQuestion(
        "Q-010",
        "Is Kubernetes required?",
        "choice",
        True,
        "kubernetes",
        ("yes", "no", "later", "undecided"),
        condition=lambda answers: answers.get("docker", "").lower() in {"yes", "undecided"},
        creates_decision=True,
        open_question_text="Is Kubernetes required, deferred, or excluded?",
    ),
    PlanningQuestion(
        "Q-011",
        "Deployment target (optional; do not include credentials)",
        "short_text",
        False,
        "deployment_target",
        open_question_text="Which deployment target should be used?",
    ),
    PlanningQuestion(
        "Q-012",
        "Important quality requirements (comma-separated, optional)",
        "list",
        False,
        "quality_requirements",
    ),
)


def normalize_project_name(value: str) -> str:
    """Normalize a human project name without turning it into a package identifier."""
    collapsed = re.sub(r"\s+", " ", value.strip())
    return collapsed[:80]


def infer_project_name(goal: str) -> str:
    """Create a conservative display-name suggestion from the goal."""
    words = re.findall(r"[A-Za-z0-9]+", goal)
    stop_words = {"build", "create", "make", "develop", "an", "a", "the"}
    selected = [word for word in words if word.lower() not in stop_words][:4]
    return " ".join(selected).title() or "New Project"


def infer_project_category(goal: str) -> str:
    """Select only the question branch; this is not an architecture decision."""
    lowered = goal.lower()
    if any(token in lowered for token in ("cli", "command-line", "terminal tool")):
        return "cli_tool"
    if any(token in lowered for token in ("api", "service", "backend")) and not any(
        token in lowered for token in ("website", "web app", "ecommerce", "platform")
    ):
        return "api_service"
    if any(
        token in lowered
        for token in ("website", "web app", "ecommerce", "e-commerce", "platform", "store")
    ):
        return "web_application"
    return "generic_software"


def questions_for_category(
    category: str,
    answers: dict[str, str] | None = None,
) -> list[PlanningQuestion]:
    """Return applicable questions in stable catalog order."""
    answers = answers or {}
    return [question for question in QUESTION_CATALOG if question.applies(category, answers)]


def split_list(value: str) -> list[str]:
    """Split comma or newline separated human input."""
    return [
        item.strip(" -")
        for item in re.split(r"[,\n]+", value)
        if item.strip(" -")
    ]


def build_planning_context(
    goal: str,
    project_name: str,
    category: str,
    answers: dict[str, str],
    planning_date: date | None = None,
) -> PlanningContext:
    """Normalize confirmed answers into a complete V1 planning context."""
    planning_date = planning_date or date.today()
    brief = ProjectBrief(
        name=normalize_project_name(project_name),
        goal=goal.strip(),
        category=category,
        target_users=split_list(answers["target_users"]),
        first_release_scope=split_list(answers["first_release_scope"]),
        out_of_scope=split_list(answers.get("out_of_scope", "")),
        planning_date=planning_date,
    )

    open_questions = _build_open_questions(answers, category)
    decisions = _build_decisions(answers, category)
    requirements = _build_requirements(brief, answers, decisions)
    components = _build_components(brief, answers, decisions)
    tasks = _build_tasks(brief, answers, requirements, decisions, open_questions)
    decisions = [
        replace(
            decision,
            related_requirement_ids=[
                requirement.requirement_id
                for requirement in requirements
                if decision.decision_id in requirement.decision_ids
            ],
            related_task_ids=[
                task.task_id
                for task in tasks
                if decision.decision_id in task.decision_ids
            ],
        )
        for decision in decisions
    ]

    context = PlanningContext(
        brief=brief,
        requirements=requirements,
        architecture_components=components,
        tasks=tasks,
        decisions=decisions,
        assumptions=[
            "Planning files describe the first release unless a section says otherwise.",
            "Human review is required before implementation begins.",
        ],
        open_questions=open_questions,
        quality_goals=split_list(answers.get("quality_requirements", "")),
        deployment_summary=_deployment_summary(answers),
        authentication_summary=_authentication_summary(answers),
    )
    context.validate()
    return context


def _is_unresolved(value: str) -> bool:
    return not value.strip() or value.strip().lower() == "undecided"


def _build_open_questions(
    answers: dict[str, str],
    category: str,
) -> list[OpenQuestion]:
    candidates: list[str] = []
    for question in QUESTION_CATALOG:
        if (
            question.applies(category, answers)
            and question.open_question_text
            and _is_unresolved(answers.get(question.destination, ""))
        ):
            candidates.append(question.open_question_text)
    return [
        OpenQuestion(question_id=f"OQ-{index:03d}", text=text)
        for index, text in enumerate(dict.fromkeys(candidates), start=1)
    ]


def _decision_details(topic: str, choice: str) -> tuple[str, list[str], list[str], list[str]]:
    normalized = choice.lower()
    rationale_map = {
        "frontend": ["Provides the selected user-interface approach for the first release."],
        "backend": ["Provides the selected server-side application boundary."],
        "database": ["Matches the confirmed persistence direction for the first release."],
        "authentication": ["Defines how user identity will be represented and verified."],
        "deployment": ["Keeps the deployment scope explicit and reviewable."],
    }
    alternatives_map = {
        "frontend": ["React", "Next.js", "Vue", "server-rendered", "none"],
        "backend": ["FastAPI", "Django", "Flask", "Node.js", "Go", "other"],
        "database": ["PostgreSQL", "MongoDB", "SQLite", "none", "other"],
        "authentication": ["session", "JWT", "external identity provider", "none"],
        "deployment": ["Docker only", "Docker with Kubernetes", "no containers", "undecided"],
    }
    positives = [f"Creates a clear {topic} direction for requirements and task planning."]
    negatives = [f"The {topic} choice must be validated during implementation."]
    alternatives = [
        item for item in alternatives_map[topic] if item.lower() != normalized
    ]
    return rationale_map[topic][0], alternatives, positives, negatives


def _build_decisions(answers: dict[str, str], category: str) -> list[DecisionRecord]:
    candidates: list[tuple[str, str, str]] = []
    if category == "web_application" and not _is_unresolved(answers.get("frontend", "")):
        candidates.append(("frontend", "Select the frontend approach", answers["frontend"]))
    if category in {"web_application", "api_service"} and not _is_unresolved(
        answers.get("backend", "")
    ):
        candidates.append(("backend", "Select the backend approach", answers["backend"]))
    if not _is_unresolved(answers.get("database", "")):
        candidates.append(("database", "Select the primary database", answers["database"]))
    if category in {"web_application", "api_service"} and not _is_unresolved(
        answers.get("authentication", "")
    ):
        candidates.append(
            ("authentication", "Select the authentication approach", answers["authentication"])
        )

    docker = answers.get("docker", "undecided")
    kubernetes = answers.get("kubernetes", "not applicable")
    target = answers.get("deployment_target", "").strip()
    if docker.lower() != "undecided":
        if docker.lower() == "no":
            deployment_choice = "No container requirement for the first release"
        elif kubernetes.lower() == "yes":
            deployment_choice = "Docker with Kubernetes"
        elif kubernetes.lower() == "later":
            deployment_choice = "Docker for V1; Kubernetes deferred"
        elif kubernetes.lower() == "no":
            deployment_choice = "Docker without Kubernetes"
        else:
            deployment_choice = "Docker; Kubernetes remains undecided"
        if target:
            deployment_choice += f"; target: {target}"
        candidates.append(("deployment", "Select the deployment direction", deployment_choice))

    decisions: list[DecisionRecord] = []
    for index, (topic, title, choice) in enumerate(candidates, start=1):
        rationale, alternatives, positives, negatives = _decision_details(topic, choice)
        decisions.append(
            DecisionRecord(
                decision_id=f"DEC-{index:03d}",
                slug=topic,
                title=title,
                topic=topic,
                choice=choice,
                context=f"The project needs an explicit {topic} direction for the first release.",
                rationale=[rationale],
                alternatives=alternatives,
                positive_consequences=positives,
                negative_consequences=negatives,
            )
        )
    return decisions


def _build_requirements(
    brief: ProjectBrief,
    answers: dict[str, str],
    decisions: list[DecisionRecord],
) -> list[Requirement]:
    decision_by_topic = {decision.topic: decision.decision_id for decision in decisions}
    requirements: list[Requirement] = []
    for index, scope_item in enumerate(brief.first_release_scope, start=1):
        title = scope_item.rstrip(".").capitalize()
        requirements.append(
            Requirement(
                requirement_id=f"FR-{index:03d}",
                title=title,
                category="functional",
                priority="must",
                status="accepted",
                source="user",
                statement=f"The first release must support: {scope_item.rstrip('.')}.",
                acceptance=(
                    f"A reviewer can verify that {scope_item.rstrip('.').lower()} "
                    "works as agreed."
                ),
            )
        )

    nfr_statements = [
        (
            "Secret Management",
            "Production secrets must be supplied through runtime configuration.",
            "No production secret is committed to source control.",
        ),
        (
            "Failure Visibility",
            "Critical failures must be visible to operators without exposing sensitive data.",
            "Failures are logged with enough context for diagnosis and without credentials.",
        ),
    ]
    for quality in split_list(answers.get("quality_requirements", "")):
        nfr_statements.append(
            (
                quality.title(),
                f"The system should address the confirmed quality goal: {quality}.",
                f"The implementation documents and verifies its approach to {quality.lower()}.",
            )
        )
    for index, (title, statement, acceptance) in enumerate(nfr_statements, start=1):
        requirements.append(
            Requirement(
                requirement_id=f"NFR-{index:03d}",
                title=title,
                category="non_functional",
                priority="must" if index <= 2 else "should",
                status="accepted" if index <= 2 else "proposed",
                source="planning" if index <= 2 else "user",
                statement=statement,
                acceptance=acceptance,
            )
        )

    constraints: list[tuple[str, str, str]] = []
    docker = answers.get("docker", "undecided").lower()
    kubernetes = answers.get("kubernetes", "not applicable").lower()
    if docker == "yes":
        constraints.append(
            (
                "Containerization",
                "The first release requires Docker.",
                "A Docker-based local workflow is documented.",
            )
        )
    elif docker == "no":
        constraints.append(
            (
                "Containerization",
                "Docker is not required for the first release.",
                "V1 tasks do not depend on Docker.",
            )
        )
    if kubernetes == "later":
        constraints.append(
            (
                "Kubernetes Scope",
                "Kubernetes is deferred until after the first release.",
                "No V1 task requires Kubernetes.",
            )
        )
    elif kubernetes == "no":
        constraints.append(
            (
                "Kubernetes Scope",
                "Kubernetes is outside the first-release scope.",
                "No V1 task requires Kubernetes.",
            )
        )

    for index, (title, statement, acceptance) in enumerate(constraints, start=1):
        requirements.append(
            Requirement(
                requirement_id=f"CON-{index:03d}",
                title=title,
                category="constraint",
                priority="must",
                status="accepted",
                source="user",
                statement=statement,
                acceptance=acceptance,
                decision_ids=[
                    decision_by_topic["deployment"]
                ] if "deployment" in decision_by_topic else [],
            )
        )
    return requirements


def _build_components(
    brief: ProjectBrief,
    answers: dict[str, str],
    decisions: list[DecisionRecord],
) -> list[ArchitectureComponent]:
    decision_by_topic = {decision.topic: decision.decision_id for decision in decisions}
    components: list[ArchitectureComponent] = []
    frontend = answers.get("frontend", "")
    if brief.category == "web_application" and not _is_unresolved(frontend) and frontend != "none":
        components.append(
            ArchitectureComponent(
                name="Web Frontend",
                responsibilities=[
                    "Present the confirmed user-facing first-release flows.",
                    "Communicate with the backend through an explicit application boundary.",
                ],
                decision_ids=[decision_by_topic["frontend"]],
            )
        )
    backend = answers.get("backend", "")
    if brief.category in {"web_application", "api_service"} and not _is_unresolved(backend):
        components.append(
            ArchitectureComponent(
                name="Backend Application",
                responsibilities=[
                    "Own application rules and server-side validation.",
                    "Coordinate persistence and external integrations.",
                ],
                decision_ids=[decision_by_topic["backend"]],
            )
        )
    database = answers.get("database", "")
    if not _is_unresolved(database) and database != "none":
        components.append(
            ArchitectureComponent(
                name="Primary Data Store",
                responsibilities=[
                    "Persist the confirmed first-release data.",
                    "Provide the consistency guarantees required by the domain.",
                ],
                decision_ids=[decision_by_topic["database"]],
            )
        )
    if not components:
        components.append(
            ArchitectureComponent(
                name="Application",
                responsibilities=[
                    "Deliver the confirmed first-release scope.",
                    "Keep unresolved technical choices explicit.",
                ],
            )
        )
    return components


def _build_tasks(
    brief: ProjectBrief,
    answers: dict[str, str],
    requirements: list[Requirement],
    decisions: list[DecisionRecord],
    open_questions: list[OpenQuestion],
) -> list[TaskItem]:
    functional_ids = [
        requirement.requirement_id
        for requirement in requirements
        if requirement.category == "functional"
    ]
    nfr_ids = [
        requirement.requirement_id
        for requirement in requirements
        if requirement.category == "non_functional"
    ]
    constraint_ids = [
        requirement.requirement_id
        for requirement in requirements
        if requirement.category == "constraint"
    ]
    decision_ids = [decision.decision_id for decision in decisions]
    unresolved_technical = any(
        phrase in question.text.lower()
        for question in open_questions
        for phrase in ("frontend", "backend", "database")
    )

    tasks: list[TaskItem] = [
        TaskItem(
            task_id="T-001",
            title="Establish the application skeleton",
            status="blocked" if unresolved_technical else "ready",
            priority="P0",
            owner="unassigned",
            dependencies=[],
            requirement_ids=(nfr_ids[:1] + constraint_ids),
            decision_ids=decision_ids,
            objective=(
                "Create the initial component boundaries described by the accepted "
                "architecture."
            ),
            acceptance_criteria=[
                "The selected components can be started in a documented development workflow.",
                "Configuration contains no committed production secrets.",
            ],
            notes=["Resolve blocking technical open questions before implementation." ]
            if unresolved_technical
            else [],
        )
    ]

    previous = "T-001"
    for index, (requirement_id, scope_item) in enumerate(
        zip(functional_ids, brief.first_release_scope), start=2
    ):
        task_id = f"T-{index:03d}"
        tasks.append(
            TaskItem(
                task_id=task_id,
                title=f"Implement {scope_item.rstrip('.').lower()}",
                status="proposed",
                priority="P0",
                owner="unassigned",
                dependencies=[previous],
                requirement_ids=[requirement_id],
                decision_ids=decision_ids,
                objective=f"Deliver the first-release outcome: {scope_item.rstrip('.')}.",
                acceptance_criteria=[
                    next(
                        requirement.acceptance
                        for requirement in requirements
                        if requirement.requirement_id == requirement_id
                    )
                ],
            )
        )
        previous = task_id

    quality_task_id = f"T-{len(tasks) + 1:03d}"
    tasks.append(
        TaskItem(
            task_id=quality_task_id,
            title="Verify quality and safety requirements",
            status="proposed",
            priority="P1",
            owner="unassigned",
            dependencies=[previous],
            requirement_ids=nfr_ids,
            decision_ids=[],
            objective="Verify the agreed non-functional requirements for the first release.",
            acceptance_criteria=[
                "Each accepted non-functional requirement has documented verification evidence."
            ],
        )
    )

    deployment_decisions = [
        decision.decision_id for decision in decisions if decision.topic == "deployment"
    ]
    if answers.get("docker", "").lower() == "yes":
        tasks.append(
            TaskItem(
                task_id=f"T-{len(tasks) + 1:03d}",
                title="Prepare the confirmed deployment workflow",
                status="proposed",
                priority="P1",
                owner="unassigned",
                dependencies=[quality_task_id],
                requirement_ids=constraint_ids,
                decision_ids=deployment_decisions,
                objective="Prepare the deployment path confirmed for the first release.",
                acceptance_criteria=[
                    "The deployment workflow matches the accepted deployment decision.",
                    "The workflow is documented and reviewable.",
                ],
            )
        )
    return tasks


def _deployment_summary(answers: dict[str, str]) -> str:
    docker = answers.get("docker", "undecided").lower()
    kubernetes = answers.get("kubernetes", "not applicable").lower()
    target = answers.get("deployment_target", "").strip()
    if docker == "no":
        summary = "Docker is not required for the first release."
    elif docker == "yes" and kubernetes == "yes":
        summary = "The confirmed direction is Docker with Kubernetes."
    elif docker == "yes" and kubernetes == "later":
        summary = "Docker is required for V1; Kubernetes is deferred."
    elif docker == "yes" and kubernetes == "no":
        summary = "Docker is required for V1; Kubernetes is outside V1 scope."
    elif docker == "yes":
        summary = "Docker is required; Kubernetes remains undecided."
    else:
        summary = "Deployment containerization is not yet decided."
    if target:
        summary += f" The stated deployment target is {target}."
    return summary


def _authentication_summary(answers: dict[str, str]) -> str:
    authentication = answers.get("authentication", "").strip()
    if _is_unresolved(authentication):
        return "Authentication approach is not yet decided."
    if authentication.lower() == "none":
        return "Authentication is not required for the first release."
    return f"The confirmed authentication approach is {authentication}."
