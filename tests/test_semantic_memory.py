"""Tests for SemanticMemory — SQLite + FTS5 full-text search, tags, CRUD."""

from __future__ import annotations

import os
import tempfile

from agent_runtime.memory.semantic import SemanticMemory


class TestSemanticMemoryStubMode:
    """In-memory fallback when no db_path is provided."""

    def test_read_returns_empty_initially(self) -> None:
        """Function implementation."""
        mem = SemanticMemory()
        assert mem.read({}) == {}

    def test_write_and_read_stub(self) -> None:
        """Function implementation."""
        mem = SemanticMemory()
        mem.write({"some": "data"})
        assert mem.read({}) == {"some": "data"}

    def test_store_and_get_stub(self) -> None:
        """Function implementation."""
        mem = SemanticMemory()
        mem.store("api_limit", "1000 req/min")
        result = mem.get("api_limit")
        assert result == {"key": "api_limit", "value": "1000 req/min"}

    def test_get_missing_returns_none(self) -> None:
        """Function implementation."""
        mem = SemanticMemory()
        assert mem.get("missing") is None

    def test_delete_stub(self) -> None:
        """Function implementation."""
        mem = SemanticMemory()
        mem.store("key", "val")
        assert mem.delete("key") is True
        assert mem.get("key") is None

    def test_delete_missing_returns_false(self) -> None:
        """Function implementation."""
        mem = SemanticMemory()
        assert mem.delete("nope") is False

    def test_count_stub(self) -> None:
        """Function implementation."""
        mem = SemanticMemory()
        assert mem.count() == 0
        mem.store("a", "1")
        mem.store("b", "2")
        assert mem.count() == 2

    def test_list_all_stub(self) -> None:
        """Function implementation."""
        mem = SemanticMemory()
        mem.store("x", "1")
        mem.store("y", "2")
        items = mem.list_all()
        keys = {it["key"] for it in items}
        assert keys == {"x", "y"}

    def test_search_returns_empty_in_stub(self) -> None:
        """Function implementation."""
        mem = SemanticMemory()
        assert mem.search("anything") == []


class TestSemanticMemorySQLite:
    """SQLite-backed mode with FTS5."""

    def _db(self, tmpdir: str) -> str:
        """Function implementation."""
        return os.path.join(tmpdir, "semantic.db")

    def test_store_and_get(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            mem = SemanticMemory(db_path=self._db(d))
            try:
                mem.store("rate_limit", "1000 requests per minute", tags=["api", "config"])
                result = mem.get("rate_limit")
                assert result is not None
                assert result["key"] == "rate_limit"
                assert result["value"] == "1000 requests per minute"
                assert "api" in result["tags"]
                assert "config" in result["tags"]
            finally:
                mem.close()

    def test_get_missing(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            mem = SemanticMemory(db_path=self._db(d))
            try:
                assert mem.get("nonexistent") is None
            finally:
                mem.close()

    def test_update_existing_key(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            mem = SemanticMemory(db_path=self._db(d))
            try:
                mem.store("key", "old_value")
                mem.store("key", "new_value", tags=["updated"])
                result = mem.get("key")
                assert result["value"] == "new_value"
                assert "updated" in result["tags"]
            finally:
                mem.close()

    def test_delete(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            mem = SemanticMemory(db_path=self._db(d))
            try:
                mem.store("temp", "data")
                assert mem.delete("temp") is True
                assert mem.get("temp") is None
                assert mem.count() == 0
            finally:
                mem.close()

    def test_delete_missing_returns_false(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            mem = SemanticMemory(db_path=self._db(d))
            try:
                assert mem.delete("ghost") is False
            finally:
                mem.close()

    def test_count(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            mem = SemanticMemory(db_path=self._db(d))
            try:
                assert mem.count() == 0
                mem.store("a", "1")
                mem.store("b", "2")
                assert mem.count() == 2
            finally:
                mem.close()

    def test_list_all(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            mem = SemanticMemory(db_path=self._db(d))
            try:
                mem.store("first", "1")
                mem.store("second", "2")
                items = mem.list_all()
                assert len(items) == 2
                keys = {it["key"] for it in items}
                assert keys == {"first", "second"}
            finally:
                mem.close()

    def test_full_text_search(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            mem = SemanticMemory(db_path=self._db(d))
            try:
                mem.store("timeout_policy", "30 second timeout for API calls")
                mem.store("retry_policy", "Retry failed requests 3 times")
                mem.store("auth_config", "OAuth2 with JWT tokens")

                results = mem.search("timeout")
                assert len(results) >= 1
                assert any(r["key"] == "timeout_policy" for r in results)
            finally:
                mem.close()

    def test_search_no_results(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            mem = SemanticMemory(db_path=self._db(d))
            try:
                mem.store("fact", "some value")
                results = mem.search("xyznonexistent")
                assert results == []
            finally:
                mem.close()

    def test_search_empty_query(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            mem = SemanticMemory(db_path=self._db(d))
            try:
                mem.store("fact", "value")
                assert mem.search("") == []
                assert mem.search("   ") == []
            finally:
                mem.close()

    def test_search_by_tags_any(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            mem = SemanticMemory(db_path=self._db(d))
            try:
                mem.store("a", "val", tags=["python", "testing"])
                mem.store("b", "val", tags=["python", "config"])
                mem.store("c", "val", tags=["java"])

                results = mem.search_by_tags(["testing"])
                assert len(results) == 1
                assert results[0]["key"] == "a"
            finally:
                mem.close()

    def test_search_by_tags_all(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            mem = SemanticMemory(db_path=self._db(d))
            try:
                mem.store("a", "val", tags=["python", "testing"])
                mem.store("b", "val", tags=["python", "config"])

                results = mem.search_by_tags(["python", "testing"], match_all=True)
                assert len(results) == 1
                assert results[0]["key"] == "a"
            finally:
                mem.close()

    def test_metadata_roundtrip(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            mem = SemanticMemory(db_path=self._db(d))
            try:
                mem.store("fact", "value", metadata={"source": "docs", "confidence": 0.9})
                result = mem.get("fact")
                assert result["metadata"]["source"] == "docs"
                assert result["metadata"]["confidence"] == 0.9
            finally:
                mem.close()


class TestSemanticMemoryTierProtocol:
    """Tests for the MemoryTier read/write interface."""

    def test_read_returns_count(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "sem.db")
            mem = SemanticMemory(db_path=db)
            try:
                mem.store("a", "1")
                mem.store("b", "2")
                result = mem.read({})
                assert result["fact_count"] == 2
            finally:
                mem.close()

    def test_read_with_query(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "sem.db")
            mem = SemanticMemory(db_path=db)
            try:
                mem.store("timeout", "30 seconds")
                result = mem.read({
                    "runtime": {"memory": {"semantic": {"query": "timeout"}}}
                })
                assert "facts" in result
                assert len(result["facts"]) >= 1
            finally:
                mem.close()

    def test_write_stores_facts(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "sem.db")
            mem = SemanticMemory(db_path=db)
            try:
                mem.write({
                    "runtime": {
                        "memory": {
                            "semantic": {
                                "store": [
                                    {"key": "fact1", "value": "value1", "tags": ["test"]},
                                    {"key": "fact2", "value": "value2"},
                                ]
                            }
                        }
                    }
                })
                assert mem.count() == 2
                assert mem.get("fact1")["value"] == "value1"
            finally:
                mem.close()
