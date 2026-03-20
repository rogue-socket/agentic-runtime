from __future__ import annotations

"""File: src/agent_runtime/storage/sqlite.py

Purpose:
Implement SQLite-backed persistence for runs, steps, and state versions.

Description:
Provides concrete `Storage` operations used by executor, replay, and
inspection paths, including schema bootstrap and lightweight migrations.

Key Components:
- `SQLiteStorage`
- table creation/migration helpers
- CRUD operations for run/step/state records

Dependencies:
- `sqlite3` and JSON helpers from `agent_runtime.utils`

Inputs/Outputs:
- Input: runtime dataclasses and run identifiers
- Output: durable records and reconstructed runtime dataclasses

Side Effects:
- Creates/updates SQLite database schema and rows on disk.
"""

from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional, TYPE_CHECKING
import sqlite3
import threading

from ..storage.base import Storage
from ..utils import json_dumps, json_loads

if TYPE_CHECKING:
    from ..core import Run, StepExecution


class SQLiteStorage(Storage):
    """SQLite-backed implementation of the runtime storage contract.

    Uses a single persistent connection per instance.  All write operations
    participate in the current transaction when called inside a
    ``with storage.transaction():`` block; otherwise each operation auto-commits
    individually (backward-compatible with pre-transaction callers).

    Thread safety: a ``threading.Lock`` serialises all connection access.
    The lock is non-reentrant for writes, but ``transaction()`` itself is
    reentrant — nested calls are absorbed by the outermost transaction.
    """

    def __init__(self, db_path: str) -> None:
        """Initialize storage, open persistent connection, and ensure schema."""
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = self._open_connection()
        self._in_transaction = False
        self._init_db()

    # -- connection management ------------------------------------------------

    def _open_connection(self) -> sqlite3.Connection:
        """Open a persistent SQLite connection with row access by column name.

        ``isolation_level=None`` puts the connection in *autocommit* mode so
        that we can manage BEGIN / COMMIT / ROLLBACK explicitly rather than
        relying on Python's implicit transaction handling.
        """
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # WAL journal mode permits concurrent readers while a write
        # transaction is open and is more resilient to crashes.
        conn.execute("PRAGMA journal_mode=WAL")
        # Enforce foreign-key constraints at the engine level.
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _conn_execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a single SQL statement on the persistent connection.

        If called outside a ``transaction()`` block the statement is wrapped in
        an implicit BEGIN / COMMIT pair.  Inside a transaction block the
        statement participates in the outer transaction.
        """
        auto = not self._in_transaction
        if auto:
            self._conn.execute("BEGIN")
        try:
            cursor = self._conn.execute(sql, params)
            if auto:
                self._conn.execute("COMMIT")
            return cursor
        except BaseException:
            if auto:
                self._conn.execute("ROLLBACK")
            raise

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """Group multiple writes into a single atomic SQLite transaction.

        * All ``create_run``, ``update_run_status``, ``append_step``, and
          ``save_state`` calls inside the block share one BEGIN / COMMIT.
        * On any exception the entire batch is rolled back — no partial
          writes are visible.
        * Reentrant: nested ``transaction()`` calls are no-ops absorbed by the
          outermost transaction.  SQLite does not support true nested
          transactions; savepoints could be added later if needed.

        TODO(future): Use SAVEPOINT for nested transactions if callers
          ever need independent rollback of inner blocks.
        """
        if self._in_transaction:
            # Already inside an outer transaction — pass through.
            yield
            return

        with self._lock:
            self._conn.execute("BEGIN")
            self._in_transaction = True
            try:
                yield
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            finally:
                self._in_transaction = False

    def close(self) -> None:
        """Close the persistent connection.

        Safe to call multiple times.  Any uncommitted transaction is
        rolled back automatically by SQLite on connection close.
        """
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
            self._conn = None  # type: ignore[assignment]

    # -- schema bootstrap -----------------------------------------------------

    def _init_db(self) -> None:
        """Create base tables and backfill newer columns if missing."""
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                workflow_version TEXT,
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
                handler_duration_ms INTEGER,
                tool_duration_ms INTEGER,
                attempts INTEGER,
                agent_trace_json TEXT,
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
        self._ensure_runs_columns(self._conn)
        self._ensure_steps_columns(self._conn)

    def _ensure_steps_columns(self, conn: sqlite3.Connection) -> None:
        """Add missing `steps` table columns for backward compatibility."""
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
        if "handler_duration_ms" not in columns:
            conn.execute("ALTER TABLE steps ADD COLUMN handler_duration_ms INTEGER")
        if "tool_duration_ms" not in columns:
            conn.execute("ALTER TABLE steps ADD COLUMN tool_duration_ms INTEGER")
        if "agent_trace_json" not in columns:
            conn.execute("ALTER TABLE steps ADD COLUMN agent_trace_json TEXT")

    def _ensure_runs_columns(self, conn: sqlite3.Connection) -> None:
        """Add missing `runs` table columns for backward compatibility."""
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        if "workflow_hash" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN workflow_hash TEXT")
        if "workflow_version" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN workflow_version TEXT")
        if "workflow_yaml" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN workflow_yaml TEXT")
        if "workflow_steps_json" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN workflow_steps_json TEXT")
        if "input_hash" not in columns:
            conn.execute("ALTER TABLE runs ADD COLUMN input_hash TEXT")

    def create_run(self, run: Run) -> None:
        """Insert initial run metadata row."""
        self._conn_execute(
            """
            INSERT INTO runs (id, status, workflow_id, workflow_version, workflow_hash, workflow_yaml, workflow_steps_json, input_hash, created_at, started_at, completed_at, error, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.status,
                run.workflow_id,
                run.workflow_version,
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
        """Update run status and optional timestamps/error."""
        self._conn_execute(
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
        """Insert one step execution record."""
        self._conn_execute(
            """
            INSERT INTO steps (
                run_id, step_id, type, status, input_json, output_json, error, last_error,
                state_before_json, state_after_json, execution_index, started_at, finished_at,
                duration_ms, handler_duration_ms, tool_duration_ms, attempts, agent_trace_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                step.step_id,
                step.step_type,
                step.status,
                json_dumps(step.input) if step.input is not None else None,
                json_dumps(step.output) if step.output is not None else None,
                step.error,
                step.last_error,
                json_dumps(step.state_before) if step.state_before is not None else None,
                json_dumps(step.state_after) if step.state_after is not None else None,
                step.execution_index,
                step.started_at,
                step.finished_at,
                step.duration_ms,
                step.handler_duration_ms,
                step.tool_duration_ms,
                step.attempt_count,
                json_dumps(step.agent_trace) if step.agent_trace is not None else None,
            ),
        )

    def save_state(self, run_id: str, step_id: Optional[str], version: int, state: Dict[str, Any]) -> None:
        """Insert one versioned state snapshot row."""
        from ..utils import utc_now

        self._conn_execute(
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
        """Load run metadata row and convert to `Run` dataclass."""
        row = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"Run not found: {run_id}")

        from ..core import Run
        run = Run(
            run_id=row["id"],
            workflow_id=row["workflow_id"],
            workflow_version=row["workflow_version"],
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
        """Load ordered step execution rows for a run id."""
        rows = self._conn.execute(
            "SELECT * FROM steps WHERE run_id = ? ORDER BY execution_index ASC, id ASC",
            (run_id,),
        ).fetchall()
        steps: list[StepExecution] = []
        for row in rows:
            from ..core import StepExecution
            agent_trace_raw = row["agent_trace_json"] if "agent_trace_json" in row.keys() else None
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
                    handler_duration_ms=row["handler_duration_ms"],
                    tool_duration_ms=row["tool_duration_ms"],
                    attempt_count=row["attempts"],
                    execution_index=row["execution_index"],
                    agent_trace=json_loads(agent_trace_raw) if agent_trace_raw else None,
                )
            )
        return steps

    def load_latest_state(self, run_id: str) -> Dict[str, Any]:
        """Load most recent state snapshot by version."""
        row = self._conn.execute(
            "SELECT state_json FROM state_versions WHERE run_id = ? ORDER BY version DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"No state found for run: {run_id}")
        return json_loads(row["state_json"])

    def load_initial_state(self, run_id: str) -> Dict[str, Any]:
        """Load first persisted state snapshot by version."""
        row = self._conn.execute(
            "SELECT state_json FROM state_versions WHERE run_id = ? ORDER BY version ASC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"No state found for run: {run_id}")
        return json_loads(row["state_json"])

    def load_latest_state_version(self, run_id: str) -> int:
        """Return max state version number for a run."""
        row = self._conn.execute(
            "SELECT MAX(version) as max_version FROM state_versions WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None or row["max_version"] is None:
            return 0
        return int(row["max_version"])

    def load_max_execution_index(self, run_id: str) -> int:
        """Return max persisted execution index for a run."""
        row = self._conn.execute(
            "SELECT MAX(execution_index) as max_execution_index FROM steps WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None or row["max_execution_index"] is None:
            return 0
        return int(row["max_execution_index"])

    def list_runs(self, limit: int = 20) -> list:
        """Load most recent runs ordered by creation time descending."""
        rows = self._conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        runs = []
        for row in rows:
            from ..core import Run
            runs.append(Run(
                run_id=row["id"],
                workflow_id=row["workflow_id"],
                workflow_version=row["workflow_version"],
                workflow_hash=row["workflow_hash"],
                workflow_yaml=None,  # skip large payload for listing
                workflow_steps=None,
                input_hash=row["input_hash"],
                status=row["status"],
                created_at=row["created_at"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                error=row["error"],
            ))
        return runs
