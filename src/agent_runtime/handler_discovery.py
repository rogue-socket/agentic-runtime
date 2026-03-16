"""Handler discovery module.

Scans a directory for Python modules containing handler functions and registers
them into a StepHandlerRegistry.

Discovery conventions (per module):
  1. If the module defines ``__handlers__`` (a dict mapping name -> function),
     those are registered.
  2. Otherwise, every public function (name not starting with ``_``) is
     registered using the function name as the handler name.

This allows both explicit control and zero-config convenience.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Callable, Dict, List

from .steps import StepHandlerRegistry


def discover_handlers(handlers_dir: str) -> Dict[str, Callable]:
    """Scan *handlers_dir* for ``.py`` files and return discovered handlers.

    Returns a dict mapping handler name -> handler function.
    """
    discovered: Dict[str, Callable] = {}

    if not os.path.isdir(handlers_dir):
        return discovered

    for filename in sorted(os.listdir(handlers_dir)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue

        filepath = os.path.join(handlers_dir, filename)
        module_name = f"_discovered_handlers.{filename[:-3]}"

        spec = importlib.util.spec_from_file_location(module_name, filepath)
        if spec is None or spec.loader is None:
            continue

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Convention 1: explicit __handlers__ dict
        explicit = getattr(module, "__handlers__", None)
        if isinstance(explicit, dict):
            for name, fn in explicit.items():
                if callable(fn):
                    discovered[name] = fn
            continue

        # Convention 2: all public functions
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            attr = getattr(module, attr_name)
            if callable(attr) and not isinstance(attr, type):
                discovered[attr_name] = attr

    return discovered


def register_discovered_handlers(
    registry: StepHandlerRegistry,
    handlers_dir: str,
) -> List[str]:
    """Discover handlers from *handlers_dir* and register them.

    Returns the list of handler names that were registered.
    """
    handlers = discover_handlers(handlers_dir)
    for name, fn in handlers.items():
        registry.register(name, fn)
    return list(handlers.keys())
