from __future__ import annotations

"""Persistent semantic memory tier backed by SQLite.

Stores long-term knowledge as key-value facts with optional tags and
supports three retrieval modes:

1. **Exact key lookup** — ``get("api_rate_limit")``
2. **Tag-based query** — ``search_by_tags(["python", "best-practice"])``
3. **Full-text search** — ``search("rate limit timeout")`` powered by
   SQLite FTS5 (ships with Python's ``sqlite3`` module)

When no ``db_path`` is provided, the tier operates as an in-memory store
(compatible with the existing test/stub interface).

.. note::

   Vector-similarity retrieval (embeddings + cosine distance) is not
   implemented.  See the TODO at the bottom of this file for the
   roadmap item.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class SemanticMemory:
    """SQLite-backed semantic memory with FTS5 full-text search.

    When ``db_path`` is None the tier falls back to a plain in-memory dict,
    preserving backward compatibility with tests that instantiate
    ``SemanticMemory()`` without arguments.
    """

    def __init__(self, db_path: Optional[str] = None, max_results: int = 10) -> None:
        self._db_path = db_path
        self._max_results = max_results
        self._fallback: Dict[str, Any] = {}
        if db_path is not None:
            self._init_db()

    # ------------------------------------------------------------------
    # SQLite setup
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
                CREATE TABLE IF NOT EXISTS semantic_facts (
                    key         TEXT PRIMARY KEY,
                    value       TEXT NOT NULL,
                    tags        TEXT NOT NULL DEFAULT '',
                    metadata    TEXT,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                )
                """
            )
            # FTS5 virtual table for full-text search over key + value + tags.
            # content= links it to semantic_facts so we don't duplicate storage.
            # We use a content-sync approach: manual sync on insert/update/delete.
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS semantic_facts_fts
                USING fts5(key, value, tags, content='semantic_facts', content_rowid='rowid')
                """
            )

    # ------------------------------------------------------------------
    # MemoryTier protocol
    # ------------------------------------------------------------------

    def read(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Return semantic facts relevant to the current run context.

        Looks for ``runtime.memory.semantic.query`` in context to drive
        retrieval.  If no query is present, returns a count summary so
        model steps know knowledge is available.
        """
        if self._db_path is None:
            return dict(self._fallback)

        query = (
            context
            .get("runtime", {})
            .get("memory", {})
            .get("semantic", {})
            .get("query")
        )
        if query:
            facts = self.search(query)
        else:
            facts = []

        count = self.count()
        result: Dict[str, Any] = {"fact_count": count}
        if facts:
            result["facts"] = facts
        return result

    def write(self, payload: Dict[str, Any]) -> None:
        """Persist facts from state into semantic memory.

        Looks for ``runtime.memory.semantic.store`` — a list of dicts each
        containing ``key``, ``value``, and optionally ``tags`` (list of
        strings) and ``metadata`` (dict).
        """
        if self._db_path is None:
            self._fallback = dict(payload)
            return

        items = (
            payload
            .get("runtime", {})
            .get("memory", {})
            .get("semantic", {})
            .get("store", [])
        )
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            value = item.get("value")
            if key and value is not None:
                self.store(
                    key=str(key),
                    value=str(value),
                    tags=item.get("tags", []),
                    metadata=item.get("metadata"),
                )

    # ------------------------------------------------------------------
    # Public API — store / get / delete
    # ------------------------------------------------------------------

    def store(
        self,
        key: str,
        value: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert or update a semantic fact."""
        if self._db_path is None:
            self._fallback[key] = value
            return

        tags_str = ",".join(sorted(tags)) if tags else ""
        meta_str = json.dumps(metadata, default=str) if metadata else None
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT rowid FROM semantic_facts WHERE key = ?", (key,)
            ).fetchone()

            if existing:
                rowid = existing["rowid"]
                # Delete old FTS entry, update main row, re-insert FTS entry.
                conn.execute(
                    "INSERT INTO semantic_facts_fts(semantic_facts_fts, rowid, key, value, tags) "
                    "VALUES('delete', ?, ?, ?, ?)",
                    (rowid, key,
                     conn.execute("SELECT value FROM semantic_facts WHERE key = ?", (key,)).fetchone()["value"],
                     conn.execute("SELECT tags FROM semantic_facts WHERE key = ?", (key,)).fetchone()["tags"]),
                )
                conn.execute(
                    "UPDATE semantic_facts SET value = ?, tags = ?, metadata = ?, updated_at = ? "
                    "WHERE key = ?",
                    (value, tags_str, meta_str, now, key),
                )
                conn.execute(
                    "INSERT INTO semantic_facts_fts(rowid, key, value, tags) VALUES (?, ?, ?, ?)",
                    (rowid, key, value, tags_str),
                )
            else:
                conn.execute(
                    "INSERT INTO semantic_facts (key, value, tags, metadata, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (key, value, tags_str, meta_str, now, now),
                )
                rowid = conn.execute(
                    "SELECT rowid FROM semantic_facts WHERE key = ?", (key,)
                ).fetchone()["rowid"]
                conn.execute(
                    "INSERT INTO semantic_facts_fts(rowid, key, value, tags) VALUES (?, ?, ?, ?)",
                    (rowid, key, value, tags_str),
                )

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single fact by exact key."""
        if self._db_path is None:
            val = self._fallback.get(key)
            return {"key": key, "value": val} if val is not None else None

        with self._connect() as conn:
            row = conn.execute(
                "SELECT key, value, tags, metadata, created_at, updated_at "
                "FROM semantic_facts WHERE key = ?",
                (key,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def delete(self, key: str) -> bool:
        """Delete a fact by key.  Returns True if the fact existed."""
        if self._db_path is None:
            return self._fallback.pop(key, None) is not None

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT rowid, value, tags FROM semantic_facts WHERE key = ?", (key,)
            ).fetchone()
            if not existing:
                return False
            conn.execute(
                "INSERT INTO semantic_facts_fts(semantic_facts_fts, rowid, key, value, tags) "
                "VALUES('delete', ?, ?, ?, ?)",
                (existing["rowid"], key, existing["value"], existing["tags"]),
            )
            conn.execute("DELETE FROM semantic_facts WHERE key = ?", (key,))
        return True

    # ------------------------------------------------------------------
    # Public API — search
    # ------------------------------------------------------------------

    def search(self, query: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Full-text search across keys, values, and tags.

        Uses SQLite FTS5 ``MATCH`` with automatic prefix tokenization.
        Returns results ranked by FTS5 BM25 relevance.
        """
        if self._db_path is None:
            return []
        limit = limit or self._max_results

        # FTS5 expects a MATCH expression.  Tokenize the query into
        # prefix terms so partial words match.
        tokens = query.strip().split()
        if not tokens:
            return []
        match_expr = " ".join(f'"{t}"*' for t in tokens)

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT sf.key, sf.value, sf.tags, sf.metadata,
                       sf.created_at, sf.updated_at
                FROM semantic_facts_fts fts
                JOIN semantic_facts sf ON sf.rowid = fts.rowid
                WHERE fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (match_expr, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search_by_tags(
        self, tags: List[str], match_all: bool = False, limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve facts matching one or more tags.

        Args:
            tags: Tag strings to match.
            match_all: If True, facts must contain **all** tags.  If False
                (default), facts matching **any** tag are returned.
            limit: Maximum results.
        """
        if self._db_path is None or not tags:
            return []
        limit = limit or self._max_results

        with self._connect() as conn:
            if match_all:
                # Every tag must appear in the comma-separated tags column.
                where_parts = []
                params: list = []
                for tag in tags:
                    where_parts.append("(',' || tags || ',' LIKE ?)")
                    params.append(f"%,{tag},%")
                where_clause = " AND ".join(where_parts)
            else:
                where_parts = []
                params = []
                for tag in tags:
                    where_parts.append("(',' || tags || ',' LIKE ?)")
                    params.append(f"%,{tag},%")
                where_clause = " OR ".join(where_parts)

            params.append(limit)
            rows = conn.execute(
                f"SELECT key, value, tags, metadata, created_at, updated_at "
                f"FROM semantic_facts WHERE {where_clause} "
                f"ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_all(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return all facts ordered by most recently updated."""
        if self._db_path is None:
            return [{"key": k, "value": v} for k, v in self._fallback.items()]
        limit = limit or self._max_results
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value, tags, metadata, created_at, updated_at "
                "FROM semantic_facts ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count(self) -> int:
        """Return total number of stored facts."""
        if self._db_path is None:
            return len(self._fallback)
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM semantic_facts").fetchone()
        return row["n"] if row else 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a database row to a plain dict, unpacking tags and metadata."""
        d: Dict[str, Any] = {
            "key": row["key"],
            "value": row["value"],
        }
        tags_raw = row["tags"]
        d["tags"] = [t for t in tags_raw.split(",") if t] if tags_raw else []
        meta_raw = row["metadata"] if "metadata" in row.keys() else None
        if meta_raw:
            try:
                d["metadata"] = json.loads(meta_raw)
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = None
        else:
            d["metadata"] = None
        if "created_at" in row.keys():
            d["created_at"] = row["created_at"]
        if "updated_at" in row.keys():
            d["updated_at"] = row["updated_at"]
        return d


# TODO(roadmap): Vector-similarity retrieval for semantic memory.
#   To support embedding-based lookup (e.g., "find facts related to error
#   handling"), integrate a lightweight vector backend:
#   - Option A: sqlite-vss extension (keeps everything in one DB file)
#   - Option B: chromadb (in-process, pip-installable)
#   The current FTS5 approach covers keyword/token matching well.  Vector
#   search would add semantic similarity for queries where exact tokens
#   don't overlap (e.g., "rate limiting" matching "throttle policy").
#   Implementation sketch:
#   1. Add an `embedding BLOB` column to semantic_facts
#   2. On store(), call an embedding function (configurable provider)
#   3. Add `search_similar(query_text, top_k)` that embeds the query
#      and finds nearest neighbors
#   4. Hybrid retrieval: combine FTS5 + vector scores for ranking
