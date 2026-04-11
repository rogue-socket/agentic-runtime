"""Tests for the CLI module — helpers, dispatch, and subcommands."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from unittest.mock import patch

import pytest

from agent_runtime.cli import (
    _coerce_value,
    _build_input_state,
    _diff_state,
    _parse_env_line,
    _redact,
    _init_project,
    run_cli,
)
from conftest import make_storage


# ── _coerce_value ──────────────────────────────────────────────────


class TestCoerceValue:
    def test_bool_true(self) -> None:
        """Function implementation."""
        assert _coerce_value("true") is True
        assert _coerce_value("True") is True
        assert _coerce_value("TRUE") is True

    def test_bool_false(self) -> None:
        """Function implementation."""
        assert _coerce_value("false") is False

    def test_int(self) -> None:
        """Function implementation."""
        assert _coerce_value("42") == 42
        assert _coerce_value("-1") == -1

    def test_float(self) -> None:
        """Function implementation."""
        assert _coerce_value("3.14") == 3.14

    def test_json_object(self) -> None:
        """Function implementation."""
        result = _coerce_value('{"key": "val"}')
        assert result == {"key": "val"}

    def test_json_array(self) -> None:
        """Function implementation."""
        result = _coerce_value('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_plain_string(self) -> None:
        """Function implementation."""
        assert _coerce_value("hello world") == "hello world"

    def test_string_looks_like_json_but_invalid(self) -> None:
        """Function implementation."""
        assert _coerce_value("{broken") == "{broken"


# ── _parse_env_line ────────────────────────────────────────────────


class TestParseEnvLine:
    def test_basic(self) -> None:
        """Function implementation."""
        assert _parse_env_line("FOO=bar") == ("FOO", "bar")

    def test_quoted_double(self) -> None:
        """Function implementation."""
        assert _parse_env_line('KEY="value"') == ("KEY", "value")

    def test_quoted_single(self) -> None:
        """Function implementation."""
        assert _parse_env_line("KEY='value'") == ("KEY", "value")

    def test_export_prefix(self) -> None:
        """Function implementation."""
        assert _parse_env_line("export MY_VAR=123") == ("MY_VAR", "123")

    def test_comment_ignored(self) -> None:
        """Function implementation."""
        assert _parse_env_line("# comment") is None

    def test_empty_ignored(self) -> None:
        """Function implementation."""
        assert _parse_env_line("") is None
        assert _parse_env_line("   ") is None

    def test_no_equals(self) -> None:
        """Function implementation."""
        assert _parse_env_line("NOVALUE") is None

    def test_empty_key(self) -> None:
        """Function implementation."""
        assert _parse_env_line("=value") is None


# ── _redact ────────────────────────────────────────────────────────


class TestRedact:
    def test_redacts_api_key(self) -> None:
        """Function implementation."""
        result = _redact({"api_key": "sk-secret", "name": "safe"})
        assert result["api_key"] == "***REDACTED***"
        assert result["name"] == "safe"

    def test_redacts_nested(self) -> None:
        """Function implementation."""
        result = _redact({"outer": {"password": "x", "data": 1}})
        assert result["outer"]["password"] == "***REDACTED***"
        assert result["outer"]["data"] == 1

    def test_redacts_token(self) -> None:
        """Function implementation."""
        result = _redact({"auth_token": "abc"})
        assert result["auth_token"] == "***REDACTED***"

    def test_list_recursion(self) -> None:
        """Function implementation."""
        result = _redact([{"secret": "x"}, {"name": "y"}])
        assert result[0]["secret"] == "***REDACTED***"
        assert result[1]["name"] == "y"

    def test_plain_value_passthrough(self) -> None:
        """Function implementation."""
        assert _redact("hello") == "hello"
        assert _redact(42) == 42


# ── _build_input_state ─────────────────────────────────────────────


class TestBuildInputState:
    def test_no_declared_inputs_passthrough(self) -> None:
        """Function implementation."""
        result = _build_input_state(["a=1", "b=hello"], {})
        assert result == {"a": 1, "b": "hello"}

    def test_declared_required_provided(self) -> None:
        """Function implementation."""
        result = _build_input_state(
            ["issue=bug report"],
            {"issue": {"required": True}},
        )
        assert result == {"issue": "bug report"}

    def test_declared_default_used(self) -> None:
        """Function implementation."""
        result = _build_input_state(
            [],
            {"severity": {"required": False, "default": "low"}},
        )
        assert result == {"severity": "low"}

    def test_missing_required_raises(self) -> None:
        """Function implementation."""
        with pytest.raises(SystemExit, match="Missing required input"):
            _build_input_state([], {"issue": {"required": True}})

    def test_unknown_input_raises(self) -> None:
        """Function implementation."""
        with pytest.raises(SystemExit, match="Unknown inputs"):
            _build_input_state(
                ["extra=val"],
                {"issue": {"required": False, "default": "x"}},
            )

    def test_invalid_format_raises(self) -> None:
        """Function implementation."""
        with pytest.raises(SystemExit, match="Invalid input format"):
            _build_input_state(["no-equals"], {})

    def test_coercion_in_values(self) -> None:
        """Function implementation."""
        result = _build_input_state(["flag=true", "count=5"], {})
        assert result["flag"] is True
        assert result["count"] == 5


# ── _init_project ──────────────────────────────────────────────────


class TestInitProject:
    def test_creates_scaffold(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            _init_project(d)
            assert os.path.isdir(os.path.join(d, "workflows"))
            assert os.path.isdir(os.path.join(d, "tools"))
            assert os.path.isdir(os.path.join(d, "agents"))
            assert os.path.isdir(os.path.join(d, "functions"))
            assert os.path.isdir(os.path.join(d, "workflows", "tests"))
            assert os.path.isdir(os.path.join(d, "agents", "tests"))
            assert os.path.isdir(os.path.join(d, "functions", "tests"))
            assert os.path.isdir(os.path.join(d, "tools", "tests"))
            assert os.path.isfile(os.path.join(d, "tools", "tests", "tool_tests.yaml"))
            assert os.path.isfile(os.path.join(d, "functions", "tests", "function_tests.yaml"))
            assert os.path.isfile(os.path.join(d, "runtime.yaml"))
            assert os.path.isfile(os.path.join(d, ".env"))
            assert os.path.isfile(os.path.join(d, "runtime.db"))
            assert not os.path.exists(os.path.join(d, "workflows", "example.yaml"))
            assert not os.path.exists(os.path.join(d, "tools", "example_tool.py"))
            assert not os.path.exists(os.path.join(d, "functions", "stubs.py"))
            assert not os.path.exists(os.path.join(d, "agents", "summarizer.yaml"))
            assert not os.path.exists(os.path.join(d, "agents", "fixer.yaml"))

    def test_idempotent(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            _init_project(d)
            # Overwrite one file to confirm it's not clobbered
            marker = os.path.join(d, "runtime.yaml")
            with open(marker, "w") as f:
                f.write("custom")
            _init_project(d)
            with open(marker) as f:
                assert f.read() == "custom"

    def test_does_not_create_sample_agent_files(self) -> None:
        """Init should create skeleton only, without sample agent definitions."""
        with tempfile.TemporaryDirectory() as d:
            _init_project(d)
            assert not os.path.exists(os.path.join(d, "agents", "summarizer.yaml"))
            assert not os.path.exists(os.path.join(d, "agents", "fixer.yaml"))


# ── run_cli dispatch ───────────────────────────────────────────────


class TestRunCLIInit:
    def test_init_returns_zero(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            code = run_cli(["init", "--path", d])
            assert code == 0
            assert os.path.isdir(os.path.join(d, "workflows"))
            assert os.path.isfile(os.path.join(d, ".env"))
            assert os.path.isfile(os.path.join(d, "runtime.db"))


class TestRunCLIConfig:
    def test_config_invokes_setup_flow(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            with patch("agent_runtime.cli._run_setup_flow") as mock_setup:
                code = run_cli([
                    "config",
                    "--path",
                    d,
                    "--provider",
                    "openai",
                    "--api-key-env",
                    "OPENAI_API_KEY",
                    "--api-key",
                    "test-key",
                    "--model",
                    "gpt-4o",
                    "--no-dotenv",
                ])
            assert code == 0
            mock_setup.assert_called_once()


class TestRunCLIList:
    def test_list_no_agents_dir(self, capsys) -> None:
        """Function implementation."""
        code = run_cli(["list", "--agents-dir", "/nonexistent_dir_xyz"])
        assert code == 0
        assert "No agents directory" in capsys.readouterr().out

    def test_list_empty_agents_dir(self, capsys) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            code = run_cli(["list", "--agents-dir", d])
            assert code == 0
            assert "No agents found" in capsys.readouterr().out


class TestRunCLIDocs:
    def test_docs_builds_index_and_workflow_reference(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            docs_guide = os.path.join(d, "docs", "guide")
            workflows_dir = os.path.join(d, "workflows")
            os.makedirs(docs_guide, exist_ok=True)
            os.makedirs(workflows_dir, exist_ok=True)

            with open(os.path.join(docs_guide, "intro.md"), "w", encoding="utf-8") as f:
                f.write("# Intro\n")

            workflow_yaml = """schema_version: v1
