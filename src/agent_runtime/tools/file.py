"""Built-in file read/write tool.

Provides controlled filesystem access scoped to a configurable root
directory.  Paths that escape the root are rejected.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .base import RuntimeContext, ToolResult


# Default root is the current working directory.
# In production, callers should configure a tighter sandbox.
_DEFAULT_ROOT = os.getcwd()

_MAX_READ_BYTES = 1_048_576  # 1 MB safety limit


class FileTool:
    """Read and write files within a sandboxed root directory."""

    name = "tools.file"
    description = "Read or write files (scoped to project root)"
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "write", "append", "exists", "list"],
                "description": "File operation to perform",
            },
            "path": {
                "type": "string",
                "description": "Relative file path within the project root",
            },
            "content": {
                "type": "string",
                "description": "Content to write (for write/append actions)",
            },
        },
        "required": ["action", "path"],
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    def __init__(self, root: Optional[str] = None) -> None:
        self.root = os.path.abspath(root or _DEFAULT_ROOT)

    def _safe_path(self, relative: str) -> Optional[str]:
        """Resolve path and verify it stays within root."""
        resolved = os.path.normpath(os.path.join(self.root, relative))
        if resolved != self.root and not resolved.startswith(self.root + os.sep):
            return None
        return resolved

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        action = input.get("action", "")
        rel_path = input.get("path", "")
        content = input.get("content", "")

        if not rel_path:
            return ToolResult(success=False, output=None, error="path is required", metadata=None)

        abs_path = self._safe_path(rel_path)
        if abs_path is None:
            return ToolResult(
                success=False,
                output=None,
                error="Path escapes the allowed root directory",
                metadata=None,
            )

        if action == "read":
            if not os.path.isfile(abs_path):
                return ToolResult(success=False, output=None, error=f"File not found: {rel_path}", metadata=None)
            with open(abs_path, "r", encoding="utf-8") as f:
                data = f.read(_MAX_READ_BYTES)
            return ToolResult(success=True, output={"content": data}, error=None, metadata=None)

        if action == "write":
            os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(success=True, output={"path": rel_path, "bytes": len(content)}, error=None, metadata=None)

        if action == "append":
            os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
            with open(abs_path, "a", encoding="utf-8") as f:
                f.write(content)
            return ToolResult(success=True, output={"path": rel_path, "bytes": len(content)}, error=None, metadata=None)

        if action == "exists":
            return ToolResult(
                success=True,
                output={"exists": os.path.exists(abs_path), "is_file": os.path.isfile(abs_path), "is_dir": os.path.isdir(abs_path)},
                error=None,
                metadata=None,
            )

        if action == "list":
            if not os.path.isdir(abs_path):
                return ToolResult(success=False, output=None, error=f"Not a directory: {rel_path}", metadata=None)
            entries = sorted(os.listdir(abs_path))
            return ToolResult(success=True, output={"entries": entries}, error=None, metadata=None)

        return ToolResult(success=False, output=None, error=f"Unknown action: {action}", metadata=None)
