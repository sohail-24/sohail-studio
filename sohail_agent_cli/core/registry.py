"""Agent registry for the multi-agent system."""

from __future__ import annotations

from typing import Any

from .models import AgentCapability, AgentInfo, Task


class AgentRegistry:
    """
    Registry for managing available agents and their capabilities.
    
    The registry maintains a mapping of agent names to their information
    and provides methods for finding agents by capability.
    """
    
    def __init__(self) -> None:
        """Initialize an empty agent registry."""
        self._agents: dict[str, AgentInfo] = {}
        self._capability_index: dict[AgentCapability, list[str]] = {
            cap: [] for cap in AgentCapability
        }
    
    def register(self, agent_info: AgentInfo) -> None:
        """
        Register an agent with the registry.
        
        Args:
            agent_info: Information about the agent to register
        """
        self._agents[agent_info.name] = agent_info
        
        # Update capability index
        for cap in agent_info.capabilities:
            if agent_info.name not in self._capability_index[cap]:
                self._capability_index[cap].append(agent_info.name)
    
    def unregister(self, agent_name: str) -> None:
        """
        Unregister an agent from the registry.
        
        Args:
            agent_name: Name of the agent to unregister
        """
        if agent_name not in self._agents:
            return
        
        agent_info = self._agents[agent_name]
        
        # Remove from capability index
        for cap in agent_info.capabilities:
            if agent_name in self._capability_index[cap]:
                self._capability_index[cap].remove(agent_name)
        
        # Remove from agents dict
        del self._agents[agent_name]
    
    def get(self, agent_name: str) -> AgentInfo | None:
        """
        Get information about a registered agent.
        
        Args:
            agent_name: Name of the agent
        
        Returns:
            AgentInfo if found, None otherwise
        """
        return self._agents.get(agent_name)
    
    def list_agents(self) -> list[AgentInfo]:
        """List all registered agents."""
        return list(self._agents.values())
    
    def find_by_capability(self, capability: AgentCapability) -> list[AgentInfo]:
        """
        Find all agents that have a specific capability.
        
        Args:
            capability: The capability to search for
        
        Returns:
            List of agents with the capability
        """
        agent_names = self._capability_index.get(capability, [])
        return [self._agents[name] for name in agent_names if name in self._agents]
    
    def find_for_task(self, task: Task) -> list[AgentInfo]:
        """
        Find all agents that can handle a given task.
        
        Args:
            task: The task to find agents for
        
        Returns:
            List of agents that can handle the task
        """
        if not task.required_capabilities:
            return self.list_agents()
        
        # Find agents that have ALL required capabilities
        candidates: set[str] | None = None
        
        for cap in task.required_capabilities:
            agents_with_cap = set(self._capability_index.get(cap, []))
            if candidates is None:
                candidates = agents_with_cap
            else:
                candidates &= agents_with_cap
        
        if not candidates:
            return []
        
        return [self._agents[name] for name in candidates if name in self._agents]
    
    def get_capabilities(self) -> list[AgentCapability]:
        """Get all registered capabilities."""
        return [
            cap for cap, agents in self._capability_index.items() 
            if len(agents) > 0
        ]
    
    def is_registered(self, agent_name: str) -> bool:
        """Check if an agent is registered."""
        return agent_name in self._agents
    
    def __len__(self) -> int:
        """Return the number of registered agents."""
        return len(self._agents)
    
    def __contains__(self, agent_name: str) -> bool:
        """Check if an agent name is registered."""
        return agent_name in self._agents
