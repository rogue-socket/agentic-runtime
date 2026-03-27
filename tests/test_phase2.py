"""Tests for Phase 2: pipeline, function resolver, workflow step types.

Covers:
- PipelineStep validation and parsing
- Multi-step pipeline execution (single + react)
- Pipeline model inheritance (system, model)
- Pipeline state referencing (named ids, dot-paths)
- Function resolver (qualified, unqualified, subdirectories, errors)
- Workflow parser: type:agent, type:function steps
- Executor dispatch: agent and function steps
"""

import asyncio
import os
import tempfile
import textwrap

import pytest

from agent_runtime.agent.definition import (
    AgentDefinition,
    PipelineStep,
    StrategyConfig,
    load_agent_definition,
)
from agent_runtime.agent.strategies import (
    AgentResult,
    SingleCallStrategy,
    ReActStrategy,
    _render_pipeline_prompt,
    _resolve_pipeline_tool_inputs,
)
from agent_runtime.agent.executor import AgentExecutor
from agent_runtime.agent.prompts import PromptEntry, PromptRegistry
from agent_runtime.errors import AgentValidationError
from agent_runtime.function_resolver import resolve_function
from agent_runtime.tools.base import ToolResult
from agent_runtime.workflow import load_workflow_from_text, _validate_step
from agent_runtime.errors import WorkflowValidationError
from conftest import FakeLLMClient, FakeTool, FakeToolRegistry, fake_agent_context


def _run(coro):
    return asyncio.run(coro)


# ── Fake helpers ─────────────────────────────────────────────────────────


def _ctx():
    return fake_agent_context()


# ── PipelineStep Validation ─────────────────────────────────────────────


class TestPipelineStep:
    def test_valid_model_step(self):
        s = PipelineStep(id="a", type="model", prompt="Hello")
        assert s.type == "model"
        assert s.prompt == "Hello"

    def test_valid_tool_step(self):
        s = PipelineStep(id="a", type="tool", tool="tools.echo")
        assert s.type == "tool"
        assert s.tool == "tools.echo"

    def test_invalid_type_raises(self):
        with pytest.raises(AgentValidationError, match="Invalid pipeline step type"):
            PipelineStep(id="a", type="agent")

    def test_model_without_prompt_raises(self):
        with pytest.raises(AgentValidationError, match="requires a 'prompt'"):
            PipelineStep(id="a", type="model", prompt="")

    def test_tool_without_tool_raises(self):
        with pytest.raises(AgentValidationError, match="requires a 'tool'"):
            PipelineStep(id="a", type="tool")

    def test_model_inherits_defaults(self):
        s = PipelineStep(id="a", type="model", prompt="Hello")
        assert s.model is None  # will inherit from agent
        assert s.system is None  # will inherit from agent

    def test_model_override(self):
        s = PipelineStep(
            id="a", type="model", prompt="Hello",
            model="openai/gpt-4", system="Override system"
        )
        assert s.model == "openai/gpt-4"
        assert s.system == "Override system"


# ── Pipeline Parsing from YAML ──────────────────────────────────────────


