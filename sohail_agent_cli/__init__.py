"""Sohail-Agent-CLI: A local AI engineering assistant."""

__version__ = "2.0.0"
__author__ = "Sohail"
__description__ = "A local AI engineering assistant for DevOps, code generation, and repository automation"

from sohail_agent_cli.core import (
    Task,
    TaskResult,
    TaskStatus,
    AgentCapability,
    ExecutionPlan,
    PlanStep,
    AgentRegistry,
    TaskRouter,
    ExecutionPlanner,
)

from sohail_agent_cli.providers import (
    BaseProvider,
    ProviderConfig,
    GenerationRequest,
    GenerationResult,
    OllamaProvider,
    MockProvider,
)

from sohail_agent_cli.workers import (
    BaseWorker,
    WorkerResult,
    WorkerSafetyLevel,
    FileWorker,
    ShellWorker,
)

from sohail_agent_cli.analyzers import (
    StackDetector,
    DetectedStack,
    StackType,
    RepoAnalyzer,
    RepoAnalysis,
    DeploymentReadinessAnalyzer,
    ReadinessReport,
)

__all__ = [
    "__version__",
    "__author__",
    "__description__",
    # Core
    "Task",
    "TaskResult",
    "TaskStatus",
    "AgentCapability",
    "ExecutionPlan",
    "PlanStep",
    "AgentRegistry",
    "TaskRouter",
    "ExecutionPlanner",
    # Providers
    "BaseProvider",
    "ProviderConfig",
    "GenerationRequest",
    "GenerationResult",
    "OllamaProvider",
    "MockProvider",
    # Workers
    "BaseWorker",
    "WorkerResult",
    "WorkerSafetyLevel",
    "FileWorker",
    "ShellWorker",
    # Analyzers
    "StackDetector",
    "DetectedStack",
    "StackType",
    "RepoAnalyzer",
    "RepoAnalysis",
    "DeploymentReadinessAnalyzer",
    "ReadinessReport",
]
