from __future__ import annotations

"""File: src/agent_runtime/cli.py

Purpose:
Implement `ai` command-line interface for runtime operations.

Description:
Defines command parsing and handlers for project init, run, inspect,
resume, replay, state diff, and visualization commands.

Key Components:
- `run_cli` command dispatcher
- helper registries for default tool/memory setup
- inspect/state-history rendering helpers

Dependencies:
- Core executor/runtime modules, SQLite storage, visualization builders

Inputs/Outputs:
- Input: CLI args and workflow references
- Output: console reports, exit codes, and persisted run artifacts

Side Effects:
- Creates files/directories, writes DB rows, may open browser.

TODO(ux): ICP is solo dev / small team building an agent. The CLI
  experience should optimize for that persona:
    - `ai init` should scaffold only the base project skeleton (dirs + config),
        while quickstart commands can layer opinionated examples on top.
  - `ai run` output should show a concise progress summary by default
    (step name + status + duration), not just silence until completion.
  - Add `ai quickstart` command that creates a minimal agent, runs it,
    and opens the HTML visualization — a single-command "wow" moment.
"""

import argparse
import asyncio
import io
import getpass
import json
import os
import subprocess
import tarfile
import time
from pathlib import Path
from pprint import pformat
import re
import sys
from typing import Any, Dict, List, Optional
import webbrowser
import yaml

from .core import Executor
from .config import RuntimeConfig, load_config, apply_cli_overrides
from .logging import StructuredLogger
from .memory import EpisodicMemory, MemoryManager, ProceduralMemory, SemanticMemory, WorkingMemory
from .resume import determine_resume_step, validate_resume
from .replay import RunReplayer
from .state import RuntimeState
from .storage import SQLiteStorage
from .tools import ToolRegistry
from .tools.echo import EchoTool
from .tools.http import HttpTool
from .tools.file import FileTool
from .tools.shell import ShellTool
from .tools.discovery import register_discovered_tools
from .tools.base import RuntimeContext
from .function_resolver import resolve_function
from .errors import (
    RunNotFoundError,
    RuntimeErrorBase,
    WorkflowValidationError,
    get_error_code,
    get_user_message,
)
from .observability import normalize_agent_trace
from .debugger import LiveDebugger, load_debug_profile
from .workflow import load_workflow, load_workflow_from_text
from .workflow_registry import WorkflowRegistry, parse_workflow_reference
from .visualization import GraphBuilder, RunLoader, TimelineBuilder, render_ascii, render_html
from .utils import sha256_json
from .agent import AgentDefinition, AgentRegistry, load_agent_definition
from .llm import LLMClient

_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|token|password|credential|auth|bearer)",
    re.IGNORECASE,
)

_DEFAULT_PROVIDER_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "local": "LOCAL_LLM_KEY",
}

_DEFAULT_PROVIDER_MODEL = {
    "openai": "gpt-4o",
    "anthropic": "claude-3-opus",
    "gemini": "gemini-2.5-flash",
    "local": "llama-3",
}

_DEFAULT_PROVIDER_BASE_URL = {
    "local": "http://localhost:8080/v1",
}

_TEST_SCOPE_DIRS = {
    "workflows": ["workflows/tests"],
    "agents": ["agents/tests"],
    "functions": ["functions/tests"],
    "tools": ["tools/tests"],
    "all": ["workflows/tests", "agents/tests", "functions/tests", "tools/tests"],
}

_TEST_README_TEMPLATE = """# {domain} tests

Place project tests for `{domain}/` in this folder.

Suggested naming:
- Test files: `test_<name>.py`
- Test cases: `test_<behavior>()`

Run tests with:
- `ai test {domain}`
- `ai test {domain} <target>`
"""

_TOOL_TEST_TEMPLATE = """schema_version: v1
tool_tests: []

# Example:
# tool_tests:
#   - id: priority_marks_critical
#     tool: tools.priority_heuristic
#     input:
#       issue: "API is down with 500 errors"
#     assert:
#       - path: success
#         equals: true
#       - path: output.priority
#         equals: "P0 (critical)"
"""

_FUNCTION_TEST_TEMPLATE = """schema_version: v1
function_tests: []

# Example:
# function_tests:
#   - id: classify_high
#     function: stubs.classify_severity
#     input:
#       issue: "Login fails with 500 errors"
#     assert:
#       - path: success
#         equals: true
#       - path: output.severity
#         equals: high
"""

_TOOL_TEST_SPEC_FILENAMES = {"tool_tests.yaml", "tool_tests.yml"}
_TOOL_TEST_SPEC_SUFFIXES = (".tooltest.yaml", ".tooltest.yml")
_FUNCTION_TEST_SPEC_FILENAMES = {"function_tests.yaml", "function_tests.yml"}
_FUNCTION_TEST_SPEC_SUFFIXES = (".functest.yaml", ".functest.yml")


