from __future__ import annotations

"""Episodic memory tier backed by SQLite.

Stores per-run episode records (workflow_id, inputs summary, outputs summary,
status, timestamp) and provides recall of past episodes for context hydration.

Each episode is a condensed snapshot of a completed run — not the full state
tree, but enough to answer "what happened last time this workflow ran?"
"""

import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class EpisodicMemory:
    """SQLite-backed episodic memory.

    When no ``db_path`` is provided, the tier operates in-memory (compatible
    with the original stub interface used by tests and CLI defaults).
    """

    def __init__(self, db_path: Optional[str] = None, max_recall: int = 5) -> None:
        self._db_path = db_path
        self._max_recall = max_recall
        self._fallback: Dict[str, Any] = {}
        if db_path is not None:
            self._init_db()

    # ------------------------------------------------------------------
    # SQLite helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        assert self._db_path is not None
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
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
        return {"runtime": {"episodes": episodes}}

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

        # Build compact summaries from the payload
        inputs_keys = list(payload.get("inputs", {}).keys())
        steps_keys = list(payload.get("steps", {}).keys())
        inputs_summary = ", ".join(inputs_keys) if inputs_keys else ""
        outputs_summary = ", ".join(steps_keys) if steps_keys else ""

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
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO episodes
                    (workflow_id, run_id, status, inputs_summary, outputs_summary, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (workflow_id, run_id, status, inputs_summary, outputs_summary, error, now),
            )

    def recall(self, workflow_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Return the most recent episodes for *workflow_id*."""
        if self._db_path is None:
            return []
        with self._connect() as conn:
            rows = conn.execute(
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
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM episodes ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
