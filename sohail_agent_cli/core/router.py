"""Task router for the multi-agent system."""

from __future__ import annotations

import random
from typing import Any

from .models import AgentInfo, Task, TaskStatus
from .registry import AgentRegistry


class TaskRouter:
    """
    Routes tasks to appropriate agents based on capabilities and routing strategy.
    
    The router uses the agent registry to find candidates and applies
    routing strategies to select the best agent for a task.
    """
    
    def __init__(self, registry: AgentRegistry) -> None:
        """
        Initialize the task router.
        
        Args:
            registry: The agent registry to use for finding agents
        """
        self._registry = registry
    
    def route(
        self, 
        task: Task, 
        strategy: str = "capability_match",
    ) -> AgentInfo | None:
        """
        Route a task to an appropriate agent.
        
        Args:
            task: The task to route
            strategy: Routing strategy to use
                - "capability_match": Select agent with best capability match
                - "random": Random selection from capable agents
                - "first_available": Select first capable agent
        
        Returns:
            The selected agent, or None if no agent can handle the task
        """
        candidates = self._registry.find_for_task(task)
        
        if not candidates:
            return None
        
        if strategy == "random":
            return random.choice(candidates)
        elif strategy == "first_available":
            return candidates[0]
        elif strategy == "capability_match":
            return self._select_by_capability_match(task, candidates)
        else:
            raise ValueError(f"Unknown routing strategy: {strategy}")
    
    def _select_by_capability_match(
        self, 
        task: Task, 
        candidates: list[AgentInfo],
    ) -> AgentInfo:
        """
        Select the agent with the best capability match.
        
        Prefers agents that have exactly the required capabilities
        over agents with additional capabilities.
        
        Args:
            task: The task to route
            candidates: List of candidate agents
        
        Returns:
            The best matching agent
        """
        if not candidates:
            raise ValueError("No candidate agents provided")
        
        if len(candidates) == 1:
            return candidates[0]
        
        required = set(task.required_capabilities)
        
        # Score each candidate
        scored: list[tuple[AgentInfo, float]] = []
        for agent in candidates:
            agent_caps = set(agent.capabilities)
            
            # Calculate match score
            # Higher score = better match (fewer extra capabilities)
            extra_caps = len(agent_caps - required)
            match_score = 1.0 / (1 + extra_caps)
            
            scored.append((agent, match_score))
        
        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        
        return scored[0][0]
    
    def can_route(self, task: Task) -> bool:
        """
        Check if a task can be routed to any agent.
        
        Args:
            task: The task to check
        
        Returns:
            True if at least one agent can handle the task
        """
        candidates = self._registry.find_for_task(task)
        return len(candidates) > 0
    
    def get_routing_options(self, task: Task) -> list[AgentInfo]:
        """
        Get all agents that could handle a task.
        
        Args:
            task: The task to check
        
        Returns:
            List of agents that can handle the task
        """
        return self._registry.find_for_task(task)
    
    def assign_task(self, task: Task, strategy: str = "capability_match") -> bool:
        """
        Assign a task to an agent and update the task.
        
        Args:
            task: The task to assign
            strategy: Routing strategy
        
        Returns:
            True if assignment was successful
        """
        agent = self.route(task, strategy)
        
        if agent is None:
            task.status = TaskStatus.FAILED
            return False
        
        task.assigned_agent = agent.name
        task.status = TaskStatus.ROUTED
        return True
