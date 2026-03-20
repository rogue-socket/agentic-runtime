"""End-to-end Executor tests for type:function, type:agent, and circular branches.

These tests wire up real Executor instances and run complete workflows
to verify the modern step types work through the full execution loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest

from agent_runtime.core import Executor, StepDefinition, StepStatus, NextRule
from agent_runtime.errors import BranchResolutionError, StepExecutionError
from agent_runtime.tools.registry import ToolRegistry
from agent_runtime.tools.base import RuntimeContext, ToolResult
from agent_runtime.agent.definition import AgentDefinition, PipelineStep, StrategyConfig
from agent_runtime.agent.registry import AgentRegistry
from agent_runtime.llm.types import LLMResponse
from conftest import make_storage, make_memory_manager


# ---------------------------------------------------------------------------
# type:function — end‑to‑end through Executor
# ---------------------------------------------------------------------------


class TestFunctionStepE2E:

    def test_function_step_success(self) -> None:
        """A function step produces output visible in run state."""

        def summarize(inputs: dict) -> dict:
            return {"summary": f"Summary of: {inputs['issue']}"}

        steps = [
            StepDefinition(
                step_id="summarize",
                step_type="function",
                function_ref="stubs.summarize",
                function_callable=summarize,
                input_spec={"issue": "inputs.issue"},
            )
        ]
        executor = Executor(steps, make_storage(), None, make_memory_manager(), ToolRegistry())
        run = executor.run("wf", {"issue": "Login fails"})

        assert run.status == StepStatus.COMPLETED
        assert run.state.data["steps"]["summarize"]["summary"] == "Summary of: Login fails"

    def test_function_step_missing_callable(self) -> None:
        """A function step with no resolved callable fails gracefully."""
        steps = [
            StepDefinition(
                step_id="broken",
                step_type="function",
                function_ref="missing.func",
                function_callable=None,
            )
        ]
        executor = Executor(steps, make_storage(), None, make_memory_manager(), ToolRegistry())
        run = executor.run("wf", {})

        assert run.status == StepStatus.FAILED

    def test_multi_function_linear(self) -> None:
        """Two function steps run sequentially and share state."""

        def step_one(inputs: dict) -> dict:
            return {"value": 10}

        def step_two(inputs: dict) -> dict:
            return {"doubled": inputs["value"] * 2}

        steps = [
            StepDefinition(
                step_id="one",
                step_type="function",
                function_callable=step_one,
                function_ref="step_one",
            ),
            StepDefinition(
                step_id="two",
                step_type="function",
                function_callable=step_two,
                function_ref="step_two",
                input_spec={"value": "steps.one.value"},
            ),
        ]
        executor = Executor(steps, make_storage(), None, make_memory_manager(), ToolRegistry())
        run = executor.run("wf", {})

        assert run.status == StepStatus.COMPLETED
        assert run.state.data["steps"]["two"]["doubled"] == 20

    def test_function_step_with_branching(self) -> None:
        """Function steps can participate in conditional branching."""

        def classify(inputs: dict) -> dict:
            return {"severity": "critical"}

        def handle_critical(inputs: dict) -> dict:
            return {"action": "page_oncall"}

        def handle_low(inputs: dict) -> dict:
            return {"action": "log_only"}

        steps = [
            StepDefinition(
                step_id="classify",
                step_type="function",
                function_ref="classify",
                function_callable=classify,
                next_rules=[
                    NextRule(when="state.steps.classify.severity == 'critical'", goto="critical_path"),
                    NextRule(when=None, goto="low_path", is_default=True),
                ],
            ),
            StepDefinition(
                step_id="critical_path",
                step_type="function",
                function_ref="handle_critical",
                function_callable=handle_critical,
            ),
            StepDefinition(
                step_id="low_path",
                step_type="function",
                function_ref="handle_low",
                function_callable=handle_low,
            ),
        ]
        executor = Executor(steps, make_storage(), None, make_memory_manager(), ToolRegistry())
        run = executor.run("wf", {})

        assert run.status == StepStatus.COMPLETED
        assert "critical_path" in run.state.data["steps"]
        assert run.state.data["steps"]["critical_path"]["action"] == "page_oncall"


# ---------------------------------------------------------------------------
# type:agent — end‑to‑end through Executor (with fake LLM)
# ---------------------------------------------------------------------------


class FakeLLMClient:
    """Minimal LLM client that returns a canned response."""

    def __init__(self, response_text: str = "result from LLM") -> None:
        self._text = response_text

    def call(self, **kwargs: Any) -> LLMResponse:
        return LLMResponse(
            text=self._text,
            provider="fake",
            model="fake-model",
            usage={},
            raw={},
        )


class TestAgentStepE2E:

    def _make_agent_registry(self, agent_def: AgentDefinition) -> AgentRegistry:
        registry = AgentRegistry()
        registry.register(agent_def)
        return registry

    def test_agent_step_single_strategy(self) -> None:
        """Agent step with single-call strategy runs through Executor."""
        agent_def = AgentDefinition(
            agent_id="summarizer",
            version="v1",
            model="fake-model",
            system="You summarize issues.",
            strategy=StrategyConfig(type="single"),
            pipeline=[
                PipelineStep(
                    id="summarize_call",
                    type="model",
                    prompt="Summarize: {{ inputs.issue }}",
                ),
            ],
        )
        registry = self._make_agent_registry(agent_def)

        steps = [
            StepDefinition(
                step_id="summarize",
                step_type="agent",
                agent_id="summarizer",
                input_spec={"issue": "inputs.issue"},
            )
        ]

        executor = Executor(
            steps,
            make_storage(),
            None,
            make_memory_manager(),
            ToolRegistry(),
            agent_registry=registry,
            llm_client=FakeLLMClient("The login system has a token validation bug."),
        )
        run = executor.run("wf", {"issue": "Login fails on invalid tokens"})

        assert run.status == StepStatus.COMPLETED
        assert "summarize" in run.state.data["steps"]

    def test_agent_step_no_registry_fails(self) -> None:
        """Agent step fails clearly when no AgentRegistry is configured."""
        steps = [
            StepDefinition(
                step_id="review",
                step_type="agent",
                agent_id="reviewer",
            )
        ]
        executor = Executor(
            steps, make_storage(), None, make_memory_manager(), ToolRegistry(),
            agent_registry=None,
        )
        run = executor.run("wf", {})

        assert run.status == StepStatus.FAILED
        assert "AgentRegistry" in (run.error or "")

    def test_agent_step_no_llm_client_fails(self) -> None:
        """Agent step fails clearly when no LLM client is configured."""
        agent_def = AgentDefinition(
            agent_id="test_agent",
            version="v1",
            model="fake-model",
            system="test",
            strategy=StrategyConfig(type="single"),
            pipeline=[PipelineStep(id="call", type="model", prompt="test")],
        )
        registry = self._make_agent_registry(agent_def)

        steps = [
            StepDefinition(
                step_id="review",
                step_type="agent",
                agent_id="test_agent",
            )
        ]
        executor = Executor(
            steps, make_storage(), None, make_memory_manager(), ToolRegistry(),
            agent_registry=registry,
            llm_client=None,
        )
        run = executor.run("wf", {})

        assert run.status == StepStatus.FAILED
        assert "LLM" in (run.error or "") or "llm" in (run.error or "").lower()


# ---------------------------------------------------------------------------
# Circular branch detection
# ---------------------------------------------------------------------------


class TestCircularBranchDetection:

    def test_circular_branch_raises(self) -> None:
        """Two steps that branch back to each other should raise BranchResolutionError."""

        def noop(inputs: dict) -> dict:
            return {"done": True}

        steps = [
            StepDefinition(
                step_id="step_a",
                step_type="function",
                function_ref="noop",
                function_callable=noop,
                next_rules=[NextRule(when=None, goto="step_b", is_default=True)],
            ),
            StepDefinition(
                step_id="step_b",
                step_type="function",
                function_ref="noop",
                function_callable=noop,
                next_rules=[NextRule(when=None, goto="step_a", is_default=True)],
            ),
        ]
        executor = Executor(steps, make_storage(), None, make_memory_manager(), ToolRegistry())

        with pytest.raises(BranchResolutionError, match="Circular branch detected"):
            executor.run("wf", {})

    def test_self_referencing_step_raises(self) -> None:
        """A step that branches to itself should raise BranchResolutionError."""

        def noop(inputs: dict) -> dict:
            return {"done": True}

        steps = [
            StepDefinition(
                step_id="loop",
                step_type="function",
                function_ref="noop",
                function_callable=noop,
                next_rules=[NextRule(when=None, goto="loop", is_default=True)],
            ),
        ]
        executor = Executor(steps, make_storage(), None, make_memory_manager(), ToolRegistry())

        with pytest.raises(BranchResolutionError, match="Circular branch detected"):
            executor.run("wf", {})

    def test_linear_workflow_no_false_positive(self) -> None:
        """Normal linear workflow (no branches) should not trigger cycle detection."""

        def step_fn(inputs: dict) -> dict:
            return {"ok": True}

        steps = [
            StepDefinition(step_id="a", step_type="function", function_ref="f", function_callable=step_fn),
            StepDefinition(step_id="b", step_type="function", function_ref="f", function_callable=step_fn),
            StepDefinition(step_id="c", step_type="function", function_ref="f", function_callable=step_fn),
        ]
        executor = Executor(steps, make_storage(), None, make_memory_manager(), ToolRegistry())
        run = executor.run("wf", {})

        assert run.status == StepStatus.COMPLETED
        assert len(run.state.data["steps"]) == 3

    def test_branching_without_cycle_succeeds(self) -> None:
        """A workflow that branches forward (not backward) should succeed."""

        def classify(inputs: dict) -> dict:
            return {"path": "fast"}

        def fast(inputs: dict) -> dict:
            return {"result": "quick"}

        def slow(inputs: dict) -> dict:
            return {"result": "thorough"}

        steps = [
            StepDefinition(
                step_id="classify",
                step_type="function",
                function_ref="classify",
                function_callable=classify,
                next_rules=[
                    NextRule(goto="fast", when="state.steps.classify.path == 'fast'"),
                    NextRule(when=None, goto="slow", is_default=True),
                ],
            ),
            StepDefinition(step_id="fast", step_type="function", function_ref="fast", function_callable=fast),
            StepDefinition(step_id="slow", step_type="function", function_ref="slow", function_callable=slow),
        ]
        executor = Executor(steps, make_storage(), None, make_memory_manager(), ToolRegistry())
        run = executor.run("wf", {})

        assert run.status == StepStatus.COMPLETED
        assert "fast" in run.state.data["steps"]
        assert run.state.data["steps"]["fast"]["result"] == "quick"
