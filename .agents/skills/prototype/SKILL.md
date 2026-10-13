---
name: prototype
description: "Build an isolated experiment to answer a specific state, interaction, or UI design question."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Prototype one Clarify decision

State the question and the observable result that would settle it. Use a Python harness for lifecycle or domain behavior, QML for native pill/focus/geometry questions, and React for Settings questions. An HTML simulator can illustrate a state machine, but it cannot validate Windows interaction.

Keep the experiment separate from production, with fake providers, in-memory state, and temporary data. Reuse the existing toolchain and relevant UI components. Do not overwrite existing demo media or include a prototype in the runtime entrypoint.

Optimize for a quick, observable answer. Add only the checks needed to trust the experiment. Show relevant state and failure cases. Record the result and its limitations; transfer the validated decision into product code only within authorized implementation.

Keep or remove the experiment according to the user's request and its value as evidence. Do not create a branch, commit, or publish an issue just to archive it.
