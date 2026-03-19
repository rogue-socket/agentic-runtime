"""Example tool module.

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
        priority_block = f"\n\n## Priority\n{priority}" if priority else ""
        report = (
            f"# {title}\n\n"
            f"## Summary\n{summary}"
            f"{priority_block}\n\n"
            f"## Next Steps\n{next_steps}\n"
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
