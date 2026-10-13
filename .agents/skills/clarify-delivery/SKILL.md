---
name: clarify-delivery
description: "Coordinate an authorized code change from source inspection through tests, repair, and final review."
---

# Deliver a Clarify change

Read the [project workflow](../../../docs/agents/workflow.md)
for authorization, risk, checks, and completion rules.

1. Establish the task's observable outcome and acceptance criteria. Inspect Git
   status, the starting branch, existing code, tests, and any supplied issue's
   full context. Preserve unrelated work. Before implementation, use
   [worktree preparation](../../../docs/agents/workflow.md#worktrees-and-parallel-work) to create or verify
   a linked worktree against freshly fetched `origin/main`.
2. Trace the real ownership and call path. Read the architecture contract for
   structural work. Choose the smallest coherent change; use `codebase-design`
   for an interface or dependency decision and `diagnosing-bugs` when the cause
   is unclear.
3. Classify the affected behavior using the workflow's validation table. Choose
   existing test boundaries autonomously. Use `tdd` for meaningful changed
   behavior and keep tests isolated from personal data and external effects.
4. Delegate independent outcomes under the project's parallel-work rules.
   Keep shared-contract changes serial; the coordinator owns integration.
   Implement in complete slices. Run focused checks during editing; repair
   actual failures and preserve compatibility, cancellation, resource ownership,
   and once-only effects.
5. Run the applicable final checks once the candidate is stable. Use
   `code-review` for separate requirements and engineering passes. Fix confirmed
   in-scope findings and rerun affected checks.
6. Fetch and verify the integrated candidate still contains current `origin/main`.
   If the base advanced, integrate it safely and repeat affected checks and review.
   Finish the requested delivery level. A local change ends with a reviewable
   diff. A requested PR, merge, or release also needs the corresponding terminal
   Git/CI/asset evidence. Use `clarify-release` for publication.

Report the result, validation, and material open limits. A running command,
deployed bundle, or passing unit test is evidence only for what it checked.
Do not create a spec, ticket chain, prototype, or extra review stage unless it
solves an actual problem in this task.
