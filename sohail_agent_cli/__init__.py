"""Sohail-Agent-CLI: A local AI engineering assistant."""

__version__ = "2.0.0"
__author__ = "Sohail"
__description__ = "A local AI engineering assistant for DevOps, code generation, and repository automation"

from sohail_agent_cli.analyzers import (
    DeploymentReadinessAnalyzer,
    DetectedStack,
    ReadinessReport,
    RepoAnalysis,
    RepoAnalyzer,
    StackDetector,
    StackType,
)
from sohail_agent_cli.core import (
    AgentCapability,
    AgentRegistry,
    ExecutionPlan,
    ExecutionPlanner,
    PlanStep,
    Task,
    TaskResult,
    TaskRouter,
    TaskStatus,
)
from sohail_agent_cli.providers import (
    BaseProvider,
    GenerationRequest,
    GenerationResult,
    MockProvider,
    OllamaProvider,
    ProviderConfig,
)
from sohail_agent_cli.workers import (
    BaseWorker,
    FileWorker,
    ShellWorker,
    WorkerResult,
    WorkerSafetyLevel,
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
