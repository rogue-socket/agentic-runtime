from __future__ import annotations

import importlib.util
import inspect
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List

from .registry import ToolRegistry


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]


def _looks_like_tool(cls: type) -> bool:
    """Return True if *cls* quacks like a Tool (has the required attributes)."""
    return (
        isinstance(cls, type)
        and hasattr(cls, "name")
        and hasattr(cls, "description")
        and hasattr(cls, "input_schema")
        and hasattr(cls, "execute")
        and callable(getattr(cls, "execute", None))
    )


class ToolDiscovery:
    """Scan a directory for Python modules containing Tool implementations."""

    def discover(self, tools_dir: str) -> List[ToolSpec]:
        """Return ToolSpec metadata for each discovered tool class."""
        specs: List[ToolSpec] = []
        for _name, instance in _discover_tool_instances(tools_dir):
            specs.append(
                ToolSpec(
                    name=instance.name,
                    description=instance.description,
                    input_schema=instance.input_schema,
                )
            )
        return specs


def discover_tools(tools_dir: str) -> Dict[str, object]:
    """Scan *tools_dir* for ``.py`` files and return discovered tool instances.

    Returns a dict mapping tool name -> tool instance.

    Discovery convention: every class in a module that satisfies the Tool
    protocol (has ``name``, ``description``, ``input_schema``, and ``execute``)
    and whose name does not start with ``_`` is instantiated and collected.
    """
    return dict(_discover_tool_instances(tools_dir))


def register_discovered_tools(
    registry: ToolRegistry,
    tools_dir: str,
) -> List[str]:
    """Discover tools from *tools_dir* and register them.

    Returns a list of tool names that were registered.
    """
    instances = discover_tools(tools_dir)
    for _name, tool in instances.items():
        registry.register(tool)
    return list(instances.keys())


def _discover_tool_instances(tools_dir: str) -> List[tuple]:
    """Internal: scan directory, import modules, find Tool classes, instantiate."""
    results: List[tuple] = []

    if not os.path.isdir(tools_dir):
        return results

    for filename in sorted(os.listdir(tools_dir)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue

        filepath = os.path.join(tools_dir, filename)
        module_name = f"_discovered_tools.{filename[:-3]}"

        spec = importlib.util.spec_from_file_location(module_name, filepath)
        if spec is None or spec.loader is None:
            continue

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            attr = getattr(module, attr_name)
            if not _looks_like_tool(attr):
                continue
            # Skip base classes / protocols imported into the module
            if attr.__module__ != module_name:
                continue
            try:
                instance = attr()
                results.append((instance.name, instance))
            except Exception:
                continue

    return results
    def discover(self, context: Dict[str, Any]) -> List[ToolSpec]:
        # [SCAFFOLD:TOOL_DISCOVERY] Wire to dynamic discovery backends.
        return []
