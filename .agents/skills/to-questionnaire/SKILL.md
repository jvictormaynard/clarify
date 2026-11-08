---
name: to-questionnaire
description: "Draft focused questions for a contributor or maintainer who holds missing project information."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Draft a Clarify questionnaire

Use the known recipient and decision; ask for them only if they are missing and affect the draft. Check the repository and existing issue discussion first so the questions target facts the recipient actually holds.

Order questions by their effect on the blocked decision. Include enough sanitized context to answer, an answer space, and any deadline the user provided. Avoid repeated or compound questions. Partial answers should remain useful.

Return the draft in the conversation or an OS temporary file. Follow [file retention](../../../docs/agents/workflow.md#files-and-evidence) if a repository artifact was explicitly requested. Follow [tracker rules](../../../docs/agents/issue-tracker.md) for an authorized issue comment. Drafting a questionnaire does not authorize sending it.
