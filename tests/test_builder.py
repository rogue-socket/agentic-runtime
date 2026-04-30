"""Tests for RuntimeBuilder and Runtime."""

from __future__ import annotations

import os
import tempfile

import pytest

from agent_runtime.builder import Runtime, RuntimeBuilder, _looks_like_yaml
from agent_runtime.config import RuntimeConfig
from agent_runtime.core import StepStatus


ECHO_WORKFLOW = """\
schema_version: v1
workflow:
  id: test_echo
  version: v1
steps:
  - id: greet
    type: tool
    tool: tools.echo
    inputs:
      message: "hello"
"""

WORKFLOW_WITH_INPUTS = """\
schema_version: v1
workflow:
  id: test_inputs
  version: v1
inputs:
  name:
    description: Who to greet
    default: world
steps:
  - id: greet
    type: tool
    tool: tools.echo
    inputs:
      message: inputs.name
"""


class TestLooksLikeYaml:
    def test_multiline_is_yaml(self):
        assert _looks_like_yaml("workflow:\n  id: x") is True

    def test_starts_with_schema_version(self):
        assert _looks_like_yaml("schema_version: v1") is True

    def test_file_path_is_not_yaml(self):
        assert _looks_like_yaml("workflows/example.yaml") is False

    def test_bare_word_is_not_yaml(self):
        assert _looks_like_yaml("example") is False


class TestRuntimeBuilder:
    def test_build_returns_runtime(self):
        rt = RuntimeBuilder().with_db_path(":memory:").build()
        try:
            assert isinstance(rt, Runtime)
        finally:
            rt.close()

    def test_with_model(self):
        rt = RuntimeBuilder().with_db_path(":memory:").with_model("openai/gpt-4o").build()
        try:
            assert rt._config.default_model == "openai/gpt-4o"
        finally:
            rt.close()

    def test_with_config(self):
        cfg = RuntimeConfig(db_path=":memory:", default_model="test/model")
        rt = RuntimeBuilder().with_config(cfg).build()
        try:
            assert rt._config.default_model == "test/model"
        finally:
            rt.close()

    def test_with_config_path(self):
        with tempfile.TemporaryDirectory() as d:
            yaml_path = os.path.join(d, "runtime.yaml")
            with open(yaml_path, "w") as f:
                f.write("schema_version: v1\ndefault_model: test/from-file\n")
            rt = RuntimeBuilder().with_config_path(yaml_path).with_db_path(":memory:").build()
            try:
                assert rt._config.default_model == "test/from-file"
            finally:
                rt.close()

    def test_with_extra_tool(self):
        class FakeTool:
            name = "tools.fake"
            description = "fake"
            input_schema = {"type": "object", "properties": {}}
            async def execute(self, input, context):
                pass

        rt = RuntimeBuilder().with_db_path(":memory:").with_tool(FakeTool()).build()
        try:
            assert "tools.fake" in rt._tool_registry._tools
        finally:
            rt.close()


class TestRuntimeContextManager:
    def test_with_statement_closes(self):
        with RuntimeBuilder().with_db_path(":memory:").build() as rt:
            assert rt._closed is False
        assert rt._closed is True

    def test_close_is_idempotent(self):
        rt = RuntimeBuilder().with_db_path(":memory:").build()
        rt.close()
        rt.close()  # should not raise


class TestRuntimeRun:
    def test_run_inline_yaml(self):
        with RuntimeBuilder().with_db_path(":memory:").build() as rt:
            run = rt.run(ECHO_WORKFLOW)
            assert run.succeeded
            assert run.get_output("greet") is not None

    def test_run_with_inputs(self):
        with RuntimeBuilder().with_db_path(":memory:").build() as rt:
            run = rt.run(WORKFLOW_WITH_INPUTS, inputs={"name": "Alice"})
            assert run.succeeded
            assert run.get_input("name") == "Alice"

    def test_run_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            wf_path = os.path.join(d, "test.yaml")
            with open(wf_path, "w") as f:
                f.write(ECHO_WORKFLOW)
            with RuntimeBuilder().with_db_path(":memory:").build() as rt:
                run = rt.run(wf_path)
                assert run.succeeded

    def test_run_after_close_raises(self):
        rt = RuntimeBuilder().with_db_path(":memory:").build()
        rt.close()
        with pytest.raises(RuntimeError, match="closed"):
            rt.run(ECHO_WORKFLOW)

    @pytest.mark.asyncio
    async def test_run_async(self):
        with RuntimeBuilder().with_db_path(":memory:").build() as rt:
            run = await rt.run_async(ECHO_WORKFLOW)
            assert run.succeeded

    def test_run_collects_step_names(self):
        with RuntimeBuilder().with_db_path(":memory:").build() as rt:
            run = rt.run(ECHO_WORKFLOW)
            assert run.step_names == ["greet"]

    def test_event_callback(self):
        events = []
        with RuntimeBuilder().with_db_path(":memory:").with_on_event(lambda n, p: events.append(n)).build() as rt:
            rt.run(ECHO_WORKFLOW)
        assert "RUN_START" in events
        assert "RUN_COMPLETE" in events

    def test_per_run_event_overrides_builder(self):
        builder_events = []
        run_events = []
        with RuntimeBuilder().with_db_path(":memory:").with_on_event(lambda n, p: builder_events.append(n)).build() as rt:
            rt.run(ECHO_WORKFLOW, on_event=lambda n, p: run_events.append(n))
        assert len(builder_events) == 0
        assert "RUN_START" in run_events
