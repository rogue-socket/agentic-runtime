from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING
import sqlite3

from ..storage.base import Storage
from ..utils import json_dumps, json_loads

if TYPE_CHECKING:
    from ..core import Run, StepExecution


class SQLiteStorage(Storage):
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT,
                    metadata_json TEXT
                );
                CREATE TABLE IF NOT EXISTS steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_json TEXT,
                    output_json TEXT,
                    error TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    duration_ms INTEGER,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );
                CREATE TABLE IF NOT EXISTS state_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    step_id TEXT,
                    version INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                );
                """
            )

    def create_run(self, run: Run) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (id, status, workflow_id, created_at, started_at, completed_at, error, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.status,
                    run.workflow_id,
                    run.created_at,
                    run.started_at,
                    run.completed_at,
                    run.error,
                    json_dumps(run.metadata) if run.metadata else None,
                ),
            )

    def update_run_status(
        self,
        run_id: str,
        status: str,
        error: Optional[str],
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status = ?, error = ?,
                    started_at = COALESCE(started_at, ?),
                    completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (status, error, started_at, completed_at, run_id),
            )

    def append_step(self, run_id: str, step: StepExecution) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO steps (run_id, step_id, type, status, input_json, output_json, error, started_at, finished_at, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    step.step_id,
                    step.step_type,
                    step.status,
                    json_dumps(step.input) if step.input else None,
                    json_dumps(step.output) if step.output else None,
                    step.error,
                    step.started_at,
                    step.finished_at,
                    step.duration_ms,
                ),
            )

    def save_state(self, run_id: str, step_id: Optional[str], version: int, state: Dict[str, Any]) -> None:
        from ..utils import utc_now

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO state_versions (run_id, step_id, version, state_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    step_id,
                    version,
                    json_dumps(state),
                    utc_now().isoformat(),
                ),
            )

    def load_run(self, run_id: str) -> Run:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise ValueError(f"Run not found: {run_id}")

            run = Run(
                run_id=row["id"],
                workflow_id=row["workflow_id"],
                status=row["status"],
                created_at=row["created_at"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                error=row["error"],
                metadata=json_loads(row["metadata_json"]) if row["metadata_json"] else None,
            )
            return run
