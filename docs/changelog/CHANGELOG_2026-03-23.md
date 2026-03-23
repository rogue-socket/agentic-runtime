# Changelog — 2026-03-23

## Orchestration & Agent Runtime

- **ReAct Context Amnesia Fix**:
  Resolved a critical issue where ReAct iterations failed to inject tool outputs and observations into context on subsequent loops. This issue was resolved by refactoring the `LLMAdapter` protocol and downstream providers (`OpenAIAdapter`, `AnthropicAdapter`, `GeminiAdapter`) to natively accept and process a structured `history` array. The framework now dynamically assembles conversation history across iterations dynamically over native JSON schema, as opposed to concatenating strings into a scratchpad text block.

- **Scoped Globbing for Runtime Loaders**:
  Fixed an environment bleed bug that caused duplicate definition validation errors (`Duplicate workflow version`) when workflows or agents lived inside deep nested template subdirectories that shadowed standard paths. `WorkflowRegistry.from_directory` and `AgentRegistry.from_directory` now limit their glob search strictly to the direct root parameter of the module without recursing blindly via decorators, bounding namespace contexts safely.

- **Explicit Key Pathing for Workflow Binding**:
  Clarified the behavior surrounding step communication within orchestration pipelines. Variables defined by downstream YAML blocks mapping off of an agent (`inputs: \n  message: steps.my_agent.status`) strictly require three-segment mappings. Passing unrestricted dictionaries will trigger `WorkflowValidationError`. The workflow codebase was annotated properly detailing restrictions and mapping rules.
