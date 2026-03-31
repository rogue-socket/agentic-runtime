"""Tests for strategies.py bug fixes."""
import pytest


class TestParseToolCallsRegex:
    """Bug 6: _parse_tool_calls now uses regex tolerant of whitespace."""

    def test_standard_format(self):
        from agent_runtime.agent.strategies import _parse_tool_calls
        text = '```tool_call\n{"tool": "search", "input": {"q": "hello"}}\n```'
        result = _parse_tool_calls(text)
        assert len(result) == 1
        assert result[0]["tool"] == "search"

    def test_space_before_tag(self):
        from agent_runtime.agent.strategies import _parse_tool_calls
        text = '``` tool_call\n{"tool": "search", "input": {}}\n```'
        result = _parse_tool_calls(text)
        assert len(result) == 1
        assert result[0]["tool"] == "search"

    def test_extra_whitespace(self):
        from agent_runtime.agent.strategies import _parse_tool_calls
        text = '```  tool_call  \n{"tool": "fetch", "input": {"url": "x"}}\n```'
        result = _parse_tool_calls(text)
        assert len(result) == 1
        assert result[0]["tool"] == "fetch"

    def test_multiple_calls(self):
        from agent_runtime.agent.strategies import _parse_tool_calls
        text = (
            'some text\n```tool_call\n{"tool": "a", "input": {}}\n```\n'
            'more text\n``` tool_call\n{"tool": "b", "input": {}}\n```\n'
        )
        result = _parse_tool_calls(text)
        assert len(result) == 2
        assert result[0]["tool"] == "a"
        assert result[1]["tool"] == "b"

    def test_invalid_json_skipped(self):
        from agent_runtime.agent.strategies import _parse_tool_calls
        text = '```tool_call\nnot json\n```'
        assert _parse_tool_calls(text) == []

    def test_no_tool_key_skipped(self):
        from agent_runtime.agent.strategies import _parse_tool_calls
        text = '```tool_call\n{"action": "search"}\n```'
        assert _parse_tool_calls(text) == []


class TestParseFinalAnswerRegex:
    """Bug 6: _parse_final_answer now uses regex tolerant of whitespace."""

    def test_standard_format(self):
        from agent_runtime.agent.strategies import _parse_final_answer
        text = '```final_answer\n{"result": "done"}\n```'
        result = _parse_final_answer(text)
        assert result == {"result": "done"}

    def test_space_before_tag(self):
        from agent_runtime.agent.strategies import _parse_final_answer
        text = '``` final_answer\n{"result": "ok"}\n```'
        result = _parse_final_answer(text)
        assert result == {"result": "ok"}

    def test_no_answer(self):
        from agent_runtime.agent.strategies import _parse_final_answer
        assert _parse_final_answer("just some text") is None


class TestResolvePipelineToolInputs:
    """Bug 5: dotted literals like 'com.example.package' should not resolve as paths."""

    def test_dotted_literal_not_resolved(self):
        from agent_runtime.agent.strategies import _resolve_pipeline_tool_inputs
        state = {"inputs": {"x": 1}}
        result = _resolve_pipeline_tool_inputs(
            {"pkg": "com.example.package"},
            state,
        )
        assert result["pkg"] == "com.example.package"

    def test_valid_path_resolved(self):
        from agent_runtime.agent.strategies import _resolve_pipeline_tool_inputs
        state = {"inputs": {"url": "https://example.com"}, "analyze": {"file": "main.py"}}
        result = _resolve_pipeline_tool_inputs(
            {"target": "analyze.file"},
            state,
        )
        assert result["target"] == "main.py"

    def test_inputs_path_resolved(self):
        from agent_runtime.agent.strategies import _resolve_pipeline_tool_inputs
        state = {"inputs": {"repo": "my-repo"}}
        result = _resolve_pipeline_tool_inputs(
            {"repo": "inputs.repo"},
            state,
        )
        assert result["repo"] == "my-repo"

    def test_non_dotted_passes_through(self):
        from agent_runtime.agent.strategies import _resolve_pipeline_tool_inputs
        state = {"inputs": {}}
        result = _resolve_pipeline_tool_inputs(
            {"name": "hello"},
            state,
        )
        assert result["name"] == "hello"

    def test_empty_inputs(self):
        from agent_runtime.agent.strategies import _resolve_pipeline_tool_inputs
        assert _resolve_pipeline_tool_inputs(None, {}) == {}


