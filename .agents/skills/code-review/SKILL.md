---
name: code-review
description: "Review a PR, branch, staged or unstaged change for requirement coverage, architecture, and defects."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Review a Clarify change

Fix the review boundary first. Use the supplied commit, PR base, or range. Otherwise inspect the branch and worktree: use the merge base with the intended target for branch work, and include staged, unstaged, and new files for unfinished work. Record the base SHA, HEAD SHA, and dirty paths. An empty diff is a result, not an error.

Read the user request and any linked issue, comments, checklist, or spec. Use the current request as acceptance criteria when there is no formal spec; state any missing requirement.

Review in two separate passes:
1. Requirements: missing behavior, wrong behavior, compatibility, and scope.
2. Engineering: ownership, concurrency, cancellation, effects, resources, privacy, maintainability, and test quality.

Check `CONTRIBUTING.md`, `docs/architecture.md`, and relevant release or privacy docs. Trace callers and tests beyond the diff. For UI work, follow persistence through the bridge to rendering, and check focus, keyboard, DPI, and geometry. For lifecycle work, inspect late results, publication claims, shutdown, and cleanup.

Treat duplication, scattered changes, oversized interfaces, and unnecessary indirection as evidence to investigate, not automatic violations. Small adapters and compatibility code can be necessary. Check concrete bugs before style preferences. Formatting enforced by tooling does not need a duplicate review comment.

Use the review level in the project workflow. For independent review, give each fresh read-only reviewer the original request, the same fixed source state, its review axis, applicable rules, and observed check results. Reviewers do not write, run mutating checks, or delegate again. The coordinator consolidates findings and repairs the candidate. If delegation is unavailable, describe sequential passes as self-review and state that independent review was unavailable.

Report actionable findings with severity, file and line, failure scenario, and a repair direction. Keep requirement and engineering conclusions distinct. State test evidence and any open validation limit. For implementation tasks, repair confirmed in-scope findings and rerun affected checks. For a review-only request, report findings without editing the code.
