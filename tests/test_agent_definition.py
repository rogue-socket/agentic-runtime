"""Tests for the agent definition layer (Phase 1 + Phase 2 pipeline).

Covers: PromptRegistry, AgentDefinition, PipelineStep, AgentRegistry,
strategies, and AgentExecutor.
"""

import asyncio
import os
import tempfile
import textwrap

import pytest

from agent_runtime.agent.prompts import PromptEntry, PromptRegistry
from agent_runtime.agent.definition import (
    AgentDefinition,
    PipelineStep,
    StrategyConfig,
    load_agent_definition,
)
from agent_runtime.agent.registry import AgentRegistry
from agent_runtime.agent.strategies import (
    AgentResult,
    AgentTurn,
    SingleCallStrategy,
    ReActStrategy,
    resolve_strategy,
    _parse_tool_calls,
    _parse_final_answer,
    _build_tool_preamble,
    _resolve_pipeline_system,
)
from agent_runtime.agent.executor import AgentExecutor
from agent_runtime.errors import AgentValidationError
from conftest import FakeLLMClient, FakeTool, FakeToolRegistry, fake_agent_context


def _run(coro):
    return asyncio.run(coro)


def _simple_pipeline(prompt="Hello {{ inputs.text }}"):
    """Return a minimal one-step pipeline for tests."""
    return [PipelineStep(id="main", type="model", prompt=prompt)]


# ── Prompt Registry ──────────────────────────────────────────────────────


