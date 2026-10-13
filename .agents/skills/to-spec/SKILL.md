---
name: to-spec
description: "Turn an established request or discussion into a concise implementation specification."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Write a Clarify specification

Synthesize the current request, accepted decisions, and verified code context. Research facts rather than interviewing the user again about decisions already made.

Include:
- User problem and observable outcome.
- Acceptance criteria and compatibility.
- Changed responsibilities, interfaces, effects, and data ownership.
- Validation boundary and Windows acceptance where needed.
- Out-of-scope work and unresolved decisions.

Use actual paths as navigation pointers when helpful; do not treat line numbers as durable contracts. Keep the spec proportional to the work. A small fix can use the PR description instead of a new file.

Save a requested durable local spec under `docs/agents/plans/<slug>/spec.md`. Follow [tracker rules](../../../docs/agents/issue-tracker.md) if publication was explicitly requested. Publishing is separate from writing a draft. Technical test-boundary choices do not need user approval. Do not invent acceptance criteria to fill an extensive user-story template.
