# The Runtime That Remembers

There is a predictable point where many AI projects stop feeling impressive and start feeling fragile. It is rarely the first bad answer. Engineers can tolerate a mediocre summary or a slightly off classification. The real break happens later, when a run fails halfway through, a tool has already fired, the process restarts, and nobody can say with confidence what actually happened.

Did the model choose a different branch than last time? Did a retry repeat an external action? Did one step quietly overwrite something another step needed? Was the bug in the prompt, the orchestration, the provider, the tool, or the state that drifted three steps earlier? In a lot of agent systems, those questions have to be answered from logs, vibes, and memory.

What makes that moment so corrosive is not merely that the system failed. Software fails all the time. It is that the failure leaves behind an argument with no shared evidence. One person remembers the prompt differently. Another trusts the provider less. A third suspects the tool wrapper. Someone reruns the pipeline and gets a different branch, which only deepens the confusion. The system has become theatrical in the worst sense: full of effects, short on facts.

This repository is interesting because it is built around the claim that this is the wrong place to be clever. The novelty is not supposed to live in hidden chain-of-thought or in a bigger stack of abstractions. It lives in turning agent execution into something that behaves like software with custody: durable, inspectable, resumable, replayable.

That is why the center of gravity here is not the prompt, and not even the agent. It is the run.

Seen from a distance, that may sound almost conservative, as though the project were choosing administration over invention. But that is precisely what makes it worth reading closely. Most of the pain in production AI does not come from a shortage of expressive power. It comes from an excess of events that cannot be reconstructed. This runtime is built on the suspicion that intelligence, once operationalized, becomes a logistics problem.

