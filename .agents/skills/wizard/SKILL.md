---
name: wizard
description: "Prepare concise instructions or a local helper for a setup step that truly requires the user."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Prepare a necessary manual step

First perform all authorized steps that tools can complete. Use a manual procedure only for a user-owned login, consent, hardware interaction, or inaccessible platform action.

Identify the exact step, why the user is required, its current official instructions, and the observable completion result. Keep the guide short and specific. Use PowerShell for native Windows operations and Bash only when the actual procedure runs in WSL.

Generate a helper only for a repeated or complex procedure. Keep it local to this project or in a temporary directory; validate syntax and simulate safe paths. Do not run an interactive script unattended or launch a visible terminal without a need.

Read secrets with hidden input and pass them through stdin or supported secure storage. Provider keys belong in Clarify's SecretStore/DPAPI flow, not a wizard-generated plaintext profile. An explicitly requested development environment file must stay ignored and must not expose its values. Avoid shell tracing, secret command-line arguments, `eval`, and cross-shell filesystem deletion.

External mutations still require the original task's authorization. Prepare the concrete artifact before requesting any missing approval. Do not copy the upstream generic secret-writing Bash template into this project.
