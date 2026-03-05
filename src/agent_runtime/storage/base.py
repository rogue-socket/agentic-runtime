from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import Run, StepExecution


class Storage(ABC):
    @abstractmethod
    def create_run(self, run: Run) -> None:
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
        raise NotImplementedError

    @abstractmethod
    def append_step(self, run_id: str, step: StepExecution) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_state(self, run_id: str, step_id: Optional[str], version: int, state: Dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def load_run(self, run_id: str) -> Run:
        raise NotImplementedError

    @abstractmethod
    def load_steps(self, run_id: str) -> list[StepExecution]:
        raise NotImplementedError

    @abstractmethod
    def load_latest_state(self, run_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def load_initial_state(self, run_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def load_latest_state_version(self, run_id: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def load_max_execution_index(self, run_id: str) -> int:
        raise NotImplementedError
