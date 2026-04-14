You are updating repository Copilot context files. Perform a full `.copilot` refresh now.

Goal:
- Make `.copilot` an accurate, current snapshot for the next session.

Required actions:
1. Read and reconcile against:
   - README.md
   - planning/vision/todos.md
   - documentation/about/architecture.md
   - documentation/changelog/CHANGELOG_2026-03-31.md

2. Update these files in place:
   - .copilot/instructions.md
   - .copilot/project_context.md
   - .copilot/session_state.md
   - .copilot/working_set.md
   - .copilot/resume_prompt.md

3. If a meaningful design/process decision was made during this refresh, append one ADR entry to:
   - .copilot/architecture_decisions.md

4. Enforce TODO taxonomy consistency with planning/vision/todos.md.
   Allowed tags:
   - TODO(roadmap): ...
   - TODO(pain-point): ...
   - TODO(ux): ...
   - TODO(security): ...
   - TODO(eng): ...
   - optional milestone tag (example: TODO(0.2.0): ...)

5. Include environment guidance in updated context files:
   - Prefer conda env `wa-data` if available in this workspace
   - Fallback to project-default `agent_runtime`

Output format (required):
SECTION 1 - Updated files summary
SECTION 2 - session_state.md content
SECTION 3 - working_set.md content
SECTION 4 - resume prompt text
SECTION 5 - ADR entry added (or "none")
SECTION 6 - follow-up risks/actions

Rules:
- Do not change runtime behavior code unless explicitly required to keep context accurate.
- Keep edits concise, concrete, and internally consistent across all `.copilot` files.
- If a fact cannot be verified from repository sources, mark it as "unverified" instead of guessing.
