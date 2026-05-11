from __future__ import annotations

"""Episodic memory tier backed by SQLite.

Stores per-run episode records (workflow_id, inputs summary, outputs summary,
status, timestamp) and provides recall of past episodes for context hydration.

Each episode is a condensed snapshot of a completed run — not the full state
tree, but enough to answer "what happened last time this workflow ran?"
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Maximum byte length for truncated value summaries in episodes.
_MAX_SUMMARY_BYTES = 512


def _truncated_json(obj: Any, max_bytes: int = _MAX_SUMMARY_BYTES) -> str:
    """Serialize *obj* to JSON, truncating to *max_bytes* if needed."""
    try:
        text = json.dumps(obj, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(obj)
    if len(text) > max_bytes:
        return text[: max_bytes - 3] + "..."
    return text


class EpisodicMemory:
    """SQLite-backed episodic memory.

    When no ``db_path`` is provided, the tier operates in-memory (compatible
    with the original stub interface used by tests and CLI defaults).
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        max_recall: int = 5,
        max_summary_bytes: int = _MAX_SUMMARY_BYTES,
    ) -> None:
        """Initialize the episodic memory tier.

        Args:
            db_path: SQLite path; ``None`` enables in-memory stub mode.
            max_recall: Default episode count returned by ``recall()`` and
                hydrated into state.
            max_summary_bytes: Truncation budget for ``inputs_summary`` and
                ``outputs_summary`` when persisting an episode. Larger values
                preserve more detail at the cost of disk and prompt budget
                downstream.
        """
        self._db_path = db_path
        self._max_recall = max_recall
        self._max_summary_bytes = max_summary_bytes
        self._fallback: Dict[str, Any] = {}
        self._conn: Optional[sqlite3.Connection] = None
        if db_path is not None:
            self._conn = self._open_connection()
            self._init_db()

    # ------------------------------------------------------------------
    # SQLite helpers
    # ------------------------------------------------------------------

    def _open_connection(self) -> sqlite3.Connection:
        """Function implementation."""
        assert self._db_path is not None
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Function implementation."""
        assert self._conn is not None
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS episodes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT    NOT NULL,
                run_id      TEXT,
                status      TEXT,
                inputs_summary TEXT,
                outputs_summary TEXT,
                error       TEXT,
                created_at  TEXT    NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying SQLite connection if open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # MemoryTier protocol
    # ------------------------------------------------------------------

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Return recent episodes as ``runtime.episodes`` for state hydration.

        When in stub mode (no db_path), returns the fallback dict to maintain
        backward compatibility with existing tests.
        """
        if self._db_path is None:
            return dict(self._fallback)

        workflow_id = context.get("runtime", {}).get("workflow_id") or context.get("workflow_id", "")
        if not workflow_id:
            return {}

        episodes = self.recall(workflow_id, limit=self._max_recall)
        if not episodes:
            return {}
        return {"episodes": episodes}

    def write(self, payload: Dict[str, Any]) -> None:
        """Persist a condensed episode from the current run state."""
        if self._db_path is None:
            self._fallback = dict(payload)
            return

        runtime = payload.get("runtime", {})
        workflow_id = runtime.get("workflow_id", "")
        if not workflow_id:
            return

        run_id = runtime.get("run_id", "")
        status = runtime.get("status", "")
        error = runtime.get("error")

        # Build compact summaries from the payload — include actual values
        # (truncated) so episodes are useful for cross-run learning.
        inputs_summary = _truncated_json(payload.get("inputs", {}), max_bytes=self._max_summary_bytes)
        steps_data = payload.get("steps", {})
        # For outputs, capture the last step's output (most relevant) or
        # a compact mapping of step_id -> truncated output.
        outputs_summary = _truncated_json(
            {k: v for k, v in steps_data.items()} if steps_data else {},
            max_bytes=self._max_summary_bytes,
        )

        self.record(
            workflow_id=workflow_id,
            run_id=run_id,
            status=status,
            inputs_summary=inputs_summary,
            outputs_summary=outputs_summary,
            error=error,
        )

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def record(
        self,
        workflow_id: str,
        run_id: str = "",
        status: str = "",
        inputs_summary: str = "",
        outputs_summary: str = "",
        error: Optional[str] = None,
    ) -> None:
        """Write a single episode row."""
        if self._db_path is None:
            return
        now = datetime.now(timezone.utc).isoformat()
        assert self._conn is not None
        self._conn.execute(
            """
            INSERT INTO episodes
                (workflow_id, run_id, status, inputs_summary, outputs_summary, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (workflow_id, run_id, status, inputs_summary, outputs_summary, error, now),
        )
        self._conn.commit()

    def recall(self, workflow_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Return the most recent episodes for *workflow_id*."""
        if self._db_path is None:
            return []
        assert self._conn is not None
        rows = self._conn.execute(
            """
            SELECT workflow_id, run_id, status, inputs_summary,
                   outputs_summary, error, created_at
            FROM episodes
            WHERE workflow_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (workflow_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def recall_all(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return most recent episodes across all workflows."""
        if self._db_path is None:
            return []
        assert self._conn is not None
        rows = self._conn.execute(
            """
            SELECT workflow_id, run_id, status, inputs_summary,
                   outputs_summary, error, created_at
            FROM episodes ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
