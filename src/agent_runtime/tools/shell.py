"""Built-in shell command tool.

Executes commands in a subprocess and captures stdout, stderr, and return
code.  Commands are run with a configurable timeout.

Security notes:
- Commands are passed through the system shell.  Only use this tool with
  trusted workflow definitions — never expose it to untrusted user input.
- A maximum output size is enforced to prevent memory exhaustion.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, Optional

from .base import RuntimeContext, ToolResult


_DEFAULT_TIMEOUT = 60  # seconds
_MAX_OUTPUT_BYTES = 1_048_576  # 1 MB


class ShellTool:
    """Execute shell commands and capture output."""

    name = "tools.shell"
    description = "Run a shell command and return stdout, stderr, and return code"
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory (optional)",
            },
            "timeout": {
                "type": "number",
                "description": "Timeout in seconds (default 60)",
            },
        },
        "required": ["command"],
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        command = input.get("command", "")
        if not command:
            return ToolResult(success=False, output=None, error="command is required", metadata=None)

        cwd = input.get("cwd")
        cmd_timeout = input.get("timeout", _DEFAULT_TIMEOUT)

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                timeout=cmd_timeout,
                cwd=cwd,
            )
            stdout = result.stdout[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            stderr = result.stderr[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")

            return ToolResult(
                success=result.returncode == 0,
                output={
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": result.returncode,
                },
                error=stderr if result.returncode != 0 else None,
                metadata=None,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output=None,
                error=f"Command timed out after {cmd_timeout}s",
                metadata=None,
            )
        except OSError as exc:
            return ToolResult(
                success=False,
                output=None,
                error=f"Failed to execute command: {exc}",
                metadata=None,
            )
