You are joining an ongoing development session for this repository.

Your task is to reconstruct the development context before writing any code.

Steps:

1. Read the following files:
   - .copilot/project_context.md
   - .copilot/session_state.md
   - .copilot/working_set.md
   - .copilot/architecture_decisions.md
   - vision/todos.md

2. Optionally skim for recent changes:
   - docs/changelog/CHANGELOG_2026-03-23.md (latest)
   - docs/changelog/CHANGELOG_2026-03-20.md
   - docs/about/gaps_2026-03-17.md

3. Build a concise understanding of:
   - overall project architecture
   - current feature/task being worked on
   - relevant modules and files
   - current progress
   - outstanding issues
   - next recommended step

4. Output a short structured summary:

Project Summary
Current Feature
Relevant Files
Progress
Open Problems
Next Step

5. Ask clarification questions if context is missing.

Rules:
- Do NOT implement code yet.
- Do NOT assume architecture not described in the context files.
- Assume conda env `agent_runtime` is the canonical local Python environment.
- The runtime uses Python 3.10+, async-first internals with sync CLI wrappers.
- All state goes through RuntimeState with namespaced paths (inputs.*/steps.*/runtime.*).
- All persistence goes through the Storage ABC — never access SQLite directly.
- Primary step types are `agent`, `function`, and `tool`; `model` is deprecated compatibility only.
- All tools implement the Tool protocol.
- Memory tiers hydrate under runtime.memory.<tier> — never mutate inputs/steps from memory.
- If proposing deferred or partial implementation work, require inline TODOs using repo categories from vision/todos.md: `roadmap`, `pain-point`, `ux`, `security`, `eng`.