![Conceptual architecture of the runtime](https://quickchart.io/graphviz?graph=digraph%20G%20%7B%20rankdir%3DLR%3B%20Workflow_YAML%20-%3E%20Executor%3B%20Executor%20-%3E%20Agent_Steps%3B%20Executor%20-%3E%20Function_Steps%3B%20Executor%20-%3E%20Tool_Steps%3B%20Agent_Steps%20-%3E%20LLM_Adapters%3B%20Executor%20-%3E%20SQLite_History%3B%20Executor%20-%3E%20Memory_Tiers%3B%20%7D)

## The workflow as the unit of order

One of the most consequential decisions in the codebase is easy to miss because it can sound like mere structure. The workflow is the primary unit of order, and the agent is one kind of capability the workflow can call.

That can sound like a dry architectural distinction until you place it in the broader evolution of developer systems. The first version of a technology is usually organized around whatever first made the magic possible: a script, a library call, a wrapper, a clever abstraction that gets the demo across the line. Later, when people try to operate that same technology repeatedly, under pressure, with retries and side effects and accountability, the center of gravity moves. The important question stops being "what can generate an answer?" and becomes "what owns order?"

In a real incident-response organization, the playbook is the thing that owns the process. The specialists do not own the incident. The database person, the on-call engineer, the support lead, and the comms person are all invoked by the playbook at different moments for different reasons. The playbook determines order, branching, escalation, and retry. The specialists provide capability.

This runtime has adopted exactly that model.

Workflows describe orchestration in YAML. They decide what happens first, what happens next, what data each step reads, and where branching occurs. Inside those workflows, the system recognizes three kinds of work: agent steps for LLM-backed reasoning, function steps for deterministic Python logic, and tool steps for external side effects. That separation is not cosmetic. It is an ownership model.

Most agent frameworks eventually blur these categories. Everything becomes "a chain" or "a node" or "an action," which looks flexible until you need to debug a production failure. Here, the dispatch paths are intentionally different because the failure modes are different. A Python function is not an LLM call. An LLM call is not a shell command. A shell command is not a state transform. The runtime refuses to flatten those distinctions.

Even the onboarding flow hints at that taste. The branching quickstart can run without an API key. That is not just a convenience feature. It is a product statement. The first success path is designed to prove the execution model before it asks you to trust the model.

## The ledger hidden inside the workflow engine

The boldest design choice in this repository is that it treats execution history as a first-class artifact rather than as exhaust.

The executor does not simply run a step and move on. Around each step it captures a state snapshot before execution, materializes the step input, dispatches the work, validates the output, captures the post-step state, records timing and retry metadata, notes the resolved next step, and persists the whole thing to SQLite. The step is not just something that happened. It becomes a record.

That record is surprisingly rich. A persisted step can carry status, input, output, error details, attempt count, timing, token usage, model name, agent trace, branch target, and side-effect metadata. The run itself stores the workflow id, version, workflow hash, serialized workflow YAML, and state history. By the time a run finishes, the runtime has not merely produced a result. It has assembled a case file.

The state model is what keeps that case file readable. State is namespaced into `inputs`, `steps`, and `runtime`. Each step writes under `steps.<step_id>`. Memory tiers hydrate under `runtime.memory.<tier>`. This is simple enough to explain in one sentence and strict enough to matter. It prevents the usual pipeline disease where multiple components treat a shared dictionary like public sidewalk.

There is real product taste in the contract system too. A step can declare what it reads and what it writes. The workflow loader catches future reads before execution starts. Runtime enforcement catches missing or undeclared outputs at the step boundary. This means the YAML is not merely configuration; it is an interface contract between pieces of work.

That is the deeper idea embodied by the parser and executor: the system is trying to replace implicit coordination with explicit handoffs.

## A runtime is a theory of blame

Every serious runtime carries, whether it admits it or not, a theory of blame. Not blame in the moralizing sense, and not the bureaucratic sense either. The useful kind of blame is simply the ability to say where a system changed, why it changed, and what evidence supports that story.

Most agent stacks are weak here. They can often tell you that a run failed, sometimes even which call raised an exception, but they struggle to tell a disciplined causal story about the route by which the failure became inevitable. By the time an engineer arrives, the scene has already been trampled. State has been mutated in place. Logs are scattered across libraries. The model call is opaque. A retry may already have altered the ground under investigation.

This codebase keeps resisting that collapse into fog. `state_before` and `state_after` are not incidental debug details. `next_step_resolved` is not just a convenience field. Attempt counts, side-effect metadata, workflow hashes, and persisted traces all serve the same larger purpose: they give uncertainty somewhere specific to go. When something strange happens, the runtime does not ask an operator to remember. It asks the record.

That is a more literary idea than it first appears, because it turns execution into narrative without turning it into myth. The run becomes readable precisely because it is constrained. It has chapters, witnesses, timestamps, and a chain of custody. It does not need to be romantic to be legible.

![How a step becomes a persisted artifact](https://quickchart.io/graphviz?graph=digraph%20G%20%7B%20rankdir%3DLR%3B%20state_before%20-%3E%20step_input%20-%3E%20StepExecution%3B%20StepExecution%20-%3E%20state_after%3B%20StepExecution%20-%3E%20persisted_trace%3B%20state_after%20-%3E%20state_versions%3B%20%7D)

## Why SQLite is not the embarrassing part

A lot of systems treat SQLite as an early-stage compromise. This codebase treats it more like a deliberate bet.

That bet makes sense. The runtime is local-first. It wants durability, atomicity, and an inspectable source of truth without forcing users into a server product on day one. So the storage layer leans into SQLite's strengths: a single file, explicit transactions, WAL mode, foreign keys, versioned state snapshots, and a schema that is expressive enough to hold both execution history and the memory tiers.

Once you see that, features like resume and replay stop looking like separate capabilities. They are just consequences of the storage model.

Resume works because the runtime has enough historical structure to know where execution stopped and what state boundary is safe to continue from. It also refuses to resume blindly. The stored workflow hash is compared to the current workflow, and if the definition has changed, the runtime declines to continue. That is a subtle but serious decision. A weaker system would call that flexibility. This one calls it corruption risk.

Replay is even more revealing. It does not re-run tools. It does not call the model again. It reconstructs a run from persisted state transitions and can verify that the reconstructed pre-step state matches what was recorded originally. In other words, replay here is not an imitation of the past. It is an audit of the recorded past.

This is where the runtime starts to feel less like an agent toy and more like a warehouse operation. Every handoff gets scanned. Every package movement leaves a timestamp. If something breaks on station five, you do not rerun the whole building and hope for the best. You resume from the last trustworthy checkpoint, and if you want to understand what happened yesterday, you inspect the scans rather than reenact the shift.

![Recovery is built from persisted checkpoints, not optimism](https://quickchart.io/graphviz?graph=digraph%20G%20%7B%20rankdir%3DLR%3B%20Run_Start%20-%3E%20Persisted_Checkpoint%20-%3E%20Step_Failure%3B%20Step_Failure%20-%3E%20Resume%3B%20Step_Failure%20-%3E%20Replay%3B%20Resume%20-%3E%20Workflow_Hash_Lock%3B%20Replay%20-%3E%20No_Reexecution%3B%20%7D)

## Contained chaos: what the runtime does with LLM behavior

The system is not naive about models. It knows they are the least reliable part of the stack, so it tries hard to contain their mess instead of pretending to eliminate it.

Agent definitions are where that containment happens. An agent can have its own prompt, strategy, tools, and internal pipeline. The workflow sees only an agent step with declared inputs and outputs. Inside that boundary, the agent executor can run a single-pass pipeline or a ReAct loop, auto-inject tool descriptions, parse tool calls, aggregate token usage, and capture a turn-by-turn trace.

That separation matters. The workflow layer stays declarative and stable while the messy business of model interaction is quarantined behind an explicit step type. The non-determinism is real, but it is localized.

There is also restraint in the adapter layer. The project makes a point of using stdlib `urllib` instead of accumulating HTTP dependencies. On the surface that looks like asceticism. In practice it reinforces the repo's broader sensibility: keep the runtime thin, explicit, and portable; do not let infrastructure convenience become framework sprawl.

The same attitude shows up in the LLM limits. Request counts, token totals, cost ceilings, and rate limits are modeled in the client path rather than scattered through application code. This is another example of the runtime doing the unglamorous but essential work. Prompt engineering gets attention; budget enforcement pays the bills.

The code reviewer agent is a good illustration. It uses a ReAct strategy, has an explicit allowlist of tools, and carries versioned prompts. That sounds familiar if you have used other agent stacks. What is different here is that the workflow runtime around it insists on receipts: execution index, attempt counts, traces, branch resolution, and persisted state. The model is allowed to improvise, but not to disappear.

## Memory here means institution, not mysticism

Many AI systems talk about memory as if it were a mystical upgrade. This repository is more sober, and because of that, more persuasive.

Its four memory tiers map neatly onto the way a competent team actually accumulates knowledge. Working memory is the whiteboard for the current incident: bounded scratch space, recent entries, active task context. Episodic memory is the incident archive: what happened in past runs, under which workflow, with what outcome. Semantic memory is the searchable internal wiki: durable facts with tags, metadata, and full-text search. Procedural memory is the runbook layer: the rules and playbooks that should emerge from repeated experience.

The beautiful part is not just that these tiers exist. It is that they are kept in their own namespace under `runtime.memory` and are hydrated and persisted by a coordinator instead of being smeared directly into the workflow state. The system is saying that cross-run knowledge is important, but it must not be allowed to contaminate step ownership.

There is also an honesty to the implementation that makes the design more trustworthy. Semantic memory is not pretending to be a vector database when it is not. It is a SQLite-backed fact store with FTS5, tag retrieval, and CRUD. Procedural memory is not pretending to be automated organizational learning when it is not. It is explicitly still a stub.

That honesty matters because it keeps the reader from confusing the architecture with a wish list. The memory model is useful today because it is concrete. It is also credible tomorrow because the missing pieces are named plainly rather than hidden behind marketing language.

## The most surprising idea: history becomes a testing surface

The cleverest thing in the repository may be that it keeps turning runtime history into engineering leverage.

Replay is the obvious example. A completed run can become a golden fixture. Historical state can be re-verified. Model changes can be compared step by step. But the more novel example is branch coverage.

Because the runtime persists `next_step_resolved`, the system can analyze which declared branch targets have actually been exercised across prior runs. That is an unusually sharp idea. It treats workflow control flow the way developers already treat code paths in tests. Not every branch that exists has been lived through. The runtime can tell you which paths are still theoretical.

That is the moment where the repo stops being merely operational and becomes epistemic. It is not only executing workflows; it is measuring how much of their behavior the team has actually seen.

![Persisted branch targets turn history into coverage](https://quickchart.io/graphviz?graph=digraph%20G%20%7B%20rankdir%3DLR%3B%20classify%20-%3E%20escalate%20%5Blabel%3D%22covered%22%5D%3B%20classify%20-%3E%20close%20%5Blabel%3D%22untested%22%2C%20style%3Ddashed%5D%3B%20%7D)

Once you notice that pattern, other choices in the codebase click into place. Visualization is not decoration. State diffs are not convenience output. The ASCII and HTML views, the inspection paths, the replay verifier, the transaction safety tests, the workflow hash lock, and the rich step record all belong to the same worldview: if an agent system matters, its history must become a usable engineering surface.

## What the system refuses to do, and why that makes it stronger

Every technical stack eventually reaches a point where adding power and preserving clarity start pulling in different directions. Early generations of tooling usually chase breadth. They expand the menu, widen the abstraction, promise one more layer of convenience. Mature infrastructure has to learn a harsher lesson: every new degree of freedom has a carrying cost, and some guarantees weaken the moment the surface area becomes too eager.

That is why this system resists several fashionable expansions. It does not chase full DAG execution. The core loop is pointer-based and sequential, with branching but no general fan-out or fan-in. It does not pretend to be a multi-tenant platform. It does not wrap itself in a hosted dashboard story. It does not try to be a compatibility layer for every existing agent framework. Even discovery is a little conservative and uneven: some registries scan shallowly, functions scan recursively, and direct file-path execution remains more capable than some registry lookups.

Those are real limits. They matter. But they also reveal discipline.

A runtime that wants strong replay, clean resume semantics, clear state ownership, and comprehensible local debugging has to be careful about where it introduces complexity. Parallelism, distributed execution, richer expression languages, and automatic memory extraction all have their place in the longer arc of systems development. But there is a difference between features that enlarge a platform and features that deepen a contract. This runtime is far more interested in the second category.

You can feel that discipline in the tests. There are tests for replay not re-executing tools, for transactional rollback, for branch coverage, for workflow integrity on resume, for output contracts, for safe evaluation. This is a repo that understands its product surface is not just the CLI. It is the set of promises an engineer can build against.

## Why this codebase is more interesting than a better prompt

The deepest idea embodied by this system is that the hard problem in agentic software is not generating a next token. It is governing a sequence of irreversible or expensive acts in a way that other engineers can trust.

That is why this project feels different from a lot of AI infrastructure. It is not organized around the fantasy that agents are autonomous minds waiting to be unleashed. It is organized around a more mature question: what would it take to make agentic work look like something a production team could own?

The answer, in this codebase, is surprisingly concrete. Let the workflow orchestrate and the agent become a component rather than a sovereign container. Separate reasoning, deterministic logic, and side effects so that each can fail according to its own nature. Give state an ownership model. Persist the run as if someone will eventually have to argue about it in good faith. Treat replay and resume as consequences of storage rather than as magic tricks. Keep memory honest. Turn history into a testing surface. Refuse the kinds of convenience that would dissolve those guarantees the moment the system comes under pressure.

Once you see the system through that lens, the repo stops looking like a toolkit and starts looking like an argument. It is arguing that AI workflows do not need more mystique. They need better administration. They need receipts, checkpoints, contracts, and traceability. They need the boring virtues that every serious software system eventually rediscovers.

That is why this runtime is compelling. It does not ask you to believe that agents will become reliable on their own. It asks a better question, and a more durable one: what if reliability came not from making the agent more dramatic, but from making the surrounding system more answerable? That is the quiet ambition written through this repository. Not artificial genius, but accountable execution. Not spectacle, but memory.