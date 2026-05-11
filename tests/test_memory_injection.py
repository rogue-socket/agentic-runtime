"""Tests for opt-in memory injection into agent system prompts."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from agent_runtime.agent.definition import (
    AgentDefinition,
    PipelineStep,
    StrategyConfig,
    _parse_memory_injection,
)
from agent_runtime.agent.strategies import (
    SingleCallStrategy,
    _build_memory_preamble,
    _resolve_pipeline_system,
)
from agent_runtime.errors import AgentValidationError
from agent_runtime.tools.registry import ToolRegistry
from conftest import FakeLLMClient, fake_agent_context


def _agent(memory_injection: List[str], system: str = "You are helpful.") -> AgentDefinition:
    return AgentDefinition(
        agent_id="a",
        version="0.1.0",
        model="mock/test",
        system=system,
        pipeline=[PipelineStep(id="m1", type="model", prompt="hi")],
        strategy=StrategyConfig(type="single"),
        memory_injection=memory_injection,
    )


# -- _build_memory_preamble unit tests --------------------------------------


def test_preamble_empty_when_no_memory_in_state() -> None:
    assert _build_memory_preamble({}, ["semantic"]) == ""


def test_preamble_skips_empty_tier() -> None:
    state = {"runtime": {"memory": {"semantic": {}}}}
    assert _build_memory_preamble(state, ["semantic"]) == ""


def test_preamble_includes_only_requested_tiers() -> None:
    state = {
        "runtime": {
            "memory": {
                "semantic": {"facts": ["sky is blue"]},
                "episodic": {"episodes": [{"workflow_id": "wf1"}]},
            }
        }
    }
    out = _build_memory_preamble(state, ["semantic"])
    assert "### semantic" in out
    assert "sky is blue" in out
    assert "### episodic" not in out


def test_preamble_renders_multiple_tiers_in_order() -> None:
    state = {
        "runtime": {
            "memory": {
                "semantic": {"facts": ["f1"]},
                "episodic": {"episodes": ["e1"]},
            }
        }
    }
    out = _build_memory_preamble(state, ["episodic", "semantic"])
    assert out.index("### episodic") < out.index("### semantic")


# -- _resolve_pipeline_system integration -----------------------------------


def test_resolve_system_prepends_memory_when_injection_set() -> None:
    agent = _agent(memory_injection=["semantic"])
    state = {"runtime": {"memory": {"semantic": {"facts": ["alpha"]}}}}
    result = _resolve_pipeline_system(
        agent, agent.pipeline[0], tool_registry=None, state=state
    )
    assert result is not None
    assert "## Memory" in result
    assert "alpha" in result
    assert result.endswith("You are helpful.")


def test_resolve_system_unchanged_when_injection_empty() -> None:
    agent = _agent(memory_injection=[])
    state = {"runtime": {"memory": {"semantic": {"facts": ["alpha"]}}}}
    result = _resolve_pipeline_system(
        agent, agent.pipeline[0], tool_registry=None, state=state
    )
    assert result == "You are helpful."


def test_resolve_system_no_injection_when_state_missing() -> None:
    agent = _agent(memory_injection=["semantic"])
    result = _resolve_pipeline_system(
        agent, agent.pipeline[0], tool_registry=None, state=None
    )
    assert result == "You are helpful."


def test_resolve_system_handles_no_base_system() -> None:
    agent = _agent(memory_injection=["semantic"], system="")
    state = {"runtime": {"memory": {"semantic": {"facts": ["alpha"]}}}}
    result = _resolve_pipeline_system(
        agent, agent.pipeline[0], tool_registry=None, state=state
    )
    assert result is not None
    assert "## Memory" in result
    assert "alpha" in result


# -- end-to-end: memory reaches the LLM call --------------------------------


def test_memory_injection_reaches_llm_via_strategy() -> None:
    agent = _agent(memory_injection=["semantic"], system="Answer questions.")
    fake = FakeLLMClient(["ok"])
    state = {"runtime": {"memory": {"semantic": {"facts": ["water boils at 100C"]}}}}
    ctx = fake_agent_context(state=state)

    asyncio.run(
        SingleCallStrategy().run(agent, fake, ToolRegistry(), inputs={}, context=ctx)
    )
    assert len(fake.calls) == 1
    system = fake.calls[0]["system"]
    assert "## Memory" in system
    assert "water boils at 100C" in system


def test_no_memory_injection_keeps_system_clean() -> None:
    agent = _agent(memory_injection=[], system="Answer questions.")
    fake = FakeLLMClient(["ok"])
    state = {"runtime": {"memory": {"semantic": {"facts": ["x"]}}}}
    ctx = fake_agent_context(state=state)

    asyncio.run(
        SingleCallStrategy().run(agent, fake, ToolRegistry(), inputs={}, context=ctx)
    )
    assert fake.calls[0]["system"] == "Answer questions."


# -- YAML parsing -----------------------------------------------------------


def test_parse_memory_injection_accepts_valid_tiers() -> None:
    result = _parse_memory_injection(["semantic", "episodic"], "test.yaml")
    assert result == ["semantic", "episodic"]


def test_parse_memory_injection_dedups() -> None:
    result = _parse_memory_injection(["semantic", "semantic"], "test.yaml")
    assert result == ["semantic"]


def test_parse_memory_injection_rejects_unknown_tier() -> None:
    with pytest.raises(AgentValidationError, match="invalid memory_injection tier"):
        _parse_memory_injection(["bogus"], "test.yaml")


def test_parse_memory_injection_rejects_non_list() -> None:
    with pytest.raises(AgentValidationError, match="must be a list"):
        _parse_memory_injection("semantic", "test.yaml")


def test_parse_memory_injection_empty_default() -> None:
    assert _parse_memory_injection([], "test.yaml") == []
    assert _parse_memory_injection(None, "test.yaml") == []


def test_to_dict_round_trip_preserves_memory_injection() -> None:
    agent = _agent(memory_injection=["semantic", "episodic"])
    data = agent.to_dict()
    assert data["agent"]["memory_injection"] == ["semantic", "episodic"]


def test_to_dict_omits_memory_injection_when_empty() -> None:
    agent = _agent(memory_injection=[])
    data = agent.to_dict()
    assert "memory_injection" not in data["agent"]
