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
from collections import defaultdict
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import yaml

from ..errors import StorageValidationError
from ..observability import percentile
from ..schema_versioning import STORAGE_SCHEMA_VERSION_CURRENT
from ..storage.base import Storage
from ..utils import json_dumps, json_loads

if TYPE_CHECKING:
    from ..core import Run, StepExecution

_HEALTH_WEIGHTS: Dict[str, float] = {
    "ads": 0.28,
    "opr": 0.16,
    "one_minus_porr": 0.14,
    "one_minus_htr": 0.12,
    "recovery": 0.10,
    "one_minus_ece": 0.08,
    "one_minus_nis": 0.06,
    "latency": 0.06,
}


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
        try:
            self._init_db()
        except BaseException:
            self._conn.close()
            raise

    # -- connection management ------------------------------------------------

    def _open_connection(self) -> sqlite3.Connection:
        """Open a persistent SQLite connection with row access by column name.

        ``isolation_level=None`` puts the connection in *autocommit* mode so
        that we can manage BEGIN / COMMIT / ROLLBACK explicitly rather than
        relying on Python's implicit transaction handling. ``check_same_thread=False``
        lets the worker-thread sync→async bridge reuse a connection opened on
        another thread; ``self._lock`` serialises all access.
        """
        conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
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
        self._check_open()
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

    def _check_open(self) -> None:
        """Raise if the storage connection has been closed."""
        if self._conn is None:
            raise RuntimeError("SQLiteStorage is closed")

    def close(self) -> None:
        """Close the persistent connection.

        Safe to call multiple times.  Any uncommitted transaction is
        rolled back automatically by SQLite on connection close.

        """
        with self._lock:
            self._close_unlocked()

    def _close_unlocked(self) -> None:
        """Inner close without locking — called by close() under the lock."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
            self._conn = None  # type: ignore[assignment]

    def __enter__(self) -> "SQLiteStorage":
        """Function implementation."""
        return self

    def __exit__(self, *exc_info: Any) -> None:
        """Function implementation."""
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
                model_name TEXT,
                next_step_resolved TEXT,
                side_effects_json TEXT,
                cost_usd REAL,
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
        # Indexes on foreign key columns — SQLite does not auto-create these.
        self._conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_steps_run_id ON steps(run_id);
            CREATE INDEX IF NOT EXISTS idx_state_versions_run_id ON state_versions(run_id);
            """
        )

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
        if "model_name" not in columns:
            conn.execute("ALTER TABLE steps ADD COLUMN model_name TEXT")
        if "next_step_resolved" not in columns:
            conn.execute("ALTER TABLE steps ADD COLUMN next_step_resolved TEXT")
        if "side_effects_json" not in columns:
            conn.execute("ALTER TABLE steps ADD COLUMN side_effects_json TEXT")
        if "cost_usd" not in columns:
            conn.execute("ALTER TABLE steps ADD COLUMN cost_usd REAL")

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
                token_usage_json, model_name, next_step_resolved, side_effects_json, cost_usd
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                step.model_name,
                step.next_step_resolved,
                json_dumps(step.side_effects) if step.side_effects is not None else None,
                step.cost_usd,
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
        with self._lock:
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
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steps WHERE run_id = ? ORDER BY execution_index ASC, id ASC",
                (run_id,),
            ).fetchall()
        from ..core import StepExecution
        steps: list[StepExecution] = []
        for row in rows:
            rkeys = row.keys()
            agent_trace_raw = row["agent_trace_json"] if "agent_trace_json" in rkeys else None
            token_usage_raw = row["token_usage_json"] if "token_usage_json" in rkeys else None
            side_effects_raw = row["side_effects_json"] if "side_effects_json" in rkeys else None
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
                    model_name=row["model_name"] if "model_name" in rkeys else None,
                    next_step_resolved=row["next_step_resolved"] if "next_step_resolved" in rkeys else None,
                    side_effects=json_loads(side_effects_raw) if side_effects_raw else None,
                    cost_usd=row["cost_usd"] if "cost_usd" in rkeys else None,
                )
            )
        return steps

    def load_latest_state(self, run_id: str) -> Dict[str, Any]:
        """Load most recent state snapshot by version."""
        with self._lock:
            row = self._conn.execute(
                "SELECT state_json FROM state_versions WHERE run_id = ? ORDER BY version DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"No state found for run: {run_id}")
        return json_loads(row["state_json"])

    def load_initial_state(self, run_id: str) -> Dict[str, Any]:
        """Load first persisted state snapshot by version."""
        with self._lock:
            row = self._conn.execute(
                "SELECT state_json FROM state_versions WHERE run_id = ? ORDER BY version ASC LIMIT 1",
                (run_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"No state found for run: {run_id}")
        return json_loads(row["state_json"])

    def load_latest_state_version(self, run_id: str) -> int:
        """Return max state version number for a run."""
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(version) as max_version FROM state_versions WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None or row["max_version"] is None:
            return 0
        return int(row["max_version"])

    def load_max_execution_index(self, run_id: str) -> int:
        """Return max persisted execution index for a run."""
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(execution_index) as max_execution_index FROM steps WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None or row["max_execution_index"] is None:
            return 0
        return int(row["max_execution_index"])

    def list_runs(self, limit: int = 20) -> list:
        """Load most recent runs ordered by creation time descending."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        from ..core import Run
        runs = []
        for row in rows:
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

    @staticmethod
    def _parse_iso_timestamp(raw: Any) -> Optional[datetime]:
        """Function implementation."""
        if not isinstance(raw, str) or not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _pick_metadata_value(metadata: Dict[str, Any], keys: list[str]) -> tuple[Any, bool]:
        """Function implementation."""
        if not isinstance(metadata, dict):
            return None, False
        for key in keys:
            if key in metadata:
                return metadata[key], True
        return None, False

    @staticmethod
    def _parse_bool(value: Any) -> Optional[bool]:
        """Function implementation."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "t", "yes", "y", "1"}:
                return True
            if lowered in {"false", "f", "no", "n", "0"}:
                return False
        return None

    @staticmethod
    def _parse_confidence(value: Any) -> Optional[float]:
        """Function implementation."""
        if not isinstance(value, (int, float)):
            return None
        conf = float(value)
        if conf < 0.0:
            return None
        if conf <= 1.0:
            return conf
        if conf <= 100.0:
            return conf / 100.0
        return None

    @classmethod
    def _extract_confidence_values(cls, value: Any, depth: int = 0) -> list[float]:
        """Function implementation."""
        if depth > 4:
            return []
        out: list[float] = []
        if isinstance(value, dict):
            for key, child in value.items():
                key_l = str(key).lower()
                if "confidence" in key_l or key_l.endswith("_probability") or key_l == "probability":
                    parsed = cls._parse_confidence(child)
                    if parsed is not None:
                        out.append(parsed)
                out.extend(cls._extract_confidence_values(child, depth + 1))
        elif isinstance(value, list):
            for child in value:
                out.extend(cls._extract_confidence_values(child, depth + 1))
        return out

    @staticmethod
    def _extract_step_meta(workflow_yaml: Optional[str]) -> Dict[str, Dict[str, Any]]:
        """Function implementation."""
        if not workflow_yaml:
            return {}
        try:
            raw = yaml.safe_load(workflow_yaml) or {}
        except Exception:  # noqa: BLE001
            return {}
        steps = raw.get("steps")
        if not isinstance(steps, list):
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                continue
            step_id = step.get("id")
            if not isinstance(step_id, str) or not step_id:
                continue
            out[step_id] = {
                "step_index": idx,
                "step_type": str(step.get("type", "unknown") or "unknown"),
                "agent_id": step.get("agent") if isinstance(step.get("agent"), str) else None,
                "tool_name": step.get("tool") if isinstance(step.get("tool"), str) else None,
            }
        return out

    @staticmethod
    def _classify_input(initial_state: Optional[Dict[str, Any]], metadata: Dict[str, Any]) -> str:
        """Function implementation."""
        value, found = SQLiteStorage._pick_metadata_value(metadata, ["input_class", "input_type", "segment"])
        if found and isinstance(value, str) and value.strip():
            return value.strip()

        if not isinstance(initial_state, dict):
            return "__unknown__"
        inputs = initial_state.get("inputs")
        if not isinstance(inputs, dict) or not inputs:
            return "__empty__"
        keys = sorted(str(k) for k in inputs.keys())
        return ",".join(keys)

    @staticmethod
    def _compute_ece(samples: list[tuple[float, bool]], bins: int = 10) -> tuple[Optional[float], list[Dict[str, Any]]]:
        """Function implementation."""
        if not samples:
            return None, []

        bucket_counts = [0 for _ in range(bins)]
        bucket_success = [0 for _ in range(bins)]
        bucket_conf_sum = [0.0 for _ in range(bins)]

        for conf, success in samples:
            if conf < 0.0:
                conf = 0.0
            if conf > 1.0:
                conf = 1.0
            idx = min(int(conf * bins), bins - 1)
            bucket_counts[idx] += 1
            bucket_conf_sum[idx] += conf
            if success:
                bucket_success[idx] += 1

        total = len(samples)
        ece = 0.0
        bin_stats: list[Dict[str, Any]] = []
        for idx in range(bins):
            count = bucket_counts[idx]
            if count <= 0:
                continue
            avg_conf = bucket_conf_sum[idx] / count
            accuracy = bucket_success[idx] / count
            contrib = (count / total) * abs(accuracy - avg_conf)
            ece += contrib
            bin_stats.append({
                "bin": idx,
                "count": count,
                "avg_confidence": avg_conf,
                "accuracy": accuracy,
                "abs_gap": abs(accuracy - avg_conf),
            })
        return ece, bin_stats

    @staticmethod
    def _safe_rate(num: int, den: int) -> Optional[float]:
        """Function implementation."""
        if den <= 0:
            return None
        return num / den

    @staticmethod
    def _score_latency(p95_ms: Optional[float], target_ms: int) -> Optional[float]:
        """Function implementation."""
        if p95_ms is None:
            return None
        if p95_ms <= 0:
            return 1.0
        return max(0.0, min(1.0, float(target_ms) / float(p95_ms)))

    def build_observability_report(
        self,
        top_steps: int = 10,
        window_days: int = 7,
        latency_target_ms: int = 5000,
    ) -> Dict[str, Any]:
        """Build run-level, diagnostic, and health metrics for product observability."""
        top_n = max(1, int(top_steps))
        window_days = max(1, int(window_days))
        latency_target_ms = max(1, int(latency_target_ms))

        run_rows = self._conn.execute(
            """
            SELECT id, status, workflow_id, input_hash, workflow_yaml,
                   created_at, started_at, completed_at, error, metadata_json
            FROM runs
            """
        ).fetchall()

        initial_rows = self._conn.execute(
            """
            SELECT sv.run_id, sv.state_json
            FROM state_versions sv
            JOIN (
                SELECT run_id, MIN(version) AS min_version
                FROM state_versions
                GROUP BY run_id
            ) first_state
              ON first_state.run_id = sv.run_id
             AND first_state.min_version = sv.version
            """
        ).fetchall()
        initial_by_run: Dict[str, Dict[str, Any]] = {}
        for row in initial_rows:
            try:
                initial_by_run[str(row["run_id"])] = json_loads(row["state_json"])
            except Exception:  # noqa: BLE001
                continue

        step_rows = self._conn.execute(
            """
            SELECT run_id, step_id, type, status, duration_ms, error, last_error,
                   token_usage_json, output_json, execution_index
            FROM steps
            ORDER BY run_id ASC, execution_index ASC, id ASC
            """
        ).fetchall()

        run_records: Dict[str, Dict[str, Any]] = {}
        run_timestamps: list[datetime] = []
        status_counts: Dict[str, int] = {}
        run_durations_ms: list[float] = []
        failed_runs = 0

        for row in run_rows:
            run_id = str(row["id"])
            status = str(row["status"] or "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1
            if status == "FAILED":
                failed_runs += 1

            created_at = self._parse_iso_timestamp(row["created_at"])
            started_at = self._parse_iso_timestamp(row["started_at"])
            completed_at = self._parse_iso_timestamp(row["completed_at"])
            ts = created_at or started_at or completed_at
            if ts is not None:
                run_timestamps.append(ts)

            duration_ms: Optional[float] = None
            if started_at is not None and completed_at is not None:
                duration_ms = max(0.0, (completed_at - started_at).total_seconds() * 1000.0)
                run_durations_ms.append(duration_ms)

            metadata: Dict[str, Any] = {}
            metadata_raw = row["metadata_json"]
            if metadata_raw:
                try:
                    parsed = json_loads(metadata_raw)
                    if isinstance(parsed, dict):
                        metadata = parsed
                except Exception:  # noqa: BLE001
                    metadata = {}

            run_records[run_id] = {
                "run_id": run_id,
                "status": status,
                "workflow_id": str(row["workflow_id"] or "unknown"),
                "input_hash": row["input_hash"],
                "workflow_yaml": row["workflow_yaml"],
                "timestamp": ts,
                "duration_ms": duration_ms,
                "metadata": metadata,
            }

        step_agg: Dict[str, Dict[str, Any]] = {}
        steps_by_run: Dict[str, list[Dict[str, Any]]] = defaultdict(list)
        run_confidences: Dict[str, list[float]] = defaultdict(list)
        error_classes: Dict[str, int] = {}
        total_tokens = 0
        total_steps = 0
        failed_steps = 0

        for row in step_rows:
            total_steps += 1
            run_id = str(row["run_id"])
            step_id = str(row["step_id"] or "unknown")
            step_status = str(row["status"] or "UNKNOWN")
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

            if step_status == "FAILED":
                failed_steps += 1
                agg["failed"] += 1

            if isinstance(error, str) and error:
                error_class = error.split(":", 1)[0].strip() or "UnknownError"
                error_classes[error_class] = error_classes.get(error_class, 0) + 1

            token_usage_raw = row["token_usage_json"]
            if token_usage_raw:
                try:
                    usage = json_loads(token_usage_raw)
                    if isinstance(usage, dict):
                        tokens = usage.get("total_tokens")
                        if tokens is None:
                            prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0))
                            completion = usage.get("completion_tokens", usage.get("output_tokens", 0))
                            tokens = int(prompt or 0) + int(completion or 0)
                        total_tokens += int(tokens or 0)
                except Exception:  # noqa: BLE001
                    pass

            output = None
            output_raw = row["output_json"]
            if output_raw:
                try:
                    output = json_loads(output_raw)
                except Exception:  # noqa: BLE001
                    output = None
            if output is not None:
                confidences = self._extract_confidence_values(output)
                if confidences:
                    run_confidences[run_id].extend(confidences)

            steps_by_run[run_id].append({
                "step_id": step_id,
                "step_type": str(row["type"] or "unknown"),
                "status": step_status,
                "duration_ms": duration_ms if isinstance(duration_ms, (int, float)) else None,
                "error": error,
                "execution_index": row["execution_index"],
            })

        # Cache parsed workflow metadata by workflow_id to avoid re-parsing
        # the same YAML for every run that shares a workflow.
        _step_meta_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}
        step_meta_by_run: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for run_id, record in run_records.items():
            wf_id = record.get("workflow_id", "")
            if wf_id not in _step_meta_cache:
                _step_meta_cache[wf_id] = self._extract_step_meta(record.get("workflow_yaml"))
            step_meta_by_run[run_id] = _step_meta_cache[wf_id]

        # Failure recovery proxy: failed run is considered recovered when a later
        # completed run exists for the same workflow + input hash.
        recovered_proxy_ids: set[str] = set()
        grouped_runs: Dict[tuple[str, Optional[str]], list[Dict[str, Any]]] = defaultdict(list)
        for record in run_records.values():
            grouped_runs[(record["workflow_id"], record.get("input_hash"))].append(record)
        for records in grouped_runs.values():
            records.sort(key=lambda item: item.get("timestamp") or datetime.min.replace(tzinfo=timezone.utc))
            for idx, record in enumerate(records):
                if record["status"] != "FAILED":
                    continue
                for later in records[idx + 1 :]:
                    if later["status"] == "COMPLETED":
                        recovered_proxy_ids.add(record["run_id"])
                        break

        # Enrich run records with product-oriented diagnostic signals.
        for run_id, record in run_records.items():
            metadata = record["metadata"]
            initial_state = initial_by_run.get(run_id)
            input_class = self._classify_input(initial_state, metadata)

            outcome_raw, outcome_found = self._pick_metadata_value(
                metadata,
                ["outcome_achieved", "intended_outcome_achieved", "downstream_success"],
            )
            human_raw, human_found = self._pick_metadata_value(
                metadata,
                ["human_touched", "human_intervention", "manual_override", "manual_edit", "manual_retry"],
            )
            reversed_raw, reversed_found = self._pick_metadata_value(
                metadata,
                ["reversed", "reopened", "rolled_back", "compensated", "post_outcome_reversal"],
            )
            oracle_raw, oracle_found = self._pick_metadata_value(
                metadata,
                ["oracle_passed", "oracle_ok", "oracle_success"],
            )
            oracle_id, oracle_id_found = self._pick_metadata_value(
                metadata,
                ["oracle_scenario_id", "oracle_case_id", "oracle_id"],
            )
            recovery_raw, recovery_found = self._pick_metadata_value(
                metadata,
                ["recovered_via_resume", "recovered_via_replay", "recovered_via_resume_replay"],
            )
            confidence_raw, confidence_found = self._pick_metadata_value(
                metadata,
                ["confidence", "confidence_score", "model_confidence", "predicted_confidence"],
            )

            status = record["status"]
            eligible_terminal = status in {"COMPLETED", "FAILED", "COMPLETED_WITH_ERRORS"}
            status_success = status == "COMPLETED"
            outcome_achieved = self._parse_bool(outcome_raw)
            if outcome_achieved is None:
                outcome_achieved = status_success

            human_touched = self._parse_bool(human_raw)
            if human_touched is None:
                human_touched = False

            reversed_outcome = self._parse_bool(reversed_raw)
            if reversed_outcome is None:
                reversed_outcome = False

            oracle_passed = self._parse_bool(oracle_raw)
            oracle_matched = oracle_id_found and isinstance(oracle_id, str) and bool(oracle_id.strip())
            if not oracle_matched and oracle_found:
                oracle_matched = True

            recovery_signal = self._parse_bool(recovery_raw)

            confidence = self._parse_confidence(confidence_raw) if confidence_found else None
            if confidence is None:
                conf_values = run_confidences.get(run_id, [])
                if conf_values:
                    confidence = sum(conf_values) / len(conf_values)

            ads = eligible_terminal and status_success and outcome_achieved and (not human_touched) and (not reversed_outcome)

            first_break_step: Optional[Dict[str, Any]] = None
            if eligible_terminal and (not ads):
                run_steps = steps_by_run.get(run_id, [])
                for step in run_steps:
                    if step["status"] == "FAILED" or (isinstance(step["error"], str) and step["error"]):
                        first_break_step = step
                        break
                if first_break_step is None and run_steps:
                    first_break_step = run_steps[-1]

            record.update({
                "input_class": input_class,
                "eligible_terminal": eligible_terminal,
                "successful": eligible_terminal and status_success and outcome_achieved,
                "ads": ads,
                "human_touched": human_touched,
                "reversed": reversed_outcome,
                "oracle_passed": oracle_passed,
                "oracle_matched": oracle_matched,
                "recovery_signal": recovery_signal,
                "recovery_signal_found": recovery_found,
                "recovery_proxy": run_id in recovered_proxy_ids,
                "confidence": confidence,
                "confidence_found": confidence is not None,
                "first_break_step": first_break_step,
                "metadata_quality": {
                    "outcome_found": outcome_found,
                    "human_found": human_found,
                    "reversed_found": reversed_found,
                    "oracle_found": oracle_found,
                    "recovery_found": recovery_found,
                    "confidence_found": confidence_found,
                },
            })

        now = max(run_timestamps) if run_timestamps else datetime.now(timezone.utc)
        current_start = now - timedelta(days=window_days)
        previous_start = current_start - timedelta(days=window_days)

        for record in run_records.values():
            ts = record.get("timestamp")
            if ts is None:
                record["window"] = "unknown"
            elif ts >= current_start:
                record["window"] = "current"
            elif ts >= previous_start:
                record["window"] = "previous"
            else:
                record["window"] = "older"

        def _window_nis(target_runs: list[Dict[str, Any]], baseline_runs: list[Dict[str, Any]]) -> tuple[Optional[float], list[Dict[str, Any]]]:
            """Function implementation."""
            target_eligible = [r for r in target_runs if r.get("eligible_terminal")]
            if not target_eligible:
                return None, []
            baseline_classes = {str(r.get("input_class")) for r in baseline_runs if r.get("eligible_terminal")}
            target_classes: Dict[str, int] = {}
            novel_count = 0
            for run in target_eligible:
                cls = str(run.get("input_class") or "__unknown__")
                target_classes[cls] = target_classes.get(cls, 0) + 1
                if cls not in baseline_classes:
                    novel_count += 1
            nis = novel_count / len(target_eligible)
            novel_classes = [
                {"input_class": cls, "count": count}
                for cls, count in target_classes.items()
                if cls not in baseline_classes
            ]
            novel_classes.sort(key=lambda item: item["count"], reverse=True)
            return nis, novel_classes

        def _compute_window_metrics(window_name: str) -> Dict[str, Any]:
            """Function implementation."""
            segment = [r for r in run_records.values() if r.get("window") == window_name]
            eligible = [r for r in segment if r.get("eligible_terminal")]
            successful = [r for r in eligible if r.get("successful")]
            failed = [r for r in eligible if r.get("status") == "FAILED"]
            ads_runs = [r for r in eligible if r.get("ads")]

            ads_rate = self._safe_rate(len(ads_runs), len(eligible))
            porr_rate = self._safe_rate(sum(1 for r in successful if r.get("reversed")), len(successful))
            htr_rate = self._safe_rate(sum(1 for r in eligible if r.get("human_touched")), len(eligible))

            oracle_evaluable = [r for r in eligible if r.get("oracle_passed") is not None]
            oracle_passed = [r for r in oracle_evaluable if r.get("oracle_passed") is True]
            opr_rate = self._safe_rate(len(oracle_passed), len(oracle_evaluable))
            omr_rate = self._safe_rate(sum(1 for r in eligible if r.get("oracle_matched")), len(eligible))

            failed_with_signal = [r for r in failed if r.get("recovery_signal_found")]
            if failed_with_signal:
                re_source = "metadata"
                recovered = sum(1 for r in failed_with_signal if r.get("recovery_signal") is True)
                re_rate = self._safe_rate(recovered, len(failed))
            else:
                re_source = "proxy"
                recovered = sum(1 for r in failed if r.get("recovery_proxy"))
                re_rate = self._safe_rate(recovered, len(failed))

            ads_durations = [float(r["duration_ms"]) for r in ads_runs if isinstance(r.get("duration_ms"), (int, float))]
            srd50 = percentile(ads_durations, 50) if ads_durations else None
            srd95 = percentile(ads_durations, 95) if ads_durations else None

            confidence_samples: list[tuple[float, bool]] = []
            high_conf_non_ads = 0
            high_conf_total = 0
            for run in eligible:
                conf = run.get("confidence")
                if not isinstance(conf, (int, float)):
                    continue
                conf_f = max(0.0, min(1.0, float(conf)))
                is_ads = bool(run.get("ads"))
                confidence_samples.append((conf_f, is_ads))
                if conf_f >= 0.8:
                    high_conf_total += 1
                    if not is_ads:
                        high_conf_non_ads += 1
            ece, calibration_bins = self._compute_ece(confidence_samples, bins=10)
            ofr = self._safe_rate(high_conf_non_ads, high_conf_total)

            non_ads_runs = [r for r in eligible if not r.get("ads")]
            step_counts: Dict[str, int] = {}
            agent_counts: Dict[str, int] = {}
            tool_counts: Dict[str, int] = {}
            input_counts: Dict[str, int] = {}
            step_attribution_rows: list[Dict[str, Any]] = []

            for run in non_ads_runs:
                first_break = run.get("first_break_step")
                if not isinstance(first_break, dict):
                    continue
                step_id = str(first_break.get("step_id") or "unknown")
                step_meta = step_meta_by_run.get(run["run_id"], {}).get(step_id, {})
                step_idx = step_meta.get("step_index")
                step_type = step_meta.get("step_type") or first_break.get("step_type") or "unknown"
                agent_id = step_meta.get("agent_id")
                tool_name = step_meta.get("tool_name")
                input_class = str(run.get("input_class") or "__unknown__")

                step_counts[step_id] = step_counts.get(step_id, 0) + 1
                if isinstance(agent_id, str) and agent_id:
                    agent_counts[agent_id] = agent_counts.get(agent_id, 0) + 1
                if isinstance(tool_name, str) and tool_name:
                    tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
                input_counts[input_class] = input_counts.get(input_class, 0) + 1

                step_attribution_rows.append({
                    "run_id": run["run_id"],
                    "step_id": step_id,
                    "step_index": step_idx,
                    "step_type": step_type,
                    "agent_id": agent_id,
                    "tool_name": tool_name,
                    "input_class": input_class,
                })

            non_ads_count = len(non_ads_runs)
            per_step_fbsr = []
            for step_id, count in step_counts.items():
                exemplar = next((row for row in step_attribution_rows if row["step_id"] == step_id), None)
                per_step_fbsr.append({
                    "step_id": step_id,
                    "step_index": exemplar.get("step_index") if exemplar else None,
                    "step_type": exemplar.get("step_type") if exemplar else None,
                    "agent_id": exemplar.get("agent_id") if exemplar else None,
                    "tool_name": exemplar.get("tool_name") if exemplar else None,
                    "count": count,
                    "fbsr": (count / non_ads_count) if non_ads_count else 0.0,
                })
            per_step_fbsr.sort(key=lambda item: (item["fbsr"], item["count"]), reverse=True)

            def _top_rows(counter: Dict[str, int], key: str) -> list[Dict[str, Any]]:
                """Function implementation."""
                rows = []
                for name, count in counter.items():
                    rows.append({
                        key: name,
                        "count": count,
                        "rate": (count / non_ads_count) if non_ads_count else 0.0,
                    })
                rows.sort(key=lambda item: (item["rate"], item["count"]), reverse=True)
                return rows[:top_n]

            tsc = per_step_fbsr[0]["fbsr"] if per_step_fbsr else None

            return {
                "window": window_name,
                "counts": {
                    "runs": len(segment),
                    "eligible_runs": len(eligible),
                    "successful_runs": len(successful),
                    "failed_runs": len(failed),
                    "ads_runs": len(ads_runs),
                    "non_ads_runs": non_ads_count,
                },
                "outcomes": {
                    "ads_rate": ads_rate,
                    "post_outcome_reversal_rate": porr_rate,
                    "human_touch_rate": htr_rate,
                    "recovery_efficiency": re_rate,
                    "recovery_efficiency_source": re_source,
                    "oracle_pass_rate": opr_rate,
                    "oracle_match_rate": omr_rate,
                },
                "latency": {
                    "successful_run_duration_median_ms": srd50,
                    "successful_run_duration_p95_ms": srd95,
                    "latency_target_ms": latency_target_ms,
                    "latency_score": self._score_latency(srd95, latency_target_ms),
                },
                "calibration": {
                    "samples": len(confidence_samples),
                    "ece": ece,
                    "overconfident_failure_rate": ofr,
                    "bins": calibration_bins,
                },
                "attribution": {
                    "first_break_step_rate": per_step_fbsr[:top_n],
                    "top_agents": _top_rows(agent_counts, "agent_id"),
                    "top_tools": _top_rows(tool_counts, "tool_name"),
                    "top_input_classes": _top_rows(input_counts, "input_class"),
                    "top_step_concentration": tsc,
                },
            }

        current_metrics = _compute_window_metrics("current")
        previous_metrics = _compute_window_metrics("previous")

        current_segment = [r for r in run_records.values() if r.get("window") == "current"]
        previous_segment = [r for r in run_records.values() if r.get("window") == "previous"]
        older_segment = [r for r in run_records.values() if r.get("window") == "older"]

        current_nis, current_novel_classes = _window_nis(current_segment, previous_segment)
        previous_nis, previous_novel_classes = _window_nis(previous_segment, older_segment)

        def _metric_or_neutral(value: Optional[float], *, invert: bool = False) -> tuple[float, bool]:
            """Function implementation."""
            if value is None:
                return 0.5, True
            bounded = max(0.0, min(1.0, float(value)))
            if invert:
                bounded = 1.0 - bounded
            return bounded, False

        def _compute_health(snapshot: Dict[str, Any], nis_value: Optional[float]) -> Dict[str, Any]:
            """Function implementation."""
            outcomes = snapshot.get("outcomes", {})
            latency = snapshot.get("latency", {})
            calibration = snapshot.get("calibration", {})

            ads_val, ads_missing = _metric_or_neutral(outcomes.get("ads_rate"))
            opr_val, opr_missing = _metric_or_neutral(outcomes.get("oracle_pass_rate"))
            porr_val, porr_missing = _metric_or_neutral(outcomes.get("post_outcome_reversal_rate"), invert=True)
            htr_val, htr_missing = _metric_or_neutral(outcomes.get("human_touch_rate"), invert=True)
            re_val, re_missing = _metric_or_neutral(outcomes.get("recovery_efficiency"))
            ece_val, ece_missing = _metric_or_neutral(calibration.get("ece"), invert=True)
            nis_val, nis_missing = _metric_or_neutral(nis_value, invert=True)
            lat_val, lat_missing = _metric_or_neutral(latency.get("latency_score"))

            score = 100.0 * (
                _HEALTH_WEIGHTS["ads"] * ads_val
                + _HEALTH_WEIGHTS["opr"] * opr_val
                + _HEALTH_WEIGHTS["one_minus_porr"] * porr_val
                + _HEALTH_WEIGHTS["one_minus_htr"] * htr_val
                + _HEALTH_WEIGHTS["recovery"] * re_val
                + _HEALTH_WEIGHTS["one_minus_ece"] * ece_val
                + _HEALTH_WEIGHTS["one_minus_nis"] * nis_val
                + _HEALTH_WEIGHTS["latency"] * lat_val
            )

            components = {
                "ads": ads_val,
                "opr": opr_val,
                "one_minus_porr": porr_val,
                "one_minus_htr": htr_val,
                "recovery": re_val,
                "one_minus_ece": ece_val,
                "one_minus_nis": nis_val,
                "latency": lat_val,
            }
            defaults = {
                "ads": ads_missing,
                "opr": opr_missing,
                "one_minus_porr": porr_missing,
                "one_minus_htr": htr_missing,
                "recovery": re_missing,
                "one_minus_ece": ece_missing,
                "one_minus_nis": nis_missing,
                "latency": lat_missing,
            }
            return {
                "score": score,
                "weights": dict(_HEALTH_WEIGHTS),
                "components": components,
                "defaults_applied": defaults,
            }

        health_current = _compute_health(current_metrics, current_nis)
        health_previous = _compute_health(previous_metrics, previous_nis)

        curr_out = current_metrics.get("outcomes", {})
        prev_out = previous_metrics.get("outcomes", {})
        curr_lat = current_metrics.get("latency", {})
        prev_lat = previous_metrics.get("latency", {})
        curr_cal = current_metrics.get("calibration", {})
        prev_cal = previous_metrics.get("calibration", {})
        curr_attr = current_metrics.get("attribution", {})
        prev_attr = previous_metrics.get("attribution", {})

        breakers: list[Dict[str, Any]] = []

        def _add_breaker(name: str, tripped: bool, current: Optional[float], previous: Optional[float], reason: str) -> None:
            """Function implementation."""
            breakers.append({
                "name": name,
                "tripped": tripped,
                "current": current,
                "previous": previous,
                "reason": reason,
            })

        ads_drop = False
        if curr_out.get("ads_rate") is not None and prev_out.get("ads_rate") is not None:
            ads_drop = (prev_out["ads_rate"] - curr_out["ads_rate"]) > 0.03
        _add_breaker(
            "ads_drop_gt_3pp",
            ads_drop,
            curr_out.get("ads_rate"),
            prev_out.get("ads_rate"),
            "ADS dropped by more than 3 percentage points",
        )

        porr_rise = False
        if curr_out.get("post_outcome_reversal_rate") is not None and prev_out.get("post_outcome_reversal_rate") is not None:
            porr_rise = (curr_out["post_outcome_reversal_rate"] - prev_out["post_outcome_reversal_rate"]) > 0.01
        _add_breaker(
            "porr_rise_gt_1pp",
            porr_rise,
            curr_out.get("post_outcome_reversal_rate"),
            prev_out.get("post_outcome_reversal_rate"),
            "Post-outcome reversal rate increased by more than 1 percentage point",
        )

        latency_spike = False
        if curr_lat.get("successful_run_duration_p95_ms") is not None and prev_lat.get("successful_run_duration_p95_ms") not in (None, 0):
            latency_spike = (
                (curr_lat["successful_run_duration_p95_ms"] - prev_lat["successful_run_duration_p95_ms"])
                / prev_lat["successful_run_duration_p95_ms"]
            ) > 0.30
        _add_breaker(
            "srd95_spike_gt_30pct",
            latency_spike,
            curr_lat.get("successful_run_duration_p95_ms"),
            prev_lat.get("successful_run_duration_p95_ms"),
            "Successful-run p95 latency increased by more than 30%",
        )

        ece_worse = False
        if curr_cal.get("ece") is not None and prev_cal.get("ece") not in (None, 0):
            ece_worse = ((curr_cal["ece"] - prev_cal["ece"]) / prev_cal["ece"]) > 0.20
        _add_breaker(
            "ece_worse_gt_20pct",
            ece_worse,
            curr_cal.get("ece"),
            prev_cal.get("ece"),
            "Calibration error increased by more than 20%",
        )

        nis_jump = False
        if current_nis is not None and previous_nis is not None:
            if previous_nis > 0:
                nis_jump = ((current_nis - previous_nis) / previous_nis) > 0.25
            else:
                nis_jump = current_nis > 0.25
        _add_breaker(
            "nis_jump_gt_25pct",
            nis_jump,
            current_nis,
            previous_nis,
            "Novel input share increased by more than 25%",
        )

        score_delta = health_current["score"] - health_previous["score"]
        breaker_tripped = any(item["tripped"] for item in breakers)

        tsc_curr = curr_attr.get("top_step_concentration")
        tsc_prev = prev_attr.get("top_step_concentration")
        distributed_improvement = True
        if tsc_curr is not None and tsc_prev is not None:
            if (tsc_curr > 0.40) and (tsc_curr - tsc_prev > 0.05):
                distributed_improvement = False

        if previous_metrics["counts"]["eligible_runs"] == 0:
            health_status = "insufficient_baseline"
        elif breaker_tripped:
            health_status = "regressing"
        elif score_delta >= 2.0 and distributed_improvement:
            health_status = "improving"
        elif score_delta > 0.0:
            health_status = "mixed"
        else:
            health_status = "regressing"

        # Legacy per-step and error sections retained for backward compatibility.
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

        metadata_coverage = {
            "total_runs": len(run_records),
            "outcome_flag_runs": sum(1 for r in run_records.values() if r["metadata_quality"]["outcome_found"]),
            "human_touch_flag_runs": sum(1 for r in run_records.values() if r["metadata_quality"]["human_found"]),
            "reversal_flag_runs": sum(1 for r in run_records.values() if r["metadata_quality"]["reversed_found"]),
            "oracle_flag_runs": sum(1 for r in run_records.values() if r["metadata_quality"]["oracle_found"]),
            "recovery_flag_runs": sum(1 for r in run_records.values() if r["metadata_quality"]["recovery_found"]),
            "confidence_flag_runs": sum(1 for r in run_records.values() if r["metadata_quality"]["confidence_found"]),
        }

        return {
            "runs": {
                "total": len(run_rows),
                "failed": failed_runs,
                "failure_rate": (failed_runs / len(run_rows)) if run_rows else 0.0,
                "status_counts": status_counts,
                "avg_duration_ms": (sum(run_durations_ms) / len(run_durations_ms)) if run_durations_ms else None,
                "p95_duration_ms": percentile(run_durations_ms, 95) if run_durations_ms else None,
            },
            "steps": {
                "total": total_steps,
                "failed": failed_steps,
                "failure_rate": (failed_steps / total_steps) if total_steps else 0.0,
                "top_failing": per_step[:top_n],
            },
            "llm": {
                "total_tokens": total_tokens,
            },
            "errors": {
                "top_classes": [
                    {"error_class": name, "count": count}
                    for name, count in top_errors[:top_n]
                ],
            },
            "windows": {
                "window_days": window_days,
                "current_start": current_start.isoformat(),
                "current_end": now.isoformat(),
                "previous_start": previous_start.isoformat(),
                "previous_end": current_start.isoformat(),
            },
            "outcomes": {
                "current": current_metrics["outcomes"],
                "previous": previous_metrics["outcomes"],
            },
            "diagnostics": {
                "step_attribution": {
                    "current": current_metrics["attribution"],
                    "previous": previous_metrics["attribution"],
                    "top_step_concentration_delta": (
                        None
                        if current_metrics["attribution"].get("top_step_concentration") is None
                        or previous_metrics["attribution"].get("top_step_concentration") is None
                        else current_metrics["attribution"]["top_step_concentration"]
                        - previous_metrics["attribution"]["top_step_concentration"]
                    ),
                },
                "success_latency": {
                    "current": current_metrics["latency"],
                    "previous": previous_metrics["latency"],
                },
                "input_coverage": {
                    "current_novel_input_share": current_nis,
                    "previous_novel_input_share": previous_nis,
                    "current_novel_classes": current_novel_classes[:top_n],
                    "previous_novel_classes": previous_novel_classes[:top_n],
                },
                "calibration": {
                    "current": current_metrics["calibration"],
                    "previous": previous_metrics["calibration"],
                },
            },
            "health": {
                "weights": dict(_HEALTH_WEIGHTS),
                "current": health_current,
                "previous": health_previous,
                "delta": score_delta,
                "status": health_status,
                "distributed_improvement": distributed_improvement,
                "circuit_breakers": breakers,
            },
            "data_quality": {
                "metadata_coverage": metadata_coverage,
                "notes": [
                    "Recovery efficiency uses metadata when available; otherwise proxy based on later successful runs with same workflow_id/input_hash.",
                    "Oracle pass rate requires explicit metadata oracle flags. Missing values are treated as unknown and default to neutral in health score.",
                    "Confidence calibration uses explicit confidence metadata or confidence-like numeric outputs extracted from step output payloads.",
                ],
            },
        }