class TestPromptRegistry:
    def test_register_and_get(self):
        reg = PromptRegistry()
        entry = PromptEntry(prompt_id="sys", version="v1", text="Hello")
        reg.register(entry)
        assert reg.get("sys", "v1") is entry

    def test_get_latest(self):
        reg = PromptRegistry()
        reg.register(PromptEntry(prompt_id="sys", version="v1", text="Old"))
        reg.register(PromptEntry(prompt_id="sys", version="v2", text="New"))
        assert reg.get("sys").text == "New"

    def test_get_latest_numeric_sort(self):
        reg = PromptRegistry()
        for i in [1, 2, 10, 3]:
            reg.register(
                PromptEntry(prompt_id="p", version=f"v{i}", text=f"text-{i}")
            )
        assert reg.get("p").version == "v10"

    def test_duplicate_raises(self):
        reg = PromptRegistry()
        reg.register(PromptEntry(prompt_id="p", version="v1", text="a"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(PromptEntry(prompt_id="p", version="v1", text="b"))

    def test_get_missing_raises(self):
        reg = PromptRegistry()
        with pytest.raises(KeyError, match="not found"):
            reg.get("nope")

    def test_get_missing_version_raises(self):
        reg = PromptRegistry()
        reg.register(PromptEntry(prompt_id="p", version="v1", text="a"))
        with pytest.raises(KeyError, match="version 'v9'"):
            reg.get("p", "v9")

    def test_resolve_latest(self):
        reg = PromptRegistry()
        reg.register(PromptEntry(prompt_id="sys", version="v1", text="Hello"))
        assert reg.resolve("prompts.sys") == "Hello"

    def test_resolve_pinned(self):
        reg = PromptRegistry()
        reg.register(PromptEntry(prompt_id="sys", version="v1", text="Old"))
        reg.register(PromptEntry(prompt_id="sys", version="v2", text="New"))
        assert reg.resolve("prompts.sys@v1") == "Old"
        assert reg.resolve("prompts.sys@v2") == "New"

    def test_resolve_bad_prefix(self):
        reg = PromptRegistry()
        with pytest.raises(ValueError, match="must start with"):
            reg.resolve("sys.prompt")

    def test_list_prompts(self):
        reg = PromptRegistry()
        reg.register(PromptEntry(prompt_id="a", version="v2", text="x"))
        reg.register(PromptEntry(prompt_id="a", version="v1", text="y"))
        reg.register(PromptEntry(prompt_id="b", version="v1", text="z"))
        listing = reg.list_prompts()
        assert listing == {"a": ["v1", "v2"], "b": ["v1"]}

    def test_from_directory(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.yaml")
            with open(path, "w") as f:
                f.write(textwrap.dedent("""\
                    prompts:
                      - id: greet
                        version: v1
                        text: "Hello world"
                      - id: farewell
                        version: v1
                        text: "Goodbye"
                """))
            reg = PromptRegistry.from_directory(d)
            assert reg.get("greet").text == "Hello world"
            assert reg.get("farewell").text == "Goodbye"

    def test_from_directory_single_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "single.yaml")
            with open(path, "w") as f:
                f.write(textwrap.dedent("""\
                    prompt:
                      id: solo
                      version: v1
                      text: "I am alone"
                """))
            reg = PromptRegistry.from_directory(d)
            assert reg.resolve("prompts.solo") == "I am alone"

    def test_from_directory_missing_dir(self):
        reg = PromptRegistry.from_directory("/nonexistent/path")
        assert reg.list_prompts() == {}


# ── Agent Definition ─────────────────────────────────────────────────────


class TestAgentDefinition:
    def test_load_minimal(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(textwrap.dedent("""\
                schema_version: v1

                agent:
                  id: test_agent
                  version: v1
                  model: openai/gpt-4
                  pipeline:
                    - id: main
                      type: model
                      prompt: "Hello {{ inputs.text }}"
            """))
            f.flush()
            path = f.name
        try:
            defn = load_agent_definition(path)
            assert defn.schema_version == "v1"
            assert defn.agent_id == "test_agent"
            assert defn.version == "v1"
            assert defn.model == "openai/gpt-4"
            assert defn.strategy.type == "single"
            assert defn.tools == []
            assert defn.temperature == 0.2
            assert len(defn.pipeline) == 1
            assert defn.pipeline[0].id == "main"
        finally:
            os.unlink(path)

    def test_load_full(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(textwrap.dedent("""\
                schema_version: v1

                agent:
                  id: reviewer
                  version: v2
                  description: "Code reviewer"
                  model: gemini/gemini-2.5-flash
                  system: "You are a reviewer"
                  tools:
                    - tools.file
                    - tools.http
                  strategy:
                    type: react
                    max_iterations: 5
                  temperature: 0.3
                  max_tokens: 8192
                  params:
                    top_p: 0.9
                  pipeline:
                    - id: analyze
                      type: model
                      prompt: "Analyze: {{ inputs.diff }}"
                    - id: fetch
                      type: tool
                      tool: tools.file
                      inputs:
                        path: analyze.suggested_file
                    - id: review
                      type: model
                      prompt: "Review {{ analyze.text }} with {{ fetch }}"
            """))
            f.flush()
            path = f.name
        try:
            defn = load_agent_definition(path)
            assert defn.schema_version == "v1"
            assert defn.agent_id == "reviewer"
            assert defn.version == "v2"
            assert defn.description == "Code reviewer"
            assert defn.system == "You are a reviewer"
            assert defn.tools == ["tools.file", "tools.http"]
            assert defn.strategy.type == "react"
            assert defn.strategy.max_iterations == 5
            assert defn.temperature == 0.3
            assert defn.max_tokens == 8192
            assert defn.params == {"top_p": 0.9}
            assert len(defn.pipeline) == 3
            assert defn.pipeline[0].type == "model"
            assert defn.pipeline[1].type == "tool"
            assert defn.pipeline[1].tool == "tools.file"
            assert defn.pipeline[2].type == "model"
        finally:
            os.unlink(path)

    def test_load_missing_file(self):
        with pytest.raises(AgentValidationError, match="not found"):
            load_agent_definition("/nonexistent/agent.yaml")

    def test_load_missing_required_field(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("schema_version: v1\nagent:\n  id: x\n")
            f.flush()
            path = f.name
        try:
            with pytest.raises(AgentValidationError, match="missing required field 'version'"):
                load_agent_definition(path)
        finally:
            os.unlink(path)

    def test_load_missing_schema_version(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("agent:\n  id: x\n  version: v1\n")
            f.flush()
            path = f.name
        try:
            with pytest.raises(AgentValidationError, match="schema_version is required"):
                load_agent_definition(path)
        finally:
            os.unlink(path)

    def test_load_missing_agent_key(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("workflow:\n  id: x\n")
            f.flush()
            path = f.name
        try:
            with pytest.raises(AgentValidationError, match="missing top-level 'agent'"):
                load_agent_definition(path)
        finally:
            os.unlink(path)

    def test_invalid_strategy_type(self):
        with pytest.raises(AgentValidationError, match="Invalid strategy type"):
            StrategyConfig(type="invalid")

    def test_custom_strategy_requires_handler(self):
        with pytest.raises(AgentValidationError, match="requires 'custom_handler'"):
            StrategyConfig(type="custom")

    def test_to_dict_roundtrip(self):
        defn = AgentDefinition(
            agent_id="test",
            version="v1",
            model="gpt-4",
            system="sys",
            tools=["tools.echo"],
            pipeline=_simple_pipeline(),
        )
        d = defn.to_dict()
        assert d["schema_version"] == "v1"
        assert d["agent"]["id"] == "test"
        assert d["agent"]["tools"] == ["tools.echo"]
        assert len(d["agent"]["pipeline"]) == 1
        assert d["agent"]["pipeline"][0]["type"] == "model"

    def test_strategy_shorthand_string(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(textwrap.dedent("""\
                schema_version: v1

                agent:
                  id: t
                  version: v1
                  model: m
                  strategy: react
                  pipeline:
                    - id: main
                      type: model
                      prompt: "hello"
            """))
            f.flush()
            path = f.name
        try:
            defn = load_agent_definition(path)
            assert defn.strategy.type == "react"
        finally:
            os.unlink(path)

    def test_tools_as_single_string(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(textwrap.dedent("""\
                schema_version: v1

                agent:
                  id: t
                  version: v1
                  model: m
                  tools: tools.echo
                  pipeline:
                    - id: main
                      type: model
                      prompt: "hello"
            """))
            f.flush()
            path = f.name
        try:
            defn = load_agent_definition(path)
            assert defn.tools == ["tools.echo"]
        finally:
            os.unlink(path)

    def test_missing_pipeline_raises(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(textwrap.dedent("""\
                schema_version: v1

                agent:
                  id: t
                  version: v1
                  model: m
            """))
            f.flush()
            path = f.name
        try:
            with pytest.raises(AgentValidationError, match="pipeline"):
                load_agent_definition(path)
        finally:
            os.unlink(path)

    def test_pipeline_tool_not_in_allowlist_raises(self):
        with pytest.raises(AgentValidationError, match="not in the agent's tools list"):
            AgentDefinition(
                agent_id="a", version="v1", model="m",
                tools=["tools.echo"],
                pipeline=[
                    PipelineStep(id="main", type="tool", tool="tools.file"),
                ],
            )

    def test_pipeline_model_step_requires_prompt(self):
        with pytest.raises(AgentValidationError, match="requires a 'prompt'"):
            PipelineStep(id="bad", type="model", prompt="")

    def test_pipeline_tool_step_requires_tool(self):
        with pytest.raises(AgentValidationError, match="requires a 'tool'"):
            PipelineStep(id="bad", type="tool")


# ── Agent Registry ───────────────────────────────────────────────────────


class TestAgentRegistry:
    def test_register_and_get(self):
        reg = AgentRegistry()
        defn = AgentDefinition(agent_id="a", version="v1", model="m")
        reg.register(defn)
        assert reg.get("a", "v1") is defn

    def test_get_latest(self):
        reg = AgentRegistry()
        reg.register(AgentDefinition(agent_id="a", version="v1", model="m"))
        reg.register(AgentDefinition(agent_id="a", version="v2", model="m"))
        assert reg.get("a").version == "v2"

    def test_duplicate_raises(self):
        reg = AgentRegistry()
        reg.register(AgentDefinition(agent_id="a", version="v1", model="m"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(AgentDefinition(agent_id="a", version="v1", model="m"))

    def test_get_missing_raises(self):
        reg = AgentRegistry()
        with pytest.raises(KeyError, match="not found"):
            reg.get("nope")

    def test_list_agents(self):
        reg = AgentRegistry()
        reg.register(AgentDefinition(agent_id="a", version="v2", model="m"))
        reg.register(AgentDefinition(agent_id="a", version="v1", model="m"))
        reg.register(AgentDefinition(agent_id="b", version="v1", model="m"))
        assert reg.list_agents() == {"a": ["v1", "v2"], "b": ["v1"]}

    def test_from_directory(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "agent.yaml")
            with open(path, "w") as f:
                f.write(textwrap.dedent("""\
                    schema_version: v1

                    agent:
                      id: disc_agent
                      version: v1
                      model: gpt-4
                      pipeline:
                        - id: main
                          type: model
                          prompt: "hello"
                """))
            reg = AgentRegistry.from_directory(d)
            assert reg.get("disc_agent").model == "gpt-4"

    def test_from_directory_skips_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.yaml")
            with open(bad, "w") as f:
                f.write("not_an_agent: true\n")
            good = os.path.join(d, "good.yaml")
            with open(good, "w") as f:
                f.write(textwrap.dedent("""\
                    schema_version: v1

                    agent:
                      id: ok
                      version: v1
                      model: m
                      pipeline:
                        - id: main
                          type: model
                          prompt: "x"
                """))
            reg = AgentRegistry.from_directory(d)
            assert "ok" in reg.list_agents()

    def test_from_directory_missing(self):
        reg = AgentRegistry.from_directory("/nonexistent/path")
        assert reg.list_agents() == {}


# ── Strategy Parsing Helpers ─────────────────────────────────────────────


class TestStrategyParsing:
    def test_parse_tool_calls(self):
        text = (
            "I need to check the file.\n"
            '```tool_call\n{"tool": "tools.file", "input": {"path": "a.py"}}\n```\n'
            "Done."
        )
        calls = _parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "tools.file"
        assert calls[0]["input"]["path"] == "a.py"

    def test_parse_multiple_tool_calls(self):
        text = (
            '```tool_call\n{"tool": "tools.file", "input": {}}\n```\n'
            '```tool_call\n{"tool": "tools.echo", "input": {"message": "hi"}}\n```'
        )
        calls = _parse_tool_calls(text)
        assert len(calls) == 2

    def test_parse_tool_calls_empty(self):
        assert _parse_tool_calls("no tools here") == []

    def test_parse_tool_calls_bad_json(self):
        text = "```tool_call\nnot json\n```"
        assert _parse_tool_calls(text) == []

    def test_parse_final_answer(self):
        text = (
            "Thinking...\n"
            '```final_answer\n{"summary": "all good", "score": 9}\n```'
        )
        result = _parse_final_answer(text)
        assert result == {"summary": "all good", "score": 9}

    def test_parse_final_answer_none(self):
        assert _parse_final_answer("just text") is None

    def test_parse_final_answer_bad_json(self):
        text = "```final_answer\nnot json\n```"
        assert _parse_final_answer(text) is None


# ── Strategy Resolution ──────────────────────────────────────────────────


class TestResolveStrategy:
    def test_resolve_single(self):
        s = resolve_strategy(StrategyConfig(type="single"))
        assert isinstance(s, SingleCallStrategy)

    def test_resolve_react(self):
        s = resolve_strategy(StrategyConfig(type="react"))
        assert isinstance(s, ReActStrategy)

    def test_resolve_unknown_raises(self):
        # Can't even construct with invalid type, so test resolve directly
        with pytest.raises(ValueError, match="Unknown strategy"):
            cfg = StrategyConfig.__new__(StrategyConfig)
            cfg.type = "bogus"
            cfg.max_iterations = 10
            cfg.stop_conditions = []
            cfg.custom_handler = None
            resolve_strategy(cfg)


# ── Strategies (with mock LLM) ──────────────────────────────────────────


def _ctx():
    return fake_agent_context()


class TestSingleCallStrategy:
    def test_no_tools(self):
        client = FakeLLMClient(["The answer is 42"])
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            pipeline=_simple_pipeline("What is the answer?"),
        )
        result = _run(
            SingleCallStrategy().run(agent, client, FakeToolRegistry(), {}, _ctx())
        )
        assert result.outputs == {"text": "The answer is 42"}
        assert result.iterations == 1
        assert len(result.trace) == 1

    def test_with_final_answer(self):
        client = FakeLLMClient([
            '```final_answer\n{"status": "done"}\n```'
        ])
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            pipeline=_simple_pipeline("Do the thing"),
        )
        result = _run(
            SingleCallStrategy().run(agent, client, FakeToolRegistry(), {}, _ctx())
        )
        assert result.outputs == {"status": "done"}

    def test_with_tool_call(self):
        # With pipeline, the model step's response contains a tool_call.
        # The pipeline executes it inline (no second LLM call — that's up to
        # the pipeline definition, not the strategy).
        client = FakeLLMClient([
            '```tool_call\n{"tool": "tools.echo", "input": {"message": "hi"}}\n```',
        ])
        echo = FakeTool("tools.echo", output={"echoed": "hi"})
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m", tools=["tools.echo"],
            pipeline=_simple_pipeline("Echo something"),
        )
        result = _run(
            SingleCallStrategy().run(
                agent, client, FakeToolRegistry([echo]), {}, _ctx()
            )
        )
        # one pipeline run, tool was executed inline in the model step
        assert result.iterations == 1
        assert len(result.trace[0].tool_calls) == 1


class TestReActStrategy:
    def test_immediate_final_answer(self):
        client = FakeLLMClient([
            '```final_answer\n{"result": "fast"}\n```'
        ])
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            strategy=StrategyConfig(type="react", max_iterations=3),
            pipeline=_simple_pipeline("Do it"),
        )
        result = _run(
            ReActStrategy().run(agent, client, FakeToolRegistry(), {}, _ctx())
        )
        assert result.outputs == {"result": "fast"}
        assert result.iterations == 1

    def test_tool_then_final(self):
        client = FakeLLMClient([
            '```tool_call\n{"tool": "tools.echo", "input": {}}\n```',
            '```final_answer\n{"done": true}\n```',
        ])
        echo = FakeTool("tools.echo")
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.echo"],
            strategy=StrategyConfig(type="react", max_iterations=5),
            pipeline=_simple_pipeline("Do it"),
        )
        result = _run(
            ReActStrategy().run(
                agent, client, FakeToolRegistry([echo]), {}, _ctx()
            )
        )
        assert result.outputs == {"done": True}
        assert result.iterations == 2

    def test_max_iterations(self):
        # Returns text without final_answer, pipeline runs each iteration
        client = FakeLLMClient([
            "Thinking...",
            "Still thinking...",
            "Almost there...",
        ])
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            strategy=StrategyConfig(type="react", max_iterations=3),
            pipeline=_simple_pipeline("Think about it"),
        )
        result = _run(
            ReActStrategy().run(
                agent, client, FakeToolRegistry(), {}, _ctx()
            )
        )
        assert result.iterations == 3

    def test_plain_text_response(self):
        client = FakeLLMClient(["Just a plain answer"])
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            strategy=StrategyConfig(type="react"),
            pipeline=_simple_pipeline("Answer me"),
        )
        result = _run(
            ReActStrategy().run(agent, client, FakeToolRegistry(), {}, _ctx())
        )
        # plain text — no final_answer, so react keeps looping until max_iterations
        assert result.iterations == 10  # default max_iterations


# ── Agent Executor ───────────────────────────────────────────────────────


class TestAgentExecutor:
    def test_execute_basic(self):
        client = FakeLLMClient(["Hello world"])
        executor = AgentExecutor(
            llm_client=client,
            tool_registry=FakeToolRegistry(),
        )
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            pipeline=_simple_pipeline("Say hello"),
        )
        result = _run(executor.execute(agent, {"input": "test"}, _ctx()))
        assert result.outputs == {"text": "Hello world"}

    def test_execute_resolves_prompt_reference(self):
        client = FakeLLMClient(["Done"])
        prompt_reg = PromptRegistry()
        prompt_reg.register(
            PromptEntry(prompt_id="sys", version="v1", text="Resolved system prompt")
        )
        executor = AgentExecutor(
            llm_client=client,
            tool_registry=FakeToolRegistry(),
        )
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m", system="prompts.sys",
            prompt_registry=prompt_reg,
            pipeline=_simple_pipeline("Do something"),
        )
        result = _run(executor.execute(agent, {}, _ctx()))
        # verify the resolved prompt was passed to LLM
        assert client.calls[0]["system"] == "Resolved system prompt"

    def test_execute_resolves_pinned_prompt(self):
        client = FakeLLMClient(["Done"])
        prompt_reg = PromptRegistry()
        prompt_reg.register(
            PromptEntry(prompt_id="sys", version="v1", text="Old")
        )
        prompt_reg.register(
            PromptEntry(prompt_id="sys", version="v2", text="New")
        )
        executor = AgentExecutor(
            llm_client=client,
            tool_registry=FakeToolRegistry(),
        )
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m", system="prompts.sys@v1",
            prompt_registry=prompt_reg,
            pipeline=_simple_pipeline("Do something"),
        )
        result = _run(executor.execute(agent, {}, _ctx()))
        assert client.calls[0]["system"] == "Old"

    def test_execute_inline_prompt_untouched(self):
        client = FakeLLMClient(["Done"])
        executor = AgentExecutor(
            llm_client=client,
            tool_registry=FakeToolRegistry(),
        )
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            system="Inline system prompt",
            pipeline=_simple_pipeline("Do something"),
        )
        result = _run(executor.execute(agent, {}, _ctx()))
        assert client.calls[0]["system"] == "Inline system prompt"

    def test_execute_with_react_strategy(self):
        client = FakeLLMClient([
            '```tool_call\n{"tool": "tools.echo", "input": {}}\n```',
            '```final_answer\n{"status": "ok"}\n```',
        ])
        echo = FakeTool("tools.echo")
        executor = AgentExecutor(
            llm_client=client,
            tool_registry=FakeToolRegistry([echo]),
        )
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.echo"],
            strategy=StrategyConfig(type="react", max_iterations=5),
            pipeline=_simple_pipeline("Use echo tool"),
        )
        result = _run(executor.execute(agent, {"task": "test"}, _ctx()))
        assert result.outputs == {"status": "ok"}
        assert result.iterations == 2
        assert len(result.trace) == 2
        assert result.trace[0].tool_calls[0].tool_name == "tools.echo"


