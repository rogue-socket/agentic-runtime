We are ending the development session for now.

Create a complete checkpoint of the current project state.

Tasks:

1. Update .copilot/session_state.md with:
   - feature being worked on
   - progress made in this session
   - files modified
   - key implementation details
   - active local environment context (include conda env `agent_runtime`)
   - remaining tasks
   - known bugs or issues
   - recommended next steps

2. Update .copilot/working_set.md to reflect the most relevant files for the next session.

3. If architectural or design decisions were made, append them to:
   .copilot/architecture_decisions.md

Each decision should include:
- decision
- context
- reasoning
- implications

4. Capture TODO follow-ups using repo taxonomy from `planning/vision/todos.md`.
For any deferred work from this session, require categorized TODO format in notes/code:
- `TODO(roadmap): ...`
- `TODO(pain-point): ...`
- `TODO(ux): ...`
- `TODO(security): ...`
- `TODO(eng): ...`
- or explicit milestone tags like `TODO(0.2.0): ...`

5. Generate a short "next session bootstrap prompt" that can be pasted into a new Copilot chat.

Include these references in your checkpoint context:
- `documentation/changelog/CHANGELOG_2026-03-31.md`
- `documentation/about/architecture.md`
- `planning/vision/todos.md`

Environment context:
- Prefer `wa-data` in this workspace when available; fallback to `agent_runtime`.

Output format:

SECTION 1 — Updated session_state.md  
SECTION 2 — Updated working_set.md  
SECTION 3 — Architecture decisions (if any)  
SECTION 4 — Bootstrap prompt for next session