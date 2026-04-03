"""Tests for tool auto-discovery from a directory."""

from __future__ import annotations

import os
import tempfile

from agent_runtime.tools.discovery import (
    ToolDiscovery,
    ToolSpec,
    discover_tools,
    register_discovered_tools,
)
from agent_runtime.tools.registry import ToolRegistry


# Sample tool module source that satisfies the Tool protocol
_VALID_TOOL_SRC = '''\
class GreetTool:
    name = "tools.greet"
    description = "Says hello"
    input_schema = {"type": "object", "properties": {"name": {"type": "string"}}}

    async def execute(self, input, context):
        return {"success": True, "output": {"greeting": f"Hello {input['name']}"}}
'''

_SECOND_TOOL_SRC = '''\
class CountTool:
    name = "tools.count"
    description = "Counts items"
    input_schema = {"type": "object", "properties": {"items": {"type": "array"}}}

    async def execute(self, input, context):
        return {"success": True, "output": {"count": len(input.get("items", []))}}
'''

# Module with no tool classes
_NO_TOOLS_SRC = '''\
def helper():
    return 42
'''

# Module with a class that doesn't satisfy the protocol (no execute)
_INVALID_TOOL_SRC = '''\
class NotATool:
    name = "bad"
    description = "Missing execute"
    input_schema = {}
'''


class TestDiscoverTools:

    def test_discover_valid_tool(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "greet.py"), "w") as f:
                f.write(_VALID_TOOL_SRC)
            tools = discover_tools(d)
            assert "tools.greet" in tools
            assert hasattr(tools["tools.greet"], "execute")

    def test_discover_multiple_tools(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "greet.py"), "w") as f:
                f.write(_VALID_TOOL_SRC)
            with open(os.path.join(d, "count.py"), "w") as f:
                f.write(_SECOND_TOOL_SRC)
            tools = discover_tools(d)
            assert len(tools) == 2
            assert "tools.greet" in tools
            assert "tools.count" in tools

    def test_no_tools_in_module(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "helpers.py"), "w") as f:
                f.write(_NO_TOOLS_SRC)
            tools = discover_tools(d)
            assert tools == {}

    def test_ignores_invalid_tool_classes(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "bad.py"), "w") as f:
                f.write(_INVALID_TOOL_SRC)
            tools = discover_tools(d)
            assert tools == {}

    def test_ignores_underscore_files(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "_internal.py"), "w") as f:
                f.write(_VALID_TOOL_SRC)
            tools = discover_tools(d)
            assert tools == {}

    def test_nonexistent_directory(self) -> None:
        """Function implementation."""
        tools = discover_tools("/nonexistent/path/tools")
        assert tools == {}

    def test_empty_directory(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            tools = discover_tools(d)
            assert tools == {}


class TestRegisterDiscoveredTools:

    def test_registers_into_registry(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "greet.py"), "w") as f:
                f.write(_VALID_TOOL_SRC)
            registry = ToolRegistry()
            names = register_discovered_tools(registry, d)
            assert "tools.greet" in names
            tool = registry.get("tools.greet")
            assert tool.name == "tools.greet"


class TestToolDiscoveryClass:

    def test_discover_returns_specs(self) -> None:
        """Function implementation."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "greet.py"), "w") as f:
                f.write(_VALID_TOOL_SRC)
            discovery = ToolDiscovery()
            specs = discovery.discover(d)
            assert len(specs) == 1
            assert isinstance(specs[0], ToolSpec)
            assert specs[0].name == "tools.greet"
            assert specs[0].description == "Says hello"
