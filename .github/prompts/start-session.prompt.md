You are joining an ongoing development session for this repository.

Your task is to reconstruct the development context before writing any code.

Steps:

1. Read the following files:
   - .copilot/project_context.md
   - .copilot/session_state.md
   - .copilot/working_set.md
   - .copilot/architecture_decisions.md

2. Optionally skim for recent changes:
   - docs/CHANGELOG_2026-03-18.md (latest)
   - docs/CHANGELOG_2026-03-17.md
   - docs/GAPS_2026-03-17.md

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
- The runtime uses Python 3.10+, async-first internals with sync CLI wrappers.
- All state goes through RuntimeState with namespaced paths (inputs.*/steps.*/runtime.*).
- All persistence goes through the Storage ABC — never access SQLite directly.
- All tools implement the Tool protocol; all handlers are Callable[[RuntimeState], dict].
- Memory tiers hydrate under runtime.memory.<tier> — never mutate inputs/steps from memory.