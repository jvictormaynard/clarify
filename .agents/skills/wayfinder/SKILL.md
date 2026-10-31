---
name: wayfinder
description: "Map unresolved decisions for a large multi-session effort whose implementation route is unclear."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Map a large Clarify effort

Use this only when unresolved architecture or product decisions prevent a reliable implementation plan. A concrete feature should proceed through delivery directly.

Define the destination, scope, known decisions, unresolved questions, and dependencies. Keep the map in the conversation or an OS temporary file under the workflow's [file retention rules](../../../docs/agents/workflow.md#files-and-evidence). Each decision note states the question, evidence needed, alternatives, and resolution.

Resolve technical facts from source or primary documentation. Prototype only questions that need runtime evidence. Ask the user for product decisions that cannot be inferred. Track which questions are unblocked; resolve as many as the authorized task and evidence allow, with no fixed one-ticket-per-session restriction.

Link each decision's source and avoid copying its full detail into the map. Once the route is clear, create a concise spec or implementation slices if useful, then continue an authorized implementation. A planning-only request ends with the map and open decisions.

Use [tracker rules](../../../docs/agents/issue-tracker.md) for external publication. Do not create tasks, agents, services, or accounts merely because the map names them.
