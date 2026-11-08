---
name: triage
description: "Evaluate incoming repository issues or requested PRs and prepare evidence-based implementation briefs."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Triage Clarify requests

Follow [tracker rules](../../../docs/agents/issue-tracker.md). Read the full body, comments, labels, checklist, linked issues, and relevant attachments. For a PR, inspect its diff and target state.

Check for duplicates, an existing implementation, accepted design decisions, and platform limits. Reproduce a reported bug with an isolated fixture or state that the live claim is not yet verified. Keep reports and comments free of keys, transcripts, provider bodies, recordings, and personal paths.

Distinguish category from readiness: bug or enhancement; needs evidence, ready for implementation, needs maintainer decision, or already resolved. Discover current labels rather than requiring a new label taxonomy.

Give the observed behavior, requested behavior, evidence, owner/interfaces, acceptance criteria, validation, and remaining decision. Use the maintainer's exclusions before reporting actionable totals. An unverified duplicate or theoretical feature conflict is not grounds for closure.

A read-only triage request produces recommendations. Apply labels, comments, assignment, or closure only within the requested mutation scope. Never send a reporter a message without authorization.
