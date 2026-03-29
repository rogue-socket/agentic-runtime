# Onboarding Walkthrough

This walkthrough is a guided path for a first-time user, designed to match
the "single-command onboarding" style common in modern CLIs. It pairs a
quickstart wizard with optional manual steps for folks who prefer scripts.

## Quickstart (Golden Path)

If you do not have a project folder yet, create one first:

```bash
mkdir my-agent
cd my-agent
```

Run this in your project root:

```bash
ai quickstart
```

If you do not have an API key yet:

```bash
ai quickstart --sample branching
```

Optional guided mode is still available with:

```bash
ai onboard
```

The wizard and quickstart both initialize project structure and walk provider setup.

The wizard will:
1. Initialize the project structure if missing.
2. Configure an LLM provider and API key.
3. Offer to run a sample workflow.

## Visual Walkthrough

```mermaid
flowchart TD
  A["Start: User runs `ai` or `ai onboard`"] --> B{"runtime.yaml exists?"}
  B -- No --> C["Initialize project structure"]
  B -- Yes --> D["Load .env and continue"]
  C --> D
  D --> E["Choose provider + enter API key"]
  E --> F["Write .env + update runtime.yaml"]
  F --> G{"Run sample now?"}
  G -- Yes --> H["Run provider-specific sample workflow"]
  G -- No --> I["Show next steps + commands"]
  H --> J["Inspect + visualize run"]
  I --> J
```

## Scripted Walkthrough

Removed — use `ai onboard` or `ai quickstart` for the guided flow.
