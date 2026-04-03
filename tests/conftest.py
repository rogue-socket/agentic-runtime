"""Shared test fixtures for agentic-runtime tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_runtime.agent.strategies import AgentContext
from agent_runtime.llm.types import LLMResponse
from agent_runtime.memory.base import MemoryManager
from agent_runtime.memory.episodic import EpisodicMemory
from agent_runtime.memory.procedural import ProceduralMemory
from agent_runtime.memory.semantic import SemanticMemory
from agent_runtime.memory.working import WorkingMemory
from agent_runtime.storage.sqlite import SQLiteStorage
from agent_runtime.tools.base import ToolResult


def make_storage() -> SQLiteStorage:
    """Create a temporary SQLiteStorage instance for testing."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    return SQLiteStorage(tmp.name)


def make_memory_manager() -> MemoryManager:
    """Create an in-memory MemoryManager with all four tiers."""
    return MemoryManager(
        working=WorkingMemory(),
        episodic=EpisodicMemory(),
        semantic=SemanticMemory(),
        procedural=ProceduralMemory(),
    )


def functions_dir() -> str:
    """Return the absolute path to the project's functions/ directory."""
    return str(Path(__file__).resolve().parents[1] / "functions")


# [Pain Point Solved] #N10 Non-Deterministic Testing Paralysis: FakeLLMClient,
#   FakeTool, and FakeToolRegistry let you test the full execution pipeline with
#   predictable outputs. Combined with functions/stubs.py, you can integration-test
#   multi-step workflows without making a single LLM call.
# ── Fake helpers for agent / LLM / tool tests ──────────────────────────


class FakeLLMClient:
    """Fake LLM client that returns pre-configured responses."""

    def __init__(self, responses):
        """Function implementation."""
        self.responses = list(responses)
        self.calls = []

    def call(self, **kwargs):
        """Function implementation."""
        self.calls.append(kwargs)
        text = self.responses.pop(0) if self.responses else "empty"
        return LLMResponse(
            text=text, provider="fake", model="fake-model", usage={"tokens": 10}
        )


class FakeTool:
    """Minimal tool that satisfies the Tool protocol."""

    def __init__(self, name, output=None):
        """Function implementation."""
        self.name = name
        self.description = f"Fake {name}"
        self.input_schema = {"type": "object", "properties": {}}
        self.timeout = None
        self.retries = None
        self._output = output or {"result": "ok"}

    async def execute(self, input, context):
        """Function implementation."""
        return ToolResult(success=True, output=self._output, error=None, metadata=None)


class FakeToolRegistry:
    def __init__(self, tools=None):
        """Function implementation."""
        self._tools = {t.name: t for t in (tools or [])}

    def get(self, name):
        """Function implementation."""
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not found")
        return self._tools[name]


def fake_agent_context(**overrides):
    """Create a minimal AgentContext for testing."""
    defaults = dict(run_id="r1", step_id="s1", state={})
    defaults.update(overrides)
    return AgentContext(**defaults)
