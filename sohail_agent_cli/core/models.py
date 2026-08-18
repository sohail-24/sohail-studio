"""Core models for the multi-agent task system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable


class TaskStatus(Enum):
    """Status of a task in the execution pipeline."""
    PENDING = auto()
    PLANNED = auto()
    ROUTED = auto()
    EXECUTING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class AgentCapability(Enum):
    """Capabilities that agents can advertise."""
    REPO_ANALYSIS = "repo_analysis"
    STACK_DETECTION = "stack_detection"
    DOCKER_GENERATION = "docker_generation"
    K8S_GENERATION = "k8s_generation"
    CICD_GENERATION = "cicd_generation"
    DOC_GENERATION = "doc_generation"
    INTERVIEW_PREP = "interview_prep"
    SCAFFOLDING = "scaffolding"
    CODE_REVIEW = "code_review"
    FILE_OPERATIONS = "file_operations"
    SHELL_EXECUTION = "shell_execution"


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    step_id: str
    description: str
    agent_name: str
    inputs: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    completed: bool = False
    error: str | None = None


@dataclass
class ExecutionPlan:
    """A plan for executing a complex task across multiple agents."""
    plan_id: str
    original_task: str
    steps: list[PlanStep] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    def get_ready_steps(self) -> list[PlanStep]:
        """Get steps that are ready to execute (dependencies met)."""
        completed_ids = {s.step_id for s in self.steps if s.completed}
        return [
            s for s in self.steps 
            if not s.completed and all(d in completed_ids for d in s.depends_on)
        ]
    
    def is_complete(self) -> bool:
        """Check if all steps are completed."""
        return all(s.completed for s in self.steps)
    
    def has_failures(self) -> bool:
        """Check if any step has failed."""
        return any(s.error is not None for s in self.steps)


@dataclass
class Task:
    """A task to be executed by the multi-agent system."""
    task_id: str
    task_type: str
    description: str
    inputs: dict[str, Any] = field(default_factory=dict)
    required_capabilities: list[AgentCapability] = field(default_factory=list)
    priority: int = 5  # 1-10, higher is more important
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    plan: ExecutionPlan | None = None
    assigned_agent: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert task to dictionary."""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "description": self.description,
            "inputs": self.inputs,
            "required_capabilities": [c.value for c in self.required_capabilities],
            "priority": self.priority,
            "status": self.status.name,
            "created_at": self.created_at.isoformat(),
            "assigned_agent": self.assigned_agent,
        }


@dataclass
class TaskResult:
    """Result of executing a task."""
    task_id: str
    success: bool
    message: str
    outputs: dict[str, Any] = field(default_factory=dict)
    generated_files: list[Path] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    execution_time_ms: float = 0.0
    agent_name: str | None = None
    error: str | None = None
    
    @classmethod
    def success_result(
        cls,
        task_id: str,
        message: str,
        outputs: dict[str, Any] | None = None,
        generated_files: list[Path] | None = None,
    ) -> TaskResult:
        """Create a successful result."""
        return cls(
            task_id=task_id,
            success=True,
            message=message,
            outputs=outputs or {},
            generated_files=generated_files or [],
        )
    
    @classmethod
    def failure_result(
        cls,
        task_id: str,
        message: str,
        error: str | None = None,
    ) -> TaskResult:
        """Create a failure result."""
        return cls(
            task_id=task_id,
            success=False,
            message=message,
            error=error,
        )


@dataclass
class AgentInfo:
    """Information about a registered agent."""
    name: str
    description: str
    capabilities: list[AgentCapability]
    version: str = "1.0.0"
    config: dict[str, Any] = field(default_factory=dict)
    
    def has_capability(self, capability: AgentCapability) -> bool:
        """Check if agent has a specific capability."""
        return capability in self.capabilities
    
    def can_handle_task(self, task: Task) -> bool:
        """Check if agent can handle a task based on required capabilities."""
        return all(self.has_capability(c) for c in task.required_capabilities)
