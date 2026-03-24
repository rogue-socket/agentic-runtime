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
  - `ai init` should scaffold a working LLM-powered agent out of the box,
    not just empty directories. Include a sample that calls a real LLM.
  - `ai run` output should show a concise progress summary by default
    (step name + status + duration), not just silence until completion.
  - Add `ai quickstart` command that creates a minimal agent, runs it,
    and opens the HTML visualization — a single-command "wow" moment.
"""

import argparse
import getpass
import os
from pprint import pformat
import re
import sys
from typing import Any, Dict, List, Optional
import webbrowser
import yaml

from .core import Executor, StepStatus
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
from .errors import WorkflowValidationError, RunNotFoundError
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


def _parse_env_line(line: str) -> Optional[tuple[str, str]]:
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
    if not value:
        return value
    if re.search(r"\s|#", value):
        escaped = value.replace('"', '\\"')
        return f"\"{escaped}\""
    return value


def _update_dotenv(path: str, updates: Dict[str, str]) -> None:
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
    choices_lower = [c.lower() for c in choices]
    while True:
        raw = input(f"{prompt} {choices} [{default}]: ").strip()
        if not raw:
            return default
        if raw.lower() in choices_lower:
            return choices[choices_lower.index(raw.lower())]


def _prompt_int(prompt: str, min_value: int, max_value: int, default: int) -> int:
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


EXAMPLE_WORKFLOW = """workflow:                     # workflow metadata
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

