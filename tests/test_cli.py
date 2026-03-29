"""Tests for the CLI module — helpers, dispatch, and subcommands."""

from __future__ import annotations

import json
import os
import sqlite3
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
            assert os.path.isfile(os.path.join(d, "agents", "fixer.yaml"))

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

    def test_model_not_in_agent_yaml(self) -> None:
        """Agent definitions should not contain a model field — model comes from runtime config."""
        with tempfile.TemporaryDirectory() as d:
            _init_project(d)
            for name in ("summarizer.yaml", "fixer.yaml"):
                path = os.path.join(d, "agents", name)
                with open(path) as f:
                    content = f.read()
                assert "model:" not in content


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


class TestRunCLIDocs:
    def test_docs_builds_index_and_workflow_reference(self) -> None:
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
        before = {}
        after = {f"k{i}": i for i in range(25)}
        diff = _diff_state(before, after)
        assert len(diff["added"]) == 21
        assert diff["added"][-1] == "... (+5 more)"

    def test_diff_state_full_shows_all(self) -> None:
        before = {}
        after = {f"k{i}": i for i in range(25)}
        diff = _diff_state(before, after, full=True)
        assert len(diff["added"]) == 25
        assert not any(item.startswith("...") for item in diff["added"])

    def test_diff_state_respects_custom_limit(self) -> None:
        before = {}
        after = {f"k{i}": i for i in range(10)}
        diff = _diff_state(before, after, diff_limit=3)
        assert len(diff["added"]) == 4
        assert diff["added"][-1] == "... (+7 more)"

    def test_diff_state_zero_limit_hides_paths(self) -> None:
        before = {}
        after = {f"k{i}": i for i in range(4)}
        diff = _diff_state(before, after, diff_limit=0)
        assert diff["added"] == ["... (+4 more)"]


class TestRunCLIDiffArgs:
    def test_state_diff_accepts_new_flags(self) -> None:
        storage = make_storage()
        try:
            code = run_cli(["state-diff", "missing", "--db-path", storage.db_path, "--diff-limit", "5", "--full"])
            assert code == 1
        finally:
            storage.close()

    def test_state_diff_negative_limit_exits(self) -> None:
        storage = make_storage()
        try:
            with pytest.raises(SystemExit, match="--diff-limit must be >= 0"):
                run_cli(["state-diff", "missing", "--db-path", storage.db_path, "--diff-limit", "-1"])
        finally:
            storage.close()

    def test_inspect_accepts_diff_flags(self) -> None:
        storage = make_storage()
        try:
            code = run_cli(["inspect", "missing", "--db-path", storage.db_path, "--state-history", "--diff-limit", "5", "--full"])
            assert code == 1
        finally:
            storage.close()


class TestRunCLIQuickstart:
    def test_quickstart_branching_sample_first_success(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            code = run_cli(["quickstart", "--path", d, "--sample", "branching"])
            assert code == 0
            db_path = os.path.join(d, "runtime.db")
            assert os.path.isfile(db_path)

            with sqlite3.connect(db_path) as conn:
                statuses = [row[0] for row in conn.execute("SELECT status FROM runs").fetchall()]

            assert "COMPLETED" in statuses

    def test_quickstart2_alias_warns_and_still_runs(self, capsys) -> None:
        with tempfile.TemporaryDirectory() as d:
            code = run_cli(["quickstart2", "--path", d])
            assert code == 0
            out = capsys.readouterr().out
            assert "deprecated" in out.lower()
            assert "ai quickstart --sample branching" in out


