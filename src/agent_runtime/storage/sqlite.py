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
                    workflow_hash TEXT,
                    workflow_yaml TEXT,
                    workflow_steps_json TEXT,
                    input_hash TEXT,
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
                    last_error TEXT,
                    state_before_json TEXT,
                    state_after_json TEXT,
                    execution_index INTEGER,
                    started_at TEXT,
                    finished_at TEXT,
                    duration_ms INTEGER,
                    attempts INTEGER,
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
            self._ensure_runs_columns(conn)
            self._ensure_steps_columns(conn)

    def _ensure_steps_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(steps)").fetchall()}
        if "attempts" not in columns:
            conn.execute("ALTER TABLE steps ADD COLUMN attempts INTEGER")
        if "last_error" not in columns:
            conn.execute("ALTER TABLE steps ADD COLUMN last_error TEXT")
        if "state_before_json" not in columns:
            conn.execute("ALTER TABLE steps ADD COLUMN state_before_json TEXT")
        if "state_after_json" not in columns:
            conn.execute("ALTER TABLE steps ADD COLUMN state_after_json TEXT")
        if "execution_index" not in columns:
            conn.execute("ALTER TABLE steps ADD COLUMN execution_index INTEGER")

    def _ensure_runs_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        if "workflow_hash" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN workflow_hash TEXT")
        if "workflow_yaml" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN workflow_yaml TEXT")
        if "workflow_steps_json" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN workflow_steps_json TEXT")
        if "input_hash" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN input_hash TEXT")

    def create_run(self, run: Run) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (id, status, workflow_id, workflow_hash, workflow_yaml, workflow_steps_json, input_hash, created_at, started_at, completed_at, error, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.status,
                    run.workflow_id,
                    run.workflow_hash,
                    run.workflow_yaml,
                    json_dumps(run.workflow_steps) if run.workflow_steps else None,
                    run.input_hash,
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
                INSERT INTO steps (run_id, step_id, type, status, input_json, output_json, error, last_error, state_before_json, state_after_json, execution_index, started_at, finished_at, duration_ms, attempts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    step.step_id,
                    step.step_type,
                    step.status,
                    json_dumps(step.input) if step.input else None,
                    json_dumps(step.output) if step.output else None,
                    step.error,
                    step.last_error,
                    json_dumps(step.state_before) if step.state_before else None,
                    json_dumps(step.state_after) if step.state_after else None,
                    step.execution_index,
                    step.started_at,
                    step.finished_at,
                    step.duration_ms,
                    step.attempt_count,
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

            from ..core import Run
            run = Run(
                run_id=row["id"],
                workflow_id=row["workflow_id"],
                workflow_hash=row["workflow_hash"],
                workflow_yaml=row["workflow_yaml"],
                workflow_steps=json_loads(row["workflow_steps_json"]) if row["workflow_steps_json"] else None,
                input_hash=row["input_hash"],
                status=row["status"],
                created_at=row["created_at"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                error=row["error"],
                metadata=json_loads(row["metadata_json"]) if row["metadata_json"] else None,
            )
            return run

    def load_steps(self, run_id: str) -> list[StepExecution]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM steps WHERE run_id = ? ORDER BY execution_index ASC, id ASC",
                (run_id,),
            ).fetchall()
            steps: list[StepExecution] = []
            for row in rows:
                from ..core import StepExecution
                steps.append(
                    StepExecution(
                        step_id=row["step_id"],
                        step_type=row["type"],
                        status=row["status"],
                        started_at=row["started_at"],
                        finished_at=row["finished_at"],
                        input=json_loads(row["input_json"]) if row["input_json"] else None,
                        output=json_loads(row["output_json"]) if row["output_json"] else None,
                        error=row["error"],
                        last_error=row["last_error"],
                        state_before=json_loads(row["state_before_json"]) if row["state_before_json"] else None,
                        state_after=json_loads(row["state_after_json"]) if row["state_after_json"] else None,
                        duration_ms=row["duration_ms"],
                        attempt_count=row["attempts"],
                        execution_index=row["execution_index"],
                    )
                )
            return steps

    def load_latest_state(self, run_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM state_versions WHERE run_id = ? ORDER BY version DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"No state found for run: {run_id}")
            return json_loads(row["state_json"])

    def load_initial_state(self, run_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM state_versions WHERE run_id = ? ORDER BY version ASC LIMIT 1",
                (run_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"No state found for run: {run_id}")
            return json_loads(row["state_json"])

    def load_latest_state_version(self, run_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(version) as max_version FROM state_versions WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None or row["max_version"] is None:
                return 0
            return int(row["max_version"])

    def load_max_execution_index(self, run_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(execution_index) as max_execution_index FROM steps WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None or row["max_execution_index"] is None:
                return 0
            return int(row["max_execution_index"])