class TestPipelineParsing:
    def test_multi_step_pipeline(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(textwrap.dedent("""\
                agent:
                  id: multi
                  version: v1
                  model: gpt-4
                  tools:
                    - tools.file
                  pipeline:
                    - id: analyze
                      type: model
                      prompt: "Analyze {{ inputs.code }}"
                    - id: fetch
                      type: tool
                      tool: tools.file
                      inputs:
                        path: analyze.file
                    - id: review
                      type: model
                      prompt: "Review {{ analyze.text }}"
                      model: openai/gpt-4o
            """))
            f.flush()
            path = f.name
        try:
            defn = load_agent_definition(path)
            assert len(defn.pipeline) == 3
            assert defn.pipeline[0].type == "model"
            assert defn.pipeline[0].model is None  # inherits agent model
            assert defn.pipeline[1].type == "tool"
            assert defn.pipeline[1].tool == "tools.file"
            assert defn.pipeline[1].inputs == {"path": "analyze.file"}
            assert defn.pipeline[2].model == "openai/gpt-4o"  # overrides
        finally:
            os.unlink(path)

    def test_duplicate_pipeline_ids_raises(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(textwrap.dedent("""\
                agent:
                  id: dup
                  version: v1
                  model: m
                  pipeline:
                    - id: same
                      type: model
                      prompt: "a"
                    - id: same
                      type: model
                      prompt: "b"
            """))
            f.flush()
            path = f.name
        try:
            with pytest.raises(AgentValidationError, match="duplicate"):
                load_agent_definition(path)
        finally:
            os.unlink(path)

    def test_tool_not_in_allowlist_raises(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(textwrap.dedent("""\
                agent:
                  id: bad
                  version: v1
                  model: m
                  tools:
                    - tools.echo
                  pipeline:
                    - id: fetch
                      type: tool
                      tool: tools.file
            """))
            f.flush()
            path = f.name
        try:
            with pytest.raises(AgentValidationError, match="not in the agent's tools"):
                load_agent_definition(path)
        finally:
            os.unlink(path)


# ── Pipeline Prompt Rendering ────────────────────────────────────────────


class TestPipelinePromptRendering:
    def test_render_inputs(self):
        state = {"inputs": {"code": "x = 1"}}
        result = _render_pipeline_prompt("Review: {{ inputs.code }}", state)
        assert result == "Review: x = 1"

    def test_render_step_ref(self):
        state = {"inputs": {}, "analyze": {"text": "found bug"}}
        result = _render_pipeline_prompt("Issues: {{ analyze.text }}", state)
        assert result == "Issues: found bug"

    def test_render_missing_raises(self):
        with pytest.raises(KeyError, match="not found"):
            _render_pipeline_prompt("{{ missing.key }}", {"inputs": {}})


# ── Pipeline Tool Input Resolution ──────────────────────────────────────


class TestPipelineToolInputs:
    def test_resolve_dot_path(self):
        state = {"analyze": {"file": "/tmp/a.py"}}
        result = _resolve_pipeline_tool_inputs(
            {"path": "analyze.file"}, state
        )
        assert result == {"path": "/tmp/a.py"}

    def test_literal_passthrough(self):
        result = _resolve_pipeline_tool_inputs(
            {"count": 5, "flag": True}, {}
        )
        assert result == {"count": 5, "flag": True}

    def test_none_inputs(self):
        assert _resolve_pipeline_tool_inputs(None, {}) == {}

    def test_unresolvable_dot_path_literal(self):
        result = _resolve_pipeline_tool_inputs(
            {"path": "missing.key"}, {"inputs": {}}
        )
        assert result == {"path": "missing.key"}


# ── Multi-step Pipeline Execution ────────────────────────────────────────


class TestMultiStepPipeline:
    def test_single_strategy_multi_step(self):
        """Pipeline: model → tool → model, single strategy."""
        client = FakeLLMClient([
            "Analysis: found issue in /tmp/a.py",  # analyze step
            '```final_answer\n{"review": "approved"}\n```',  # review step
        ])
        file_tool = FakeTool("tools.file", output={"content": "def foo(): pass"})
        agent = AgentDefinition(
            agent_id="reviewer", version="v1", model="m",
            system="You are a reviewer",
            tools=["tools.file"],
            pipeline=[
                PipelineStep(id="analyze", type="model",
                             prompt="Analyze: {{ inputs.code }}"),
                PipelineStep(id="fetch", type="tool", tool="tools.file",
                             inputs={"path": "analyze.text"}),
                PipelineStep(id="review", type="model",
                             prompt="Review with {{ fetch.content }}"),
            ],
        )
        result = _run(
            SingleCallStrategy().run(
                agent, client, FakeToolRegistry([file_tool]), {"code": "x=1"}, _ctx()
            )
        )
        assert result.outputs == {"review": "approved"}
        assert result.iterations == 1
        # 3 turns: model, tool, model
        assert len(result.trace) == 3
        assert result.trace[0].llm_response is not None  # model step
        assert len(result.trace[1].tool_calls) == 1  # tool step
        assert result.trace[2].llm_response is not None  # model step

    def test_model_step_inherits_agent_system(self):
        """Pipeline model step uses agent-level system when not overridden."""
        client = FakeLLMClient(["ok"])
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            system="Global system",
            pipeline=[PipelineStep(id="main", type="model", prompt="hello")],
        )
        _run(SingleCallStrategy().run(
            agent, client, FakeToolRegistry(), {}, _ctx()
        ))
        assert client.calls[0]["system"] == "Global system"

    def test_model_step_overrides_system(self):
        """Pipeline model step can override agent-level system."""
        client = FakeLLMClient(["ok"])
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            system="Global system",
            pipeline=[PipelineStep(
                id="main", type="model", prompt="hello",
                system="Step system",
            )],
        )
        _run(SingleCallStrategy().run(
            agent, client, FakeToolRegistry(), {}, _ctx()
        ))
        assert client.calls[0]["system"] == "Step system"

    def test_model_step_overrides_model(self):
        """Pipeline model step can override agent-level model."""
        client = FakeLLMClient(["ok"])
        agent = AgentDefinition(
            agent_id="a", version="v1", model="default-model",
            pipeline=[PipelineStep(
                id="main", type="model", prompt="hello",
                model="override-model",
            )],
        )
        _run(SingleCallStrategy().run(
            agent, client, FakeToolRegistry(), {}, _ctx()
        ))
        assert client.calls[0]["model"] == "override-model"

    def test_react_multi_step_pipeline(self):
        """React strategy: pipeline runs per iteration, last model decides loop/stop."""
        client = FakeLLMClient([
            "Need more info",  # iter 1: analyze
            "Checking...",     # iter 1: review (no final_answer → loop)
            "Found it",        # iter 2: analyze
            '```final_answer\n{"status": "done"}\n```',  # iter 2: review → stop
        ])
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            strategy=StrategyConfig(type="react", max_iterations=5),
            pipeline=[
                PipelineStep(id="analyze", type="model", prompt="Analyze: {{ inputs.task }}"),
                PipelineStep(id="review", type="model", prompt="Review: {{ analyze.text }}"),
            ],
        )
        result = _run(
            ReActStrategy().run(agent, client, FakeToolRegistry(), {"task": "test"}, _ctx())
        )
        assert result.outputs == {"status": "done"}
        assert result.iterations == 2
        # 2 model steps per iteration × 2 iterations = 4 turns
        assert len(result.trace) == 4

    def test_pipeline_tool_failure_raises(self):
        """Tool step failure in pipeline should raise and fail the agent."""

        class FailingTool:
            name = "tools.fail"
            description = "Always fails"
            input_schema = {}
            timeout = None
            retries = None

            async def execute(self, input, context):
                return ToolResult(success=False, output=None, error="boom", metadata=None)

        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            tools=["tools.fail"],
            pipeline=[
                PipelineStep(id="call", type="tool", tool="tools.fail"),
            ],
        )
        with pytest.raises(RuntimeError, match="Pipeline tool step 'call' failed"):
            _run(SingleCallStrategy().run(
                agent, FakeLLMClient([]),
                FakeToolRegistry([FailingTool()]), {}, _ctx()
            ))


