#!/usr/bin/env python3
"""Minimal ForrestRun example — inline YAML workflow with RuntimeBuilder.

No external dependencies, no API keys needed. Uses tools.echo for output.
Uses in-memory SQLite to keep everything self-contained.
"""

from forrestrun import RuntimeBuilder

WORKFLOW = """
schema_version: v1
workflow:
  id: hello_world
  version: v1

inputs:
  name:
    description: Name to greet
    default: "World"

steps:
  - id: greet
    type: tool
    tool: tools.echo
    inputs:
      message: inputs.name

  - id: info
    type: tool
    tool: tools.echo
    inputs:
      message: "Welcome to ForrestRun — an embeddable workflow engine for AI agents."
"""

if __name__ == "__main__":
    with RuntimeBuilder().with_db_path(":memory:").build() as runtime:
        result = runtime.run(WORKFLOW, inputs={"name": "Developer"})
        print("\n✓ Workflow completed successfully!")
        print(f"Run ID: {result.run_id}")
        print(f"Status: {result.status}")
        print(f"\nStep outputs:")
        for step_id in result.step_names:
            output = result.get_output(step_id)
            if output:
                print(f"  {step_id}: {output}")