workflow:
  id: docs_sample
  version: v1
inputs:
  issue:
    description: Issue text
    required: true
steps:
  - id: summarize
    type: function
    function: stubs.generate_summary
"""
            with open(os.path.join(workflows_dir, "sample.yaml"), "w", encoding="utf-8") as f:
                f.write(workflow_yaml)

            code = run_cli(["docs", "--path", d])
            assert code == 0

            content_js = os.path.join(d, "docs", "content.js")
            generated_md = os.path.join(d, "docs", "guide", "workflow-reference-generated.md")
            assert os.path.isfile(content_js)
            assert os.path.isfile(generated_md)

            with open(content_js, "r", encoding="utf-8") as f:
                content_text = f.read()
            assert "guide/intro.md" in content_text

            with open(generated_md, "r", encoding="utf-8") as f:
                generated_text = f.read()
            assert "docs_sample@v1" in generated_text
            assert "summarize" in generated_text

    def test_docs_builds_site_index_when_present(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            docs_site = os.path.join(d, "docs", "site")
            os.makedirs(docs_site, exist_ok=True)

            with open(os.path.join(docs_site, "readme.md"), "w", encoding="utf-8") as f:
                f.write("# Site\n")

            code = run_cli(["docs", "--path", d, "--no-workflow-reference"])
            assert code == 0
            assert os.path.isfile(os.path.join(d, "docs", "site", "content.js"))


class TestRunCLIMetrics:
    def test_metrics_json_output(self, capsys) -> None:
        """Function implementation."""
        storage = make_storage()
        try:
            code = run_cli(["metrics", "--db-path", storage.db_path, "--json"])
            assert code == 0
            out = capsys.readouterr().out
            payload = json.loads(out)
            assert "runs" in payload
            assert "steps" in payload
            assert "errors" in payload
        finally:
            storage.close()


class TestDiffState:
    def test_diff_state_default_truncates(self) -> None:
        """Function implementation."""
        before = {}
        after = {f"k{i}": i for i in range(25)}
        diff = _diff_state(before, after)
        assert len(diff["added"]) == 21
        assert diff["added"][-1] == "... (+5 more)"

    def test_diff_state_full_shows_all(self) -> None:
        """Function implementation."""
        before = {}
        after = {f"k{i}": i for i in range(25)}
        diff = _diff_state(before, after, full=True)
        assert len(diff["added"]) == 25
        assert not any(item.startswith("...") for item in diff["added"])

    def test_diff_state_respects_custom_limit(self) -> None:
        """Function implementation."""
        before = {}
        after = {f"k{i}": i for i in range(10)}
        diff = _diff_state(before, after, diff_limit=3)
        assert len(diff["added"]) == 4
        assert diff["added"][-1] == "... (+7 more)"

    def test_diff_state_zero_limit_hides_paths(self) -> None:
        """Function implementation."""
        before = {}
        after = {f"k{i}": i for i in range(4)}
        diff = _diff_state(before, after, diff_limit=0)
        assert diff["added"] == ["... (+4 more)"]


class TestRunCLIDiffArgs:
    def test_state_diff_accepts_new_flags(self) -> None:
        """Function implementation."""
        storage = make_storage()
        try:
            code = run_cli(["state-diff", "missing", "--db-path", storage.db_path, "--diff-limit", "5", "--full"])
            assert code == 1
        finally:
            storage.close()

    def test_state_diff_negative_limit_exits(self) -> None:
        """Function implementation."""
        storage = make_storage()
        try:
            with pytest.raises(SystemExit, match="--diff-limit must be >= 0"):
                run_cli(["state-diff", "missing", "--db-path", storage.db_path, "--diff-limit", "-1"])
        finally:
            storage.close()

    def test_inspect_accepts_diff_flags(self) -> None:
        """Function implementation."""
        storage = make_storage()
        try:
            code = run_cli(["inspect", "missing", "--db-path", storage.db_path, "--state-history", "--diff-limit", "5", "--full"])
            assert code == 1
        finally:
            storage.close()


class TestRunCLIQuickstart:
    def test_quickstart_starter_without_keys_auto_falls_back(self, capsys) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            with patch("agent_runtime.cli._run_setup_flow") as mock_setup:
                code = run_cli(["quickstart", "--path", d])

            assert code == 0
            mock_setup.assert_called_once()
            db_path = os.path.join(d, "runtime.db")
            assert os.path.isfile(db_path)

            out = capsys.readouterr().out
            assert "running no-key sample automatically" in out.lower()

            conn = sqlite3.connect(db_path)
            try:
                statuses = [row[0] for row in conn.execute("SELECT status FROM runs").fetchall()]
            finally:
                conn.close()

            assert "COMPLETED" in statuses


class TestRunCLITestCommand:
    def test_test_workflows_runs_scoped_pytest(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            test_dir = os.path.join(d, "workflows", "tests")
            os.makedirs(test_dir, exist_ok=True)
            test_file = os.path.join(test_dir, "test_checkout.py")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("def test_checkout_flow():\n    assert True\n")

            with patch("agent_runtime.cli.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                code = run_cli(["test", "workflows", "--path", d])

            assert code == 0
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            assert args[0][:3] == [sys.executable, "-m", "pytest"]
            assert "workflows/tests/test_checkout.py" in args[0]
            assert kwargs["cwd"] == d

    def test_test_scope_with_target_filters_files(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            test_dir = os.path.join(d, "workflows", "tests")
            os.makedirs(test_dir, exist_ok=True)
            with open(os.path.join(test_dir, "test_checkout.py"), "w", encoding="utf-8") as f:
                f.write("def test_checkout_flow():\n    assert True\n")
            with open(os.path.join(test_dir, "test_billing.py"), "w", encoding="utf-8") as f:
                f.write("def test_billing_flow():\n    assert True\n")

            with patch("agent_runtime.cli.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                code = run_cli(["test", "workflows", "checkout", "--path", d])

            assert code == 0
            args, _ = mock_run.call_args
            command = args[0]
            assert "workflows/tests/test_checkout.py" in command
            assert "workflows/tests/test_billing.py" not in command

    def test_test_no_matches_returns_one(self, capsys) -> None:
        with tempfile.TemporaryDirectory() as d:
            test_dir = os.path.join(d, "agents", "tests")
            os.makedirs(test_dir, exist_ok=True)
            with open(os.path.join(test_dir, "test_advisor.py"), "w", encoding="utf-8") as f:
                f.write("def test_advisor_agent():\n    assert True\n")

            code = run_cli(["test", "agents", "missing", "--path", d])
            assert code == 1
            assert "No test files, tool test cases, or function test cases matched targets" in capsys.readouterr().out

    def test_test_no_files_returns_zero(self, capsys) -> None:
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "tools", "tests"), exist_ok=True)
            code = run_cli(["test", "tools", "--path", d])
            assert code == 0
            assert "No test files found for scope 'tools'" in capsys.readouterr().out

    def test_tool_specs_run_without_pytest_files(self, capsys) -> None:
        with tempfile.TemporaryDirectory() as d:
            tools_dir = os.path.join(d, "tools")
            tests_dir = os.path.join(tools_dir, "tests")
            os.makedirs(tests_dir, exist_ok=True)

            with open(os.path.join(tools_dir, "sample_tool.py"), "w", encoding="utf-8") as f:
                f.write(
                    "from agent_runtime.tools.base import RuntimeContext, ToolResult\n"
                    "\n"
                    "class SampleTool:\n"
                    "    name = 'tools.sample'\n"
                    "    description = 'sample deterministic tool'\n"
                    "    input_schema = {'type': 'object', 'properties': {'value': {'type': 'integer'}}}\n"
                    "    timeout = None\n"
                    "    retries = None\n"
                    "\n"
                    "    async def execute(self, input, context: RuntimeContext):\n"
                    "        v = int(input.get('value', 0))\n"
                    "        return ToolResult(success=True, output={'double': v * 2}, error=None, metadata=None)\n"
                )

            with open(os.path.join(tests_dir, "tool_tests.yaml"), "w", encoding="utf-8") as f:
                f.write(
                    "schema_version: v1\n"
                    "tool_tests:\n"
                    "  - id: doubles_number\n"
                    "    tool: tools.sample\n"
                    "    input:\n"
                    "      value: 4\n"
                    "    assert:\n"
                    "      - path: success\n"
                    "        equals: true\n"
                    "      - path: output.double\n"
                    "        equals: 8\n"
                )

            code = run_cli(["test", "tools", "--path", d])
            assert code == 0
            out = capsys.readouterr().out
            assert "doubles_number" in out
            assert "Tool spec summary: selected=1 failed=0 parse_errors=0" in out

    def test_tool_specs_filter_by_target(self, capsys) -> None:
        with tempfile.TemporaryDirectory() as d:
            tools_dir = os.path.join(d, "tools")
            tests_dir = os.path.join(tools_dir, "tests")
            os.makedirs(tests_dir, exist_ok=True)

            with open(os.path.join(tools_dir, "sample_tool.py"), "w", encoding="utf-8") as f:
                f.write(
                    "from agent_runtime.tools.base import RuntimeContext, ToolResult\n"
                    "\n"
                    "class SampleTool:\n"
                    "    name = 'tools.sample'\n"
                    "    description = 'sample deterministic tool'\n"
                    "    input_schema = {'type': 'object'}\n"
                    "    timeout = None\n"
                    "    retries = None\n"
                    "\n"
                    "    async def execute(self, input, context: RuntimeContext):\n"
                    "        return ToolResult(success=True, output={'kind': input.get('kind')}, error=None, metadata=None)\n"
                )

            with open(os.path.join(tests_dir, "tool_tests.yaml"), "w", encoding="utf-8") as f:
                f.write(
                    "tool_tests:\n"
                    "  - id: checkout_case\n"
                    "    tool: tools.sample\n"
                    "    input: {kind: checkout}\n"
                    "    assert:\n"
                    "      - path: output.kind\n"
                    "        equals: checkout\n"
                    "  - id: billing_case\n"
                    "    tool: tools.sample\n"
                    "    input: {kind: billing}\n"
                    "    assert:\n"
                    "      - path: output.kind\n"
                    "        equals: billing\n"
                )

            code = run_cli(["test", "tools", "checkout", "--path", d])
            assert code == 0
            out = capsys.readouterr().out
            assert "checkout_case" in out
            assert "billing_case" not in out

    def test_tool_specs_assertion_failure_returns_one(self, capsys) -> None:
        with tempfile.TemporaryDirectory() as d:
            tools_dir = os.path.join(d, "tools")
            tests_dir = os.path.join(tools_dir, "tests")
            os.makedirs(tests_dir, exist_ok=True)

            with open(os.path.join(tools_dir, "sample_tool.py"), "w", encoding="utf-8") as f:
                f.write(
                    "from agent_runtime.tools.base import RuntimeContext, ToolResult\n"
                    "\n"
                    "class SampleTool:\n"
                    "    name = 'tools.sample'\n"
                    "    description = 'sample deterministic tool'\n"
                    "    input_schema = {'type': 'object'}\n"
                    "    timeout = None\n"
                    "    retries = None\n"
                    "\n"
                    "    async def execute(self, input, context: RuntimeContext):\n"
                    "        return ToolResult(success=True, output={'value': 1}, error=None, metadata=None)\n"
                )

            with open(os.path.join(tests_dir, "tool_tests.yaml"), "w", encoding="utf-8") as f:
                f.write(
                    "tool_tests:\n"
                    "  - id: mismatch_case\n"
                    "    tool: tools.sample\n"
                    "    input: {}\n"
                    "    assert:\n"
                    "      - path: output.value\n"
                    "        equals: 2\n"
                )

            code = run_cli(["test", "tools", "--path", d])
            assert code == 1
            assert "mismatch_case" in capsys.readouterr().out

    def test_function_specs_run_without_pytest_files(self, capsys) -> None:
        with tempfile.TemporaryDirectory() as d:
            functions_dir = os.path.join(d, "functions")
            tests_dir = os.path.join(functions_dir, "tests")
            os.makedirs(tests_dir, exist_ok=True)

            with open(os.path.join(functions_dir, "sample.py"), "w", encoding="utf-8") as f:
                f.write(
                    "def double_value(inputs: dict) -> dict:\n"
                    "    value = int(inputs.get('value', 0))\n"
                    "    return {'double': value * 2}\n"
                )

            with open(os.path.join(tests_dir, "function_tests.yaml"), "w", encoding="utf-8") as f:
                f.write(
                    "schema_version: v1\n"
                    "function_tests:\n"
                    "  - id: doubles_number\n"
                    "    function: sample.double_value\n"
                    "    input:\n"
                    "      value: 4\n"
                    "    assert:\n"
                    "      - path: success\n"
                    "        equals: true\n"
                    "      - path: output.double\n"
                    "        equals: 8\n"
                )

            code = run_cli(["test", "functions", "--path", d])
            assert code == 0
            out = capsys.readouterr().out
            assert "doubles_number" in out
            assert "Function spec summary: selected=1 failed=0 parse_errors=0" in out

    def test_function_specs_filter_by_target(self, capsys) -> None:
        with tempfile.TemporaryDirectory() as d:
            functions_dir = os.path.join(d, "functions")
            tests_dir = os.path.join(functions_dir, "tests")
            os.makedirs(tests_dir, exist_ok=True)

            with open(os.path.join(functions_dir, "sample.py"), "w", encoding="utf-8") as f:
                f.write(
                    "def get_label(inputs: dict) -> dict:\n"
                    "    return {'label': inputs.get('label')}\n"
                )

            with open(os.path.join(tests_dir, "function_tests.yaml"), "w", encoding="utf-8") as f:
                f.write(
                    "function_tests:\n"
                    "  - id: checkout_case\n"
                    "    function: sample.get_label\n"
                    "    input: {label: checkout}\n"
                    "    assert:\n"
                    "      - path: output.label\n"
                    "        equals: checkout\n"
                    "  - id: billing_case\n"
                    "    function: sample.get_label\n"
                    "    input: {label: billing}\n"
                    "    assert:\n"
                    "      - path: output.label\n"
                    "        equals: billing\n"
                )

            code = run_cli(["test", "functions", "checkout", "--path", d])
            assert code == 0
            out = capsys.readouterr().out
            assert "checkout_case" in out
            assert "billing_case" not in out

    def test_function_specs_assertion_failure_returns_one(self, capsys) -> None:
        with tempfile.TemporaryDirectory() as d:
            functions_dir = os.path.join(d, "functions")
            tests_dir = os.path.join(functions_dir, "tests")
            os.makedirs(tests_dir, exist_ok=True)

            with open(os.path.join(functions_dir, "sample.py"), "w", encoding="utf-8") as f:
                f.write(
                    "def returns_one(inputs: dict) -> dict:\n"
                    "    return {'value': 1}\n"
                )

            with open(os.path.join(tests_dir, "function_tests.yaml"), "w", encoding="utf-8") as f:
                f.write(
                    "function_tests:\n"
                    "  - id: mismatch_case\n"
                    "    function: sample.returns_one\n"
                    "    input: {}\n"
                    "    assert:\n"
                    "      - path: output.value\n"
                    "        equals: 2\n"
                )

            code = run_cli(["test", "functions", "--path", d])
            assert code == 1
            assert "mismatch_case" in capsys.readouterr().out

    def test_quickstart_branching_sample_first_success(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            code = run_cli(["quickstart", "--path", d, "--sample", "branching"])
            assert code == 0
            db_path = os.path.join(d, "runtime.db")
            assert os.path.isfile(db_path)

            conn = sqlite3.connect(db_path)
            try:
                statuses = [row[0] for row in conn.execute("SELECT status FROM runs").fetchall()]
            finally:
                conn.close()

            assert "COMPLETED" in statuses