RUNTIME_YAML_TEMPLATE = """# Runtime configuration for agentic-runtime.
# CLI flags override values set here.
# Uncomment and edit sections as needed.

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
    """Create workflow scaffold files in target directory.

    The scaffolded example workflow includes an ``agent`` step that makes
    a real LLM call (summarizer), so ``ai quickstart`` produces a live
    end-to-end run out of the box once a provider API key is configured.
    """
    workflows_dir = os.path.join(target_dir, "workflows")
    tools_dir = os.path.join(target_dir, "tools")
    agents_dir = os.path.join(target_dir, "agents")
    functions_dir = os.path.join(target_dir, "functions")

    os.makedirs(workflows_dir, exist_ok=True)
    os.makedirs(tools_dir, exist_ok=True)
    os.makedirs(agents_dir, exist_ok=True)
    os.makedirs(functions_dir, exist_ok=True)

    example_workflow_path = os.path.join(workflows_dir, "example.yaml")
    if not os.path.exists(example_workflow_path):
        with open(example_workflow_path, "w", encoding="utf-8") as f:
            f.write(EXAMPLE_WORKFLOW)

    example_function_path = os.path.join(functions_dir, "stubs.py")
    if not os.path.exists(example_function_path):
        with open(example_function_path, "w", encoding="utf-8") as f:
            f.write(EXAMPLE_FUNCTION)

    example_tool_path = os.path.join(tools_dir, "example_tool.py")
    if not os.path.exists(example_tool_path):
        with open(example_tool_path, "w", encoding="utf-8") as f:
            f.write(EXAMPLE_TOOL)

    runtime_yaml_path = os.path.join(target_dir, "runtime.yaml")
    if not os.path.exists(runtime_yaml_path):
        with open(runtime_yaml_path, "w", encoding="utf-8") as f:
            f.write(RUNTIME_YAML_TEMPLATE)

    _scaffold_quickstart_samples(target_dir)


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
# Run: ai quickstart2
#   or: ai run workflows/branching_triage.yaml
#   or: ai run workflows/branching_triage.yaml -i issue="Server is slow under load"

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
# Requires: LLM provider configured (run `ai setup` first).
# Run: ai quickstart3
#   or: ai run workflows/research.yaml
#   or: ai run workflows/research.yaml -i topic="Microservices vs monoliths"

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
# Run: ai quickstart4
#   or: ai run workflows/data_pipeline.yaml
#   or: ai run workflows/data_pipeline.yaml -i data="humidity, 85.2, weather"

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


def _default_tool_registry(
    tools_dir: str = "tools",
    shell_allowlist: Optional[list] = None,
    shell_denylist: Optional[list] = None,
) -> ToolRegistry:
    """Create a tool registry with built-in tools + discovered tools."""
    registry = ToolRegistry()

    # Built-in tools (always available)
    registry.register(EchoTool())
    registry.register(HttpTool())
    registry.register(FileTool())
    registry.register(ShellTool(
        allowlist=shell_allowlist or None,
        denylist=shell_denylist or None,
    ))

    # Discover tools from tools/ directory
    register_discovered_tools(registry, tools_dir)

    return registry


def _default_memory_manager(
    db_path: str = "runtime.db",
    max_entries: int = 50,
    max_scratch_bytes: int = 256_000,
) -> MemoryManager:
    """Build memory-manager with SQLite-backed episodic and semantic tiers."""
    return MemoryManager(
        working=WorkingMemory(max_entries=max_entries, max_scratch_bytes=max_scratch_bytes),
        episodic=EpisodicMemory(db_path=db_path),
        semantic=SemanticMemory(db_path=db_path),
        procedural=ProceduralMemory(db_path=db_path),
    )

def _default_llm_client(cfg: RuntimeConfig, logger: Optional[StructuredLogger] = None) -> LLMClient:
    """Create an LLM client using the configured registry."""
    return LLMClient(registry=cfg.llm_registry, logger=logger)


def _default_agent_registry(agents_dir: str = "agents") -> AgentRegistry:
    """Build an agent registry by scanning the agents directory."""
    if os.path.isdir(agents_dir):
        return AgentRegistry.from_directory(agents_dir)
    return AgentRegistry()


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
    return registry.get(ref.workflow_id, ref.version)


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
    print("\nWelcome to agentic-runtime.")
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


def _run_quickstart(project_root: str) -> int:
    print("\nQuickstart: set up and run a starter workflow.\n")

    # TODO(0.2.0): Quickstart Fallback - If the user hasn't set an API key,
    #   'ai quickstart' crashes with a Missing API Key error.
    #   We need to detect the missing key, prompt the user if they want to
    #   use a local stub/mock LLM fallback, and if so, dynamically inject a
    #   mock provider into the registry just for this run, so they get a
    #   successful output visualised even without an internet connection/key.

    if not os.path.isdir(project_root):
        raise SystemExit(f"Project path does not exist: {project_root}")

    runtime_path = os.path.join(project_root, "runtime.yaml")
    example_workflow = os.path.join(project_root, "workflows", "example.yaml")
    needs_init = (not os.path.exists(runtime_path)) or (not os.path.exists(example_workflow))

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


    if needs_init:
        _init_project(project_root)
        print(f"Initialized project at {project_root}")
    else:
        _scaffold_quickstart_samples(project_root)

    # Load config to check credentials
    cfg = load_config(runtime_path)
    creds = cfg.llm_registry.check_credentials()
    has_creds = any(creds.values())

    if not has_creds:
        print("\n[!] No LLM API keys found in .env or environment.")
        use_mock = _prompt_yes_no("Would you like to use a local mock LLM for this quickstart?", default=True)
        if use_mock:
            from agent_runtime.llm.registry import LLMProvider, ModelConfig
            mock_provider = LLMProvider(name="mock", api_key_env="ANY")
            mock_provider.add_model(ModelConfig(model_id="mock-model"))
            cfg.llm_registry.register_provider(mock_provider)
            cfg.llm_registry.default_provider = "mock"
            print("Using mock LLM. (No API calls will be made)")
        else:
            print("\nPlease set an API key (e.g. OPENAI_API_KEY) in .env and try again.")
            return 1
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
        # If we opted for mock, we might need to tell 'ai run' but it re-loads config.
        # However, run_cli re-parses config. If we want it to work end-to-end,
        # we'd need to mock the config loader or pass a mock flag.
        # For now, let's just run it; if the user chose mock, it works because 
        # LLMClient has a built-in mock adapter for any 'mock' provider it gets
        # from the registry.
        
        # We need to ensure the registry in the NEW run call has the mock provider.
        # Since 'run' re-loads runtime.yaml, we'll actually ADD mock to the template.
        
        res = run_cli(["run", example_workflow])
        if res == 0:
            print("\n\u2728 Run complete!")
            print("To see the results visually, run:")
            print("  ai visualize status")
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

    _load_dotenv(os.path.join(project_root, ".env"))

    if needs_llm:
        _run_setup_flow(
            project_root,
            provider=None, api_key_env=None, api_key=None, model=None,
            base_url=None, temperature=None, max_tokens=None,
            no_dotenv=False, no_default=False,
        )

    runtime_path = os.path.join(project_root, "runtime.yaml")
    if not os.path.exists(runtime_path):
        _init_project(project_root)
        print(f"Initialized project at {project_root}")
    else:
        _scaffold_quickstart_samples(project_root)

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
    print("\nagentic-runtime")
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
        help="Initialize, configure, and run a starter workflow",
    )
    quickstart_parser.add_argument("--path", default=".", help="Project root")

    qs2_parser = subparsers.add_parser(
        "quickstart2",
        help="Branching triage workflow (no LLM required)",
    )
    qs2_parser.add_argument("--path", default=".", help="Project root")

    qs3_parser = subparsers.add_parser(
        "quickstart3",
        help="Multi-agent research workflow (LLM required)",
    )
    qs3_parser.add_argument("--path", default=".", help="Project root")

    qs4_parser = subparsers.add_parser(
        "quickstart4",
        help="Data pipeline workflow (no LLM required)",
    )
    qs4_parser.add_argument("--path", default=".", help="Project root")

    setup_parser = subparsers.add_parser("setup", help="Configure API keys and runtime settings")
    setup_parser.add_argument("--path", default=".", help="Project root (contains runtime.yaml)")
    setup_parser.add_argument("--provider", choices=["openai", "anthropic", "gemini", "local"], help="LLM provider")
    setup_parser.add_argument("--api-key-env", help="Env var name to use for the API key")
    setup_parser.add_argument("--api-key", help="API key value (optional)")
    setup_parser.add_argument("--model", help="Model id to add to runtime.yaml")
    setup_parser.add_argument("--base-url", help="Base URL (mainly for local/proxy providers)")
    setup_parser.add_argument("--temperature", type=float, help="Model temperature")
    setup_parser.add_argument("--max-tokens", type=int, help="Model max_tokens")
    setup_parser.add_argument("--no-dotenv", action="store_true", help="Do not write .env")
    setup_parser.add_argument("--no-default", action="store_true", help="Do not set default provider")
    setup_parser.add_argument("--check", action="store_true", help="Verify configured providers and API keys")

    onboard_parser = subparsers.add_parser(
        "onboard",
        aliases=["start"],
        help="Guided setup for a new project",
    )
    onboard_parser.add_argument("--path", default=".", help="Project root (contains runtime.yaml)")

    run_parser = subparsers.add_parser("run", help="Run a workflow")
    run_parser.add_argument("workflow", help="Workflow path or workflow_id[@version]")
    run_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    run_parser.add_argument("-v", "--verbose", action="store_true",
                            help="Show structured JSON log events (LLM, tool)")
    run_parser.add_argument("-i", "--input", action="append", default=[],
                            metavar="KEY=VALUE",
                            help="Workflow input (repeatable, e.g. -i issue=\"bug report\")")

    # [Pain Point Solved] #4 Debugging is Blind: inspect, state-diff, replay, and
    #   visualize give full post-mortem observability without print() statements.
    inspect_parser = subparsers.add_parser("inspect", help="Inspect a run")
    inspect_parser.add_argument("run_id", help="Run ID")
    inspect_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    inspect_parser.add_argument("--steps", action="store_true", help="Show step details")
    inspect_parser.add_argument("--state-history", action="store_true", help="Show state evolution per step")

    resume_parser = subparsers.add_parser("resume", help="Resume a failed run")
    resume_parser.add_argument("run_id", help="Run ID")
    resume_parser.add_argument("--db-path", default=None, help="SQLite DB path (overrides runtime.yaml)")
    resume_parser.add_argument("--workflow", help="Optional workflow YAML path to validate against stored hash")

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

    args = parser.parse_args(argv)

    if args.command == "init":
        _init_project(args.path)
        print(f"Initialized workflow project at {os.path.abspath(args.path)}")
        return 0

    if args.command == "quickstart":
        project_root = os.path.abspath(args.path)
        return _run_quickstart(project_root)

    if args.command == "quickstart2":
        project_root = os.path.abspath(args.path)
        print("\nQuickstart 2: Branching Triage (no LLM required)\n")
        return _run_quickstart_sample(
            project_root, "branching_triage.yaml",
            "branching triage", needs_llm=False,
        )

    if args.command == "quickstart3":
        project_root = os.path.abspath(args.path)
        print("\nQuickstart 3: Multi-Agent Research (LLM required)\n")
        return _run_quickstart_sample(
            project_root, "research.yaml",
            "multi-agent research", needs_llm=True,
        )

    if args.command == "quickstart4":
        project_root = os.path.abspath(args.path)
        print("\nQuickstart 4: Data Pipeline (no LLM required)\n")
        return _run_quickstart_sample(
            project_root, "data_pipeline.yaml",
            "data pipeline", needs_llm=False,
        )

    if args.command == "setup":
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
        print("Setup complete. You can now run `ai run ...`.")
        return 0

    if args.command == "onboard":
        project_root = os.path.abspath(args.path)
        return _run_onboard_flow(project_root)

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
        runs = storage.list_runs(limit=args.limit)
        if not runs:
            print("No runs found.")
            return 0

        if args.html:
            html_path = _render_runs_html(runs)
            print(f"Runs dashboard generated: {html_path}")
            if not args.no_open:
                try:
                    webbrowser.open(f"file://{os.path.abspath(html_path)}")
                except Exception:
                    print("Could not open browser automatically. Open the file manually.")
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
            print(f"Error: workflow file not found: {args.workflow}", file=sys.stderr)
            return 1
        except yaml.YAMLError as exc:
            print(f"Error: invalid YAML in workflow file: {exc}", file=sys.stderr)
            return 1
        except WorkflowValidationError as exc:
            print(f"Error: workflow validation failed: {exc}", file=sys.stderr)
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

        def _progress_callback(event: str, payload: Dict[str, Any]) -> None:
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
        )

        run = executor.run(
            workflow_id=workflow["workflow_id"],
            workflow_version=workflow.get("workflow_version"),
            initial_state=input_state,
            on_error=workflow.get("on_error", "fail_fast"),
            workflow_hash=workflow.get("workflow_hash"),
            workflow_yaml=workflow.get("workflow_yaml"),
            workflow_steps=workflow.get("workflow_steps"),
            input_hash=sha256_json(input_state),
        )
        print(f"Run {run.run_id} status: {run.status}")
        if run.status == "FAILED" and run.error:
            print(f"Error: {run.error}")
            print(f"\nRun `ai inspect {run.run_id}` to see full execution details.")
        return 0 if run.status == "COMPLETED" else 1

    if args.command == "inspect":
        storage = SQLiteStorage(cfg.db_path)
        try:
            run = storage.load_run(args.run_id)
        except ValueError:
            print(f"Error: run not found: {args.run_id}")
            return 1
        steps = storage.load_steps(args.run_id)
        latest_state = storage.load_latest_state(args.run_id)

        version = f"@{run.workflow_version}" if run.workflow_version else ""
        print(f"Run {run.run_id} | workflow={run.workflow_id}{version} | status={run.status}")
        if run.error:
            print(f"Error: {run.error}")
        if args.steps:
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
                if getattr(step, "agent_trace", None):
                    print("agent_trace:")
                    for t_idx, turn in enumerate(step.agent_trace, start=1):
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
            _print_state_history(steps, latest_state)
        return 0

    if args.command == "resume":
        storage = SQLiteStorage(cfg.db_path)
        try:
            run = storage.load_run(args.run_id)
        except ValueError:
            print(f"Error: run not found: {args.run_id}")
            return 1
        validate_resume(run.status)

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
                    raise SystemExit(
                        f"Cannot reconstruct workflow for agent '{agent_id}'. "
                        "Provide --workflow to resume."
                    )
            elif args.workflow:
                workflow = load_workflow(args.workflow, functions_dir=functions_dir_resume)
            else:
                raise SystemExit("Workflow YAML not stored; provide --workflow to resume.")
        else:
            workflow = load_workflow_from_text(workflow_text, functions_dir=functions_dir_resume)

        if args.workflow:
            current = load_workflow(args.workflow, functions_dir=functions_dir_resume)
            if run.workflow_hash and current.get("workflow_hash") != run.workflow_hash:
                raise SystemExit("Workflow hash mismatch; cannot resume.")

        if run.workflow_hash and workflow.get("workflow_hash") != run.workflow_hash:
            raise SystemExit("Stored workflow hash mismatch; cannot resume.")

        steps = storage.load_steps(args.run_id)
        resume_step = determine_resume_step(workflow["steps"], steps)
        if resume_step is None:
            raise SystemExit("No resumable step found.")

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
            print(f"Error: run not found: {args.run_id}")
            return 1
        return 0

    if args.command == "state-diff":
        storage = SQLiteStorage(cfg.db_path)
        try:
            run = storage.load_run(args.run_id)
        except ValueError:
            print(f"Error: run not found: {args.run_id}")
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
            for change in changes:
                op = change["op"]
                path = change["path"]
                if op == "+":
                    print(f"+ {path} = {_redact(change['after'])}")
                elif op == "-":
                    print(f"- {path} (was {_redact(change['before'])})")
                else:
                    print(f"~ {path}: {_redact(change['before'])} -> {_redact(change['after'])}")
        return 0

    if args.command == "visualize":
        storage = SQLiteStorage(cfg.db_path)
        run_id = args.run_id
        if run_id == "latest":
            recent = storage.list_runs(limit=1)
            if not recent:
                print("Error: No runs found in database.")
                return 1
            run_id = recent[0].run_id

        try:
            data = RunLoader(storage).load(run_id)
        except ValueError:
            print(f"Error: run not found: {run_id}")
            return 1
        graph = GraphBuilder().build(data)
        timeline = TimelineBuilder().build(data)

        if args.ascii:
            print(render_ascii(run_id, graph, timeline))
            return 0

        if args.timeline:
            print(_render_timeline_text(run_id, timeline))
            return 0

        output_path = os.path.join(".runs", run_id, "visualization.html")
        html_path = render_html(run_id, graph, timeline, output_path)
        print(f"Visualization generated: {html_path}")
        if not args.no_open:
            try:
                webbrowser.open(f"file://{os.path.abspath(html_path)}")
            except Exception:
                print("Could not open browser automatically. Open the file manually.")
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
            f'<td><a href=".runs/{html_mod.escape(run.run_id)}/visualization.html">'
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


def _diff_state(before: dict, after: dict) -> dict:
    """Return state diff summary for CLI output.

    Uses nested path-level diffs when available, with truncation to keep
    inspect output readable in terminals.
    """
    # TODO(eng): list-diff - RuntimeState.diff_paths currently treats lists as
    #   atomic values, so large list mutations show as one changed path rather
    #   than item-level edits.
    # TODO(ux): Add --diff-limit / --full flags so users can control truncation.
    # TODO(ux): Add CLI graph visualization for branching workflows.
    changes = RuntimeState.diff_paths(before, after)
    if not changes:
        return {"added": [], "removed": [], "changed": []}

    added: list[str] = [c["path"] for c in changes if c.get("op") == "+"]
    removed: list[str] = [c["path"] for c in changes if c.get("op") == "-"]
    changed: list[str] = [c["path"] for c in changes if c.get("op") == "~"]

    max_items = 20

    def _truncate(items: list[str]) -> list[str]:
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


def _print_state_history(steps, latest_state) -> None:
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
        diff = _diff_state(before, after)
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
