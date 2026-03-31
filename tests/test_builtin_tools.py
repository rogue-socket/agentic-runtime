"""Tests for built-in tools: HTTP, File, Shell."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest

from agent_runtime.tools.base import RuntimeContext, ToolResult
from agent_runtime.tools.http import HttpTool
from agent_runtime.tools.file import FileTool
from agent_runtime.tools.shell import ShellTool
from agent_runtime.tools.validation import validate_input


def _ctx() -> RuntimeContext:
    return RuntimeContext(run_id="r1", step_id="s1", state={}, logger=None)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# HttpTool
# ---------------------------------------------------------------------------


class TestHttpTool:
    def test_rejects_non_http_scheme(self) -> None:
        tool = HttpTool()
        result = _run(tool.execute({"url": "ftp://example.com/file"}, _ctx()))
        assert not result.success
        assert "not allowed" in result.error

    def test_rejects_file_scheme(self) -> None:
        tool = HttpTool()
        result = _run(tool.execute({"url": "file:///etc/passwd"}, _ctx()))
        assert not result.success
        assert "not allowed" in result.error

    def test_successful_get(self) -> None:
        tool = HttpTool()
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"Hello World"
        mock_resp.status = 200
        mock_resp.getheaders.return_value = [("Content-Type", "text/plain")]
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp), \
             patch("agent_runtime.tools.http._is_private_host", return_value=False):
            result = _run(tool.execute({"url": "https://api.example.com/data"}, _ctx()))

        assert result.success
        assert result.output["status"] == 200
        assert result.output["body"] == "Hello World"

    def test_post_with_json_body(self) -> None:
        tool = HttpTool()
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.status = 201
        mock_resp.getheaders.return_value = []
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open, \
             patch("agent_runtime.tools.http._is_private_host", return_value=False):
            result = _run(tool.execute({
                "url": "https://api.example.com/items",
                "method": "POST",
                "json_body": {"name": "test"},
            }, _ctx()))

        assert result.success
        req = mock_open.call_args[0][0]
        assert req.method == "POST"
        body = json.loads(req.data)
        assert body["name"] == "test"

    def test_http_error_returns_failure(self) -> None:
        import urllib.error
        tool = HttpTool()
        exc = urllib.error.HTTPError(
            "https://api.example.com", 404, "Not Found", {}, MagicMock(read=lambda: b"not found")
        )
        exc.fp = MagicMock()
        exc.fp = None

        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            "https://api.example.com", 404, "Not Found", {}, None
        )), \
             patch("agent_runtime.tools.http._is_private_host", return_value=False):
            result = _run(tool.execute({"url": "https://api.example.com/missing"}, _ctx()))

        assert not result.success
        assert result.output["status"] == 404


# ---------------------------------------------------------------------------
# FileTool
# ---------------------------------------------------------------------------


class TestFileTool:
    def test_write_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileTool(root=tmpdir)
            w = _run(tool.execute({"action": "write", "path": "test.txt", "content": "hello"}, _ctx()))
            assert w.success

            r = _run(tool.execute({"action": "read", "path": "test.txt"}, _ctx()))
            assert r.success
            assert r.output["content"] == "hello"

    def test_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileTool(root=tmpdir)
            _run(tool.execute({"action": "write", "path": "log.txt", "content": "line1\n"}, _ctx()))
            _run(tool.execute({"action": "append", "path": "log.txt", "content": "line2\n"}, _ctx()))

            r = _run(tool.execute({"action": "read", "path": "log.txt"}, _ctx()))
            assert r.output["content"] == "line1\nline2\n"

    def test_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileTool(root=tmpdir)
            r = _run(tool.execute({"action": "exists", "path": "nope.txt"}, _ctx()))
            assert r.success
            assert r.output["exists"] is False

    def test_list_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileTool(root=tmpdir)
            open(os.path.join(tmpdir, "a.txt"), "w").close()
            open(os.path.join(tmpdir, "b.txt"), "w").close()

            r = _run(tool.execute({"action": "list", "path": "."}, _ctx()))
            assert r.success
            assert "a.txt" in r.output["entries"]
            assert "b.txt" in r.output["entries"]

    def test_path_traversal_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileTool(root=tmpdir)
            r = _run(tool.execute({"action": "read", "path": "../../etc/passwd"}, _ctx()))
            assert not r.success
            assert "escapes" in r.error

    def test_read_nonexistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileTool(root=tmpdir)
            r = _run(tool.execute({"action": "read", "path": "missing.txt"}, _ctx()))
            assert not r.success
            assert "not found" in r.error.lower()

    def test_write_creates_subdirectories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileTool(root=tmpdir)
            r = _run(tool.execute({"action": "write", "path": "sub/dir/f.txt", "content": "ok"}, _ctx()))
            assert r.success
            assert os.path.isfile(os.path.join(tmpdir, "sub", "dir", "f.txt"))


# ---------------------------------------------------------------------------
# ShellTool
# ---------------------------------------------------------------------------


class TestShellTool:
    def test_echo_command(self) -> None:
        tool = ShellTool()
        result = _run(tool.execute({"command": "echo hello", "shell": True}, _ctx()))
        assert result.success
        assert "hello" in result.output["stdout"]
        assert result.output["returncode"] == 0

    def test_failed_command(self) -> None:
        tool = ShellTool()
        result = _run(tool.execute({"command": "exit 1", "shell": True}, _ctx()))
        assert not result.success
        assert result.output["returncode"] == 1

    def test_timeout(self) -> None:
        tool = ShellTool()
        # Use a very short timeout with a long sleep
        if os.name == "nt":
            cmd = "ping -n 10 127.0.0.1"
        else:
            cmd = "sleep 10"
        result = _run(tool.execute({"command": cmd, "timeout": 1}, _ctx()))
        assert not result.success
        assert "timed out" in result.error.lower()

    def test_empty_command_rejected(self) -> None:
        tool = ShellTool()
        result = _run(tool.execute({"command": ""}, _ctx()))
        assert not result.success
        assert "required" in result.error.lower()


# ---------------------------------------------------------------------------
# validate_input — required field enforcement
# ---------------------------------------------------------------------------


class TestValidateInput:
    def test_missing_required_field_raises(self) -> None:
        schema = {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        }
        with pytest.raises(ValueError, match="Missing required field: 'url'"):
            validate_input({}, schema)

    def test_multiple_required_fields_reports_first_missing(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["action", "path"],
        }
        with pytest.raises(ValueError, match="Missing required field: 'action'"):
            validate_input({}, schema)

    def test_required_field_present_passes(self) -> None:
        schema = {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        }
        validate_input({"url": "https://example.com"}, schema)

    def test_required_field_with_none_value_passes(self) -> None:
        """Present-but-None satisfies the required check (field exists in payload)."""
        schema = {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        }
        validate_input({"url": None}, schema)

    def test_no_required_array_passes(self) -> None:
        schema = {
            "type": "object",
            "properties": {"msg": {"type": "string"}},
        }
        validate_input({}, schema)

    def test_empty_schema_passes(self) -> None:
        validate_input({"anything": 1}, {})

    def test_http_tool_schema_rejects_empty(self) -> None:
        """HttpTool requires 'url' — validate_input should catch this."""
        tool = HttpTool()
        with pytest.raises(ValueError, match="Missing required field: 'url'"):
            validate_input({}, tool.input_schema)

    def test_file_tool_schema_rejects_missing_fields(self) -> None:
        """FileTool requires 'action' and 'path'."""
        tool = FileTool()
        with pytest.raises(ValueError, match="Missing required field: 'action'"):
            validate_input({}, tool.input_schema)
