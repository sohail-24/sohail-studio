"""Execution planner for the multi-agent system."""

from __future__ import annotations

import uuid
from typing import Any

from .models import (
    AgentCapability,
    ExecutionPlan,
    PlanStep,
    Task,
    TaskStatus,
)
from .registry import AgentRegistry


class ExecutionPlanner:
    """
    Plans execution of complex tasks by breaking them into steps.
    
    The planner analyzes tasks and creates execution plans that may
    involve multiple agents working in sequence or parallel.
    """
    
    def __init__(self, registry: AgentRegistry) -> None:
        """
        Initialize the execution planner.
        
        Args:
            registry: The agent registry to use for planning
        """
        self._registry = registry
    
    def plan(self, task: Task) -> ExecutionPlan:
        """
        Create an execution plan for a task.
        
        Args:
            task: The task to plan for
        
        Returns:
            An execution plan with steps
        """
        plan_id = str(uuid.uuid4())[:8]
        
        # Route based on task type
        planners = {
            "inspect_repo": self._plan_repo_inspection,
            "dockerize": self._plan_dockerization,
            "generate_k8s": self._plan_k8s_generation,
            "generate_cicd": self._plan_cicd_generation,
            "generate_docs": self._plan_doc_generation,
            "interview_notes": self._plan_interview_prep,
            "scaffold": self._plan_scaffolding,
            "full_setup": self._plan_full_setup,
        }
        
        planner = planners.get(task.task_type, self._plan_simple)
        steps = planner(task)
        
        plan = ExecutionPlan(
            plan_id=plan_id,
            original_task=task.description,
            steps=steps,
        )
        
        task.plan = plan
        task.status = TaskStatus.PLANNED
        
        return plan
    
    def _plan_simple(self, task: Task) -> list[PlanStep]:
        """Create a simple single-step plan."""
        return [
            PlanStep(
                step_id="step_1",
                description=task.description,
                agent_name="auto",
                inputs=task.inputs,
            )
        ]
    
    def _plan_repo_inspection(self, task: Task) -> list[PlanStep]:
        """Plan repository inspection task."""
        path = task.inputs.get("path", ".")
        
        return [
            PlanStep(
                step_id="analyze_repo",
                description="Analyze repository structure and detect stack",
                agent_name="repo_inspector",
                inputs={"path": path, "deep_analysis": True},
            ),
        ]
    
    def _plan_dockerization(self, task: Task) -> list[PlanStep]:
        """Plan Docker generation task."""
        path = task.inputs.get("path", ".")
        
        return [
            PlanStep(
                step_id="detect_stack",
                description="Detect technology stack",
                agent_name="repo_inspector",
                inputs={"path": path, "analysis_only": True},
            ),
            PlanStep(
                step_id="generate_docker",
                description="Generate Docker configuration",
                agent_name="docker_agent",
                inputs={"path": path},
                depends_on=["detect_stack"],
            ),
        ]
    
    def _plan_k8s_generation(self, task: Task) -> list[PlanStep]:
        """Plan Kubernetes generation task."""
        path = task.inputs.get("path", ".")
        
        return [
            PlanStep(
                step_id="detect_stack",
                description="Detect technology stack",
                agent_name="repo_inspector",
                inputs={"path": path, "analysis_only": True},
            ),
            PlanStep(
                step_id="generate_k8s",
                description="Generate Kubernetes manifests",
                agent_name="k8s_agent",
                inputs={"path": path},
                depends_on=["detect_stack"],
            ),
        ]
    
    def _plan_cicd_generation(self, task: Task) -> list[PlanStep]:
        """Plan CI/CD generation task."""
        path = task.inputs.get("path", ".")
        
        return [
            PlanStep(
                step_id="detect_stack",
                description="Detect technology stack",
                agent_name="repo_inspector",
                inputs={"path": path, "analysis_only": True},
            ),
            PlanStep(
                step_id="generate_cicd",
                description="Generate CI/CD workflows",
                agent_name="cicd_agent",
                inputs={"path": path},
                depends_on=["detect_stack"],
            ),
        ]
    
    def _plan_doc_generation(self, task: Task) -> list[PlanStep]:
        """Plan documentation generation task."""
        path = task.inputs.get("path", ".")
        
        return [
            PlanStep(
                step_id="analyze_repo",
                description="Analyze repository for documentation",
                agent_name="repo_inspector",
                inputs={"path": path, "analysis_only": True},
            ),
            PlanStep(
                step_id="generate_docs",
                description="Generate project documentation",
                agent_name="docs_agent",
                inputs={"path": path},
                depends_on=["analyze_repo"],
            ),
        ]
    
    def _plan_interview_prep(self, task: Task) -> list[PlanStep]:
        """Plan interview preparation task."""
        path = task.inputs.get("path", ".")
        
        return [
            PlanStep(
                step_id="analyze_repo",
                description="Deep repository analysis",
                agent_name="repo_inspector",
                inputs={"path": path, "analysis_only": True},
            ),
            PlanStep(
                step_id="generate_notes",
                description="Generate interview notes",
                agent_name="interview_agent",
                inputs={"path": path},
                depends_on=["analyze_repo"],
            ),
        ]
    
    def _plan_scaffolding(self, task: Task) -> list[PlanStep]:
        """Plan scaffolding task."""
        project_type = task.inputs.get("project_type", "python")
        output_path = task.inputs.get("output_path", ".")
        
        return [
            PlanStep(
                step_id="scaffold",
                description=f"Scaffold {project_type} project",
                agent_name="scaffold_agent",
                inputs={
                    "project_type": project_type,
                    "output_path": output_path,
                    **task.inputs,
                },
            ),
        ]
    
    def _plan_full_setup(self, task: Task) -> list[PlanStep]:
        """Plan full DevOps setup (all generators)."""
        path = task.inputs.get("path", ".")
        
        return [
            PlanStep(
                step_id="analyze_repo",
                description="Comprehensive repository analysis",
                agent_name="repo_inspector",
                inputs={"path": path, "analysis_only": True},
            ),
            PlanStep(
                step_id="generate_docker",
                description="Generate Docker configuration",
                agent_name="docker_agent",
                inputs={"path": path},
                depends_on=["analyze_repo"],
            ),
            PlanStep(
                step_id="generate_k8s",
                description="Generate Kubernetes manifests",
                agent_name="k8s_agent",
                inputs={"path": path},
                depends_on=["analyze_repo"],
            ),
            PlanStep(
                step_id="generate_cicd",
                description="Generate CI/CD workflows",
                agent_name="cicd_agent",
                inputs={"path": path},
                depends_on=["analyze_repo"],
            ),
            PlanStep(
                step_id="generate_docs",
                description="Generate documentation",
                agent_name="docs_agent",
                inputs={"path": path},
                depends_on=["analyze_repo"],
            ),
        ]
