from __future__ import annotations

"""File: src/agent_runtime/storage/base.py

Purpose:
Define abstract persistence contract for runtime runs/steps/state.

Description:
`Storage` specifies the durable operations required by executor, replay,
and inspection logic independent of concrete backend technology.
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import Run, StepExecution


class Storage(ABC):
    """Abstract storage API for runtime persistence.

    TODO(roadmap): Implement a PostgreSQL backend for team/production deployments.
      The abstract interface is already backend-agnostic; a PostgresStorage
      subclass should be a drop-in replacement for SQLiteStorage.
    TODO(roadmap): Consider a remote-capable storage adapter (e.g., S3 + DynamoDB)
      for cloud-native deployments where SQLite files aren't practical.
    TODO(roadmap): Storage is currently single-user — one SQLite file
      per project with no authentication or access control.  For team use:
      1. Add a `user_id` / `tenant_id` column to the runs table.
      2. Add row-level filtering in all read paths so users only see their runs.
      3. For a shared PostgreSQL backend, use connection-pool scoping or
         Row-Level Security policies.
      4. Consider an auth middleware layer in a future HTTP API surface.
    """

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """Group multiple storage operations into an atomic unit.

        Within the yielded block, all write operations (``create_run``,
        ``update_run_status``, ``append_step``, ``save_state``) are
        deferred to a single commit.  If any operation raises, all
        writes in the block are rolled back.

        The default implementation is a no-op pass-through — backends
        that support transactions (e.g. SQLite, PostgreSQL) override
        this to provide real atomicity.

        Safe to nest: inner ``transaction()`` calls are absorbed by the
        outermost transaction (savepoints are not used).
        """
        yield

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

    @abstractmethod
    def list_runs(self, limit: int = 20) -> list[Run]:
        """Load most recent runs ordered by creation time descending."""
        raise NotImplementedError
