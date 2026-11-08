---
name: grilling
description: "Resolve consequential product ambiguity or stress-test a design when the user requests an interview."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Resolve consequential ambiguity

Inspect the repository and current request before asking questions. Finding technical facts, choosing a focused test boundary, and making routine implementation decisions are the agent's work.

For a requested design interview, test assumptions against concrete project scenarios.
Use `domain-modeling` only when an accepted decision needs a durable record.

Name the unresolved decision and explain how each answer changes behavior, data, compatibility, scope, or a costly architecture choice. Provide a recommendation supported by evidence. Ask a small set of independent questions; use the available user-input tool when it helps.

While waiting, continue work that does not depend on the answer. Do not treat silence as approval for a required decision. For a low-impact reversible choice, state a reasonable assumption and proceed within authorized scope.

Recompute open decisions after each answer. The session is sufficient when the requested work has clear acceptance criteria and remaining assumptions are safe and stated. Exhaustive interviews and confirmation of shared understanding are not mandatory steps.
