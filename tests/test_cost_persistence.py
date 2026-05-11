"""Tests for end-to-end cost_usd persistence: client → AgentResult → step → SQLite."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import patch

from agent_runtime.agent.strategies import AgentResult, AgentTurn, _aggregate_cost
from agent_runtime.core import Run, RunState, StepExecution, StepStatus
from agent_runtime.llm import LLMRegistry, LLMProvider, ModelConfig
from agent_runtime.llm.client import LLMClient
from agent_runtime.llm.types import LLMResponse
from conftest import make_storage


class StubAdapter:
    provider_name = "openai"

    def call(
        self,
        *,
        api_key: str,
        model: str,
        prompt: str,
        system: Optional[str],
        params: Dict[str, Any],
        base_url: Optional[str],
        history: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        timeout: int = 60,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        return LLMResponse(
            text="ok",
            provider="openai",
            model=model,
            usage={"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
            raw={},
        )


def _client(**kwargs: Any) -> LLMClient:
    registry = LLMRegistry()
    provider = LLMProvider(name="openai", api_key_env="TEST_OPENAI_KEY")
    provider.add_model(ModelConfig(model_id="gpt-4o"))
    registry.register_provider(provider)
    return LLMClient(registry=registry, adapters={"openai": StubAdapter()}, **kwargs)


def test_response_cost_set_when_pricing_configured() -> None:
    pricing = {"openai/gpt-4o": {"input": 0.01, "output": 0.03}}
    client = _client(pricing_usd_per_1k_tokens=pricing)
    with patch.dict("os.environ", {"TEST_OPENAI_KEY": "x"}):
        resp = client.call(model="openai/gpt-4o", prompt="hi", context={"run_id": "r"})
    # (1000/1000)*0.01 + (500/1000)*0.03 = 0.025
    assert resp.cost_usd is not None
    assert abs(resp.cost_usd - 0.025) < 1e-9


def test_response_cost_none_when_pricing_unconfigured() -> None:
    client = _client()
    with patch.dict("os.environ", {"TEST_OPENAI_KEY": "x"}):
        resp = client.call(model="openai/gpt-4o", prompt="hi", context={"run_id": "r"})
    assert resp.cost_usd is None


def test_aggregate_cost_sums_across_turns() -> None:
    turns = [
        AgentTurn(
            iteration=1,
            llm_request={},
            llm_response=LLMResponse(text="", provider="openai", model="m", cost_usd=0.01),
        ),
        AgentTurn(
            iteration=2,
            llm_request={},
            llm_response=LLMResponse(text="", provider="openai", model="m", cost_usd=0.02),
        ),
    ]
    assert _aggregate_cost(turns) == 0.03


def test_aggregate_cost_none_when_no_costs() -> None:
    turns = [
        AgentTurn(
            iteration=1,
            llm_request={},
            llm_response=LLMResponse(text="", provider="openai", model="m"),
        ),
    ]
    assert _aggregate_cost(turns) is None


def test_step_cost_persists_through_sqlite_roundtrip() -> None:
    storage = make_storage()
    run = Run(
        run_id="r1",
        workflow_id="wf",
        workflow_version=None,
        workflow_hash=None,
        workflow_yaml=None,
        workflow_steps=None,
        input_hash=None,
        status=StepStatus.COMPLETED,
        created_at="2026-05-09T00:00:00",
    )
    storage.create_run(run)
    step = StepExecution(
        step_id="s1",
        step_type="agent",
        status=StepStatus.COMPLETED,
        execution_index=0,
        token_usage={"input_tokens": 100, "output_tokens": 50},
        cost_usd=0.0042,
    )
    storage.append_step("r1", step)

    loaded = storage.load_steps("r1")
    assert len(loaded) == 1
    assert loaded[0].cost_usd is not None
    assert abs(loaded[0].cost_usd - 0.0042) < 1e-9
    storage.close()


def test_step_cost_null_persists_as_none() -> None:
    storage = make_storage()
    run = Run(
        run_id="r2",
        workflow_id="wf",
        workflow_version=None,
        workflow_hash=None,
        workflow_yaml=None,
        workflow_steps=None,
        input_hash=None,
        status=StepStatus.COMPLETED,
        created_at="2026-05-09T00:00:00",
    )
    storage.create_run(run)
    step = StepExecution(step_id="s1", step_type="function", status=StepStatus.COMPLETED, execution_index=0)
    storage.append_step("r2", step)

    loaded = storage.load_steps("r2")
    assert loaded[0].cost_usd is None
    storage.close()


def test_run_total_cost_usd_aggregates_steps() -> None:
    run = Run(
        run_id="r",
        workflow_id="wf",
        workflow_version=None,
        workflow_hash=None,
        workflow_yaml=None,
        workflow_steps=None,
        input_hash=None,
        status=StepStatus.COMPLETED,
        created_at="2026-05-09T00:00:00",
    )
    run.add_step(StepExecution(step_id="a", step_type="agent", cost_usd=0.01))
    run.add_step(StepExecution(step_id="b", step_type="function"))  # no cost
    run.add_step(StepExecution(step_id="c", step_type="agent", cost_usd=0.025))
    assert run.total_cost_usd is not None
    assert abs(run.total_cost_usd - 0.035) < 1e-9


def test_run_total_cost_usd_none_when_no_step_has_cost() -> None:
    run = Run(
        run_id="r",
        workflow_id="wf",
        workflow_version=None,
        workflow_hash=None,
        workflow_yaml=None,
        workflow_steps=None,
        input_hash=None,
        status=StepStatus.COMPLETED,
        created_at="2026-05-09T00:00:00",
    )
    run.add_step(StepExecution(step_id="a", step_type="function"))
    assert run.total_cost_usd is None


def test_agent_result_cost_field_default_none() -> None:
    result = AgentResult(outputs={"x": 1})
    assert result.cost_usd is None
