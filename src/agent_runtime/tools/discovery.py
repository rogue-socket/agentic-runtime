from __future__ import annotations

import importlib.util
import inspect
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List

from .registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    """Metadata describing a discoverable tool."""

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
        # TODO(eng): module-caching - Same sys.modules caching concern as
        #   function_resolver._import_from_path — stale modules after edits.
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            logger.warning(
                "Failed to import tool module %s from %s",
                module_name, filepath,
                exc_info=True,
            )
            del sys.modules[module_name]
            continue

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
                logger.warning(
                    "Failed to instantiate tool class %s.%s from %s",
                    module_name, attr_name, filepath,
                    exc_info=True,
                )
                continue

    return results
