---
name: domain-modeling
description: "Resolve ambiguous domain terms or document an architecture decision during project work."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Maintain the Clarify domain model

Read [domain documentation rules](../../../docs/agents/domain.md) and `docs/architecture.md`. Use their language before inventing new names.

Resolve ambiguity with concrete scenarios and current code. Distinguish existing behavior, intended behavior, and an unverified assumption. Ask the user only when the difference changes a product decision; routine technical naming belongs to the implementation.

Maintain the glossary in `docs/agents/domain.md`; do not create a second root `CONTEXT.md`. Keep implementation explanations in the architecture document. Update terminology only when the current task changes or clarifies it.

Record an ADR only for a durable, costly-to-reverse choice with real alternatives and a reason a future contributor will need. Use [record formats](references/record-formats.md). A reversible internal detail belongs in the PR or code, not a new ADR. Use actual source evidence and distinguish newly accepted decisions from historical facts.
