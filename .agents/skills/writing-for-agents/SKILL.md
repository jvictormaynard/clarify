---
name: writing-for-agents
description: "Create or revise repository skills, AGENTS.md, or agent-consumed workflow documentation."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Write effective Clarify agent guidance

Keep `AGENTS.md` short: stable owners, essential constraints, and precise routes to conditional detail. Put task-specific procedures in discoverable local skills or `docs/agents/`.

Each skill description states its capability and trigger. AGENTS.md defines the repository scope; do not repeat a "Clarify only" prefix in every description. Use the product name when it identifies a specific workflow. Each body contains only rules that improve decisions, execution, or proof. Prefer judgment criteria and observable completion over canned outputs, rigid interviews, or mandatory document chains.

Keep one authoritative location per fact. Link existing architecture, contribution, privacy, and release contracts. State when a reference is needed. Use current source paths for navigation rather than repeating a stale tool list.

Preserve user intent and prior authorization. A skill must not imply permission for publication, account changes, secret writes, destructive Git operations, or unrelated implementation. Follow the project's explicit parallel-work and review instructions when delegation tools are supported. Keep every implementing agent in its own current-base worktree.

Validate frontmatter, names, metadata, links, local scope, attribution, and provenance with `python scripts/check_agent_skills.py`. Use the creator's validator when available. Walk through realistic tasks to identify a bad trigger or a premature stop. Describe these as instruction checks unless an actual agent run was tested.

Update `upstream-lock.json` only for provenance changes. Do not add a new linter or dependency when the existing tools can validate the rule.
