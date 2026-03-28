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
from datetime import datetime

from ..errors import StorageValidationError
from ..observability import percentile
from ..schema_versioning import STORAGE_SCHEMA_VERSION_CURRENT
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
        an implicit BEGIN / COMMIT pair and serialised through ``_lock``.
        Inside a transaction block the statement participates in the outer
        transaction (the lock is already held by ``transaction()``).
        """
        auto = not self._in_transaction
        if auto:
            self._lock.acquire()
        try:
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
        finally:
            if auto:
                self._lock.release()

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

        TODO(eng): Use SAVEPOINT for nested transactions if callers
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

    def __enter__(self) -> "SQLiteStorage":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

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
                token_usage_json TEXT,
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
            CREATE TABLE IF NOT EXISTS runtime_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._ensure_runs_columns(self._conn)
        self._ensure_steps_columns(self._conn)
        self._ensure_storage_schema_version(self._conn)

    def _ensure_storage_schema_version(self, conn: sqlite3.Connection) -> None:
        """Initialize and verify storage schema version contract."""
        row = conn.execute(
            "SELECT value FROM runtime_metadata WHERE key = ?",
            ("storage_schema_version",),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO runtime_metadata (key, value) VALUES (?, ?)",
                ("storage_schema_version", STORAGE_SCHEMA_VERSION_CURRENT),
            )
            return

        stored_version = row["value"]
        if stored_version != STORAGE_SCHEMA_VERSION_CURRENT:
            raise StorageValidationError(
                "Unsupported storage schema version "
                f"{stored_version}. This runtime requires {STORAGE_SCHEMA_VERSION_CURRENT}."
            )

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
        if "token_usage_json" not in columns:
            conn.execute("ALTER TABLE steps ADD COLUMN token_usage_json TEXT")

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
                duration_ms, handler_duration_ms, tool_duration_ms, attempts, agent_trace_json,
                token_usage_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json_dumps(step.token_usage) if step.token_usage is not None else None,
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
            token_usage_raw = row["token_usage_json"] if "token_usage_json" in row.keys() else None
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
                    token_usage=json_loads(token_usage_raw) if token_usage_raw else None,
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

    def build_observability_report(self, top_steps: int = 10) -> Dict[str, Any]:
        """Build aggregate support metrics for fast root-cause analysis."""
        run_rows = self._conn.execute(
            "SELECT id, status, started_at, completed_at, error FROM runs"
        ).fetchall()
        total_runs = len(run_rows)
        status_counts: Dict[str, int] = {}
        run_durations_ms: list[float] = []
        failed_runs = 0

        for row in run_rows:
            status = str(row["status"] or "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1
            if status == "FAILED":
                failed_runs += 1

            started = row["started_at"]
            completed = row["completed_at"]
            if started and completed:
                try:
                    start_dt = datetime.fromisoformat(started)
                    end_dt = datetime.fromisoformat(completed)
                    run_durations_ms.append(max(0.0, (end_dt - start_dt).total_seconds() * 1000.0))
                except ValueError:
                    pass

        step_rows = self._conn.execute(
            "SELECT step_id, status, duration_ms, error, last_error, token_usage_json FROM steps"
        ).fetchall()
        step_agg: Dict[str, Dict[str, Any]] = {}
        error_classes: Dict[str, int] = {}
        total_tokens = 0
        total_steps = 0
        failed_steps = 0

        for row in step_rows:
            total_steps += 1
            step_id = str(row["step_id"] or "unknown")
            status = str(row["status"] or "UNKNOWN")
            duration_ms = row["duration_ms"]
            error = row["error"] or row["last_error"]

            agg = step_agg.setdefault(step_id, {
                "executions": 0,
                "failed": 0,
                "durations": [],
            })
            agg["executions"] += 1
            if isinstance(duration_ms, (int, float)):
                agg["durations"].append(float(duration_ms))

            if status == "FAILED":
                failed_steps += 1
                agg["failed"] += 1

            if isinstance(error, str) and error:
                error_class = error.split(":", 1)[0].strip() or "UnknownError"
                error_classes[error_class] = error_classes.get(error_class, 0) + 1

            token_usage_raw = row["token_usage_json"]
            if token_usage_raw:
                try:
                    usage = json_loads(token_usage_raw)
                    tokens = usage.get("total_tokens")
                    if tokens is None:
                        prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0))
                        completion = usage.get("completion_tokens", usage.get("output_tokens", 0))
                        tokens = int(prompt or 0) + int(completion or 0)
                    total_tokens += int(tokens or 0)
                except Exception:  # noqa: BLE001
                    pass

        per_step = []
        for step_id, agg in step_agg.items():
            executions = int(agg["executions"])
            failed = int(agg["failed"])
            durations = agg["durations"]
            per_step.append({
                "step_id": step_id,
                "executions": executions,
                "failed": failed,
                "failure_rate": (failed / executions) if executions else 0.0,
                "avg_duration_ms": (sum(durations) / len(durations)) if durations else None,
                "p95_duration_ms": percentile(durations, 95) if durations else None,
            })

        per_step.sort(key=lambda item: (item["failed"], item["failure_rate"], item["executions"]), reverse=True)

        top_errors = sorted(error_classes.items(), key=lambda item: item[1], reverse=True)

        return {
            "runs": {
                "total": total_runs,
                "failed": failed_runs,
                "failure_rate": (failed_runs / total_runs) if total_runs else 0.0,
                "status_counts": status_counts,
                "avg_duration_ms": (sum(run_durations_ms) / len(run_durations_ms)) if run_durations_ms else None,
                "p95_duration_ms": percentile(run_durations_ms, 95) if run_durations_ms else None,
            },
            "steps": {
                "total": total_steps,
                "failed": failed_steps,
                "failure_rate": (failed_steps / total_steps) if total_steps else 0.0,
                "top_failing": per_step[: max(1, int(top_steps))],
            },
            "llm": {
                "total_tokens": total_tokens,
            },
            "errors": {
                "top_classes": [
                    {"error_class": name, "count": count}
                    for name, count in top_errors[: max(1, int(top_steps))]
                ],
            },
        }
