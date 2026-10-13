---
name: resolving-merge-conflicts
description: "Resolve conflicts in an already authorized merge or rebase while preserving both changes' intent."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Resolve Clarify Git conflicts

Inspect Git status, the active operation, unmerged paths, and both histories. Read the related issue, PR, and tests where they explain intent. Preserve existing user edits and unrelated files.

Resolve each hunk by contract and purpose, not by selecting a whole side mechanically. For lockfiles, use the repository's generator on the matching platform; do not invent dependency pins. Account for migrations, provider routes, Qt/Settings bridges, and packaging payloads.

Stage only resolved paths from this operation. Run the affected checks and review the combined result. Continue the merge or rebase when its original authorization covers completion. Do not stage all worktree files.

If intents are incompatible, report the concrete decision and continue independent work. Preserve a safe recoverable state. An authorized abort is valid when needed to recover; never erase unrelated work, force a shared history rewrite, or continue a broken operation merely to satisfy a rule.