# [Pain Point Solved] #N11 .env File in the Repo: Secrets are redacted in all
#   CLI output — inspect, state-history, and run displays never leak API keys.
def _redact(obj: Any) -> Any:
    """Recursively redact values whose keys look like secrets."""
    if isinstance(obj, dict):
        return {
            k: ("***REDACTED***" if _SECRET_KEY_RE.search(k) else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    return obj


def _to_int(value: Any) -> int:
    """Coerce a value to int, returning 0 for non-numeric types."""
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _strip_secret_keys(obj: Any) -> Any:
    """Remove secret-like keys from a nested structure."""
    if isinstance(obj, dict):
        cleaned: Dict[str, Any] = {}
        for key, value in obj.items():
            key_lower = str(key).lower()
            if _SECRET_KEY_RE.search(key_lower) and not key_lower.endswith("_env"):
                continue
            cleaned[key] = _strip_secret_keys(value)
        return cleaned
    if isinstance(obj, list):
        return [_strip_secret_keys(item) for item in obj]
    return obj


def _resolve_project_path(project_root: str, path_value: str) -> str:
    """Resolve a path from runtime.yaml relative to the project root."""
    if not path_value:
        return ""
    if os.path.isabs(path_value):
        return path_value
    return os.path.join(project_root, path_value)


def _write_tar_text(tar: tarfile.TarFile, arcname: str, text: str) -> None:
    """Write a text file into a tar archive."""
    data = text.encode("utf-8")
    info = tarfile.TarInfo(arcname)
    info.size = len(data)
    info.mtime = time.time()
    tar.addfile(info, io.BytesIO(data))


def _add_directory_to_tar(
    tar: tarfile.TarFile,
    source_dir: str,
    arc_dir: str,
) -> int:
    """Add a directory tree to a tar archive under a target archive path."""
    if not source_dir or not os.path.isdir(source_dir):
        info = tarfile.TarInfo(arc_dir.rstrip("/") + "/")
        info.type = tarfile.DIRTYPE
        info.mtime = time.time()
        tar.addfile(info)
        return 0

    files_added = 0
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", ".venv", ".pytest_cache")]
        rel_root = os.path.relpath(root, source_dir)
        rel_root = "" if rel_root == "." else rel_root
        for file_name in files:
            if file_name in (".DS_Store",):
                continue
            if file_name.endswith((".pyc", ".pyo")):
                continue
            src_path = os.path.join(root, file_name)
            rel_path = os.path.join(rel_root, file_name) if rel_root else file_name
            arc_path = os.path.join(arc_dir, rel_path)
            tar.add(src_path, arcname=arc_path, recursive=False)
            files_added += 1
    return files_added


def _safe_extract_tar(tar: tarfile.TarFile, target_dir: str) -> None:
    """Extract tar contents, blocking path traversal and absolute paths."""
    target_dir = os.path.abspath(target_dir)
    for member in tar.getmembers():
        if not member.name:
            continue
        if member.issym() or member.islnk():
            raise SystemExit(f"Unsafe archive entry (link): {member.name}")
        if os.path.isabs(member.name):
            raise SystemExit(f"Unsafe archive entry (absolute path): {member.name}")
        normalized = os.path.normpath(member.name)
        if normalized.startswith(".."):
            raise SystemExit(f"Unsafe archive entry (path traversal): {member.name}")
        dest_path = os.path.abspath(os.path.join(target_dir, normalized))
        if not dest_path.startswith(target_dir + os.sep):
            raise SystemExit(f"Unsafe archive entry (escaped root): {member.name}")
    tar.extractall(path=target_dir)


def _estimate_step_cost_usd(
    token_usage: Dict[str, Any],
    pricing: Dict[str, Dict[str, float]],
) -> Optional[float]:
    """Estimate USD cost for a step from token_usage and pricing config.

    Uses the same normalization as LLMClient: tries provider/model-specific
    pricing first, then ``*`` wildcard.
    """
    if not pricing or not token_usage:
        return None

    input_tokens = _to_int(
        token_usage.get("input_tokens", token_usage.get("prompt_tokens", 0))
    )
    output_tokens = _to_int(
        token_usage.get("output_tokens", token_usage.get("completion_tokens", 0))
    )

    # Try to find matching pricing entry; fall back to wildcard
    price_cfg = pricing.get("*")
    if not isinstance(price_cfg, dict):
        return None

    input_rate = float(price_cfg.get("input", 0.0))
    output_rate = float(price_cfg.get("output", input_rate))
    return ((input_tokens / 1000.0) * input_rate) + ((output_tokens / 1000.0) * output_rate)


def _print_run_summary(run, pricing: Dict[str, Dict[str, float]]) -> None:
    """Print a compact end-of-run summary block: duration, steps, tokens, cost, outputs.

    Cost is preferred from persisted ``step.cost_usd`` and falls back to recalculation
    from ``token_usage`` + pricing when older runs lack the column. Sections are
    omitted when there's nothing to report (e.g., a function-only run has no tokens).
    """
    duration_ms = run.total_duration_ms
    if duration_ms is not None:
        print(f"  duration: {duration_ms}ms")

    steps = run.steps
    completed = sum(1 for s in steps if s.status == "COMPLETED")
    failed = sum(1 for s in steps if s.status == "FAILED")
    parts = [f"{completed} completed"]
    if failed:
        parts.append(f"{failed} failed")
    print(f"  steps: {len(steps)} ({', '.join(parts)})")

    total_input = 0
    total_output = 0
    total_total = 0
    for step in steps:
        usage = step.token_usage or {}
        total_input += _to_int(usage.get("input_tokens", usage.get("prompt_tokens", 0)))
        total_output += _to_int(usage.get("output_tokens", usage.get("completion_tokens", 0)))
        total_total += _to_int(usage.get("total_tokens", 0))
    if total_input or total_output or total_total:
        print(f"  tokens: {total_total or (total_input + total_output)} (input: {total_input}, output: {total_output})")

    total_cost = run.total_cost_usd
    if total_cost is None and pricing:
        recalc: Optional[float] = None
        for step in steps:
            if not step.token_usage:
                continue
            step_cost = _estimate_step_cost_usd(step.token_usage, pricing)
            if step_cost is not None:
                recalc = (recalc or 0.0) + step_cost
        total_cost = recalc
    if total_cost is not None and total_cost > 0:
        print(f"  cost: ${total_cost:.6f}")

    output_keys = list(run.outputs.keys())
    if output_keys:
        preview = ", ".join(output_keys[:6])
        more = f" (+{len(output_keys) - 6} more)" if len(output_keys) > 6 else ""
        print(f"  outputs: {preview}{more}")


def _print_failure_details(run) -> None:
    """Print structured failure context for a FAILED run.

    Locates the actual failed step (preferring the one whose status is FAILED) and
    surfaces its id, type, attempt count, and the underlying error inline so the
    user doesn't need a second ``ai inspect`` round-trip just to see what broke.
    Falls back to ``run.error`` when no individual step is marked FAILED.
    """
    failed_step = None
    for step in run.steps:
        if step.status == "FAILED":
            failed_step = step
            break

    if failed_step is None:
        if run.error:
            print(f"Error: {run.error}")
        return

    attempts = failed_step.attempt_count
    attempt_str = f" — attempt {attempts}" if attempts and attempts > 1 else ""
    print(f"\nFailed step: {failed_step.step_id} ({failed_step.step_type}){attempt_str}")

    err = failed_step.error or failed_step.last_error or run.error or "(no error message recorded)"
    # Indent multi-line errors so they read as a single block under the step.
    err_lines = str(err).splitlines() or [""]
    print(f"  Error: {err_lines[0]}")
    for line in err_lines[1:]:
        print(f"         {line}")


def _parse_env_line(line: str) -> Optional[tuple[str, str]]:
    """Function implementation."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export "):].lstrip()
    if "=" not in stripped:
        return None
    key, _, value = stripped.partition("=")
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return key, value


def _print_cli_exception(exc: BaseException, *, stream=sys.stderr) -> None:
    """Print normalized user-facing error with stable taxonomy code."""
    code = get_error_code(exc)
    message = get_user_message(exc)
    detail = str(exc).strip() or type(exc).__name__
    print(f"Error [{code}]: {message}", file=stream)
    print(f"Detail: {detail}", file=stream)


# [Pain Point Solved] #N11 .env File in the Repo: .env is gitignored. This loader
#   uses os.environ.setdefault so existing env vars take precedence — safe for CI
#   where secrets come from the environment, not files.
def _load_dotenv(path: str = ".env") -> None:
    """Load environment variables from a local .env file if present."""
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parsed = _parse_env_line(line)
                if parsed is None:
                    continue
                key, value = parsed
                os.environ.setdefault(key, value)
    except OSError:
        return


def _quote_env_value(value: str) -> str:
    """Function implementation."""
    if not value:
        return value
    if re.search(r"\s|#", value):
        escaped = value.replace('"', '\\"')
        return f"\"{escaped}\""
    return value


def _update_dotenv(path: str, updates: Dict[str, str]) -> None:
    """Function implementation."""
    lines: List[str] = []
    seen: set[str] = set()
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parsed = _parse_env_line(line)
                if parsed is None:
                    lines.append(line)
                    continue
                key, _ = parsed
                if key in updates:
                    lines.append(f"{key}={_quote_env_value(updates[key])}\n")
                    seen.add(key)
                else:
                    lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={_quote_env_value(value)}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _prompt_value(prompt: str, default: Optional[str] = None, secret: bool = False) -> str:
    """Function implementation."""
    suffix = f" [{default}]" if default else ""
    full_prompt = f"{prompt}{suffix}: "
    if secret:
        value = getpass.getpass(full_prompt)
    else:
        value = input(full_prompt)
    if not value and default is not None:
        return default
    return value.strip()


def _prompt_yes_no(prompt: str, default: bool = True) -> bool:
    """Function implementation."""
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{hint}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False


def _prompt_choice(prompt: str, choices: List[str], default: str) -> str:
    """Function implementation."""
    choices_lower = [c.lower() for c in choices]
    while True:
        raw = input(f"{prompt} {choices} [{default}]: ").strip()
        if not raw:
            return default
        if raw.lower() in choices_lower:
            return choices[choices_lower.index(raw.lower())]


def _prompt_int(prompt: str, min_value: int, max_value: int, default: int) -> int:
    """Function implementation."""
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Please enter a number.")
            continue
        if value < min_value or value > max_value:
            print(f"Choose a number between {min_value} and {max_value}.")
            continue
        return value


EXAMPLE_WORKFLOW = """schema_version: v1             # workflow schema version
workflow:                     # workflow metadata
  id: example_workflow         # unique workflow id
  version: v1                  # version tag
inputs:                        # declared inputs
  issue:
    description: The issue text to analyze
    default: "Login API fails for invalid token"
on_error: fail_fast            # stop on first error
steps:                         # ordered steps (a list)
  - id: summarize
    type: agent                # agent step delegates to an agent definition
    agent: summarizer          # defined in agents/summarizer.yaml
    inputs:
      issue: inputs.issue      # read from inputs
  - id: priority
    type: tool                 # tool step uses a tool class
    tool: tools.priority_heuristic  # quick heuristic tool
    inputs:
      issue: inputs.issue
  - id: classify
    type: function             # function step calls a plain Python function
    function: stubs.classify_severity  # defined in functions/stubs.py
    inputs:
      issue: inputs.issue
  - id: next_steps
    type: agent                # agent step delegates to an agent definition
    agent: fixer               # defined in agents/fixer.yaml
    inputs:
      issue: inputs.issue
      summary: steps.summarize.summary
      priority: steps.priority.priority
  - id: build_report
    type: tool                 # tool step uses a tool class
    tool: tools.report_builder # build a markdown report
    inputs:
      title: "Quickstart Report"
      summary: steps.summarize.summary
      priority: steps.priority.priority
      next_steps: steps.next_steps.next_steps
  - id: echo_summary
    type: tool                 # tool step uses a tool class
    tool: tools.echo           # built-in echo tool
    inputs:
      message: steps.summarize.summary  # read prior step output
  - id: echo_report
    type: tool
    tool: tools.echo
    inputs:
      message: steps.build_report.report
  - id: echo_next_steps
    type: tool
    tool: tools.echo
    inputs:
      message: steps.next_steps.next_steps
"""

EXAMPLE_FUNCTION = '''"""Stub functions for the quickstart workflow.

The runtime discovers functions from the functions/ directory.
Any public function in a .py file can be referenced in workflow YAML
using the `type: function` step type.

Reference by qualified name: `module.function_name`
  e.g. `stubs.classify_severity` references `classify_severity`
  in `functions/stubs.py`.

Signature: (inputs: dict) -> dict
"""


def classify_severity(inputs: dict) -> dict:
    """Classify issue severity based on keywords.

    Usage in workflow YAML:
        - id: classify
          type: function
          function: stubs.classify_severity
          inputs:
            issue: inputs.issue
    """
    issue = (inputs.get("issue") or "").lower()
    if any(w in issue for w in ("outage", "down", "crash", "data loss")):
        severity = "critical"
    elif any(w in issue for w in ("error", "fail", "broken", "500")):
        severity = "high"
    elif any(w in issue for w in ("slow", "timeout", "latency")):
        severity = "medium"
    else:
        severity = "low"
    return {"severity": severity}


def format_output(inputs: dict) -> dict:
    """Formats text as a simple report."""
    text = inputs.get("text", "")
    return {"report": f"--- Report ---\\n{text}\\n--- End ---"}
'''

EXAMPLE_TOOL = '''"""Example tool module.

The runtime auto-discovers tools from the tools/ directory.

Discovery convention: every class that implements the Tool protocol (has
``name``, ``description``, ``input_schema``, and ``execute``) and whose
class name does not start with ``_`` is instantiated and registered.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent_runtime.tools.base import RuntimeContext, ToolResult


class ReportBuilderTool:
    """Builds a markdown report from LLM outputs.

    Usage in workflow YAML:
        - id: build_report
          type: tool
          tool: tools.report_builder
          inputs:
            title: "Incident Report"
            summary: steps.summarize.summary
            priority: steps.priority.priority
            next_steps: steps.next_steps.next_steps
    """

    name = "tools.report_builder"
    description = "Builds a markdown report from summary and next steps"
    input_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "priority": {"type": "string"},
            "next_steps": {"type": "string"},
        },
        "required": ["summary", "next_steps"],
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(
        self, input: Dict[str, Any], context: RuntimeContext
    ) -> ToolResult:
        title = input.get("title", "Quickstart Report")
        summary = input.get("summary", "")
        priority = input.get("priority", "")
        next_steps = input.get("next_steps", "")
        priority_block = f"\\n\\n## Priority\\n{priority}" if priority else ""
        report = (
            f"# {title}\\n\\n"
            f"## Summary\\n{summary}"
            f"{priority_block}\\n\\n"
            f"## Next Steps\\n{next_steps}\\n"
        )
        return ToolResult(
            success=True,
            output={"report": report},
            error=None,
            metadata=None,
        )


class PriorityHeuristicTool:
    """Assigns a rough priority based on keywords.

    Usage in workflow YAML:
        - id: priority
          type: tool
          tool: tools.priority_heuristic
          inputs:
            issue: inputs.issue
    """

    name = "tools.priority_heuristic"
    description = "Assigns a simple priority label from issue text"
    input_schema = {
        "type": "object",
        "properties": {
            "issue": {"type": "string"},
        },
        "required": ["issue"],
    }
    timeout: Optional[float] = None
    retries: Optional[int] = None

    async def execute(
        self, input: Dict[str, Any], context: RuntimeContext
    ) -> ToolResult:
        issue = (input.get("issue") or "").lower()
        if any(token in issue for token in ("outage", "down", "500", "crash")):
            priority = "P0 (critical)"
        elif any(token in issue for token in ("latency", "slow", "timeout", "401")):
            priority = "P1 (high)"
        else:
            priority = "P2 (medium)"
        return ToolResult(
            success=True,
            output={"priority": priority},
            error=None,
            metadata=None,
        )
'''

RUNTIME_YAML_TEMPLATE = """# Runtime configuration for ForrestRun.
# CLI flags override values set here.
# Uncomment and edit sections as needed.

# Schema version for runtime.yaml format.
schema_version: v1

# ─── Storage ──────────────────────────────────────────────────────────
# SQLite database path for run persistence.
db_path: runtime.db

# ─── Directory paths ──────────────────────────────────────────────────
workflows_dir: workflows
tools_dir: tools
agents_dir: agents
functions_dir: functions

# ─── State overwrite policy ───────────────────────────────────────────
# Controls what happens when a step overwrites an existing state key.
#   warn   - log a structured warning (default)
#   strict - raise an error and fail the step
#   allow  - silently allow overwrites
# overwrite_policy: warn

# ─── LLM providers ───────────────────────────────────────────────────
# API keys are resolved from environment variables — never store keys here.
# Uncomment and configure providers you intend to use.
#
# default_llm_provider: openai    # used when model has no provider/ prefix
# default_model: gpt-4o           # used by agent steps that don't specify a model
#
# llm:
#   providers:
#     openai:
#       api_key_env: OPENAI_API_KEY
#       models:
#         gpt-4:
#           temperature: 0.2
#           max_tokens: 4096
#         gpt-4o:
#           temperature: 0.1
#           max_tokens: 8192
#     anthropic:
#       api_key_env: ANTHROPIC_API_KEY
#       models:
#         claude-3-opus:
#           temperature: 0.3
#           max_tokens: 4096
#     gemini:
#       api_key_env: GEMINI_API_KEY
#       models:
#         gemini-2.5-flash:
#           temperature: 0.2
#           max_tokens: 8192
#     local:
#       api_key_env: LOCAL_LLM_KEY
#       base_url: http://localhost:8080/v1
#       models:
#         llama-3:
#           temperature: 0.5
#           max_tokens: 2048
#     mock:
#       api_key_env: ANY
#       models:
#         mock-model:
#           temperature: 0.0
#           max_tokens: 1024
#   limits:
#     rate_limit_rpm: 0                 # 0 disables global request throttling
#     max_requests_per_run: 0           # 0 disables run request cap
#     max_total_tokens_per_run: 0       # 0 disables run token cap
#     max_cost_usd_per_run: 0.0         # 0 disables run cost cap
#     pricing_usd_per_1k_tokens:
#       openai/gpt-4o:
#         input: 0.005
#         output: 0.015
#       openai/*:
#         input: 0.003
#         output: 0.006

# ─── Memory ───────────────────────────────────────────────────────────
# Working memory: ephemeral per-run scratch space.
# memory:
#   working:
#     max_entries: 50            # sliding window size for context entries
#     max_scratch_bytes: 256000  # byte budget for scratch key-value store

# ─── Shell tool restrictions ──────────────────────────────────────────
# Regex patterns matched against the first token (program name) of commands.
# Denylist is checked first.
# shell:
#   allowlist:
#     - python
#     - git
#     - npm
#   denylist:
#     - rm
#     - sudo
#     - chmod

# ─── Logging ──────────────────────────────────────────────────────────
# logging:
#   level: info               # debug | info | warning | error
#   format: json              # json | text
"""

EXAMPLE_AGENT_DEFINITION = """# Agent definition — describes an LLM-backed agent.
# Referenced from workflow steps via `type: agent` + `agent: summarizer`.
schema_version: v1

agent:
  id: summarizer
  version: v1
  description: "Summarizes an issue and calls out likely root causes"
  system: "You are a senior support engineer. Be concise and actionable."
  strategy: single              # single | react | custom
  output_key: summary           # key name for the agent's text output
  tools:
    - tools.echo
  temperature: 0.3
  max_tokens: 256
  pipeline:
    - id: main
      type: model
      prompt: |
        Summarize the issue in 2-3 sentences and call out likely root causes.

        Issue: {{ inputs.issue }}
"""

EXAMPLE_FIXER_DEFINITION = """# Agent definition — proposes fixes for issues.
# Referenced from workflow steps via `type: agent` + `agent: fixer`.
schema_version: v1

agent:
  id: fixer
  version: v1
  description: "Proposes actionable fixes for issues based on a summary and priority"
  system: "You are a senior software engineer specializing in incident response."
  strategy: single              # single | react | custom
  output_key: next_steps        # key name for the agent's text output
  tools:
    - tools.echo
  temperature: 0.4
  max_tokens: 256
  pipeline:
    - id: main
      type: model
      prompt: |
        Given this issue and its summary, propose concrete next steps to fix it.

        Issue: {{ inputs.issue }}
        Summary: {{ inputs.summary }}

        Respond with a numbered list of actionable steps a developer should take.
"""


# [Pain Point Solved] #10 Rebuild Same Infra Every Project: One command scaffolds
#   the full project structure — workflows/, tools/, agents/, functions/, runtime.yaml.
#   No more copy-pasting from the last project with its bugs.
def _init_project(target_dir: str) -> None:
    """Create minimal project scaffold in target directory.

    This intentionally creates only the base structure needed to start coding:
    directories, ``runtime.yaml``, ``.env``, and ``runtime.db``.
    """
    workflows_dir = os.path.join(target_dir, "workflows")
    tools_dir = os.path.join(target_dir, "tools")
    agents_dir = os.path.join(target_dir, "agents")
    functions_dir = os.path.join(target_dir, "functions")

    os.makedirs(workflows_dir, exist_ok=True)
    os.makedirs(tools_dir, exist_ok=True)
    os.makedirs(agents_dir, exist_ok=True)
    os.makedirs(functions_dir, exist_ok=True)
    _scaffold_test_layout(target_dir)

    runtime_yaml_path = os.path.join(target_dir, "runtime.yaml")
    if not os.path.exists(runtime_yaml_path):
        with open(runtime_yaml_path, "w", encoding="utf-8") as f:
            f.write(RUNTIME_YAML_TEMPLATE)

    env_path = os.path.join(target_dir, ".env")
    if not os.path.exists(env_path):
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("")

    runtime_db_path = os.path.join(target_dir, "runtime.db")
    if not os.path.exists(runtime_db_path):
        with open(runtime_db_path, "a", encoding="utf-8"):
            pass


def _scaffold_test_layout(target_dir: str) -> None:
    """Create per-domain test folders and lightweight readmes."""
    for scope, rel_dirs in _TEST_SCOPE_DIRS.items():
        if scope == "all":
            continue
        for rel_dir in rel_dirs:
            abs_dir = os.path.join(target_dir, rel_dir)
            os.makedirs(abs_dir, exist_ok=True)
            readme_path = os.path.join(abs_dir, "README.md")
            if not os.path.exists(readme_path):
                with open(readme_path, "w", encoding="utf-8") as f:
                    f.write(_TEST_README_TEMPLATE.format(domain=scope))

    tools_spec = os.path.join(target_dir, "tools", "tests", "tool_tests.yaml")
    if not os.path.exists(tools_spec):
        with open(tools_spec, "w", encoding="utf-8") as f:
            f.write(_TOOL_TEST_TEMPLATE)

    functions_spec = os.path.join(target_dir, "functions", "tests", "function_tests.yaml")
    if not os.path.exists(functions_spec):
        with open(functions_spec, "w", encoding="utf-8") as f:
            f.write(_FUNCTION_TEST_TEMPLATE)


def _collect_test_files(project_root: str, scope: str) -> List[str]:
    """Collect test_*.py files for the requested test scope."""
    files: List[str] = []
    for rel_dir in _TEST_SCOPE_DIRS[scope]:
        abs_dir = os.path.join(project_root, rel_dir)
        if not os.path.isdir(abs_dir):
            continue
        for root, _, names in os.walk(abs_dir):
            for name in sorted(names):
                if name.startswith("test_") and name.endswith(".py"):
                    files.append(os.path.join(root, name))
    return sorted(files)


def _filter_test_files(test_files: List[str], project_root: str, targets: List[str]) -> List[str]:
    """Filter test files by target tokens against file name/path."""
    if not targets:
        return list(test_files)
    tokens = [t.strip().lower() for t in targets if t.strip()]
    if not tokens:
        return list(test_files)

    matched: List[str] = []
    for file_path in test_files:
        rel = os.path.relpath(file_path, project_root).lower()
        stem = os.path.splitext(os.path.basename(file_path))[0].lower()
        if any(token in rel or token in stem for token in tokens):
            matched.append(file_path)
    return matched


def _run_project_tests(
    project_root: str,
    *,
    scope: str,
    targets: List[str],
    pytest_args: Optional[List[str]] = None,
) -> int:
    """Run scoped project tests via pytest."""
    if not os.path.isdir(project_root):
        raise SystemExit(f"Project path does not exist: {project_root}")

    discovered = _collect_test_files(project_root, scope)
    selected = _filter_test_files(discovered, project_root, targets)
    run_tool_specs = scope in ("tools", "all")
    run_function_specs = scope in ("functions", "all")
    tool_summary = {
        "spec_files": 0,
        "total_cases": 0,
        "selected_cases": 0,
        "failed_cases": 0,
        "parse_errors": 0,
    }
    function_summary = {
        "spec_files": 0,
        "total_cases": 0,
        "selected_cases": 0,
        "failed_cases": 0,
        "parse_errors": 0,
    }

    if run_tool_specs:
        tools_dir = _resolve_tools_dir_for_testing(project_root)
        tool_summary = _run_tool_spec_tests(project_root, tools_dir=tools_dir, targets=targets)

    if run_function_specs:
        functions_dir = _resolve_functions_dir_for_testing(project_root)
        function_summary = _run_function_spec_tests(
            project_root,
            functions_dir=functions_dir,
            targets=targets,
        )

    if targets and not selected and tool_summary["selected_cases"] == 0 and function_summary["selected_cases"] == 0:
        joined = ", ".join(targets)
        print(f"No test files, tool test cases, or function test cases matched targets: {joined}")
        return 1

    if not discovered and tool_summary["spec_files"] == 0 and function_summary["spec_files"] == 0:
        print(f"No test files found for scope '{scope}'.")
        return 0

    code = 1 if (
        tool_summary["failed_cases"] > 0
        or tool_summary["parse_errors"] > 0
        or function_summary["failed_cases"] > 0
        or function_summary["parse_errors"] > 0
    ) else 0
    if selected:
        code = max(code, _run_pytest_files(project_root, scope=scope, rel_files=[os.path.relpath(path, project_root) for path in selected], pytest_args=pytest_args))

    return code


def _run_pytest_files(
    project_root: str,
    *,
    scope: str,
    rel_files: List[str],
    pytest_args: Optional[List[str]] = None,
) -> int:
    """Run a set of relative test files through pytest."""
    cmd = [sys.executable, "-m", "pytest", *rel_files]
    if pytest_args:
        cmd.extend(pytest_args)

    print(f"Running {len(rel_files)} test file(s) in scope '{scope}'")
    result = subprocess.run(cmd, cwd=project_root, check=False)
    return int(result.returncode)


def _resolve_tools_dir_for_testing(project_root: str) -> str:
    """Resolve tools_dir from runtime config when available; fallback to tools/."""
    runtime_path = os.path.join(project_root, "runtime.yaml")
    if not os.path.exists(runtime_path):
        return os.path.join(project_root, "tools")

    try:
        cfg = load_config(runtime_path)
    except Exception:
        return os.path.join(project_root, "tools")

    return _resolve_project_path(project_root, cfg.tools_dir)


def _collect_tool_test_spec_files(project_root: str) -> List[str]:
    """Collect YAML tool-test specification files from tools/tests."""
    tests_dir = os.path.join(project_root, "tools", "tests")
    if not os.path.isdir(tests_dir):
        return []

    files: List[str] = []
    for root, _, names in os.walk(tests_dir):
        for name in sorted(names):
            lower_name = name.lower()
            if lower_name in _TOOL_TEST_SPEC_FILENAMES or lower_name.endswith(_TOOL_TEST_SPEC_SUFFIXES):
                files.append(os.path.join(root, name))
    return sorted(files)


def _collect_function_test_spec_files(project_root: str) -> List[str]:
    """Collect YAML function-test specification files from functions/tests."""
    tests_dir = os.path.join(project_root, "functions", "tests")
    if not os.path.isdir(tests_dir):
        return []

    files: List[str] = []
    for root, _, names in os.walk(tests_dir):
        for name in sorted(names):
            lower_name = name.lower()
            if lower_name in _FUNCTION_TEST_SPEC_FILENAMES or lower_name.endswith(_FUNCTION_TEST_SPEC_SUFFIXES):
                files.append(os.path.join(root, name))
    return sorted(files)


def _load_tool_test_cases(spec_path: str) -> List[Dict[str, Any]]:
    """Parse a tool-test spec file and return normalized case dictionaries."""
    with open(spec_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError("spec root must be a mapping")

    if "tool_tests" in raw:
        raw_cases = raw["tool_tests"]
        if not isinstance(raw_cases, list):
            raise ValueError("tool_tests must be a list")
    elif "tool_test" in raw:
        raw_cases = [raw["tool_test"]]
    else:
        return []

    cases: List[Dict[str, Any]] = []
    for idx, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"case #{idx} must be a mapping")

        case_id = raw_case.get("id")
        tool_name = raw_case.get("tool")
        case_input = raw_case.get("input", {})
        assertions = raw_case.get("assert", [])

        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"case #{idx} requires a non-empty string id")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError(f"case '{case_id}' requires a non-empty string tool")
        if not isinstance(case_input, dict):
            raise ValueError(f"case '{case_id}' field 'input' must be a mapping")
        if not isinstance(assertions, list):
            raise ValueError(f"case '{case_id}' field 'assert' must be a list")

        cases.append({
            "id": case_id,
            "tool": tool_name,
            "input": case_input,
            "assert": assertions,
        })

    return cases


def _load_function_test_cases(spec_path: str) -> List[Dict[str, Any]]:
    """Parse a function-test spec file and return normalized case dictionaries."""
    with open(spec_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError("spec root must be a mapping")

    if "function_tests" in raw:
        raw_cases = raw["function_tests"]
        if not isinstance(raw_cases, list):
            raise ValueError("function_tests must be a list")
    elif "function_test" in raw:
        raw_cases = [raw["function_test"]]
    else:
        return []

    cases: List[Dict[str, Any]] = []
    for idx, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"case #{idx} must be a mapping")

        case_id = raw_case.get("id")
        function_ref = raw_case.get("function")
        case_input = raw_case.get("input", {})
        assertions = raw_case.get("assert", [])

        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError(f"case #{idx} requires a non-empty string id")
        if not isinstance(function_ref, str) or not function_ref.strip():
            raise ValueError(f"case '{case_id}' requires a non-empty string function")
        if not isinstance(case_input, dict):
            raise ValueError(f"case '{case_id}' field 'input' must be a mapping")
        if not isinstance(assertions, list):
            raise ValueError(f"case '{case_id}' field 'assert' must be a list")

        cases.append({
            "id": case_id,
            "function": function_ref,
            "input": case_input,
            "assert": assertions,
        })

    return cases


def _value_contains(actual: Any, expected: Any) -> bool:
    """Return True when expected is contained in actual for supported types."""
    if isinstance(actual, dict) and isinstance(expected, dict):
        for key, value in expected.items():
            if key not in actual:
                return False
            if not _value_contains(actual[key], value):
                return False
        return True

    if isinstance(actual, list):
        if isinstance(expected, list):
            return all(item in actual for item in expected)
        return expected in actual

    if isinstance(actual, str) and isinstance(expected, str):
        return expected in actual

    return actual == expected


def _resolve_assert_path(payload: Dict[str, Any], path: str) -> tuple[bool, Any]:
    """Resolve dotted assertion path from a result payload."""
    if not path:
        return False, None

    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return False, None

    return True, current


def _evaluate_case_assertions(payload: Dict[str, Any], assertions: List[Dict[str, Any]]) -> List[str]:
    """Evaluate deterministic assertions and return human-readable failures."""
    failures: List[str] = []
    if not assertions:
        assertions = [{"path": "success", "equals": True}]

    for idx, raw_assert in enumerate(assertions, start=1):
        if not isinstance(raw_assert, dict):
            failures.append(f"assert[{idx}] must be a mapping")
            continue

        path = raw_assert.get("path")
        if not isinstance(path, str) or not path.strip():
            failures.append(f"assert[{idx}] requires a non-empty string path")
            continue

        operations = [op for op in ("equals", "contains", "exists") if op in raw_assert]
        if len(operations) != 1:
            failures.append(
                f"assert[{idx}] path '{path}' must define exactly one of equals/contains/exists"
            )
            continue

        op = operations[0]
        exists, value = _resolve_assert_path(payload, path)
        expected = raw_assert[op]

        if op == "exists":
            if not isinstance(expected, bool):
                failures.append(f"assert[{idx}] path '{path}' exists must be boolean")
                continue
            if exists != expected:
                failures.append(
                    f"assert[{idx}] path '{path}' expected exists={expected}, got exists={exists}"
                )
            continue

        if not exists:
            failures.append(f"assert[{idx}] path '{path}' not found")
            continue

        if op == "equals" and value != expected:
            failures.append(
                f"assert[{idx}] path '{path}' expected {expected!r}, got {value!r}"
            )
            continue

        if op == "contains" and not _value_contains(value, expected):
            failures.append(
                f"assert[{idx}] path '{path}' expected to contain {expected!r}, got {value!r}"
            )

    return failures


def _resolve_functions_dir_for_testing(project_root: str) -> str:
    """Resolve functions_dir from runtime config when available; fallback to functions/."""
    runtime_path = os.path.join(project_root, "runtime.yaml")
    if not os.path.exists(runtime_path):
        return os.path.join(project_root, "functions")

    try:
        cfg = load_config(runtime_path)
    except Exception:
        return os.path.join(project_root, "functions")

    return _resolve_project_path(project_root, cfg.functions_dir)


def _build_tool_test_registry(project_root: str, tools_dir: str) -> ToolRegistry:
    """Build a deterministic tool registry for tool-test execution."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(FileTool(root=project_root))
    register_discovered_tools(registry, tools_dir)
    return registry


def _matches_tool_case_targets(rel_path: str, case_id: str, tool_name: str, targets: List[str]) -> bool:
    """Return True when a tool test case matches any target token."""
    if not targets:
        return True
    haystacks = (rel_path.lower(), case_id.lower(), tool_name.lower())
    tokens = [token.strip().lower() for token in targets if token.strip()]
    return any(any(token in hay for hay in haystacks) for token in tokens)


def _run_tool_spec_tests(project_root: str, *, tools_dir: str, targets: List[str]) -> Dict[str, int]:
    """Execute YAML tool-test specs and return summary counters."""
    spec_files = _collect_tool_test_spec_files(project_root)
    if not spec_files:
        return {
            "spec_files": 0,
            "total_cases": 0,
            "selected_cases": 0,
            "failed_cases": 0,
            "parse_errors": 0,
        }

    registry = _build_tool_test_registry(project_root, tools_dir)

    total_cases = 0
    selected_cases = 0
    failed_cases = 0
    parse_errors = 0

    print(f"Discovered {len(spec_files)} tool test spec file(s)")

    for spec_path in spec_files:
        rel_spec_path = os.path.relpath(spec_path, project_root)
        try:
            cases = _load_tool_test_cases(spec_path)
        except Exception as exc:
            print(f"  ✗ {rel_spec_path}: failed to parse ({exc})")
            parse_errors += 1
            continue

        if not cases:
            continue

        for case in cases:
            total_cases += 1
            case_id = case["id"]
            tool_name = case["tool"]

            if not _matches_tool_case_targets(rel_spec_path, case_id, tool_name, targets):
                continue

            selected_cases += 1
            input_payload = case["input"]
            assertions = case["assert"]

            try:
                tool = registry.get(tool_name)
            except Exception as exc:
                failed_cases += 1
                print(f"  ✗ {case_id}: tool lookup failed for '{tool_name}' ({exc})")
                continue

            context = RuntimeContext(
                run_id="tool-test",
                step_id=case_id,
                state={"inputs": input_payload},
                logger=None,
            )

            try:
                result = asyncio.run(tool.execute(input_payload, context))
            except Exception as exc:
                failed_cases += 1
                print(f"  ✗ {case_id}: tool execution raised {exc}")
                continue

            payload = {
                "success": getattr(result, "success", None),
                "output": getattr(result, "output", None),
                "error": getattr(result, "error", None),
                "metadata": getattr(result, "metadata", None),
            }
            failures = _evaluate_case_assertions(payload, assertions)
            if failures:
                failed_cases += 1
                print(f"  ✗ {case_id}: {len(failures)} assertion failure(s)")
                for failure in failures:
                    print(f"    - {failure}")
                continue

            print(f"  ✓ {case_id}")

    print(
        "Tool spec summary: "
        f"selected={selected_cases} "
        f"failed={failed_cases} "
        f"parse_errors={parse_errors}"
    )

    return {
        "spec_files": len(spec_files),
        "total_cases": total_cases,
        "selected_cases": selected_cases,
        "failed_cases": failed_cases,
        "parse_errors": parse_errors,
    }


def _matches_function_case_targets(rel_path: str, case_id: str, function_ref: str, targets: List[str]) -> bool:
    """Return True when a function test case matches any target token."""
    if not targets:
        return True
    haystacks = (rel_path.lower(), case_id.lower(), function_ref.lower())
    tokens = [token.strip().lower() for token in targets if token.strip()]
    return any(any(token in hay for hay in haystacks) for token in tokens)


def _clear_function_module_cache() -> None:
    """Clear cached runtime function modules to avoid stale imports between runs."""
    prefix = "_runtime_functions."
    to_remove = [name for name in sys.modules if name.startswith(prefix)]
    for name in to_remove:
        del sys.modules[name]


def _run_function_spec_tests(project_root: str, *, functions_dir: str, targets: List[str]) -> Dict[str, int]:
    """Execute YAML function-test specs and return summary counters."""
    spec_files = _collect_function_test_spec_files(project_root)
    if not spec_files:
        return {
            "spec_files": 0,
            "total_cases": 0,
            "selected_cases": 0,
            "failed_cases": 0,
            "parse_errors": 0,
        }

    total_cases = 0
    selected_cases = 0
    failed_cases = 0
    parse_errors = 0

    # Function resolver caches discovered modules; clear cache for deterministic
    # test execution when files may change between invocations.
    _clear_function_module_cache()

    print(f"Discovered {len(spec_files)} function test spec file(s)")

    for spec_path in spec_files:
        rel_spec_path = os.path.relpath(spec_path, project_root)
        try:
            cases = _load_function_test_cases(spec_path)
        except Exception as exc:
            print(f"  ✗ {rel_spec_path}: failed to parse ({exc})")
            parse_errors += 1
            continue

        if not cases:
            continue

        for case in cases:
            total_cases += 1
            case_id = case["id"]
            function_ref = case["function"]

            if not _matches_function_case_targets(rel_spec_path, case_id, function_ref, targets):
                continue

            selected_cases += 1
            input_payload = case["input"]
            assertions = case["assert"]

            try:
                function_callable = resolve_function(function_ref, functions_dir)
            except Exception as exc:
                failed_cases += 1
                print(f"  ✗ {case_id}: function lookup failed for '{function_ref}' ({exc})")
                continue

            try:
                output = function_callable(input_payload)
                if asyncio.iscoroutine(output):
                    output = asyncio.run(output)
                payload = {
                    "success": True,
                    "output": output,
                    "error": None,
                    "metadata": None,
                }
            except Exception as exc:
                payload = {
                    "success": False,
                    "output": None,
                    "error": str(exc),
                    "metadata": None,
                }

            failures = _evaluate_case_assertions(payload, assertions)
            if failures:
                failed_cases += 1
                print(f"  ✗ {case_id}: {len(failures)} assertion failure(s)")
                for failure in failures:
                    print(f"    - {failure}")
                continue

            print(f"  ✓ {case_id}")

    print(
        "Function spec summary: "
        f"selected={selected_cases} "
        f"failed={failed_cases} "
        f"parse_errors={parse_errors}"
    )

    return {
        "spec_files": len(spec_files),
        "total_cases": total_cases,
        "selected_cases": selected_cases,
        "failed_cases": failed_cases,
        "parse_errors": parse_errors,
    }


def _scaffold_starter_files(target_dir: str) -> None:
    """Create starter workflow/function/tool files used by quickstart."""
    workflows_dir = os.path.join(target_dir, "workflows")
    tools_dir = os.path.join(target_dir, "tools")
    functions_dir = os.path.join(target_dir, "functions")

    os.makedirs(workflows_dir, exist_ok=True)
    os.makedirs(tools_dir, exist_ok=True)
    os.makedirs(functions_dir, exist_ok=True)

    _scaffold_file(os.path.join(workflows_dir, "example.yaml"), EXAMPLE_WORKFLOW)
    _scaffold_file(os.path.join(functions_dir, "stubs.py"), EXAMPLE_FUNCTION)
    _scaffold_file(os.path.join(tools_dir, "example_tool.py"), EXAMPLE_TOOL)

    _scaffold_quickstart_samples(target_dir)


def _build_docs_index(docs_root: Path) -> int:
    """Build content.js index for markdown files under docs_root.

    Also generates a standalone JSON manifest for site discovery.
    """
    skip = {"content.js", "app.js", "styles.css", "build-content.py", "mermaid.min.js"}
    docs: Dict[str, str] = {}
    for path in sorted(docs_root.rglob("*.md")):
        if path.name in skip:
            continue
        rel = path.relative_to(docs_root).as_posix()
        docs[rel] = path.read_text(encoding="utf-8")

    # Generate content.js for static file:// usage
    out_path = docs_root / "content.js"
    out_path.write_text("window.DOCS = " + json.dumps(docs) + ";\n", encoding="utf-8")
    
    # Generate docs-manifest.json for dynamic server-side discovery
    manifest_path = docs_root / "docs-manifest.json"
    manifest_path.write_text(json.dumps(docs), encoding="utf-8")
    
    return len(docs)


def _build_export_runtime_yaml(
    runtime_path: str,
    *,
    include_tools: bool,
) -> Dict[str, Any]:
    """Load runtime.yaml and normalize paths for export portability."""
    try:
        with open(runtime_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    normalized = _strip_secret_keys(raw)
    if not isinstance(normalized, dict):
        normalized = {}

    normalized["workflows_dir"] = "workflows"
    normalized["agents_dir"] = "agents"
    normalized["functions_dir"] = "functions"
    if include_tools:
        normalized["tools_dir"] = "tools"
    else:
        normalized.pop("tools_dir", None)

    db_path = normalized.get("db_path")
    if isinstance(db_path, str) and os.path.isabs(db_path):
        normalized["db_path"] = "runtime.db"

    return normalized


def _run_export(
    project_root: str,
    *,
    output_path: Optional[str],
    include_tools: bool,
) -> int:
    """Export a project bundle ready to run on another runtime install."""
    if not os.path.isdir(project_root):
        raise SystemExit(f"Project path does not exist: {project_root}")

    runtime_path = os.path.join(project_root, "runtime.yaml")
    if not os.path.exists(runtime_path):
        raise SystemExit(f"No runtime.yaml found at {runtime_path}")

    cfg = load_config(runtime_path)
    workflows_dir = _resolve_project_path(project_root, cfg.workflows_dir)
    agents_dir = _resolve_project_path(project_root, cfg.agents_dir)
    functions_dir = _resolve_project_path(project_root, cfg.functions_dir)
    tools_dir = _resolve_project_path(project_root, cfg.tools_dir) if include_tools else ""
    prompts_dir = os.path.join(project_root, "prompts")

    if not output_path:
        project_name = os.path.basename(os.path.abspath(project_root)) or "agentic-project"
        output_path = os.path.join(
            project_root, f"{project_name}.agentic-export.tar.gz"
        )

    export_runtime = _build_export_runtime_yaml(
        runtime_path,
        include_tools=include_tools,
    )

    manifest = {
        "schema_version": "v1",
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "includes": {
            "workflows": True,
            "agents": True,
            "functions": True,
            "tools": include_tools,
            "prompts": os.path.isdir(prompts_dir),
        },
    }

    with tarfile.open(output_path, "w:gz") as tar:
        _write_tar_text(
            tar,
            "runtime.yaml",
            yaml.safe_dump(export_runtime, sort_keys=False),
        )
        _write_tar_text(
            tar,
            "export-manifest.json",
            json.dumps(manifest, indent=2),
        )

        _add_directory_to_tar(tar, workflows_dir, "workflows")
        _add_directory_to_tar(tar, agents_dir, "agents")
        _add_directory_to_tar(tar, functions_dir, "functions")
        if include_tools:
            _add_directory_to_tar(tar, tools_dir, "tools")
        if os.path.isdir(prompts_dir):
            _add_directory_to_tar(tar, prompts_dir, "prompts")

    print(f"Exported bundle: {output_path}")
    contents = ["runtime.yaml", "workflows/", "agents/", "functions/"]
    if include_tools:
        contents.append("tools/")
    if os.path.isdir(prompts_dir):
        contents.append("prompts/")
    print("Bundle contents: " + " + ".join(contents))
    print("Note: .env is intentionally excluded; set API keys in the target environment.")
    return 0


def _run_import(
    bundle_path: str,
    *,
    target_dir: str,
    run_workflow: Optional[str],
) -> int:
    """Import a portable bundle into a project directory and optionally run a workflow."""
    if not os.path.isfile(bundle_path):
        raise SystemExit(f"Bundle not found: {bundle_path}")

    os.makedirs(target_dir, exist_ok=True)

    with tarfile.open(bundle_path, "r:*") as tar:
        _safe_extract_tar(tar, target_dir)

    runtime_path = os.path.join(target_dir, "runtime.yaml")
    if not os.path.exists(runtime_path):
        raise SystemExit(f"Import failed: runtime.yaml not found in {target_dir}")

    print(f"Imported bundle to: {target_dir}")

    if not run_workflow:
        example_workflow = os.path.join(target_dir, "workflows", "example.yaml")
        suggestion = "workflows/example.yaml" if os.path.exists(example_workflow) else "<workflow.yaml>"
        print("Next steps:")
        print(f"  ai run {suggestion}")
        print("Note: set API keys in your environment or .env before running.")
        return 0

    cwd = os.getcwd()
    try:
        os.chdir(target_dir)
        return run_cli(["run", run_workflow])
    finally:
        os.chdir(cwd)






def _normalize_workflow_inputs(raw_inputs: Any) -> List[Dict[str, Any]]:
    """Normalize workflow inputs declarations into a predictable list."""
    normalized: List[Dict[str, Any]] = []
    if isinstance(raw_inputs, list):
        for name in raw_inputs:
            if isinstance(name, str) and name.strip():
                normalized.append(
                    {
                        "name": name.strip(),
                        "required": True,
                        "default": None,
                        "description": "",
                    }
                )
        return normalized

    if not isinstance(raw_inputs, dict):
        return normalized

    for name, spec in raw_inputs.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if isinstance(spec, dict):
            normalized.append(
                {
                    "name": name,
                    "required": bool(spec.get("required", True)),
                    "default": spec.get("default"),
                    "description": str(spec.get("description", "") or ""),
                }
            )
        else:
            normalized.append(
                {
                    "name": name,
                    "required": True,
                    "default": None,
                    "description": "",
                }
            )
    return normalized


def _generate_workflow_reference(project_root: Path) -> Path:
    """Generate documentation/guide/workflow-reference-generated.md from workflow YAML."""
    workflows_root = project_root / "workflows"
    if not workflows_root.is_dir():
        # Repository-local fallback: keep docs generation working after moving
        # bundled sample project files under examples/reference_project.
        fallback = project_root / "examples" / "reference_project" / "workflows"
        if fallback.is_dir():
            workflows_root = fallback
    output_path = project_root / "documentation" / "guide" / "workflow-reference-generated.md"
    os.makedirs(output_path.parent, exist_ok=True)

    sections: List[str] = [
        "# Workflow Reference (Generated)",
        "",
        "This file is generated by `ai docs` from YAML under `workflows/`.",
        "Do not edit manually.",
        "",
    ]

    workflow_files: List[Path] = []
    if workflows_root.is_dir():
        workflow_files = sorted(list(workflows_root.rglob("*.yaml")) + list(workflows_root.rglob("*.yml")))

    if not workflow_files:
        sections.append("No workflow files found.")
        sections.append("")
        output_path.write_text("\n".join(sections), encoding="utf-8")
        return output_path

    for wf_path in workflow_files:
        try:
            data = yaml.safe_load(wf_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            sections.append(f"## {wf_path.relative_to(project_root).as_posix()}")
            sections.append("")
            sections.append("Invalid YAML. Skipped.")
            sections.append("")
            continue

        if not isinstance(data, dict):
            continue

        workflow_meta = data.get("workflow") if isinstance(data.get("workflow"), dict) else {}
        workflow_id = workflow_meta.get("id") or wf_path.stem
        workflow_version = workflow_meta.get("version") or "v1"
        workflow_rel = wf_path.relative_to(project_root).as_posix()

        sections.append(f"## {workflow_id}@{workflow_version}")
        sections.append("")
        sections.append(f"Source: `{workflow_rel}`")
        sections.append("")

        normalized_inputs = _normalize_workflow_inputs(data.get("inputs", {}))
        sections.append("### Inputs")
        if normalized_inputs:
            for item in normalized_inputs:
                required_label = "required" if item["required"] else "optional"
                default_value = item.get("default")
                default_label = (
                    f", default={json.dumps(default_value, ensure_ascii=False)}"
                    if default_value is not None
                    else ""
                )
                description = f" - {item['description']}" if item.get("description") else ""
                sections.append(f"- `{item['name']}` ({required_label}{default_label}){description}")
        else:
            sections.append("- None declared")
        sections.append("")

        steps = data.get("steps", [])
        sections.append("### Steps")
        if isinstance(steps, list) and steps:
            for idx, step in enumerate(steps, start=1):
                if not isinstance(step, dict):
                    continue
                step_id = step.get("id", f"step_{idx}")
                step_type = step.get("type", "unknown")
                summary = f"{idx}. `{step_id}` (`{step_type}`)"
                if step_type == "agent" and step.get("agent"):
                    summary += f" - agent: `{step.get('agent')}`"
                elif step_type == "function" and step.get("function"):
                    summary += f" - function: `{step.get('function')}`"
                elif step_type == "tool" and step.get("tool"):
                    summary += f" - tool: `{step.get('tool')}`"
                sections.append(summary)

                next_rules = step.get("next", [])
                if isinstance(next_rules, list) and next_rules:
                    for rule in next_rules:
                        if not isinstance(rule, dict):
                            continue
                        if "when" in rule and "goto" in rule:
                            sections.append(
                                f"   - branch: when `{rule.get('when')}` -> `{rule.get('goto')}`"
                            )
                        elif "default" in rule:
                            sections.append(f"   - branch: default -> `{rule.get('default')}`")
        else:
            sections.append("- None")
        sections.append("")

    output_path.write_text("\n".join(sections), encoding="utf-8")
    return output_path


# -- Quickstart sample files -----------------------------------------------

_QS_TRIAGE_FUNCTIONS = '''\
"""Triage functions for the branching quickstart workflow.

Demonstrates deterministic classification and branching logic
without LLM calls. Used by workflows/branching_triage.yaml.

Signature: (inputs: dict) -> dict
"""


def classify_issue(inputs: dict) -> dict:
    """Classify an issue by severity based on keywords."""
    issue = (inputs.get("issue") or "").lower()
    if any(w in issue for w in ("down", "outage", "crash", "500", "data loss")):
        return {
            "severity": "critical",
            "reason": "Service impact detected",
            "summary": f"CRITICAL: {inputs.get(\'issue\', \'\')}",
        }
    if any(w in issue for w in ("slow", "timeout", "latency", "401", "degraded")):
        return {
            "severity": "high",
            "reason": "Performance degradation",
            "summary": f"HIGH: {inputs.get(\'issue\', \'\')}",
        }
    return {
        "severity": "low",
        "reason": "No immediate impact",
        "summary": f"LOW: {inputs.get(\'issue\', \'\')}",
    }


def handle_critical(inputs: dict) -> dict:
    """Format an escalation alert for critical issues."""
    issue = inputs.get("issue", "unknown issue")
    reason = inputs.get("reason", "")
    return {
        "action": "page_oncall",
        "message": f"ESCALATION: {issue} -- {reason}. Paging on-call engineer.",
    }


def handle_normal(inputs: dict) -> dict:
    """Format a log entry for non-critical issues."""
    issue = inputs.get("issue", "unknown issue")
    severity = inputs.get("severity", "unknown")
    return {
        "action": "log_ticket",
        "message": f"Logged: {issue} (severity: {severity}). Added to backlog.",
    }
'''

_QS_PIPELINE_FUNCTIONS = '''\
"""Data pipeline functions for the pipeline quickstart workflow.

Demonstrates a chain of pure data transformations without LLM calls.
Used by workflows/data_pipeline.yaml.

Signature: (inputs: dict) -> dict
"""


def parse_csv_row(inputs: dict) -> dict:
    """Parse a comma-separated string into named fields."""
    raw = inputs.get("data", "")
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) < 3:
        parts.extend([""] * (3 - len(parts)))
    return {
        "name": parts[0],
        "value": parts[1],
        "category": parts[2],
        "field_count": len(parts),
    }


