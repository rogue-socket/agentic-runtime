"""Tests for public factory functions in defaults.py."""

from __future__ import annotations

import os
import tempfile

from agent_runtime.defaults import (
    default_agent_registry,
    default_llm_client,
    default_memory_manager,
    default_tool_registry,
)
from agent_runtime.config import RuntimeConfig


class TestDefaultToolRegistry:
    def test_builtin_tools_registered(self):
        registry = default_tool_registry(tools_dir="__nonexistent__")
        names = set(registry._tools.keys())
        assert "tools.echo" in names
        assert "tools.http" in names
        assert "tools.file" in names
        assert "tools.shell" in names

    def test_returns_tool_registry_type(self):
        from agent_runtime.tools import ToolRegistry
        registry = default_tool_registry(tools_dir="__nonexistent__")
        assert isinstance(registry, ToolRegistry)


class TestDefaultMemoryManager:
    def test_returns_memory_manager_with_all_tiers(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "test.db")
            mm = default_memory_manager(db_path=db)
            assert mm.working is not None
            assert mm.episodic is not None
            assert mm.semantic is not None
            assert mm.procedural is not None

    def test_custom_limits(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "test.db")
            mm = default_memory_manager(db_path=db, max_entries=10, max_scratch_bytes=1024)
            assert mm.working._max_entries == 10
            assert mm.working._max_scratch_bytes == 1024


class TestDefaultLLMClient:
    def test_returns_llm_client(self):
        from agent_runtime.llm import LLMClient
        cfg = RuntimeConfig()
        client = default_llm_client(cfg)
        assert isinstance(client, LLMClient)


class TestDefaultAgentRegistry:
    def test_empty_when_dir_missing(self):
        registry = default_agent_registry(agents_dir="__nonexistent__")
        assert len(registry.list_agents()) == 0

    def test_discovers_agents_from_dir(self):
        with tempfile.TemporaryDirectory() as d:
            agent_yaml = os.path.join(d, "test_agent.yaml")
            with open(agent_yaml, "w") as f:
                f.write(
                    "schema_version: v1\n"
                    "agent:\n"
                    "  id: test_agent\n"
                    "  version: v1\n"
                    "  description: test\n"
                    "  system: test system prompt\n"
                    "  pipeline:\n"
                    "    - id: main\n"
                    "      type: model\n"
                    "      prompt: hello\n"
                )
            registry = default_agent_registry(agents_dir=d)
            assert "test_agent" in registry.list_agents()