class TestLLMClientMemoryLeak:
    """Bug 2: _run_usage should not grow unbounded."""

    def test_clear_run_usage(self):
        from agent_runtime.llm.client import LLMClient
        from agent_runtime.llm.registry import LLMRegistry
        client = LLMClient(registry=LLMRegistry())
        # Simulate usage tracking
        with client._lock:
            client._get_or_create_usage("run-1")
            client._get_or_create_usage("run-2")
        assert "run-1" in client._run_usage
        client.clear_run_usage("run-1")
        assert "run-1" not in client._run_usage
        assert "run-2" in client._run_usage

    def test_lru_eviction(self):
        from agent_runtime.llm.client import LLMClient
        from agent_runtime.llm.registry import LLMRegistry
        client = LLMClient(registry=LLMRegistry())
        client._max_tracked_runs = 3
        with client._lock:
            client._get_or_create_usage("a")
            client._get_or_create_usage("b")
            client._get_or_create_usage("c")
            # This should evict "a" (oldest)
            client._get_or_create_usage("d")
        assert "a" not in client._run_usage
        assert len(client._run_usage) == 3

    def test_clear_nonexistent_noop(self):
        from agent_runtime.llm.client import LLMClient
        from agent_runtime.llm.registry import LLMRegistry
        client = LLMClient(registry=LLMRegistry())
        client.clear_run_usage("nonexistent")  # should not raise


class TestStopConditionErrorLogging:
    """Bug 1: stop_conditions should log errors, not silently swallow them."""

    @pytest.mark.asyncio
    async def test_bad_condition_emits_event(self):
        from agent_runtime.agent.strategies import ReActStrategy, AgentContext
        from agent_runtime.agent.definition import (
            AgentDefinition, PipelineStep, StrategyConfig,
        )
        from agent_runtime.llm.types import LLMResponse
        from agent_runtime.tools.registry import ToolRegistry

        events = []

        def on_event(name, payload):
            events.append((name, payload))

        class FakeLLM:
            def call(self, **kwargs):
                return LLMResponse(
                    text='```final_answer\n{"done": true}\n```',
                    usage={"input_tokens": 10, "output_tokens": 10},
                )

        agent = AgentDefinition(
            agent_id="test", version="1",
            model="mock/test",
            pipeline=[PipelineStep(id="think", type="model", prompt="test")],
            strategy=StrategyConfig(
                type="react",
                max_iterations=3,
                stop_conditions=["state.nonexistent.deep.path == True"],
            ),
        )
        ctx = AgentContext(
            run_id="r1", step_id="s1", state={}, on_event=on_event,
        )
        strategy = ReActStrategy()
        # The final_answer block means the loop stops on iteration 1 anyway,
        # but the stop condition is evaluated AFTER the final_answer check,
        # so it won't fire. Let's adjust: remove final_answer so the stop condition fires.

        class FakeLLM2:
            def call(self, **kwargs):
                return LLMResponse(
                    text="I need to think more",
                    usage={"input_tokens": 10, "output_tokens": 10},
                    provider="mock", model="test",
                )

        agent2 = AgentDefinition(
            agent_id="test", version="1",
            model="mock/test",
            pipeline=[PipelineStep(id="think", type="model", prompt="test")],
            strategy=StrategyConfig(
                type="react",
                max_iterations=2,
                stop_conditions=["nonexistent_var == True"],
            ),
        )
        events.clear()
        result = await strategy.run(agent2, FakeLLM2(), ToolRegistry(), {"q": "x"}, ctx)
        # Should have emitted AGENT_STOP_CONDITION_ERROR events
        error_events = [e for e in events if e[0] == "AGENT_STOP_CONDITION_ERROR"]
        assert len(error_events) >= 1
        assert "nonexistent_var" in error_events[0][1]["condition"]


class TestDispatchToolCallUnified:
    """Bug 3: Both native and text paths should use unified dispatch."""

    @pytest.mark.asyncio
    async def test_allowlist_rejection(self):
        from agent_runtime.agent.strategies import _dispatch_tool_call, AgentContext
        from agent_runtime.agent.definition import AgentDefinition, PipelineStep, StrategyConfig
        from agent_runtime.tools.registry import ToolRegistry

        agent = AgentDefinition(
            agent_id="test", version="1",
            model="mock/test",
            pipeline=[PipelineStep(id="think", type="model", prompt="test")],
            tools=["allowed_tool"],
        )
        ctx = AgentContext(run_id="r1", step_id="s1", state={})
        record = await _dispatch_tool_call(
            "forbidden_tool", {"x": 1},
            agent, ToolRegistry(), ctx, 1, "step1",
        )
        assert record.result is not None
        assert not record.result.success
        assert "not in the agent's allowed tools list" in record.result.error
