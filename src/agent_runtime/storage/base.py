from __future__ import annotations

"""File: src/agent_runtime/storage/base.py

Purpose:
Define abstract persistence contract for runtime runs/steps/state.

Description:
`Storage` specifies the durable operations required by executor, replay,
and inspection logic independent of concrete backend technology.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import Run, StepExecution


class Storage(ABC):
    """Abstract storage API for runtime persistence."""

    @abstractmethod
    def create_run(self, run: Run) -> None:
        """Persist a newly created run record."""
        raise NotImplementedError

    @abstractmethod
    def update_run_status(
        self,
        run_id: str,
        status: str,
        error: Optional[str],
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> None:
        """Update run status and optional terminal/start metadata."""
        raise NotImplementedError

    @abstractmethod
    def append_step(self, run_id: str, step: StepExecution) -> None:
        """Persist one step execution record for a run."""
        raise NotImplementedError

    @abstractmethod
    def save_state(self, run_id: str, step_id: Optional[str], version: int, state: Dict[str, Any]) -> None:
        """Persist one versioned state snapshot."""
        raise NotImplementedError

    @abstractmethod
    def load_run(self, run_id: str) -> Run:
        """Load run metadata for a run id."""
        raise NotImplementedError

    @abstractmethod
    def load_steps(self, run_id: str) -> list[StepExecution]:
        """Load ordered step execution history for a run."""
        raise NotImplementedError

    @abstractmethod
    def load_latest_state(self, run_id: str) -> Dict[str, Any]:
        """Load latest state snapshot for a run."""
        raise NotImplementedError

    @abstractmethod
    def load_initial_state(self, run_id: str) -> Dict[str, Any]:
        """Load initial state snapshot for a run."""
        raise NotImplementedError

    @abstractmethod
    def load_latest_state_version(self, run_id: str) -> int:
        """Load maximum persisted state version integer for a run."""
        raise NotImplementedError

    @abstractmethod
    def load_max_execution_index(self, run_id: str) -> int:
        """Load maximum step execution index integer for a run."""
        raise NotImplementedError
