---
name: clarify-delivery
description: "Implement an authorized feature, fix, or refactor through source inspection, validation, repair, and review."
---

# Deliver a Clarify change

Use the [project workflow](../../../docs/agents/workflow.md) for scope, worktrees,
validation, retained files, review, and completion. It is the execution policy;
do not add a separate spec, ticket, interview, or prototype stage by default.

1. Inspect the request, Git state, affected owners, callers, and existing tests.
   Establish the observable outcome and prepare or verify the isolated worktree.
2. Choose the smallest coherent change. Use `diagnosing-bugs` for an unclear
   failure, `codebase-design` for an interface decision, and `tdd` when a retained
   regression test is useful. Load only the method needed.
3. Implement complete slices. Delegate independent outcomes under the workflow.
   Use focused quick local checks and fix actual failures. Preserve compatibility,
   operation identity, cancellation, effect ownership, and cleanup.
4. Inspect every added file. Apply the workflow's test, documentation, and
   evidence retention rules. Inspect the full affected validation plan and use
   remote CI for complete affected validation. Keep direct UI proof and targeted
   reproduction where needed; do not duplicate the full CI selection locally.
5. Use `code-review` at the required review level. Repair confirmed findings,
   repeat only affected checks when needed, and finish the requested delivery
   under the workflow's base, review-budget, and PR ownership rules.

Report the result, terminal checks, and open limits. A local implementation does
not request a commit, PR, merge, deployment, or release. Use `clarify-release` for
desktop publication and the platform guides for server/mobile delivery.
