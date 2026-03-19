# Onboarding Walkthrough

This walkthrough is a guided path for a first-time user, designed to match
the "single-command onboarding" style common in modern CLIs. It pairs a
quickstart wizard with optional manual steps for folks who prefer scripts.

## Quickstart (Interactive)

If you do not have a project folder yet, create one first:

```bash
mkdir my-agent
cd my-agent
```

Run either of the following in your project root:

```bash
ai
```

or:

```bash
ai onboard
```

The home screen will offer numbered actions; choose **Guided setup** to launch the wizard.

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

Removed — use `ai onboard` for the guided flow.