# ── Auto Tool Prompt Injection ───────────────────────────────────────────


def _tool_with_schema(name, description, properties, required=None):
    """Create a FakeTool with a real input_schema."""
    t = FakeTool(name)
    t.description = description
    t.input_schema = {
        "type": "object",
        "properties": properties,
        **({"required": required} if required else {}),
    }
    return t


class TestBuildToolPreamble:
    def test_basic_preamble(self):
        echo = _tool_with_schema(
            "tools.echo", "Echo a message back",
            {"message": {"type": "string", "description": "Text to echo"}},
            required=["message"],
        )
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.echo"],
            strategy=StrategyConfig(type="react"),
            pipeline=_simple_pipeline(),
        )
        preamble = _build_tool_preamble(agent, FakeToolRegistry([echo]))
        assert "## Tool Calling" in preamble
        assert "## Returning Your Final Answer" in preamble
        assert "## Available Tools" in preamble
        assert "### tools.echo" in preamble
        assert "Echo a message back" in preamble
        assert "message (string, required)" in preamble
        assert "```tool_call" in preamble
        assert "```final_answer" in preamble

    def test_multiple_tools(self):
        t1 = _tool_with_schema("tools.a", "Tool A", {"x": {"type": "integer"}})
        t2 = _tool_with_schema("tools.b", "Tool B", {"y": {"type": "string"}}, required=["y"])
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.a", "tools.b"],
            strategy=StrategyConfig(type="react"),
            pipeline=_simple_pipeline(),
        )
        preamble = _build_tool_preamble(agent, FakeToolRegistry([t1, t2]))
        assert "### tools.a" in preamble
        assert "### tools.b" in preamble
        assert "Tool A" in preamble
        assert "Tool B" in preamble
        assert "y (string, required)" in preamble

    def test_unknown_tool_graceful(self):
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.missing"],
            strategy=StrategyConfig(type="react"),
            pipeline=_simple_pipeline(),
        )
        preamble = _build_tool_preamble(agent, FakeToolRegistry())
        assert "### tools.missing" in preamble
        assert "not found" in preamble

    def test_tool_without_properties(self):
        t = FakeTool("tools.noop")
        t.description = "Does nothing"
        t.input_schema = {"type": "object"}
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.noop"],
            strategy=StrategyConfig(type="react"),
            pipeline=_simple_pipeline(),
        )
        preamble = _build_tool_preamble(agent, FakeToolRegistry([t]))
        assert "### tools.noop" in preamble
        assert "Parameters:" not in preamble


