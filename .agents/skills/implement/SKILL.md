---
name: implement
description: "Implement an authorized feature, fix, or refactor from a request, spec, or ticket."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Implement Clarify work

Read the request and all available acceptance criteria. If a ticket is supplied, inspect its description, comments, checklists, dependencies, subtasks, and relevant attachments before editing.

Use the `clarify-delivery` skill as the execution coordinator. Trace the current owners and real call path. Use `codebase-design` for an interface or ownership change, `tdd` for changed behavior, and `diagnosing-bugs` when the failure is unclear.

Work in complete, small slices. Preserve public and persisted compatibility, operation identity, cancellation, once-only effects, and resource ownership. Run focused checks while editing and the applicable final gates once the candidate is stable.

Use `code-review` before completion. Fix confirmed in-scope findings and rerun affected checks. Leave a reviewable diff and report evidence. Commit, push, PR, merge, and publication follow the user's authorization; skill invocation alone does not request them.
