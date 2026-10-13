---
name: setup-matt-pocock-skills
description: "Inspect or repair this repository's skill routing, provenance, and workflow configuration."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Maintain the local Clarify skills setup

This repository is already configured. Inspect `AGENTS.md`, `.agents/skills/`, [workflow rules](../../../docs/agents/workflow.md), [tracker rules](../../../docs/agents/issue-tracker.md), [domain rules](../../../docs/agents/domain.md), and [audit](../../../docs/agents/skill-audit.md).

Use the project's files as the configuration. Change only what the user's task requires. Keep skills as versioned regular files below the repository root. Preserve the release skill and MIT attribution. Do not install global hooks, global skills, or a second instruction file.

For an upstream update, fetch an immutable commit into a temporary directory, compare every changed skill and resource, retain Clarify customizations, update `upstream-lock.json`, and run `python scripts/check_agent_skills.py` plus the creator's validator when available. Never overwrite local adaptations with an unattended update command.

The GitHub tracker is canonical; local drafts do not publish anything. Existing labels are discovered on demand, not imposed by setup. An absent optional ADR or research directory does not make setup incomplete.
