"""Function resolver — discovers and imports functions from the functions/ directory.

Functions are plain Python callables with signature ``(inputs: dict) -> dict``.
They live in ``.py`` files under the project's ``functions/`` directory.

Resolution modes:
- **Qualified**: ``formatters.format_markdown`` → looks in ``functions/formatters.py``
  for a function named ``format_markdown``.
- **Unqualified**: ``format_markdown`` → scans all ``.py`` files in ``functions/``
  for a function named ``format_markdown``.  Ambiguous matches (found in
  multiple files) raise an error.

Subdirectories are supported: ``reporting.formatters.format_markdown`` resolves
to ``functions/reporting/formatters.py``.

Resolution happens at **parse time** (fail fast).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Callable, Dict, Optional


def resolve_function(ref: str, functions_dir: str) -> Callable:
    """Resolve a function reference to an actual Python callable.

    Args:
        ref: Function reference — qualified (``module.func``) or unqualified (``func``).
        functions_dir: Absolute path to the ``functions/`` directory.

    Returns:
        The resolved callable.

    Raises:
        ValueError: If the function cannot be found or is ambiguous.
    """
    if not os.path.isdir(functions_dir):
        raise ValueError(
            f"Functions directory not found: {functions_dir}"
        )

    if "." in ref:
        return _resolve_qualified(ref, functions_dir)
    else:
        return _resolve_unqualified(ref, functions_dir)


def _resolve_qualified(ref: str, functions_dir: str) -> Callable:
    """Resolve a qualified function reference like ``formatters.format_markdown``."""
    parts = ref.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid function reference: {ref}")
    module_rel, func_name = parts

    # Convert dotted module path to file path
    module_file = os.path.join(functions_dir, *module_rel.split(".")) + ".py"
    if not os.path.isfile(module_file):
        raise ValueError(
            f"Function module not found: {module_file} "
            f"(from reference '{ref}')"
        )

    module = _import_from_path(module_file, module_rel)
    fn = getattr(module, func_name, None)
    if fn is None or not callable(fn):
        raise ValueError(
            f"Function '{func_name}' not found in {module_file}"
        )
    return fn


def _resolve_unqualified(ref: str, functions_dir: str) -> Callable:
    """Resolve an unqualified function reference by scanning all .py files."""
    matches: list[tuple[str, Callable]] = []
    functions_path = Path(functions_dir)

    for py_file in sorted(functions_path.rglob("*.py")):
        if py_file.name.startswith("_"):
            continue
        # derive module name from relative path
        rel = py_file.relative_to(functions_path)
        module_name = str(rel.with_suffix("")).replace(os.sep, ".").replace("/", ".")
        module = _import_from_path(str(py_file), module_name)
        fn = getattr(module, ref, None)
        if fn is not None and callable(fn):
            matches.append((str(py_file), fn))

    if len(matches) == 0:
        raise ValueError(
            f"Function '{ref}' not found in {functions_dir}"
        )
    if len(matches) > 1:
        files = [m[0] for m in matches]
        raise ValueError(
            f"Function '{ref}' found in multiple files: {files}. "
            f"Use a qualified reference to disambiguate (e.g. 'module.{ref}')."
        )
    return matches[0][1]


def _import_from_path(filepath: str, module_name: str):
    """Import a Python module from an absolute file path."""
    qualified = f"_runtime_functions.{module_name}"
    if qualified in sys.modules:
        return sys.modules[qualified]
    spec = importlib.util.spec_from_file_location(qualified, filepath)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot import module from {filepath}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module
