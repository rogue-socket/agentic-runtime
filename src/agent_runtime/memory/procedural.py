from __future__ import annotations

"""Procedural memory tier — SQLite-backed key/value store.

Stores learned workflows, playbooks, and reusable strategies that the
runtime can recall when executing similar tasks in the future.

When ``db_path`` is provided, entries persist across runs in a SQLite
table.  Without it the tier falls back to an in-memory dict for tests.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class ProceduralMemory:
    """SQLite-backed procedural memory.

    When no ``db_path`` is provided, the tier operates in-memory (compatible
    with the original stub interface used by tests and CLI defaults).
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Function implementation."""
        self._db_path = db_path
        self._store: Dict[str, Any] = {}
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
            CREATE TABLE IF NOT EXISTS procedural_rules (
                key        TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
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
        """Return all stored procedural rules."""
        if self._conn is None:
            return dict(self._store)

        rows = self._conn.execute(
            "SELECT key, value_json FROM procedural_rules ORDER BY updated_at DESC"
        ).fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    def write(self, payload: Dict[str, Any]) -> None:
        """Persist procedural rules from ``runtime.memory.procedural.store``."""
        store = (
            payload
            .get("runtime", {})
            .get("memory", {})
            .get("procedural", {})
            .get("store", {})
        )
        if not isinstance(store, dict) or not store:
            return

        if self._conn is None:
            self._store.update(store)
            return

        now = datetime.now(timezone.utc).isoformat()
        for key, value in store.items():
            self._conn.execute(
                """
                INSERT INTO procedural_rules (key, value_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json,
                                               updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), now, now),
            )
        self._conn.commit()


# TODO(pain-point): Procedural Memory Auto-Learning - The procedural tier is
#   an empty key/value store. The original vision: mine episodic history for
#   reusable patterns ("when input contains Python, use the code_reviewer agent
#   with strict mode") and auto-generate procedural rules. Implementation path:
#   (1) After N episodes for a workflow, run an LLM summarization pass over
#   episodic history to identify recurring patterns, (2) store extracted rules
#   as procedural entries, (3) inject matching rules into agent context during
#   hydration so the agent benefits from past experience without the developer
#   writing explicit rules.
# TODO(roadmap): Consider LLM-assisted rule extraction from episode narratives
#   to auto-populate procedural memory from episodic history.