class TestResolvePipelineSystemInjection:
    def test_react_with_tools_injects_preamble(self):
        echo = _tool_with_schema("tools.echo", "Echo", {"msg": {"type": "string"}})
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.echo"], system="Be helpful.",
            strategy=StrategyConfig(type="react"),
            pipeline=_simple_pipeline(),
        )
        step = agent.pipeline[0]
        result = _resolve_pipeline_system(agent, step, FakeToolRegistry([echo]))
        assert result.startswith("## Tool Calling")
        assert "Be helpful." in result
        assert "### tools.echo" in result

    def test_react_no_tools_no_preamble(self):
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            system="Be helpful.",
            strategy=StrategyConfig(type="react"),
            pipeline=_simple_pipeline(),
        )
        step = agent.pipeline[0]
        result = _resolve_pipeline_system(agent, step, FakeToolRegistry())
        assert result == "Be helpful."

    def test_single_strategy_no_preamble(self):
        echo = _tool_with_schema("tools.echo", "Echo", {"msg": {"type": "string"}})
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.echo"], system="Be helpful.",
            strategy=StrategyConfig(type="single"),
            pipeline=_simple_pipeline(),
        )
        step = agent.pipeline[0]
        result = _resolve_pipeline_system(agent, step, FakeToolRegistry([echo]))
        assert result == "Be helpful."

    def test_auto_tool_prompt_false_skips(self):
        echo = _tool_with_schema("tools.echo", "Echo", {"msg": {"type": "string"}})
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.echo"], system="Manual instructions.",
            strategy=StrategyConfig(type="react"),
            auto_tool_prompt=False,
            pipeline=_simple_pipeline(),
        )
        step = agent.pipeline[0]
        result = _resolve_pipeline_system(agent, step, FakeToolRegistry([echo]))
        assert result == "Manual instructions."

    def test_no_registry_no_preamble(self):
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.echo"], system="Be helpful.",
            strategy=StrategyConfig(type="react"),
            pipeline=_simple_pipeline(),
        )
        step = agent.pipeline[0]
        result = _resolve_pipeline_system(agent, step)
        assert result == "Be helpful."

    def test_no_system_prompt_preamble_only(self):
        echo = _tool_with_schema("tools.echo", "Echo", {"msg": {"type": "string"}})
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.echo"],
            strategy=StrategyConfig(type="react"),
            pipeline=_simple_pipeline(),
        )
        step = agent.pipeline[0]
        result = _resolve_pipeline_system(agent, step, FakeToolRegistry([echo]))
        assert result.startswith("## Tool Calling")
        assert "### tools.echo" in result