# ── Pipeline Prompt Resolution via Agent Executor ────────────────────────


class TestPipelinePromptResolution:
    def test_resolve_pipeline_prompt_reference(self):
        """Pipeline model step prompt can be a prompt-registry reference."""
        client = FakeLLMClient(["ok"])
        prompt_reg = PromptRegistry()
        prompt_reg.register(
            PromptEntry(prompt_id="review_prompt", version="v1",
                        text="Review: {{ inputs.code }}")
        )
        agent = AgentDefinition(
            agent_id="a", version="v1", model="m",
            prompt_registry=prompt_reg,
            pipeline=[PipelineStep(
                id="main", type="model",
                prompt="prompts.review_prompt",
            )],
        )
        executor = AgentExecutor(llm_client=client, tool_registry=FakeToolRegistry())
        result = _run(executor.execute(agent, {"code": "x=1"}, _ctx()))
        # the prompt should have been resolved to the actual text
        assert "Review:" in client.calls[0]["prompt"]


# ── Function Resolver ────────────────────────────────────────────────────


class TestFunctionResolver:
    def test_qualified_reference(self):
        with tempfile.TemporaryDirectory() as d:
            mod_path = os.path.join(d, "formatters.py")
            with open(mod_path, "w") as f:
                f.write("def format_markdown(inputs):\n    return {'report': inputs['text']}\n")
            fn = resolve_function("formatters.format_markdown", d)
            assert callable(fn)
            assert fn({"text": "hello"}) == {"report": "hello"}

    def test_unqualified_reference(self):
        with tempfile.TemporaryDirectory() as d:
            mod_path = os.path.join(d, "utils.py")
            with open(mod_path, "w") as f:
                f.write("def helper(inputs):\n    return {'out': True}\n")
            fn = resolve_function("helper", d)
            assert fn({}) == {"out": True}

    def test_unqualified_ambiguous_raises(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ["a.py", "b.py"]:
                with open(os.path.join(d, name), "w") as f:
                    f.write("def shared(inputs):\n    return {}\n")
            with pytest.raises(ValueError, match="multiple files"):
                resolve_function("shared", d)

    def test_qualified_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with pytest.raises(ValueError, match="not found"):
                resolve_function("nonexistent.func", d)

    def test_qualified_missing_function_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "mod.py"), "w") as f:
                f.write("def other(inputs): return {}\n")
            with pytest.raises(ValueError, match="not found"):
                resolve_function("mod.missing_func", d)

    def test_unqualified_not_found_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "mod.py"), "w") as f:
                f.write("def other(inputs): return {}\n")
            with pytest.raises(ValueError, match="not found"):
                resolve_function("nonexistent", d)

    def test_subdirectory_qualified(self):
        with tempfile.TemporaryDirectory() as d:
            subdir = os.path.join(d, "reporting")
            os.makedirs(subdir)
            mod_path = os.path.join(subdir, "formatters.py")
            with open(mod_path, "w") as f:
                f.write("def make_report(inputs):\n    return {'report': 'done'}\n")
            fn = resolve_function("reporting.formatters.make_report", d)
            assert fn({}) == {"report": "done"}

    def test_missing_directory_raises(self):
        with pytest.raises(ValueError, match="not found"):
            resolve_function("func", "/nonexistent/dir")

    def test_skips_private_files(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "_private.py"), "w") as f:
                f.write("def secret(inputs): return {}\n")
            with pytest.raises(ValueError, match="not found"):
                resolve_function("secret", d)


