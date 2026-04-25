# **Knowledge Base**

This page is a **conceptual overview** of ForrestRun — the architecture, the building blocks, and how they fit together. Nothing here tells you *how* to write code; for that, head to the [Manual](manual.md).

---

## **The System Architecture**

At its core, ForrestRun is an embeddable orchestration library. It bridges the gap between static definitions and dynamic AI execution.

```mermaid
graph TD
    User([User]) -->|Inputs| Runtime{Runtime}
    Runtime -->|Load| W[Workflow YAML]
    W -->|Iterate| Steps{Steps}
    
    Steps -->|Type: Agent| A[["[[i!Agent]]"]]
    Steps -->|Type: Function| F[["[[b!Function]]"]]
    Steps -->|Type: Tool| T[["[[Tool]]"]]
    
    A -->|LLM Pipeline| R1[Result]
    F -->|Python Code| R2[Result]
    T -->|External Action| R3[Result]
    
    R1 & R2 & R3 -->|Update| State[(State)]
    Runtime -.->|Persist| DB[(SQLite)]
```

---

## **Core Building Blocks**

Every solution in the runtime is built using these five essential primitives:

| Block | Role | Integration |
| :--- | :--- | :--- |
| [[i!Workflow]] | The YAML "Recipe" | Describes the sequence of operations. |
| [[i!Agent]] | LLM-backed Intel | Powers complex reasoning and decision making. |
| [[b!Function]] | Python Logic | Executes pre-defined, deterministic code blocks. |
| [[pill!Tool]] | External Bridge | Connects the runtime to APIs, databases, or local files. |
| [[b!State]] | Memory Layer | The thread of data that weaves through every step. |

---

## **Workflow vs. Agent Definitions**

It is important to distinguish between the **Orchestra** (Workflow) and the **Performer** (Agent).

::::tabs
:::tab [[i!Workflow Definition]]
Located in `workflows/`.
- **Purpose**: Defines the inputs, the sequence of steps, and the data mapping between them.
- **Analogy**: The script of a play.
:::
:::tab [[i!Agent Definition]]
Located in `agents/`.
- **Purpose**: Describes a specific AI's personality, model choice (e.g., GPT-4, Claude), and the specific tools it has access to.
- **Analogy**: The actor playing a specific role.
::::

---

## **How They Tie Together**

1. **Initialization**: You provide a [[i!Workflow]] and initial inputs.
2. **Registry Building**: The runtime loads the YAML and builds a registry of all referenced [[b!Function]]s and [[pill!Tool]]s.
3. **Step Execution**: 
   - For an `agent` step, the runtime resolves the [[i!Agent]] definition and triggers its LLM pipeline.
   - For a `function` step, it triggers a direct Python call.
   - For a `tool` step, it executes the [[pill!Tool]]'s `execute()` method with the provided context.
4. **State Persistence**: After every successful step, the [[b!State]] is updated and a snapshot is saved to the [[i!Run]] record in SQLite.

---

## **Next Steps**

Now that you understand the architecture, move on to a hands-on page:

- [Manual](manual.md) — CLI commands, YAML syntax, code examples, and error reference.
- [Getting Started](getting-started.md) — From zero to your first run.
- [Writing Agents](writing-agents.md) — How to define LLM-backed agents.
- [Writing Functions](writing-functions.md) — Deterministic Python logic steps.
- [Writing Tools](writing-tools.md) — External action steps.
