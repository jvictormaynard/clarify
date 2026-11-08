---
name: to-tickets
description: "Split a large accepted plan into verifiable implementation slices with real blocking dependencies."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Split Clarify work into tickets

Read the source plan or issue, including comments and dependencies. Inspect current code when it determines what can land safely.

Prefer complete vertical slices: each should deliver or verify one behavior across the relevant Python, Qt, Settings, and test boundaries. Add a preparation refactor only when it enables the actual change.

For a broad compatibility change, use expand, migrate, then contract so intermediate commits can remain valid. Keep destructive migration or compatibility removal explicit.

Each ticket needs an outcome, acceptance criteria, validation, and blocking dependencies. Include a parent source and current code pointers when useful. A dependency exists only when another ticket's result is required; shared filenames alone do not imply one.

Return local drafts in the conversation or an OS temporary directory. Follow [file retention](../../../docs/agents/workflow.md#files-and-evidence); a ticket breakdown does not require tracked draft files. Publish or update issues only within an explicit tracker request, using [tracker rules](../../../docs/agents/issue-tracker.md). Do not close the parent automatically. A breakdown is unnecessary for a small task, and a reasonable technical split does not need another approval when implementation is already authorized.
