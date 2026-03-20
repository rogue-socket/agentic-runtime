"""Tests for the CLI module — helpers, dispatch, and subcommands."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

import pytest

from agent_runtime.cli import (
    _coerce_value,
    _build_input_state,
    _parse_env_line,
    _redact,
    _init_project,
    run_cli,
)


# ── _coerce_value ──────────────────────────────────────────────────


class TestCoerceValue:
    def test_bool_true(self) -> None:
        assert _coerce_value("true") is True
        assert _coerce_value("True") is True
        assert _coerce_value("TRUE") is True

    def test_bool_false(self) -> None:
        assert _coerce_value("false") is False

    def test_int(self) -> None:
        assert _coerce_value("42") == 42
        assert _coerce_value("-1") == -1

    def test_float(self) -> None:
        assert _coerce_value("3.14") == 3.14

    def test_json_object(self) -> None:
        result = _coerce_value('{"key": "val"}')
        assert result == {"key": "val"}

    def test_json_array(self) -> None:
        result = _coerce_value('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_plain_string(self) -> None:
        assert _coerce_value("hello world") == "hello world"

    def test_string_looks_like_json_but_invalid(self) -> None:
        assert _coerce_value("{broken") == "{broken"


# ── _parse_env_line ────────────────────────────────────────────────


class TestParseEnvLine:
    def test_basic(self) -> None:
        assert _parse_env_line("FOO=bar") == ("FOO", "bar")

    def test_quoted_double(self) -> None:
        assert _parse_env_line('KEY="value"') == ("KEY", "value")

    def test_quoted_single(self) -> None:
        assert _parse_env_line("KEY='value'") == ("KEY", "value")

    def test_export_prefix(self) -> None:
        assert _parse_env_line("export MY_VAR=123") == ("MY_VAR", "123")

    def test_comment_ignored(self) -> None:
        assert _parse_env_line("# comment") is None

    def test_empty_ignored(self) -> None:
        assert _parse_env_line("") is None
        assert _parse_env_line("   ") is None

    def test_no_equals(self) -> None:
        assert _parse_env_line("NOVALUE") is None

    def test_empty_key(self) -> None:
        assert _parse_env_line("=value") is None


# ── _redact ────────────────────────────────────────────────────────


class TestRedact:
    def test_redacts_api_key(self) -> None:
        result = _redact({"api_key": "sk-secret", "name": "safe"})
        assert result["api_key"] == "***REDACTED***"
        assert result["name"] == "safe"

    def test_redacts_nested(self) -> None:
        result = _redact({"outer": {"password": "x", "data": 1}})
        assert result["outer"]["password"] == "***REDACTED***"
        assert result["outer"]["data"] == 1

    def test_redacts_token(self) -> None:
        result = _redact({"auth_token": "abc"})
        assert result["auth_token"] == "***REDACTED***"

    def test_list_recursion(self) -> None:
        result = _redact([{"secret": "x"}, {"name": "y"}])
        assert result[0]["secret"] == "***REDACTED***"
        assert result[1]["name"] == "y"

    def test_plain_value_passthrough(self) -> None:
        assert _redact("hello") == "hello"
        assert _redact(42) == 42


# ── _build_input_state ─────────────────────────────────────────────


class TestBuildInputState:
    def test_no_declared_inputs_passthrough(self) -> None:
        result = _build_input_state(["a=1", "b=hello"], {})
        assert result == {"a": 1, "b": "hello"}

    def test_declared_required_provided(self) -> None:
        result = _build_input_state(
            ["issue=bug report"],
            {"issue": {"required": True}},
        )
        assert result == {"issue": "bug report"}

    def test_declared_default_used(self) -> None:
        result = _build_input_state(
            [],
            {"severity": {"required": False, "default": "low"}},
        )
        assert result == {"severity": "low"}

    def test_missing_required_raises(self) -> None:
        with pytest.raises(SystemExit, match="Missing required input"):
            _build_input_state([], {"issue": {"required": True}})

    def test_unknown_input_raises(self) -> None:
        with pytest.raises(SystemExit, match="Unknown inputs"):
            _build_input_state(
                ["extra=val"],
                {"issue": {"required": False, "default": "x"}},
            )

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(SystemExit, match="Invalid input format"):
            _build_input_state(["no-equals"], {})

    def test_coercion_in_values(self) -> None:
        result = _build_input_state(["flag=true", "count=5"], {})
        assert result["flag"] is True
        assert result["count"] == 5


# ── _init_project ──────────────────────────────────────────────────


class TestInitProject:
    def test_creates_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _init_project(d)
            assert os.path.isdir(os.path.join(d, "workflows"))
            assert os.path.isdir(os.path.join(d, "tools"))
            assert os.path.isdir(os.path.join(d, "agents"))
            assert os.path.isdir(os.path.join(d, "functions"))
            assert os.path.isfile(os.path.join(d, "runtime.yaml"))
            assert os.path.isfile(os.path.join(d, "workflows", "example.yaml"))
            assert os.path.isfile(os.path.join(d, "tools", "example_tool.py"))
            assert os.path.isfile(os.path.join(d, "functions", "stubs.py"))
            assert os.path.isfile(os.path.join(d, "agents", "summarizer.yaml"))

    def test_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _init_project(d)
            # Overwrite one file to confirm it's not clobbered
            marker = os.path.join(d, "workflows", "example.yaml")
            with open(marker, "w") as f:
                f.write("custom")
            _init_project(d)
            with open(marker) as f:
                assert f.read() == "custom"

    def test_model_option(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _init_project(d, model="claude-3-opus")
            agent_path = os.path.join(d, "agents", "summarizer.yaml")
            with open(agent_path) as f:
                content = f.read()
            assert "claude-3-opus" in content


# ── run_cli dispatch ───────────────────────────────────────────────


class TestRunCLIInit:
    def test_init_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            code = run_cli(["init", "--path", d])
            assert code == 0
            assert os.path.isdir(os.path.join(d, "workflows"))


class TestRunCLIList:
    def test_list_no_agents_dir(self, capsys) -> None:
        code = run_cli(["list", "--agents-dir", "/nonexistent_dir_xyz"])
        assert code == 0
        assert "No agents directory" in capsys.readouterr().out

    def test_list_empty_agents_dir(self, capsys) -> None:
        with tempfile.TemporaryDirectory() as d:
            code = run_cli(["list", "--agents-dir", d])
            assert code == 0
            assert "No agents found" in capsys.readouterr().out