# ── Workflow Step Validation ─────────────────────────────────────────────


class TestWorkflowStepValidation:
    def test_agent_step_valid(self):
        _validate_step({"id": "s1", "type": "agent", "agent": "reviewer"})

    def test_agent_step_missing_agent(self):
        with pytest.raises(WorkflowValidationError, match="agent"):
            _validate_step({"id": "s1", "type": "agent"})

    def test_agent_step_non_string_agent(self):
        with pytest.raises(WorkflowValidationError, match="string"):
            _validate_step({"id": "s1", "type": "agent", "agent": 123})

    def test_function_step_valid(self):
        _validate_step({"id": "s1", "type": "function", "function": "format_markdown"})

    def test_function_step_missing_function(self):
        with pytest.raises(WorkflowValidationError, match="function"):
            _validate_step({"id": "s1", "type": "function"})

    def test_function_step_non_string(self):
        with pytest.raises(WorkflowValidationError, match="string"):
            _validate_step({"id": "s1", "type": "function", "function": 123})

    def test_tool_step_valid(self):
        _validate_step({"id": "s1", "type": "tool", "tool": "tools.echo"})

    def test_invalid_type(self):
        with pytest.raises(WorkflowValidationError):
            _validate_step({"id": "s1", "type": "invalid"})


# ── Workflow Parsing: type:agent and type:function ───────────────────────


class TestWorkflowParsing:
    def test_parse_agent_step(self):
        yaml_text = (
            "workflow:\n"
            "  id: test_wf\n"
            "  version: v1\n"
            "steps:\n"
            "  - id: review\n"
            "    type: agent\n"
            "    agent: code_reviewer\n"
            "    inputs:\n"
            "      diff: inputs.pr_diff\n"
            "    outputs: [summary, issues]\n"
        )
        wf = load_workflow_from_text(yaml_text)
        step = wf["steps"][0]
        assert step.step_type == "agent"
        assert step.agent_id == "code_reviewer"
        assert step.agent_version is None

    def test_parse_agent_step_with_version(self):
        yaml_text = (
            "workflow:\n"
            "  id: test_wf\n"
            "  version: v1\n"
            "steps:\n"
            "  - id: review\n"
            "    type: agent\n"
            "    agent: code_reviewer@v2\n"
        )
        wf = load_workflow_from_text(yaml_text)
        step = wf["steps"][0]
        assert step.agent_id == "code_reviewer"
        assert step.agent_version == "v2"

    def test_parse_function_step_without_dir(self):
        """Function step parses but callable is None without functions_dir."""
        yaml_text = (
            "workflow:\n"
            "  id: test_wf\n"
            "  version: v1\n"
            "steps:\n"
            "  - id: format\n"
            "    type: function\n"
            "    function: format_markdown\n"
            "    inputs:\n"
            "      text: inputs.raw\n"
            "    outputs: [report]\n"
        )
        wf = load_workflow_from_text(yaml_text)
        step = wf["steps"][0]
        assert step.step_type == "function"
        assert step.function_ref == "format_markdown"
        assert step.function_callable is None  # no functions_dir provided

    def test_parse_function_step_with_dir(self):
        """Function step resolved at parse time when functions_dir given."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "formatters.py"), "w") as f:
                f.write("def format_markdown(inputs):\n    return {'report': inputs['text']}\n")
            yaml_text = (
                "workflow:\n"
                "  id: test_wf\n"
                "  version: v1\n"
                "steps:\n"
                "  - id: format\n"
                "    type: function\n"
                "    function: formatters.format_markdown\n"
            )
            wf = load_workflow_from_text(yaml_text, functions_dir=d)
            step = wf["steps"][0]
            assert step.function_callable is not None
            assert step.function_callable({"text": "hi"}) == {"report": "hi"}

    def test_mixed_step_types(self):
        """Workflow can contain agent, function, and tool steps together."""
        yaml_text = (
            "workflow:\n"
            "  id: test_wf\n"
            "  version: v1\n"
            "steps:\n"
            "  - id: review\n"
            "    type: agent\n"
            "    agent: reviewer\n"
            "  - id: echo\n"
            "    type: tool\n"
            "    tool: tools.echo\n"
            "    inputs:\n"
            "      message: steps.review.summary\n"
        )
        wf = load_workflow_from_text(yaml_text)
        assert wf["steps"][0].step_type == "agent"
        assert wf["steps"][1].step_type == "tool"