def validate_record(inputs: dict) -> dict:
    """Validate parsed fields and coerce the value to a number."""
    errors = []
    name = inputs.get("name", "")
    value = inputs.get("value", "")
    if not name:
        errors.append("name is required")
    if not value:
        errors.append("value is required")
    try:
        numeric = float(value) if value else 0.0
    except ValueError:
        errors.append(f"value \\'{value}\\' is not numeric")
        numeric = 0.0
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "numeric_value": numeric,
        "name": name,
    }


def transform_record(inputs: dict) -> dict:
    """Normalize the value and build a display label."""
    name = inputs.get("name", "unknown")
    value = inputs.get("numeric_value", 0)
    category = inputs.get("category", "uncategorized")
    normalized = round(value / 100, 4) if value else 0
    label = f"{name} [{category}]"
    return {"label": label, "normalized": normalized, "original": value}


def format_report(inputs: dict) -> dict:
    """Produce a formatted text report from pipeline results."""
    label = inputs.get("label", "")
    normalized = inputs.get("normalized", 0)
    original = inputs.get("original", 0)
    valid = inputs.get("valid", False)
    status = "VALID" if valid else "INVALID"
    report = (
        "--- Data Pipeline Report ---\\n"
        f"  Record:     {label}\\n"
        f"  Original:   {original}\\n"
        f"  Normalized: {normalized}\\n"
        f"  Status:     {status}\\n"
        "----------------------------"
    )
    return {"report": report}