class TestReActAutoInjectionE2E:
    def test_native_tools_sent_to_llm_preamble_skipped(self):
        """End-to-end: react agent with tools passes tools arg, skips system prompt preamble."""
        echo = _tool_with_schema(
            "tools.echo", "Echo back",
            {"message": {"type": "string", "description": "What to echo"}},
            required=["message"],
        )
        client = FakeLLMClient([
            '```final_answer\n{"result": "done"}\n```',
        ])
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.echo"],
            system="You are a test agent.",
            strategy=StrategyConfig(type="react", max_iterations=3),
            auto_tool_prompt=True,
            pipeline=_simple_pipeline("Do it"),
        )
        result = _run(
            ReActStrategy().run(
                agent, client, FakeToolRegistry([echo]), {}, _ctx()
            )
        )
        call_kwargs = client.calls[0]
        # Text preamble is skipped
        assert "## Tool Calling" not in call_kwargs["system"]
        assert call_kwargs["system"] == "You are a test agent."
        
        # Tools are passed natively
        assert "tools" in call_kwargs
        assert len(call_kwargs["tools"]) == 1
        assert call_kwargs["tools"][0]["name"] == "tools.echo"

    def test_single_strategy_no_injection_e2e(self):
        """End-to-end: single strategy agent does NOT get tool preamble."""
        echo = _tool_with_schema("tools.echo", "Echo back", {})
        client = FakeLLMClient(["Hello"])
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.echo"],
            system="Just a system prompt.",
            strategy=StrategyConfig(type="single"),
            pipeline=_simple_pipeline("Say hi"),
        )
        _run(
            SingleCallStrategy().run(
                agent, client, FakeToolRegistry([echo]), {}, _ctx()
            )
        )
        assert client.calls[0]["system"] == "Just a system prompt."
