"""Base worker for safe task execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any


class WorkerSafetyLevel(Enum):
    """Safety level for worker operations."""
    READ_ONLY = auto()      # Only read operations
    WRITE_SAFE = auto()     # Write to new files only
    WRITE_UNSAFE = auto()   # Can overwrite existing files
    EXECUTE_SAFE = auto()   # Execute safe commands
    EXECUTE_UNSAFE = auto() # Execute any commands


@dataclass
class WorkerResult:
    """Result of a worker operation."""
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    
    @classmethod
    def success_result(
        cls,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> WorkerResult:
        """Create a successful result."""
        return cls(
            success=True,
            message=message,
            data=data or {},
        )
    
    @classmethod
    def failure_result(
        cls,
        message: str,
        error: str | None = None,
    ) -> WorkerResult:
        """Create a failure result."""
        return cls(
            success=False,
            message=message,
            error=error,
        )


class BaseWorker(ABC):
    """
    Abstract base class for workers.
    
    Workers provide safe execution of operations like
    file operations and shell commands.
    """
    
    def __init__(
        self,
        safety_level: WorkerSafetyLevel = WorkerSafetyLevel.READ_ONLY,
        dry_run: bool = False,
    ) -> None:
        """
        Initialize the worker.
        
        Args:
            safety_level: The safety level for operations
            dry_run: If True, don't actually execute operations
        """
        self.safety_level = safety_level
        self.dry_run = dry_run
    
    @abstractmethod
    async def execute(self, operation: str, **kwargs: Any) -> WorkerResult:
        """
        Execute an operation.
        
        Args:
            operation: The operation to execute
            **kwargs: Operation-specific arguments
        
        Returns:
            The result of the operation
        """
        pass
    
    def can_execute(self, required_level: WorkerSafetyLevel) -> bool:
        """
        Check if this worker can execute at the required safety level.
        
        Args:
            required_level: The required safety level
        
        Returns:
            True if the worker can execute
        """
        # Safety levels are ordered from safest to most dangerous
        level_order = [
            WorkerSafetyLevel.READ_ONLY,
            WorkerSafetyLevel.WRITE_SAFE,
            WorkerSafetyLevel.WRITE_UNSAFE,
            WorkerSafetyLevel.EXECUTE_SAFE,
            WorkerSafetyLevel.EXECUTE_UNSAFE,
        ]
        
        current_idx = level_order.index(self.safety_level)
        required_idx = level_order.index(required_level)
        
        return current_idx >= required_idx
    
    def _check_safety(self, required_level: WorkerSafetyLevel) -> None:
        """
        Check safety level and raise if insufficient.
        
        Args:
            required_level: The required safety level
        
        Raises:
            PermissionError: If safety level is insufficient
        """
        if not self.can_execute(required_level):
            raise PermissionError(
                f"Worker safety level {self.safety_level.name} "
                f"is insufficient for {required_level.name} operation"
            )
