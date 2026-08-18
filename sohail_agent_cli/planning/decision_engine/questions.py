"""Reusable Engineering Decision Engine V1 question groups."""

from __future__ import annotations

from .models import Question, QuestionGroup, QuestionOption


def option(value: str, label: str, description: str = "") -> QuestionOption:
    """Create a question option with compact call sites."""
    return QuestionOption(value=value, label=label, description=description)


def project_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="project",
        title="Project",
        description="Project identity and product intent.",
        questions=(
            Question(
                "EDE-Q-001",
                "project.name",
                "Project name",
                "text",
                required=True,
            ),
            Question(
                "EDE-Q-002",
                "project.goal",
                "Project goal",
                "text",
                required=True,
            ),
            Question(
                "EDE-Q-003",
                "project.target_users",
                "Target users (comma-separated)",
                "text",
                required=True,
            ),
            Question(
                "EDE-Q-004",
                "project.project_type",
                "Project type",
                "single_choice",
                required=True,
                options=(
                    option("web_application", "Web application"),
                    option("api_service", "API service"),
                    option("cli_tool", "CLI tool"),
                    option("generic_software", "Generic software"),
                ),
                default="web_application",
            ),
            Question(
                "EDE-Q-005",
                "project.expected_users",
                "Expected users for the first release",
                "number",
                required=False,
                default=100,
            ),
        ),
    )


def architecture_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="architecture",
        title="Architecture",
        description="Top-level application architecture decisions.",
        questions=(
            Question(
                "EDE-Q-006",
                "architecture.pattern",
                "Architecture pattern",
                "single_choice",
                required=True,
                options=(
                    option("monolith", "Monolith"),
                    option("modular_monolith", "Modular monolith"),
                    option("microservices", "Microservices"),
                    option("serverless", "Serverless"),
                    option("event_driven", "Event-driven"),
                    option("undecided", "Undecided"),
                ),
                default="modular_monolith",
            ),
        ),
    )


def frontend_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="frontend",
        title="Frontend",
        description="User interface technology decisions.",
        questions=(
            Question(
                "EDE-Q-007",
                "frontend.framework",
                "Frontend framework",
                "single_choice",
                required=True,
                options=(
                    option("React", "React"),
                    option("Next.js", "Next.js"),
                    option("Vue", "Vue"),
                    option("server-rendered", "Server-rendered"),
                    option("none", "None"),
                    option("undecided", "Undecided"),
                ),
                default="Next.js",
            ),
        ),
    )


def backend_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="backend",
        title="Backend",
        description="Server-side application decisions.",
        questions=(
            Question(
                "EDE-Q-008",
                "backend.framework",
                "Backend framework",
                "single_choice",
                required=True,
                options=(
                    option("FastAPI", "FastAPI"),
                    option("Django", "Django"),
                    option("Flask", "Flask"),
                    option("Node.js", "Node.js"),
                    option("Go", "Go"),
                    option("other", "Other"),
                    option("undecided", "Undecided"),
                ),
                default="FastAPI",
            ),
        ),
    )


def database_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="database",
        title="Database",
        description="Persistence decisions.",
        questions=(
            Question(
                "EDE-Q-009",
                "database.primary_database",
                "Primary database",
                "single_choice",
                required=True,
                options=(
                    option("PostgreSQL", "PostgreSQL"),
                    option("MongoDB", "MongoDB"),
                    option("SQLite", "SQLite"),
                    option("none", "None"),
                    option("other", "Other"),
                    option("undecided", "Undecided"),
                ),
                default="PostgreSQL",
            ),
        ),
    )


def authentication_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="authentication",
        title="Authentication",
        description="Identity verification decisions.",
        questions=(
            Question(
                "EDE-Q-010",
                "authentication.approach",
                "Authentication approach",
                "single_choice",
                required=True,
                options=(
                    option("session", "Session"),
                    option("JWT", "JWT"),
                    option("external identity provider", "External identity provider"),
                    option("none", "None"),
                    option("undecided", "Undecided"),
                ),
                default="session",
            ),
        ),
    )


def infrastructure_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="infrastructure",
        title="Infrastructure",
        description="Infrastructure and runtime decisions.",
        questions=(
            Question(
                "EDE-Q-011",
                "infrastructure.deployment_target",
                "Deployment target (optional; do not include credentials)",
                "text",
                required=False,
                default="managed container platform",
            ),
        ),
    )


def cloud_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="cloud",
        title="Cloud",
        description="Cloud provider decisions.",
        questions=(
            Question(
                "EDE-Q-012",
                "cloud.provider",
                "Cloud provider",
                "single_choice",
                required=False,
                options=(
                    option("AWS", "AWS"),
                    option("Azure", "Azure"),
                    option("GCP", "GCP"),
                    option("none", "None"),
                    option("undecided", "Undecided"),
                ),
                default="undecided",
            ),
        ),
    )