'''

_QS_RESEARCH_FUNCTIONS = '''\
"""Research helper functions for the multi-agent quickstart workflow.

Used by workflows/research.yaml alongside the researcher and advisor agents.

Signature: (inputs: dict) -> dict
"""


def format_brief(inputs: dict) -> dict:
    """Combine findings and recommendation into a formatted brief."""
    findings = inputs.get("findings", "No findings")
    recommendation = inputs.get("recommendation", "No recommendation")
    brief = (
        "=== RESEARCH BRIEF ===\\n\\n"
        f"FINDINGS:\\n{findings}\\n\\n"
        f"RECOMMENDATION:\\n{recommendation}\\n\\n"
        "======================"
    )
    return {"brief": brief}


def extract_action_items(inputs: dict) -> dict:
    """Count bullet/numbered items in the findings text."""
    findings = inputs.get("findings", "")
    lines = [line.strip() for line in findings.split("\\n") if line.strip()]
    count = len([
        line for line in lines
        if line and (line[0].isdigit() or line.startswith("-") or line.startswith("*"))
    ])
    return {"action_count": count, "status": "reviewed"}
'''

_QS_BRANCHING_WORKFLOW = """\
# Quickstart 2: Branching Triage
# Demonstrates: conditional branching, multiple function steps, no LLM required.
# Run: ai quickstart --sample branching
#   or: ai run workflows/branching_triage.yaml
#   or: ai run workflows/branching_triage.yaml -i issue="Server is slow under load"

schema_version: v1
workflow:
  id: branching_triage
  version: v1

inputs:
  issue:
    description: Issue text to triage
    default: "Production database is down, all API requests returning 500 errors"

on_error: fail_fast

steps:
  - id: classify
    type: function
    function: triage.classify_issue
    inputs:
      issue: inputs.issue
    next:
      - when: state.steps.classify.severity == "critical"
        goto: handle_critical
      - default: handle_normal

  - id: handle_critical
    type: function
    function: triage.handle_critical
    inputs:
      issue: inputs.issue
      reason: steps.classify.reason
    next:
      - default: echo_result

  - id: handle_normal
    type: function
    function: triage.handle_normal
    inputs:
      issue: inputs.issue
      severity: steps.classify.severity
    next:
      - default: echo_result

  - id: echo_result
    type: tool
    tool: tools.echo
    inputs:
      message: steps.classify.summary
"""

_QS_RESEARCH_WORKFLOW = """\
# Quickstart 3: Multi-Agent Research
# Demonstrates: two LLM agents collaborating, react strategy, agent-function-tool chain.
# Requires: LLM provider configured (run `ai config` first).
# Run: ai quickstart --sample research
#   or: ai run workflows/research.yaml
#   or: ai run workflows/research.yaml -i topic="Microservices vs monoliths"

schema_version: v1
workflow:
  id: research_report
  version: v1

inputs:
  topic:
    description: Topic to research
    default: "Impact of AI agents on software development productivity"

on_error: fail_fast

steps:
  - id: research
    type: agent
    agent: researcher
    inputs:
      topic: inputs.topic

  - id: advise
    type: agent
    agent: advisor
    inputs:
      findings: steps.research.findings

  - id: count_actions
    type: function
    function: research.extract_action_items
    inputs:
      findings: steps.research.findings

  - id: format
    type: function
    function: research.format_brief
    inputs:
      findings: steps.research.findings
      recommendation: steps.advise.recommendation

  - id: echo_brief
    type: tool
    tool: tools.echo
    inputs:
      message: steps.format.brief
"""

_QS_PIPELINE_WORKFLOW = """\
# Quickstart 4: Data Pipeline
# Demonstrates: pure function chain, data transformation, no LLM required.
# Run: ai quickstart --sample pipeline
#   or: ai run workflows/data_pipeline.yaml
#   or: ai run workflows/data_pipeline.yaml -i data="humidity, 85.2, weather"

schema_version: v1
workflow:
  id: data_pipeline
  version: v1

inputs:
  data:
    description: "Comma-separated record: name, value, category"
    default: "temperature, 72.5, sensor"

on_error: fail_fast

steps:
  - id: parse
    type: function
    function: pipeline.parse_csv_row
    inputs:
      data: inputs.data

  - id: validate
    type: function
    function: pipeline.validate_record
    inputs:
      name: steps.parse.name
      value: steps.parse.value

  - id: transform
    type: function
    function: pipeline.transform_record
    inputs:
      name: steps.validate.name
      numeric_value: steps.validate.numeric_value
      category: steps.parse.category

  - id: report
    type: function
    function: pipeline.format_report
    inputs:
      label: steps.transform.label
      normalized: steps.transform.normalized
      original: steps.transform.original
      valid: steps.validate.valid

  - id: echo_report
    type: tool
    tool: tools.echo
    inputs:
      message: steps.report.report
"""

_QS_RESEARCHER_AGENT = """\
schema_version: v1

agent:
  id: researcher
  version: v1
  description: "Researches a topic and produces structured key findings"
  system: "You are a research analyst. Identify key facts and structure your findings as a numbered list."
  strategy:
    type: react
    max_iterations: 3
  output_key: findings
  tools:
    - tools.echo
  temperature: 0.4
  max_tokens: 512
  pipeline:
    - id: main
      type: model
      prompt: |
        Research the following topic and identify 3-5 key findings.

        Topic: {{ inputs.topic }}

        Respond with a numbered list of findings.
"""

_QS_ADVISOR_AGENT = """\
schema_version: v1

agent:
  id: advisor
  version: v1
  description: "Provides a strategic recommendation based on research findings"
  system: "You are a strategic advisor. Based on research findings, provide a clear, actionable recommendation in 2-3 sentences."
  strategy: single
  output_key: recommendation
  tools:
    - tools.echo
  temperature: 0.3
  max_tokens: 256
  pipeline:
    - id: main
      type: model
      prompt: |
        Based on these research findings, provide one strategic recommendation.

        Findings: {{ inputs.findings }}

        Be specific and actionable.
"""


def _scaffold_file(path: str, content: str) -> None:
    """Write *content* to *path* if the file does not already exist."""
    if os.path.exists(path):
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _scaffold_quickstart_samples(target_dir: str) -> None:
    """Create additional quickstart sample files (idempotent)."""
    workflows_dir = os.path.join(target_dir, "workflows")
    functions_dir = os.path.join(target_dir, "functions")
    agents_dir = os.path.join(target_dir, "agents")

    os.makedirs(workflows_dir, exist_ok=True)
    os.makedirs(functions_dir, exist_ok=True)
    os.makedirs(agents_dir, exist_ok=True)

    _scaffold_file(os.path.join(agents_dir, "summarizer.yaml"), EXAMPLE_AGENT_DEFINITION)
    _scaffold_file(os.path.join(agents_dir, "fixer.yaml"), EXAMPLE_FIXER_DEFINITION)

    # quickstart2 — branching triage (no LLM)
    _scaffold_file(os.path.join(functions_dir, "triage.py"), _QS_TRIAGE_FUNCTIONS)
    _scaffold_file(os.path.join(workflows_dir, "branching_triage.yaml"), _QS_BRANCHING_WORKFLOW)

    # quickstart3 — multi-agent research (LLM)
    _scaffold_file(os.path.join(functions_dir, "research.py"), _QS_RESEARCH_FUNCTIONS)
    _scaffold_file(os.path.join(agents_dir, "researcher.yaml"), _QS_RESEARCHER_AGENT)
    _scaffold_file(os.path.join(agents_dir, "advisor.yaml"), _QS_ADVISOR_AGENT)
    _scaffold_file(os.path.join(workflows_dir, "research.yaml"), _QS_RESEARCH_WORKFLOW)

    # quickstart4 — data pipeline (no LLM)
    _scaffold_file(os.path.join(functions_dir, "pipeline.py"), _QS_PIPELINE_FUNCTIONS)
    _scaffold_file(os.path.join(workflows_dir, "data_pipeline.yaml"), _QS_PIPELINE_WORKFLOW)


# Factory functions — public API lives in defaults.py; aliased here for CLI use.
from .defaults import (
    default_tool_registry as _default_tool_registry,
    default_memory_manager as _default_memory_manager,
    default_llm_client as _default_llm_client,
    default_agent_registry as _default_agent_registry,
)


def _load_workflow_for_run(
    workflow_ref: str,
    workflows_dir: str = "workflows",
    functions_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve workflow from file path or id/version registry reference."""
    if os.path.exists(workflow_ref):
        return load_workflow(workflow_ref, functions_dir=functions_dir)

    ref = parse_workflow_reference(workflow_ref)
    registry = WorkflowRegistry.from_directory(workflows_dir)
    workflow = registry.get(ref.workflow_id, ref.version)

    # Workflows resolved by id/version come from registry parsing that does not
    # bind function callables. Re-parse stored YAML with functions_dir so
    # function steps have resolved callables like file-path runs do.
    if functions_dir:
        raw_yaml = workflow.get("workflow_yaml")
        if isinstance(raw_yaml, str) and raw_yaml.strip():
            return load_workflow_from_text(raw_yaml, functions_dir=functions_dir)

    return workflow


def _coerce_value(raw: str) -> Any:
    """Auto-coerce a CLI input string to its most likely Python type.

    Conversion order:
    1. ``true`` / ``false`` (case-insensitive) \u2192 bool
    2. Integer literal \u2192 int
    3. Float literal \u2192 float
    4. JSON array or object \u2192 parsed value
    5. Fallback \u2192 str (unchanged)
    """
    lower = raw.strip().lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    if raw.startswith(("{", "[")) and raw.endswith(("}", "]")):
        import json as _json
        try:
            return _json.loads(raw)
        except _json.JSONDecodeError:
            pass
    return raw


def _try_resolve_agent(
    ref: str,
    agents_dir: str = "agents",
) -> Optional[AgentDefinition]:
    """Try to resolve *ref* as an agent id from the agents/ directory.

    Returns an ``AgentDefinition`` if found, ``None`` otherwise
    (falls back to workflow resolution).
    """
    if not os.path.isdir(agents_dir):
        return None

    # Parse optional @version
    if "@" in ref:
        agent_id, _, version = ref.partition("@")
    else:
        agent_id = ref
        version = None

    for filename in os.listdir(agents_dir):
        if not filename.endswith((".yaml", ".yml")):
            continue
        filepath = os.path.join(agents_dir, filename)
        # Try definition format first (canonical)
        try:
            defn = load_agent_definition(filepath)
            if defn.agent_id == agent_id:
                if version is None or defn.version == version:
                    return defn
            continue
        except Exception as exc:
            # Only swallow "wrong agent" / "not an agent file" errors.
            # Log parse failures so users can diagnose broken YAML.
            import logging as _logging
            _logging.getLogger("agent_runtime").debug(
                "Could not load %s as definition: %s", filepath, exc,
            )
    return None


def _workflow_from_definition(defn: AgentDefinition, input_keys: list[str] | None = None) -> Dict[str, Any]:
    """Synthesize a minimal workflow dict from an AgentDefinition.

    Creates a single ``type: agent`` step so that ``ai run <agent_id>``
    works for definition-format agents that don't have a separate workflow file.

    Args:
        defn: The agent definition.
        input_keys: If provided, the step's input_spec maps each key from
            ``state.inputs.<key>`` so the agent receives clean inputs
            matching what its pipeline templates expect.
    """
    from .core import StepDefinition

    input_spec: Dict[str, Any] | None = None
    if input_keys:
        input_spec = {k: f"inputs.{k}" for k in input_keys}

    step = StepDefinition(
        step_id=defn.agent_id,
        step_type="agent",
        agent_id=defn.agent_id,
        agent_version=defn.version,
        input_spec=input_spec,
    )
    workflow_id = f"{defn.agent_id}_auto"
    return {
        "name": workflow_id,
        "workflow_id": workflow_id,
        "workflow_version": defn.version,
        "inputs": {},
        "steps": [step],
        "on_error": "fail_fast",
        "workflow_hash": "",
        "workflow_yaml": "",
        "workflow_steps": [step.step_id],
    }


def _build_input_state(
    raw_inputs: List[str], workflow_inputs: Dict[str, Any]
) -> Dict[str, Any]:
    """Parse ``-i key=value`` pairs and validate against the workflow input schema.

    Values are auto-coerced: ``true``/``false`` become booleans, numeric
    strings become int or float, and JSON-like values (arrays/objects) are
    parsed.  Plain strings are kept as-is.
    """
    provided: Dict[str, Any] = {}
    for item in raw_inputs:
        if "=" not in item:
            raise SystemExit(f"Invalid input format: {item!r}. Expected KEY=VALUE.")
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise SystemExit(f"Invalid input: empty key in {item!r}")
        provided[key] = _coerce_value(value)

    if not workflow_inputs:
        # No declared inputs — pass through as-is.
        return provided

    declared = set(workflow_inputs.keys())
    unknown = set(provided.keys()) - declared
    if unknown:
        raise SystemExit(
            f"Unknown inputs: {', '.join(sorted(unknown))}. "
            f"Declared inputs: {', '.join(sorted(declared))}"
        )

    result: Dict[str, Any] = {}
    for name, spec in workflow_inputs.items():
        if name in provided:
            result[name] = provided[name]
        elif spec.get("default") is not None:
            result[name] = spec["default"]
        elif spec.get("required", True):
            raise SystemExit(
                f"Missing required input: {name}. Provide it with: -i {name}=VALUE"
            )
    return result


def _run_setup_flow(
    project_root: str,
    *,
    provider: Optional[str],
    api_key_env: Optional[str],
    api_key: Optional[str],
    model: Optional[str],
    base_url: Optional[str],
    temperature: Optional[float],
    max_tokens: Optional[int],
    no_dotenv: bool,
    no_default: bool,
) -> Dict[str, Any]:
    """Function implementation."""
    runtime_path = os.path.join(project_root, "runtime.yaml")
    dotenv_path = os.path.join(project_root, ".env")

    if not os.path.exists(runtime_path):
        with open(runtime_path, "w", encoding="utf-8") as f:
            f.write(RUNTIME_YAML_TEMPLATE)

    chosen_provider = (provider or _prompt_value(
        "Default LLM provider (openai/anthropic/gemini/local)",
        default="openai",
    )).strip().lower()
    if chosen_provider not in ("openai", "anthropic", "gemini", "local"):
        raise SystemExit(f"Unsupported provider: {chosen_provider}")

    chosen_api_key_env = api_key_env or _DEFAULT_PROVIDER_ENV.get(chosen_provider, "")
    if not chosen_api_key_env:
        chosen_api_key_env = _prompt_value("API key env var name (e.g. OPENAI_API_KEY)")

    chosen_api_key = api_key
    if chosen_api_key is None:
        chosen_api_key = _prompt_value(
            f"Paste {chosen_api_key_env} (leave blank to skip)",
            secret=True,
        )

    write_dotenv = not no_dotenv
    if write_dotenv and chosen_api_key:
        write_dotenv = _prompt_yes_no(f"Write {chosen_api_key_env} to .env", default=True)
    if write_dotenv and chosen_api_key:
        _update_dotenv(dotenv_path, {chosen_api_key_env: chosen_api_key})
        print(f"Wrote {chosen_api_key_env} to {dotenv_path}")
    elif chosen_api_key and not write_dotenv:
        print(f"Skipped writing {chosen_api_key_env} to .env")

    model_default = _DEFAULT_PROVIDER_MODEL.get(chosen_provider)
    chosen_model = model or _prompt_value(
        "Default model id", default=model_default or ""
    )
    chosen_temperature = temperature if temperature is not None else 0.2
    chosen_max_tokens = max_tokens if max_tokens is not None else 4096

    chosen_base_url = base_url
    if chosen_provider == "local" and not chosen_base_url:
        chosen_base_url = _prompt_value(
            "Base URL for local provider",
            default=_DEFAULT_PROVIDER_BASE_URL.get("local", ""),
        )

    # Update runtime.yaml
    try:
        with open(runtime_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    if not no_default:
        raw["default_llm_provider"] = chosen_provider

    llm_block = raw.get("llm")
    if not isinstance(llm_block, dict):
        llm_block = {}
    providers_block = llm_block.get("providers")
    if not isinstance(providers_block, dict):
        providers_block = {}
    provider_block = providers_block.get(chosen_provider)
    if not isinstance(provider_block, dict):
        provider_block = {}

    provider_block["api_key_env"] = chosen_api_key_env
    if chosen_base_url:
        provider_block["base_url"] = chosen_base_url

    models_block = provider_block.get("models")
    if not isinstance(models_block, dict):
        models_block = {}
    if chosen_model:
        model_block = models_block.get(chosen_model)
        if not isinstance(model_block, dict):
            model_block = {}
        model_block["temperature"] = chosen_temperature
        model_block["max_tokens"] = chosen_max_tokens
        models_block[chosen_model] = model_block
    provider_block["models"] = models_block

    providers_block[chosen_provider] = provider_block
    llm_block["providers"] = providers_block
    if not no_default:
        llm_block["default_provider"] = chosen_provider
    raw["llm"] = llm_block

    if not no_default and chosen_model:
        raw["default_model"] = chosen_model

    with open(runtime_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, sort_keys=False)

    print(f"Updated {runtime_path}")
    if chosen_api_key and not write_dotenv:
        print(f"Remember to export {chosen_api_key_env} before running.")

    return {
        "provider": chosen_provider,
        "model": chosen_model,
        "api_key_env": chosen_api_key_env,
        "wrote_dotenv": bool(write_dotenv and chosen_api_key),
    }


def _run_onboard_flow(project_root: str) -> int:
    """Function implementation."""
    print("\nWelcome to ForrestRun.")
    print("This wizard sets up a project and your first LLM provider.\n")

    if not os.path.isdir(project_root):
        raise SystemExit(f"Project path does not exist: {project_root}")

    runtime_path = os.path.join(project_root, "runtime.yaml")
    needs_init = not os.path.exists(runtime_path)
    if needs_init:
        do_init = _prompt_yes_no("Initialize project structure here?", default=True)
        if do_init:
            _init_project(project_root)
            print(f"Initialized project at {project_root}")

    _load_dotenv(os.path.join(project_root, ".env"))

    setup_info = _run_setup_flow(
        project_root,
        provider=None,
        api_key_env=None,
        api_key=None,
        model=None,
        base_url=None,
        temperature=None,
        max_tokens=None,
        no_dotenv=False,
        no_default=False,
    )

    provider = setup_info["provider"]
    sample_path = None
    if provider == "gemini":
        sample_path = os.path.join(project_root, "workflows", "samples", "06_gemini_call.yaml")
    elif provider == "openai":
        sample_path = os.path.join(project_root, "workflows", "samples", "05_llm_call.yaml")

    if sample_path and os.path.exists(sample_path):
        do_run = _prompt_yes_no("Run a sample workflow now?", default=True)
        if do_run:
            print(f"\nRunning sample: {sample_path}\n")
            return run_cli(["run", sample_path])

    print("\nNext steps:")
    if sample_path:
        print(f"  - Run a sample: ai run {sample_path} -i issue=\"Login fails with 401\"")
    else:
        print("  - Configure a sample workflow for your provider and run it with `ai run`.")
    print("  - Inspect a run: ai inspect <run_id> --steps")
    print("  - Visualize: ai visualize <run_id> --html")
    return 0


def _normalize_quickstart_sample(sample: str) -> str:
    """Function implementation."""
    normalized = (sample or "starter").strip().lower().replace("_", "-")
    aliases = {
        "starter": "starter",
        "default": "starter",
        "example": "starter",
        "branching": "branching",
        "branching-triage": "branching",
        "triage": "branching",
        "research": "research",
        "multi-agent": "research",
        "multi-agent-research": "research",
        "pipeline": "pipeline",
        "data": "pipeline",
        "data-pipeline": "pipeline",
    }
    if normalized not in aliases:
        raise SystemExit(
            "Unsupported quickstart sample. "
            "Choose one of: starter, branching, research, pipeline."
        )
    return aliases[normalized]


def _run_quickstart(project_root: str, *, sample: str = "starter") -> int:
    """Function implementation."""
    sample_name = _normalize_quickstart_sample(sample)

    if sample_name != "starter":
        sample_config = {
            "branching": {
                "workflow": "branching_triage.yaml",
                "label": "branching triage",
                "needs_llm": False,
            },
            "research": {
                "workflow": "research.yaml",
                "label": "multi-agent research",
                "needs_llm": True,
            },
            "pipeline": {
                "workflow": "data_pipeline.yaml",
                "label": "data pipeline",
                "needs_llm": False,
            },
        }[sample_name]
        print(f"\nQuickstart sample: {sample_name}\n")
        return _run_quickstart_sample(
            project_root,
            sample_config["workflow"],
            sample_config["label"],
            needs_llm=sample_config["needs_llm"],
        )

    print("\nQuickstart (golden path): initialize, configure, and run starter workflow.\n")

    if not os.path.isdir(project_root):
        raise SystemExit(f"Project path does not exist: {project_root}")

    runtime_path = os.path.join(project_root, "runtime.yaml")
    needs_init = not os.path.exists(runtime_path)
    _init_project(project_root)
    if needs_init:
        print(f"Initialized project at {project_root}")

    _scaffold_starter_files(project_root)

    example_workflow = os.path.join(project_root, "workflows", "example.yaml")

    _load_dotenv(os.path.join(project_root, ".env"))

    _run_setup_flow(
        project_root,
        provider=None,
        api_key_env=None,
        api_key=None,
        model=None,
        base_url=None,
        temperature=None,
        max_tokens=None,
        no_dotenv=False,
        no_default=False,
    )

    # Load config to check credentials
    cfg = load_config(runtime_path)
    creds = cfg.llm_registry.check_credentials()
    has_creds = any(creds.values())

    if not has_creds:
        print("\n[!] No LLM API keys found in .env or environment.")
        print("No credentials configured; running no-key sample automatically (branching triage).")
        return _run_quickstart_sample(
            project_root,
            "branching_triage.yaml",
            "branching triage",
            needs_llm=False,
        )
    else:
        # We have creds, but let's ensure the default provider is set if not already
        if not cfg.llm_registry.default_provider:
            for p, has_key in creds.items():
                if has_key:
                    cfg.llm_registry.default_provider = p
                    break

    if not os.path.exists(example_workflow):
        fallback = os.path.join(project_root, "workflows", "samples", "01_linear_issue_summary.yaml")
        if os.path.exists(fallback):
            example_workflow = fallback
        else:
            print("No starter workflow found to run.")
            return 1

    print(f"\nRunning starter workflow: {os.path.basename(example_workflow)}\n")
    cwd = os.getcwd()
    try:
        os.chdir(project_root)
        res = run_cli(["run", example_workflow])
        if res == 0:
            print("\nQuickstart completed successfully.")
            print("Next commands:")
            print("  ai runs")
            print("  ai inspect <run_id> --steps")
            print("  ai visualize <run_id> --html")
        return res
    finally:
        os.chdir(cwd)


def _run_quickstart_sample(
    project_root: str,
    workflow_name: str,
    label: str,
    *,
    needs_llm: bool = False,
) -> int:
    """Scaffold project, optionally configure LLM, and run a sample workflow."""
    if not os.path.isdir(project_root):
        raise SystemExit(f"Project path does not exist: {project_root}")

    runtime_path = os.path.join(project_root, "runtime.yaml")
    needs_init = not os.path.exists(runtime_path)
    _init_project(project_root)
    if needs_init:
        print(f"Initialized project at {project_root}")

    _scaffold_quickstart_samples(project_root)

    _load_dotenv(os.path.join(project_root, ".env"))

    if needs_llm:
        _run_setup_flow(
            project_root,
            provider=None, api_key_env=None, api_key=None, model=None,
            base_url=None, temperature=None, max_tokens=None,
            no_dotenv=False, no_default=False,
        )

    workflow_path = os.path.join(project_root, "workflows", workflow_name)
    if not os.path.exists(workflow_path):
        print(f"Workflow not found: {workflow_path}")
        return 1

    print(f"\nRunning {label}: {workflow_path}\n")
    cwd = os.getcwd()
    try:
        os.chdir(project_root)
        return run_cli(["run", workflow_path])
    finally:
        os.chdir(cwd)


def _run_home_screen(project_root: str) -> int:
    """Function implementation."""
    print("\nForrestRun")
    print("Choose an action:\n")
    print("  1) Guided setup (recommended)")
    print("  2) Run a sample workflow")
    print("  3) Inspect a run")
    print("  4) Visualize a run")
    print("  5) Exit")
    choice = _prompt_int("Select", 1, 5, 1)

    if choice == 1:
        return _run_onboard_flow(project_root)
    if choice == 2:
        provider = _prompt_choice(
            "Which provider sample?",
            ["openai", "gemini", "anthropic", "custom"],
            "openai",
        ).lower()
        if provider == "custom":
            path = _prompt_value("Path to workflow YAML")
        else:
            filename = "05_llm_call.yaml" if provider == "openai" else "06_gemini_call.yaml"
            path = os.path.join(project_root, "workflows", "samples", filename)
        if not os.path.exists(path):
            print(f"Workflow not found: {path}")
            return 1
        return run_cli(["run", path])
    if choice == 3:
        run_id = _prompt_value("Run id")
        return run_cli(["inspect", run_id, "--steps"])
    if choice == 4:
        run_id = _prompt_value("Run id")
        return run_cli(["visualize", run_id, "--html"])
    return 0


def run_cli(argv: Optional[List[str]] = None) -> int:
    """Execute CLI command dispatch and return process exit code."""
    if argv is None and len(sys.argv) == 1:
        if sys.stdin.isatty():
            return _run_home_screen(os.path.abspath("."))
        print("No command provided. Run `ai --help` for usage.")
        return 2

    parser = argparse.ArgumentParser(prog="ai")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a new workflow project")
    init_parser.add_argument("--path", default=".", help="Target directory")

    quickstart_parser = subparsers.add_parser(
        "quickstart",
        help="Golden path: initialize, configure, and run your first workflow",
    )
    quickstart_parser.add_argument("--path", default=".", help="Project root")
    quickstart_parser.add_argument(
        "--sample",
        default="starter",
        help=(
            "Starter workflow to run. "
            "Options: starter (recommended), branching, research, pipeline"
        ),
    )

    config_parser = subparsers.add_parser(
        "config",
        help="Configure API keys and runtime settings",
    )
    config_parser.add_argument("--path", default=".", help="Project root (contains runtime.yaml)")
    config_parser.add_argument("--provider", choices=["openai", "anthropic", "gemini", "local"], help="LLM provider")
    config_parser.add_argument("--api-key-env", help="Env var name to use for the API key")
    config_parser.add_argument("--api-key", help="API key value (optional)")
    config_parser.add_argument("--model", help="Model id to add to runtime.yaml")
    config_parser.add_argument("--base-url", help="Base URL (mainly for local/proxy providers)")
    config_parser.add_argument("--temperature", type=float, help="Model temperature")
    config_parser.add_argument("--max-tokens", type=int, help="Model max_tokens")
    config_parser.add_argument("--no-dotenv", action="store_true", help="Do not write .env")
    config_parser.add_argument("--no-default", action="store_true", help="Do not set default provider")
    config_parser.add_argument("--check", action="store_true", help="Verify configured providers and API keys")

    onboard_parser = subparsers.add_parser(
        "onboard",
        aliases=["start"],
        help="Guided setup for a new project",
    )
    onboard_parser.add_argument("--path", default=".", help="Project root (contains runtime.yaml)")

    docs_parser = subparsers.add_parser(
        "docs",
        help="Generate workflow reference docs and rebuild docs indexes",
    )
    docs_parser.add_argument("--path", default=".", help="Project root (contains documentation/ and workflows/)")
    docs_parser.add_argument(
        "--no-workflow-reference",
        action="store_true",
        help="Skip generating documentation/guide/workflow-reference-generated.md",
    )
    docs_parser.add_argument(
        "--no-site-index",
        action="store_true",
        help="Skip rebuilding documentation/site/content.js",
    )

    export_parser = subparsers.add_parser(
        "export",
        help="Export a portable project bundle (no API keys)",
    )
    export_parser.add_argument("--path", default=".", help="Project root (contains runtime.yaml)")
    export_parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output archive path (default: <project>.agentic-export.tar.gz)",
    )
    export_parser.add_argument(
        "--no-tools",
        action="store_true",
        help="Exclude tools/ from the export bundle",
    )

    import_parser = subparsers.add_parser(
        "import",
        help="Import a portable bundle into a project directory",
    )
    import_parser.add_argument("bundle", help="Path to .tar.gz export bundle")
    import_parser.add_argument("--path", default=".", help="Target directory to extract into")
    import_parser.add_argument(
        "--run",
        dest="run_workflow",
        default=None,
        help="Workflow path to run after import (relative to target dir)",
    )



    def _add_llm_control_args(cmd_parser: argparse.ArgumentParser) -> None:
        """Function implementation."""
        cmd_parser.add_argument(
            "--llm-rate-limit-rpm",
            type=int,
            default=None,
            help="Global LLM requests-per-minute cap for this invocation (0 disables)",
        )
        cmd_parser.add_argument(
            "--max-llm-requests",
            type=int,
            default=None,
            help="Max LLM requests allowed for one run (0 disables)",
        )
        cmd_parser.add_argument(
            "--max-llm-tokens",
            type=int,
            default=None,
            help="Max total LLM tokens allowed for one run (0 disables)",
        )
        cmd_parser.add_argument(
            "--max-llm-cost-usd",
            type=float,
            default=None,
            help="Max estimated LLM cost in USD allowed for one run (0 disables)",
        )

    run_parser = subparsers.add_parser("run", help="Run a workflow")
    run_parser.add_argument("workflow", help="Workflow path or workflow_id[@version]")
    run_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    run_parser.add_argument("-v", "--verbose", action="store_true",
                            help="Show structured JSON log events (LLM, tool)")
    run_parser.add_argument("-i", "--input", action="append", default=[],
                            metavar="KEY=VALUE",
                            help="Workflow input (repeatable, e.g. -i issue=\"bug report\")")
    run_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable live interactive debugger for workflow/agent/tool execution",
    )
    run_parser.add_argument(
        "--breakpoint",
        action="append",
        default=[],
        metavar="SPEC",
        help="Initial debugger breakpoint (step:<id>, event:<name>, tool:<name>, agent_step:<id>, expr:<condition>)",
    )
    run_parser.add_argument(
        "--debug-profile",
        default=None,
        help="Path to JSON debug profile (start_paused + breakpoints)",
    )
    run_parser.add_argument(
        "--debug-log-dir",
        default=".runs",
        help="Directory for persisted debug event logs (set empty string to disable)",
    )
    _add_llm_control_args(run_parser)

    # [Pain Point Solved] #4 Debugging is Blind: inspect, state-diff, replay, and
    #   visualize give full post-mortem observability without print() statements.
    inspect_parser = subparsers.add_parser("inspect", help="Inspect a run")
    inspect_parser.add_argument("run_id", help="Run ID")
    inspect_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    inspect_parser.add_argument("--steps", action="store_true", help="Show step details")
    inspect_parser.add_argument("--state-history", action="store_true", help="Show state evolution per step")
    inspect_parser.add_argument("--diff-limit", type=int, default=20, help="Maximum number of changed paths per category to display")
    inspect_parser.add_argument("--full", action="store_true", help="Show full diff output without truncation")

    resume_parser = subparsers.add_parser("resume", help="Resume a failed run")
    resume_parser.add_argument("run_id", help="Run ID")
    resume_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    resume_parser.add_argument("--workflow", help="Optional workflow YAML path to validate against stored hash")
    _add_llm_control_args(resume_parser)

    replay_parser = subparsers.add_parser("replay", help="Deterministically replay a run")
    replay_parser.add_argument("run_id", help="Run ID")
    replay_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    replay_parser.add_argument("--step-by-step", action="store_true", help="Pause between replayed steps")
    replay_parser.add_argument("--until", help="Replay until and including this step id")
    replay_parser.add_argument("--verify-state", action="store_true", help="Verify state_before matches reconstructed state")

    state_diff_parser = subparsers.add_parser("state-diff", help="Show deep state changes per step")
    state_diff_parser.add_argument("run_id", help="Run ID")
    state_diff_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    state_diff_parser.add_argument("--step", help="Optional step id filter")
    state_diff_parser.add_argument("--diff-limit", type=int, default=20, help="Maximum number of changed paths to display per step")
    state_diff_parser.add_argument("--full", action="store_true", help="Show full diff output without truncation")

    visualize_parser = subparsers.add_parser("visualize", aliases=["viz"], help="Visualize run execution")
    visualize_parser.add_argument("run_id", help="Run ID")
    visualize_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    visualize_parser.add_argument("--ascii", action="store_true", help="Render ASCII visualization")
    visualize_parser.add_argument("--html", action="store_true", help="Render HTML visualization")
    visualize_parser.add_argument("--timeline", action="store_true", help="Render timeline-focused text view")
    visualize_parser.add_argument("--no-open", action="store_true", help="Do not auto-open HTML in browser")

    list_parser = subparsers.add_parser("list", help="List available agents")
    list_parser.add_argument("--agents-dir", default="agents", help="Agents directory")

    runs_parser = subparsers.add_parser("runs", help="List recent runs")
    runs_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    runs_parser.add_argument("--limit", type=int, default=20, help="Maximum number of runs to show (default 20)")
    runs_parser.add_argument("--html", action="store_true", help="Generate browsable HTML dashboard")
    runs_parser.add_argument("--no-open", action="store_true", help="Do not auto-open HTML in browser")

    metrics_parser = subparsers.add_parser(
        "metrics",
        help="Show aggregate run/step metrics for observability and support",
    )
    metrics_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    metrics_parser.add_argument("--top-steps", type=int, default=10, help="Top failing steps/errors to show")
    metrics_parser.add_argument("--window-days", type=int, default=7, help="Window size (days) for trend and health calculations")
    metrics_parser.add_argument("--latency-target-ms", type=int, default=5000, help="Target p95 latency for successful runs")
    metrics_parser.add_argument("--json", action="store_true", help="Print full report as JSON")

    test_parser = subparsers.add_parser("test", help="Run project-authored tests")
    test_parser.add_argument("scope", nargs="?", default="all", choices=["all", "workflows", "agents", "functions", "tools"], help="Test scope to run")
    test_parser.add_argument("targets", nargs="*", help="Optional target filters, e.g. workflow or agent names")
    test_parser.add_argument("--path", default=".", help="Project root containing agents/, workflows/, functions/, tools/")
    test_parser.add_argument("--pytest-args", nargs=argparse.REMAINDER, default=[], help="Extra pytest args appended at the end")

    args = parser.parse_args(argv)

    if args.command == "init":
        _init_project(args.path)
        print(f"Initialized workflow project at {os.path.abspath(args.path)}")
        return 0

    if args.command == "quickstart":
        project_root = os.path.abspath(args.path)
        return _run_quickstart(project_root, sample=args.sample)

    if args.command == "config":
        project_root = os.path.abspath(args.path)

        if not os.path.isdir(project_root):
            raise SystemExit(f"Project path does not exist: {project_root}")

        if args.check:
            runtime_path = os.path.join(project_root, "runtime.yaml")
            _load_dotenv(os.path.join(project_root, ".env"))
            if not os.path.exists(runtime_path):
                print(f"No runtime.yaml found at {runtime_path}")
                return 1
            cfg = load_config(runtime_path)
            providers = cfg.llm_registry.list_providers()
            if not providers:
                print("No LLM providers configured in runtime.yaml.")
                return 1
            statuses = cfg.llm_registry.check_credentials()
            all_ok = True
            print("LLM provider check:")
            for name in providers:
                provider_obj = cfg.llm_registry.get_provider(name)
                if provider_obj is None:
                    continue
                has_key = statuses.get(name, False)
                all_ok = all_ok and has_key
                key_status = "set" if has_key else "missing"
                print(f"  - {name}")
                print(f"    api_key_env: {provider_obj.api_key_env} ({key_status})")
                models = provider_obj.list_models()
                if models:
                    print(f"    models: {', '.join(models)}")
                else:
                    print("    models: (none)")
            return 0 if all_ok else 1

        _run_setup_flow(
            project_root,
            provider=args.provider,
            api_key_env=args.api_key_env,
            api_key=args.api_key,
            model=args.model,
            base_url=args.base_url,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            no_dotenv=args.no_dotenv,
            no_default=args.no_default,
        )
        print("Config complete. You can now run `ai run ...`.")
        return 0

    if args.command == "onboard":
        project_root = os.path.abspath(args.path)
        return _run_onboard_flow(project_root)

    if args.command == "docs":
        project_root = Path(os.path.abspath(args.path))
        docs_root = project_root / "documentation"
        if not docs_root.is_dir():
            raise SystemExit(f"documentation directory not found: {docs_root}")

        generated_reference: Optional[Path] = None
        if not args.no_workflow_reference:
            generated_reference = _generate_workflow_reference(project_root)

        count = _build_docs_index(docs_root)
        print(f"Built {docs_root / 'content.js'} and {docs_root / 'docs-manifest.json'} with {count} docs")

        site_root = docs_root / "site"
        if site_root.is_dir() and not args.no_site_index:
            site_count = _build_docs_index(site_root)
            print(f"Built {site_root / 'content.js'} with {site_count} docs")

        if generated_reference is not None:
            print(f"Generated {generated_reference}")



        return 0

    if args.command == "export":
        project_root = os.path.abspath(args.path)
        return _run_export(
            project_root,
            output_path=args.output,
            include_tools=not args.no_tools,
        )

    if args.command == "import":
        target_dir = os.path.abspath(args.path)
        return _run_import(
            args.bundle,
            target_dir=target_dir,
            run_workflow=args.run_workflow,
        )

    if args.command == "test":
        project_root = os.path.abspath(args.path)
        return _run_project_tests(
            project_root,
            scope=args.scope,
            targets=args.targets,
            pytest_args=args.pytest_args,
        )


    _load_dotenv()

    # Load runtime.yaml config with CLI overrides
    cfg = load_config()
    cfg = apply_cli_overrides(cfg, args)

    if args.command == "list":
        agents_dir = args.agents_dir
        if not os.path.isdir(agents_dir):
            print(f"No agents directory found at: {agents_dir}")
            return 0
        found = False
        for filename in sorted(os.listdir(agents_dir)):
            if not filename.endswith((".yaml", ".yml")):
                continue
            filepath = os.path.join(agents_dir, filename)
            try:
                defn = load_agent_definition(filepath)
            except Exception:
                continue
            desc = f" \u2014 {defn.description}" if defn.description else ""
            strategy = defn.strategy.type if defn.strategy else "single"
            print(f"  {defn.agent_id}@{defn.version} [{strategy}] {defn.model}{desc}")
            found = True
        if not found:
            print("No agents found.")
        return 0

    if args.command == "runs":
        storage = SQLiteStorage(cfg.db_path)
        try:
            runs = storage.list_runs(limit=args.limit)
        except BaseException:
            storage.close()
            raise
        if not runs:
            print("No runs found.")
            storage.close()
            return 0

        if args.html:
            html_path = _render_runs_html(runs)
            print(f"Runs dashboard generated: {html_path}")
            if not args.no_open:
                try:
                    webbrowser.open(f"file://{os.path.abspath(html_path)}")
                except Exception:
                    print("Could not open browser automatically. Open the file manually.")
            storage.close()
            return 0

        # Text output
        print(f"Recent runs ({len(runs)}):\n")
        for run in runs:
            version = f"@{run.workflow_version}" if run.workflow_version else ""
            status_icon = "\u2713" if run.status == "COMPLETED" else ("\u2717" if run.status == "FAILED" else "\u29d7")
            error_hint = f" \u2014 {run.error[:60]}..." if run.error and len(run.error) > 60 else (f" \u2014 {run.error}" if run.error else "")
            print(f"  {status_icon} {run.run_id[:12]}  {run.workflow_id}{version}  {run.status}{error_hint}")
            print(f"    created: {run.created_at or 'n/a'}  completed: {run.completed_at or 'n/a'}")
        print(f"\nInspect: ai inspect <run_id> --steps")
        print(f"Visualize: ai visualize <run_id>")
        storage.close()
        return 0

    if args.command == "metrics":
        storage = SQLiteStorage(cfg.db_path)
        try:
            report = storage.build_observability_report(
            top_steps=args.top_steps,
            window_days=args.window_days,
            latency_target_ms=args.latency_target_ms,
        )
        except BaseException:
            storage.close()
            raise

        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            storage.close()
            return 0

        runs_section = report.get("runs", {})
        steps_section = report.get("steps", {})
        llm_section = report.get("llm", {})
        errors_section = report.get("errors", {})
        outcomes_section = report.get("outcomes", {})
        diagnostics_section = report.get("diagnostics", {})
        health_section = report.get("health", {})

        print("Observability Metrics")
        print(f"  Runs: total={runs_section.get('total', 0)} failed={runs_section.get('failed', 0)} "
              f"failure_rate={runs_section.get('failure_rate', 0.0):.2%}")
        print(f"  Run latency: avg={runs_section.get('avg_duration_ms')}ms "
              f"p95={runs_section.get('p95_duration_ms')}ms")
        print(f"  Steps: total={steps_section.get('total', 0)} failed={steps_section.get('failed', 0)} "
              f"failure_rate={steps_section.get('failure_rate', 0.0):.2%}")
        print(f"  LLM total tokens: {llm_section.get('total_tokens', 0)}")

        current_outcomes = outcomes_section.get("current", {})
        previous_outcomes = outcomes_section.get("previous", {})
        print("\nOutcome Layer (Current vs Previous)")
        print(
            "  "
            f"ADS={current_outcomes.get('ads_rate', 0.0):.2%} "
            f"(prev {previous_outcomes.get('ads_rate', 0.0):.2%})  "
            f"PORR={current_outcomes.get('post_outcome_reversal_rate', 0.0):.2%} "
            f"(prev {previous_outcomes.get('post_outcome_reversal_rate', 0.0):.2%})"
        )
        print(
            "  "
            f"HTR={current_outcomes.get('human_touch_rate', 0.0):.2%} "
            f"(prev {previous_outcomes.get('human_touch_rate', 0.0):.2%})  "
            f"RE={current_outcomes.get('recovery_efficiency', 0.0):.2%} "
            f"[{current_outcomes.get('recovery_efficiency_source', 'unknown')}]"
        )
        print(
            "  "
            f"OPR={current_outcomes.get('oracle_pass_rate', 0.0):.2%} "
            f"OMR={current_outcomes.get('oracle_match_rate', 0.0):.2%}"
        )

        top_failing = steps_section.get("top_failing", [])
        print("\nTop Failing Steps:")
        if top_failing:
            for item in top_failing:
                print(
                    "  - "
                    f"{item.get('step_id')} executions={item.get('executions')} "
                    f"failed={item.get('failed')} "
                    f"failure_rate={item.get('failure_rate', 0.0):.2%} "
                    f"avg={item.get('avg_duration_ms')}ms "
                    f"p95={item.get('p95_duration_ms')}ms"
                )
        else:
            print("  (no step data)")

        top_errors = errors_section.get("top_classes", [])
        print("\nTop Error Classes:")
        if top_errors:
            for item in top_errors:
                print(f"  - {item.get('error_class')}: {item.get('count')}")
        else:
            print("  (no error data)")

        success_latency = diagnostics_section.get("success_latency", {})
        current_latency = success_latency.get("current", {})
        previous_latency = success_latency.get("previous", {})
        print("\nSuccess Latency (ADS Runs)")
        print(
            "  "
            f"median={current_latency.get('successful_run_duration_median_ms')}ms "
            f"p95={current_latency.get('successful_run_duration_p95_ms')}ms "
            f"target={current_latency.get('latency_target_ms')}ms "
            f"score={current_latency.get('latency_score')}"
        )
        print(
            "  "
            f"prev median={previous_latency.get('successful_run_duration_median_ms')}ms "
            f"prev p95={previous_latency.get('successful_run_duration_p95_ms')}ms"
        )

        step_attribution = diagnostics_section.get("step_attribution", {})
        current_attr = step_attribution.get("current", {})
        print("\nStep Attribution (First-Break Step Rate)")
        for item in current_attr.get("first_break_step_rate", [])[: max(1, int(args.top_steps))]:
            print(
                "  - "
                f"{item.get('step_id')} idx={item.get('step_index')} type={item.get('step_type')} "
                f"agent={item.get('agent_id')} tool={item.get('tool_name')} "
                f"fbsr={item.get('fbsr', 0.0):.2%} count={item.get('count', 0)}"
            )
        if not current_attr.get("first_break_step_rate"):
            print("  (no non-ADS runs in current window)")
        print(
            "  "
            f"top_step_concentration={current_attr.get('top_step_concentration')} "
            f"delta={step_attribution.get('top_step_concentration_delta')}"
        )

        input_coverage = diagnostics_section.get("input_coverage", {})
        print("\nInput Coverage / Drift")
        print(
            "  "
            f"NIS(current)={input_coverage.get('current_novel_input_share')} "
            f"NIS(previous)={input_coverage.get('previous_novel_input_share')}"
        )
        novel_classes = input_coverage.get("current_novel_classes", [])
        if novel_classes:
            print("  novel classes:")
            for item in novel_classes[: max(1, int(args.top_steps))]:
                print(f"    - {item.get('input_class')}: {item.get('count')}")

        calibration = diagnostics_section.get("calibration", {})
        cal_current = calibration.get("current", {})
        cal_previous = calibration.get("previous", {})
        print("\nConfidence Calibration")
        print(
            "  "
            f"ECE={cal_current.get('ece')} (prev {cal_previous.get('ece')})  "
            f"OFR={cal_current.get('overconfident_failure_rate')} "
            f"samples={cal_current.get('samples', 0)}"
        )

        print("\nHealth Score")
        print(
            "  "
            f"status={health_section.get('status')} "
            f"current={health_section.get('current', {}).get('score')} "
            f"previous={health_section.get('previous', {}).get('score')} "
            f"delta={health_section.get('delta')}"
        )
        print(
            "  "
            f"distributed_improvement={health_section.get('distributed_improvement')}"
        )
        breakers = health_section.get("circuit_breakers", [])
        if breakers:
            print("  circuit breakers:")
            for item in breakers:
                mark = "TRIPPED" if item.get("tripped") else "ok"
                print(f"    - {item.get('name')}: {mark}")
        storage.close()
        return 0

    if args.command == "run":
        log_level = "info" if getattr(args, "verbose", False) else "warning"
        logger = StructuredLogger(stream=sys.stderr, level=log_level)
        llm_client = _default_llm_client(cfg, logger)
        # Try agent-aware resolution: check agents/ for a definition
        # matching the workflow arg as an agent_id (with optional @version).
        resolved_agent = _try_resolve_agent(args.workflow)

        functions_dir = cfg.functions_dir if os.path.isdir(cfg.functions_dir) else None

        try:
            if isinstance(resolved_agent, AgentDefinition):
                # Definition-format agent: synthesize a workflow wrapper
                input_state = _build_input_state(args.input, {})
                workflow = _workflow_from_definition(resolved_agent, input_keys=list(input_state.keys()))
            else:
                workflow = _load_workflow_for_run(
                    args.workflow, cfg.workflows_dir,
                    functions_dir=functions_dir,
                )
                input_state = _build_input_state(args.input, workflow.get("inputs", {}))
        except FileNotFoundError:
            _print_cli_exception(FileNotFoundError(f"workflow file not found: {args.workflow}"))
            return 1
        except yaml.YAMLError as exc:
            _print_cli_exception(exc)
            return 1
        except WorkflowValidationError as exc:
            _print_cli_exception(exc)
            return 1

        steps = workflow["steps"]

        storage = SQLiteStorage(cfg.db_path)
        memory_manager = _default_memory_manager(
            cfg.db_path,
            max_entries=cfg.working_memory_max_entries,
            max_scratch_bytes=cfg.working_memory_max_scratch_bytes,
        )
        tool_registry = _default_tool_registry(
            cfg.tools_dir,
            shell_allowlist=cfg.shell_allowlist or None,
            shell_denylist=cfg.shell_denylist or None,
        )
        agent_registry = _default_agent_registry(cfg.agents_dir)
        debugger: Optional[LiveDebugger] = None
        debug_enabled = bool(getattr(args, "debug", False) or getattr(args, "debug_profile", None))
        if debug_enabled:
            profile_start_paused = True
            profile_breakpoints: List[str] = []
            if getattr(args, "debug_profile", None):
                try:
                    profile_start_paused, profile_breakpoints = load_debug_profile(args.debug_profile)
                except Exception as exc:  # noqa: BLE001
                    _print_cli_exception(exc)
                    return 1

            merged_breakpoints = list(profile_breakpoints)
            merged_breakpoints.extend(getattr(args, "breakpoint", []))
            debugger = LiveDebugger(
                load_latest_state=storage.load_latest_state,
                breakpoints=merged_breakpoints,
                start_paused=profile_start_paused,
                event_log_dir=(getattr(args, "debug_log_dir", ".runs") or None),
            )
            print("Debug mode enabled. Type 'h' at the (debug) prompt for commands.")

        def _progress_callback(event: str, payload: Dict[str, Any]) -> None:
            """Function implementation."""
            if debugger is not None and debugger.enabled:
                debugger.handle_event(event, payload)
                return

            step_id = payload.get("step_id", "")
            step_type = payload.get("step_type", "")
            if event == "STEP_START":
                hint = " (calling LLM...)" if step_type == "agent" else ""
                print(f"  \u29d7 {step_id} ({step_type}){hint}")
            elif event == "STEP_COMPLETE":
                duration = payload.get("duration_ms")
                duration_str = f"{duration}ms" if isinstance(duration, int) else "n/a"
                call_duration = payload.get("tool_duration_ms")
                if call_duration is None:
                    call_duration = payload.get("handler_duration_ms")
                call_str = f", call {call_duration}ms" if isinstance(call_duration, int) else ""
                print(f"  \u2713 {step_id} ({step_type}) \u2014 {duration_str}{call_str}")
            elif event == "STEP_ERROR":
                error = payload.get("error", "unknown error")
                print(f"  \u2717 {step_id} ({step_type}) \u2014 {error}")

        executor = Executor(
            steps=steps,
            storage=storage,
            logger=logger,
            memory_manager=memory_manager,
            tool_registry=tool_registry,
            overwrite_policy=cfg.overwrite_policy,
            on_event=_progress_callback,
            agent_registry=agent_registry,
            llm_client=llm_client,
            default_model=cfg.default_model,
            latency_budget_ms=workflow.get("latency_budget_ms"),
        )

        try:
            run = executor.run(
                workflow_id=workflow["workflow_id"],
                workflow_inputs=workflow.get("inputs", {}),
                workflow_version=workflow.get("workflow_version"),
                initial_state=input_state,
                on_error=workflow.get("on_error", "fail_fast"),
                workflow_hash=workflow.get("workflow_hash"),
                workflow_yaml=workflow.get("workflow_yaml"),
                workflow_steps=workflow.get("workflow_steps"),
                input_hash=sha256_json(input_state),
            )
        except Exception as exc:  # noqa: BLE001
            _print_cli_exception(exc)
            return 1
        finally:
            memory_manager.close()
            storage.close()
        print(f"Run {run.run_id} status: {run.status}")
        _print_run_summary(run, cfg.llm_pricing_usd_per_1k_tokens)
        if run.status == "FAILED":
            _print_failure_details(run)
            print(f"\nRun `ai inspect {run.run_id}` to see state and full trace.")
        return 0 if run.status == "COMPLETED" else 1

    if args.command == "inspect":
        storage = SQLiteStorage(cfg.db_path)
        try:
            run = storage.load_run(args.run_id)
        except ValueError:
            storage.close()
            _print_cli_exception(RunNotFoundError(f"run not found: {args.run_id}"))
            return 1
        steps = storage.load_steps(args.run_id)
        latest_state = storage.load_latest_state(args.run_id)

        version = f"@{run.workflow_version}" if run.workflow_version else ""
        print(f"Run {run.run_id} | workflow={run.workflow_id}{version} | status={run.status}")
        # Attach loaded steps + latest state so the run's aggregate properties
        # (total_tokens, total_cost_usd, outputs) work for the summary block.
        # load_run() returns a Run with empty steps and empty state.
        for s in steps:
            run.add_step(s)
        from agent_runtime.models import RunState
        run.state = RunState(latest_state)
        _print_run_summary(run, cfg.llm_pricing_usd_per_1k_tokens)
        if run.error:
            print(f"Error: {run.error}")
        if args.steps:
            run_total_cost = 0.0
            run_total_tokens: Dict[str, int] = {"input": 0, "output": 0}
            for idx, step in enumerate(steps, start=1):
                print(f"{idx} {step.step_id}")
                print(f"status: {step.status}")
                if step.attempt_count is not None:
                    print(f"attempts: {step.attempt_count}")
                if step.output is not None:
                    print("output:")
                    print(_redact(step.output))
                if step.error is not None:
                    print("error:")
                    print(step.error)
                elif step.last_error is not None:
                    print("last_error:")
                    print(step.last_error)
                if getattr(step, "token_usage", None):
                    print(f"token_usage: {step.token_usage}")
                    persisted_cost = getattr(step, "cost_usd", None)
                    if persisted_cost is not None:
                        print(f"cost_usd: ${persisted_cost:.6f}")
                        run_total_cost += persisted_cost
                    else:
                        step_cost = _estimate_step_cost_usd(step.token_usage, cfg.llm_pricing_usd_per_1k_tokens)
                        if step_cost is not None:
                            print(f"estimated_cost_usd: ${step_cost:.6f}")
                            run_total_cost += step_cost
                    run_total_tokens["input"] += _to_int(step.token_usage.get("input_tokens", step.token_usage.get("prompt_tokens", 0)))
                    run_total_tokens["output"] += _to_int(step.token_usage.get("output_tokens", step.token_usage.get("completion_tokens", 0)))
                if getattr(step, "agent_trace", None):
                    print("agent_trace:")
                    normalized_trace = normalize_agent_trace(step.agent_trace)
                    for t_idx, turn in enumerate(normalized_trace, start=1):
                        turn_type = turn.get("type", "unknown")
                        if turn_type == "model":
                            model = turn.get("model", "")
                            text_preview = (turn.get("response_text") or "")[:120]
                            print(f"  {t_idx}. [model] {model}: {text_preview}")
                        elif turn_type == "tool":
                            tool_name = turn.get("tool", "")
                            success = turn.get("success", "")
                            print(f"  {t_idx}. [tool] {tool_name} -> success={success}")
                        else:
                            print(f"  {t_idx}. [{turn_type}]")
                print("")
            if run_total_tokens["input"] > 0 or run_total_tokens["output"] > 0:
                print("--- Run Token Summary ---")
                print(f"total_input_tokens: {run_total_tokens['input']}")
                print(f"total_output_tokens: {run_total_tokens['output']}")
                if run_total_cost > 0:
                    print(f"total_estimated_cost_usd: ${run_total_cost:.6f}")
                print("")
        else:
            print("Steps:")
            for idx, step in enumerate(steps, start=1):
                duration = f"{step.duration_ms}ms" if step.duration_ms is not None else "n/a"
                attempts = step.attempt_count if step.attempt_count is not None else "n/a"
                print(f"  {idx}. {step.step_id} ({step.step_type}) -> {step.status} ({duration}, attempts: {attempts})")
            print("Latest state:")
            print(_redact(latest_state))

        if run.workflow_yaml:
            workflow = load_workflow_from_text(run.workflow_yaml)
            resume_step = determine_resume_step(workflow["steps"], steps)
            if resume_step:
                print(f"Resume point: step {resume_step}")
        if args.state_history:
            if args.diff_limit < 0:
                raise SystemExit("--diff-limit must be >= 0")
            _print_state_history(steps, latest_state, diff_limit=args.diff_limit, full=args.full)
        storage.close()
        return 0

    if args.command == "resume":
        storage = SQLiteStorage(cfg.db_path)
        try:
            run = storage.load_run(args.run_id)
        except ValueError:
            storage.close()
            _print_cli_exception(RunNotFoundError(f"run not found: {args.run_id}"))
            return 1
        try:
            validate_resume(run.status)
        except RuntimeErrorBase as exc:
            storage.close()
            _print_cli_exception(exc)
            return 1

        llm_client_resume = _default_llm_client(cfg)
        functions_dir_resume = cfg.functions_dir if os.path.isdir(cfg.functions_dir) else None

        workflow_text = run.workflow_yaml
        if not workflow_text:
            # No stored YAML — either the run used a definition-auto workflow
            # (ai run <agent_id>) or workflow storage was disabled.
            # Try to reconstruct from agent registry first.
            wf_id = run.workflow_id or ""
            if wf_id.endswith("_auto"):
                agent_id = wf_id.removesuffix("_auto")
                resolved = _try_resolve_agent(agent_id, cfg.agents_dir)
                if isinstance(resolved, AgentDefinition):
                    state = storage.load_latest_state(args.run_id)
                    input_keys = list(state.get("inputs", {}).keys())
                    workflow = _workflow_from_definition(resolved, input_keys=input_keys)
                else:
                    _print_cli_exception(
                        RuntimeError(
                            f"Cannot reconstruct workflow for agent '{agent_id}'. Provide --workflow to resume."
                        )
                    )
                    storage.close()
                    return 1
            elif args.workflow:
                workflow = load_workflow(args.workflow, functions_dir=functions_dir_resume)
            else:
                _print_cli_exception(RuntimeError("Workflow YAML not stored; provide --workflow to resume."))
                storage.close()
                return 1
        else:
            workflow = load_workflow_from_text(workflow_text, functions_dir=functions_dir_resume)

        if args.workflow:
            current = load_workflow(args.workflow, functions_dir=functions_dir_resume)
            if run.workflow_hash and current.get("workflow_hash") != run.workflow_hash:
                _print_cli_exception(RuntimeError("Workflow hash mismatch; cannot resume."))
                storage.close()
                return 1

        if run.workflow_hash and workflow.get("workflow_hash") != run.workflow_hash:
            _print_cli_exception(RuntimeError("Stored workflow hash mismatch; cannot resume."))
            storage.close()
            return 1

        steps = storage.load_steps(args.run_id)
        resume_step = determine_resume_step(workflow["steps"], steps)
        if resume_step is None:
            _print_cli_exception(RuntimeError("No resumable step found."))
            storage.close()
            return 1

        state = storage.load_latest_state(args.run_id)
        state_version = storage.load_latest_state_version(args.run_id)

        executor = Executor(
            steps=workflow["steps"],
            storage=storage,
            logger=StructuredLogger(),
            memory_manager=_default_memory_manager(
                cfg.db_path,
                max_entries=cfg.working_memory_max_entries,
                max_scratch_bytes=cfg.working_memory_max_scratch_bytes,
            ),
            tool_registry=_default_tool_registry(
                cfg.tools_dir,
                shell_allowlist=cfg.shell_allowlist or None,
                shell_denylist=cfg.shell_denylist or None,
            ),
            overwrite_policy=cfg.overwrite_policy,
            agent_registry=_default_agent_registry(cfg.agents_dir),
            llm_client=llm_client_resume,
            default_model=cfg.default_model,
            latency_budget_ms=workflow.get("latency_budget_ms"),
        )

        print(f"Resuming run {run.run_id} from step: {resume_step}")
        resumed = executor.resume(
            run=run,
            resume_state=state,
            start_step_id=resume_step,
            on_error=workflow.get("on_error", "fail_fast"),
            state_version=state_version,
            workflow_hash=workflow.get("workflow_hash"),
        )
        print(f"Run {resumed.run_id} status: {resumed.status}")
        storage.close()
        return 0 if resumed.status == "COMPLETED" else 1

    if args.command == "replay":
        storage = SQLiteStorage(cfg.db_path)
        replayer = RunReplayer(storage=storage, printer=print)
        try:
            replayer.replay(
                run_id=args.run_id,
                step_by_step=args.step_by_step,
                until=args.until,
                verify_state=args.verify_state,
            )
        except (ValueError, RunNotFoundError):
            storage.close()
            _print_cli_exception(RunNotFoundError(f"run not found: {args.run_id}"))
            return 1
        storage.close()
        return 0

    if args.command == "state-diff":
        if args.diff_limit < 0:
            raise SystemExit("--diff-limit must be >= 0")
        storage = SQLiteStorage(cfg.db_path)
        try:
            run = storage.load_run(args.run_id)
        except ValueError:
            storage.close()
            _print_cli_exception(RunNotFoundError(f"run not found: {args.run_id}"))
            return 1
        steps = storage.load_steps(args.run_id)
        if args.step:
            steps = [s for s in steps if s.step_id == args.step]
            if not steps:
                raise SystemExit(f"No steps found for step id: {args.step}")

        print(f"Run {run.run_id} state diff")
        for step in steps:
            print(f"\nStep: {step.step_id}")
            if step.state_before is None or step.state_after is None:
                print("(state diff unavailable)")
                continue
            changes = RuntimeState.diff_paths(step.state_before, step.state_after)
            if not changes:
                print("(no state changes)")
                continue
            shown_changes, omitted = _limit_changes(changes, diff_limit=args.diff_limit, full=args.full)
            if not shown_changes:
                print("(no state changes shown; use --full or increase --diff-limit)")
                continue
            for change in shown_changes:
                op = change["op"]
                path = change["path"]
                if op == "+":
                    print(f"+ {path} = {_redact(change['after'])}")
                elif op == "-":
                    print(f"- {path} (was {_redact(change['before'])})")
                else:
                    print(f"~ {path}: {_redact(change['before'])} -> {_redact(change['after'])}")
            if omitted:
                print(f"... (+{omitted} more changes; use --full or increase --diff-limit)")
        storage.close()
        return 0

    if args.command == "visualize":
        storage = SQLiteStorage(cfg.db_path)
        run_id = args.run_id
        if run_id == "latest":
            recent = storage.list_runs(limit=1)
            if not recent:
                storage.close()
                _print_cli_exception(RunNotFoundError("No runs found in database."))
                return 1
            run_id = recent[0].run_id

        try:
            data = RunLoader(storage).load(run_id)
        except ValueError:
            storage.close()
            _print_cli_exception(RunNotFoundError(f"run not found: {run_id}"))
            return 1
        graph = GraphBuilder().build(data)
        timeline = TimelineBuilder().build(data)

        if args.ascii:
            print(render_ascii(run_id, graph, timeline))
            storage.close()
            return 0

        if args.timeline:
            print(_render_timeline_text(run_id, timeline))
            storage.close()
            return 0

        output_path = os.path.join(".runs", run_id, "visualization.html")
        html_path = render_html(run_id, graph, timeline, output_path)
        print(f"Visualization generated: {html_path}")
        if not args.no_open:
            try:
                webbrowser.open(f"file://{os.path.abspath(html_path)}")
            except Exception:
                print("Could not open browser automatically. Open the file manually.")
        storage.close()
        return 0

    return 1


def _render_runs_html(runs) -> str:
    """Generate a standalone HTML runs dashboard and return the file path."""
    import html as html_mod

    rows = []
    for run in runs:
        version = f"@{run.workflow_version}" if run.workflow_version else ""
        status_cls = "ok" if run.status == "COMPLETED" else ("fail" if run.status == "FAILED" else "run")
        error_cell = html_mod.escape(run.error or "")
        rows.append(
            "<tr>"
            f'<td><a href="{html_mod.escape(run.run_id)}/visualization.html">'
            f"{html_mod.escape(run.run_id[:12])}</a></td>"
            f"<td>{html_mod.escape(run.workflow_id)}{html_mod.escape(version)}</td>"
            f'<td class="{status_cls}">{html_mod.escape(run.status)}</td>'
            f"<td>{html_mod.escape(run.created_at or '')}</td>"
            f"<td>{html_mod.escape(run.completed_at or '')}</td>"
            f"<td>{error_cell}</td>"
            "</tr>"
        )

    doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Runs Dashboard</title>
  <style>
    body {{ font-family: "IBM Plex Sans", "Segoe UI", sans-serif; background: #f6f8fb; margin: 0; padding: 24px; }}
    h1 {{ margin: 0 0 16px 0; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px 12px; text-align: left; font-size: 13px; }}
    th {{ background: #e5eef5; }}
    a {{ color: #0f766e; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .ok {{ color: #15803d; font-weight: 600; }}
    .fail {{ color: #b91c1c; font-weight: 600; }}
    .run {{ color: #a16207; font-weight: 600; }}
    .hint {{ font-size: 13px; color: #6b7280; margin-top: 12px; }}
  </style>
</head>
<body>
  <h1>Runs Dashboard</h1>
  <table>
    <thead><tr><th>Run ID</th><th>Workflow</th><th>Status</th><th>Created</th><th>Completed</th><th>Error</th></tr></thead>
    <tbody>{''.join(rows) if rows else '<tr><td colspan="6">No runs found.</td></tr>'}</tbody>
  </table>
  <p class="hint">Inspect: <code>ai inspect &lt;run_id&gt; --steps</code> &nbsp;|&nbsp;
  Visualize: <code>ai visualize &lt;run_id&gt;</code></p>
</body>
</html>"""

    os.makedirs(".runs", exist_ok=True)
    out_path = os.path.join(".runs", "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return out_path


def main() -> None:
    """CLI entrypoint wrapper that exits with command status code."""
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()


def _limit_changes(changes: list[dict], *, diff_limit: int, full: bool) -> tuple[list[dict], int]:
    """Return visible changes and omitted count for CLI output."""
    if full:
        return list(changes), 0
    limit = max(0, int(diff_limit))
    if limit == 0:
        return [], len(changes)
    if len(changes) <= limit:
        return list(changes), 0
    return list(changes[:limit]), len(changes) - limit


def _diff_state(before: dict, after: dict, *, diff_limit: int = 20, full: bool = False) -> dict:
    """Return state diff summary for CLI output.

    Uses nested path-level diffs when available, with truncation to keep
    inspect output readable in terminals.
    """
    # TODO(ux): Add CLI graph visualization for branching workflows.
    changes = RuntimeState.diff_paths(before, after)
    if not changes:
        return {"added": [], "removed": [], "changed": []}

    added: list[str] = [c["path"] for c in changes if c.get("op") == "+"]
    removed: list[str] = [c["path"] for c in changes if c.get("op") == "-"]
    changed: list[str] = [c["path"] for c in changes if c.get("op") == "~"]

    max_items = max(0, int(diff_limit))

    def _truncate(items: list[str]) -> list[str]:
        """Function implementation."""
        if full:
            return items
        if max_items == 0:
            return [f"... (+{len(items)} more)"] if items else []
        if len(items) <= max_items:
            return items
        remaining = len(items) - max_items
        return items[:max_items] + [f"... (+{remaining} more)"]

    return {
        "added": _truncate(added),
        "removed": _truncate(removed),
        "changed": _truncate(changed),
    }


def _format_redacted_for_cli(value: Any, *, max_chars: int = 6000) -> str:
    """Pretty-format redacted content and cap output size for terminal safety."""
    text = pformat(_redact(value), width=100, sort_dicts=True)
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n... [truncated {omitted} chars]"


def _print_state_history(steps, latest_state, *, diff_limit: int = 20, full: bool = False) -> None:
    """Print per-step state mutation summary for inspect command."""
    # TODO(eng): Support snapshot compression for large states.
    # TODO(ux): Add interactive pager mode for long histories (--pager).
    if not steps:
        return
    initial = steps[0].state_before or latest_state
    print("\nState history:")
    print("Initial state:")
    print(_format_redacted_for_cli(initial))
    print("\n----------------------------------------")
    for idx, step in enumerate(steps, start=1):
        print(f"Step {idx} {step.step_id}")
        print(f"Status: {step.status}")
        if step.attempt_count is not None:
            print(f"Attempts: {step.attempt_count}")
        before = step.state_before or {}
        after = step.state_after or {}
        diff = _diff_state(before, after, diff_limit=diff_limit, full=full)
        print("State changes:")
        if diff["added"]:
            print(f"+ {', '.join(diff['added'])}")
        if diff["removed"]:
            print(f"- {', '.join(diff['removed'])}")
        if diff["changed"]:
            print(f"~ {', '.join(diff['changed'])}")
        if not diff["added"] and not diff["removed"] and not diff["changed"]:
            print("(no changes)")
        if step.output is not None:
            print("Output:")
            print(_format_redacted_for_cli(step.output))
        if step.state_after is not None:
            print("State after:")
            print(_format_redacted_for_cli(step.state_after))
        print("\n----------------------------------------")


def _render_timeline_text(run_id: str, timeline) -> str:
    """Render timeline view to plain text for `visualize --timeline`."""
    lines = [f"Run: {run_id}", "", "State Timeline", "Initial State:", str(timeline.initial_state)]
    if timeline.run_duration_ms is not None:
        lines.insert(1, f"Run Duration: {timeline.run_duration_ms}ms")
    for item in timeline.steps:
        lines.append("\n----------------------------------------")
        lines.append(f"Step: {item.step_id}")
        lines.append(f"Status: {item.status}")
        lines.append(f"Attempts: {item.attempts}")
        duration = f"{item.duration_ms}ms" if item.duration_ms is not None else "n/a"
        lines.append(f"Duration: {duration}")
        call_duration = item.tool_duration_ms if item.tool_duration_ms is not None else item.handler_duration_ms
        if call_duration is not None:
            lines.append(f"Call Duration: {call_duration}ms")
        if item.error:
            lines.append(f"Error: {item.error}")
        elif item.last_error:
            lines.append(f"Last Error: {item.last_error}")
        lines.append("State changes:")
        if not item.state_changes:
            lines.append("(no changes)")
        for change in item.state_changes:
            if change.op == "+":
                lines.append(f"+ {change.path}")
            elif change.op == "-":
                lines.append(f"- {change.path}")
            else:
                lines.append(f"~ {change.path}")
    lines.append("\n----------------------------------------")
    lines.append("Latest State:")
    lines.append(str(timeline.latest_state))
    return "\n".join(lines)
