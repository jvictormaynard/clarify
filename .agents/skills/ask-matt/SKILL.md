---
name: ask-matt
description: "Choose the engineering skill or workflow that fits a task when the user asks where to start."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Choose a Clarify workflow

Match the task to the smallest useful route. Inspect the relevant files before recommending a workflow.

| Task | Route |
| --- | --- |
| Concrete feature or fix | `clarify-delivery`, then `implement`; use `tdd` for behavior |
| Repeated or unclear failure | `diagnosing-bugs`, then the delivery checks |
| Module interface or ownership | `codebase-design`; compare alternatives for a costly decision |
| Requested architecture survey | `improve-codebase-architecture` |
| Unclear product requirement | `grilling`; use `grill-with-docs` for durable decisions |
| Large, uncertain effort | `wayfinder`, then `to-spec` and `to-tickets` when useful |
| Incoming issue | `triage` |
| Review a change | `code-review` |
| Merge or rebase conflict | `resolving-merge-conflicts` |
| Evidence or outside facts needed | `research` or `prototype` |
| PR description or continuation | `pr` or `handoff` |
| Publish a version | Existing `clarify-release` |
| Improve agent instructions or hooks | `writing-for-agents`, `retro`, or `setup-pre-commit` |

Recommend one route and explain why. Start authorized work when the task is concrete. A spec, interview, prototype, issue, or handoff is useful only if it resolves an actual need. Do not require every task to pass through all skills.