def container_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="container",
        title="Container",
        description="Containerization decisions.",
        questions=(
            Question(
                "EDE-Q-013",
                "container.docker_required",
                "Is Docker required?",
                "boolean",
                required=True,
                default=True,
            ),
            Question(
                "EDE-Q-014",
                "container.kubernetes",
                "Is Kubernetes required?",
                "single_choice",
                required=True,
                options=(
                    option("yes", "Yes"),
                    option("no", "No"),
                    option("later", "Later"),
                    option("undecided", "Undecided"),
                ),
                default="later",
            ),
        ),
    )


def ci_cd_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="ci_cd",
        title="CI/CD",
        description="Automation workflow decisions.",
        questions=(
            Question(
                "EDE-Q-015",
                "ci_cd.provider",
                "CI/CD provider",
                "single_choice",
                required=False,
                options=(
                    option("GitHub Actions", "GitHub Actions"),
                    option("GitLab CI", "GitLab CI"),
                    option("none", "None"),
                    option("undecided", "Undecided"),
                ),
                default="GitHub Actions",
            ),
        ),
    )


def monitoring_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="monitoring",
        title="Monitoring",
        description="Operational visibility decisions.",
        questions=(
            Question(
                "EDE-Q-016",
                "monitoring.enabled",
                "Is monitoring required?",
                "boolean",
                required=False,
                default=True,
            ),
        ),
    )


def security_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="security",
        title="Security",
        description="Security baseline decisions.",
        questions=(
            Question(
                "EDE-Q-017",
                "security.baseline",
                "Security baseline",
                "single_choice",
                required=True,
                options=(
                    option("basic", "Basic"),
                    option("standard", "Standard"),
                    option("strict", "Strict"),
                    option("undecided", "Undecided"),
                ),
                default="standard",
            ),
        ),
    )


def features_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="features",
        title="Features",
        description="First-release feature boundaries.",
        questions=(
            Question(
                "EDE-Q-018",
                "features.first_release_scope",
                "First-release scope (comma-separated outcomes)",
                "text",
                required=True,
            ),
            Question(
                "EDE-Q-019",
                "features.out_of_scope",
                "Explicitly out of scope (comma-separated, optional)",
                "text",
                required=False,
            ),
        ),
    )


def notifications_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="notifications",
        title="Notifications",
        description="Messaging channel decisions.",
        questions=(
            Question(
                "EDE-Q-020",
                "notifications.channels",
                "Notification channels",
                "multi_choice",
                required=False,
                options=(
                    option("email", "Email"),
                    option("sms", "SMS"),
                    option("push", "Push"),
                    option("in_app", "In-app"),
                    option("none", "None"),
                ),
                default=("email",),
            ),
        ),
    )


def testing_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="testing",
        title="Testing",
        description="Quality strategy decisions.",
        questions=(
            Question(
                "EDE-Q-021",
                "testing.strategy",
                "Testing strategy",
                "multi_choice",
                required=True,
                options=(
                    option("unit", "Unit"),
                    option("integration", "Integration"),
                    option("e2e", "End-to-end"),
                    option("security", "Security"),
                ),
                default=("unit", "integration"),
            ),
        ),
    )


def documentation_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="documentation",
        title="Documentation",
        description="Documentation output decisions.",
        questions=(
            Question(
                "EDE-Q-022",
                "documentation.level",
                "Documentation level",
                "single_choice",
                required=True,
                options=(
                    option("basic", "Basic"),
                    option("standard", "Standard"),
                    option("detailed", "Detailed"),
                ),
                default="standard",
            ),
        ),
    )


def custom_requirements_group() -> QuestionGroup:
    return QuestionGroup(
        group_id="custom_requirements",
        title="Custom Requirements",
        description="Arbitrary engineering requirements for future agents.",
        questions=(
            Question(
                "EDE-Q-023",
                "custom_requirements.items",
                "Custom engineering requirements (comma-separated, optional)",
                "text",
                required=False,
            ),
        ),
    )


def get_default_question_groups() -> tuple[QuestionGroup, ...]:
    """Return the stable V1 Engineering Decision Engine question catalog."""
    return (
        project_group(),
        architecture_group(),
        frontend_group(),
        backend_group(),
        database_group(),
        authentication_group(),
        infrastructure_group(),
        cloud_group(),
        container_group(),
        ci_cd_group(),
        monitoring_group(),
        security_group(),
        features_group(),
        notifications_group(),
        testing_group(),
        documentation_group(),
        custom_requirements_group(),
    )


DEFAULT_QUESTION_GROUPS = get_default_question_groups()
