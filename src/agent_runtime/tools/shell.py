"""Built-in shell command tool.

Executes commands in a subprocess and captures stdout, stderr, and return
code.  Commands are run with a configurable timeout.

Security notes:
- Commands are passed through the system shell.  Only use this tool with
  trusted workflow definitions — never expose it to untrusted user input.
- A maximum output size is enforced to prevent memory exhaustion.
- An optional allowlist/denylist restricts which commands may be executed.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from typing import Any, Dict, List, Optional

from .base import RuntimeContext, ToolResult


_DEFAULT_TIMEOUT = 60  # seconds
_MAX_OUTPUT_BYTES = 1_048_576  # 1 MB


class ShellTool:
    """Execute shell commands and capture output.

    Command restrictions can be configured via ``allowlist`` and
    ``denylist``.  Each list contains shell-glob or regex patterns
    matched against the first token (program name) of the command.

    - If ``allowlist`` is set, **only** commands whose program name
      matches at least one pattern are allowed.
    - If ``denylist`` is set, commands whose program name matches
      any pattern are rejected.
    - ``denylist`` is checked first — a command denied by the denylist
      is rejected even if it matches an allowlist entry.
    """

    name = "tools.shell"
    description = "Run a shell command and return stdout, stderr, and return code"
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Command to execute",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory (optional)",
            },
            "timeout": {
                "type": "number",
                "description": "Timeout in seconds (default 60)",
            },
            "shell": {
                "type": "boolean",
                "description": "Pass command through the system shell (default false). Enable for pipes, globs, or shell builtins.",
            },
        },
        "required": ["command"],
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    def __init__(
        self,
        allowlist: Optional[List[str]] = None,
        denylist: Optional[List[str]] = None,
    ) -> None:
        """Initialize with optional command restrictions.

        Args:
            allowlist: If set, only programs matching one of these patterns
                are permitted.  Patterns are matched as anchored regexes
                against the first token of the command.
            denylist: Programs matching any of these patterns are rejected
                regardless of the allowlist.
        """
        self._allowlist = [re.compile(p) for p in allowlist] if allowlist else None
        self._denylist = [re.compile(p) for p in denylist] if denylist else None

    def _extract_programs(self, command: str) -> list[str]:
        """Extract all program names from a command string.

        Handles pipes (``|``), logical operators (``&&``, ``||``),
        semicolons (``;``), newlines, and command substitution (``$(...)``
        and backticks) to prevent denylist bypass via chaining.
        """
        # Split on shell operators and newlines to get individual commands.
        segments = re.split(r'\|{1,2}|&&|;|\n', command)
        programs: list[str] = []
        for segment in segments:
            segment = segment.strip()
            if not segment:
                continue
            try:
                tokens = shlex.split(segment)
            except ValueError:
                tokens = segment.split()
            if tokens:
                programs.append(tokens[0])
        # Detect command substitution patterns — extract program inside $()
        for match in re.finditer(r'\$\(([^)]+)\)', command):
            inner = match.group(1).strip()
            inner_programs = self._extract_programs(inner)
            programs.extend(inner_programs)
        # Detect backtick command substitution
        for match in re.finditer(r'`([^`]+)`', command):
            inner = match.group(1).strip()
            inner_programs = self._extract_programs(inner)
            programs.extend(inner_programs)
        return programs

    def _check_command(self, command: str) -> Optional[str]:
        """Return an error message if the command is restricted, else None."""
        programs = self._extract_programs(command)
        if not programs:
            return None

        for program in programs:
            if self._denylist:
                for pattern in self._denylist:
                    if pattern.fullmatch(program):
                        return f"Command '{program}' is blocked by denylist"

            if self._allowlist:
                if not any(p.fullmatch(program) for p in self._allowlist):
                    return f"Command '{program}' is not in the allowlist"

        return None

    async def execute(self, input: Dict[str, Any], context: RuntimeContext) -> ToolResult:
        """Function implementation."""
        command = input.get("command", "")
        if not command:
            return ToolResult(success=False, output=None, error="command is required", metadata=None)

        restriction_error = self._check_command(command)
        if restriction_error:
            return ToolResult(success=False, output=None, error=restriction_error, metadata=None)

        cwd = input.get("cwd")
        cmd_timeout = input.get("timeout", _DEFAULT_TIMEOUT)
        use_shell = input.get("shell", False)

        try:
            cmd: Any = shlex.split(command) if not use_shell else command
            result = subprocess.run(
                cmd,
                shell=use_shell,
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
