We are continuing development but switching to a fresh Copilot chat session.

Your job is to generate an updated context snapshot so the next chat can resume work quickly.

Update or generate the following files:

1. .copilot/session_state.md
Include:
- current feature or task
- progress completed
- files modified in this session
- design decisions made
- remaining work
- known issues

2. .copilot/working_set.md
Include:
- focus area
- relevant modules
- key files currently being edited
- related tests or dependencies

3. Generate a short resume prompt for the next chat session.

The resume prompt must instruct the next chat to read:
- .copilot/project_context.md
- .copilot/session_state.md
- .copilot/working_set.md

Output format:

SECTION 1 — Updated session_state.md  
SECTION 2 — Updated working_set.md  
SECTION 3 — Resume prompt for next chat

Keep the output structured.