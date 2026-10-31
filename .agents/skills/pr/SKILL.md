---
name: pr
description: "Write or update a pull-request description with concrete behavior, evidence, and relevant limits."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Describe a Clarify PR

Read the final diff, user request, linked issue, and validation results. Follow any repository PR template.

Lead with the concrete problem and resulting behavior. For a small change, use one or two sentences and validation. For a broader change, explain ownership or compatibility when it helps the reviewer. Use a diagram only when it makes the change easier to assess.

Report exact checks and terminal results. For visual work, upload before/after captures; add a recording when motion or timing matters. Link evidence in the PR, keep PR-only files outside Git, and state native Windows acceptance limits. If upload is unavailable, preserve local captures and report the missing attachment. Include rollback or migration risk only when material. Do not claim a build, CI, merge, or release that has not completed.

Keep descriptions secret-free. Use a structured body argument, or a file with real newlines for `gh --body-file`. Writing the description is local; create or update the PR only when requested or already authorized.

This adaptation uses the idea of showing the shape of a change. Attribution is retained in [CREDITS.md](CREDITS.md); the original fixed template is not required.
