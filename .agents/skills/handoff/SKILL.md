---
name: handoff
description: "Capture verified progress and next actions when a project task needs continuation or transfer."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Hand off Clarify work

Inspect current Git status and source state before writing the handoff. Include the user outcome, accepted decisions, branch and SHA, modified/new files, verified checks with exit results, unresolved failures, authorization already given, and the exact next action.

Reference existing issues, specs, ADRs, logs, and diffs instead of copying them. Name the applicable local skills and their paths. Distinguish completed work from proposed work and terminal test results from still-running checks.

Save a sanitized handoff to the OS temporary directory unless the user requests a repository artifact. Keep credentials, transcript text, personal audio, and private profile paths out.

Writing a handoff does not start another agent or create a Codex task. Use task-management tools only when the user asks for that action. Normal context compaction can continue the same task without a handoff.
