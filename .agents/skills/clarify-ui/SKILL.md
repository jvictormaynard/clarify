---
name: clarify-ui
description: "Design, implement, or review Clarify desktop and mobile UI with shared controls, clear task flows, and rendered checks."
---

Read the [desktop design system](../../../docs/desktop-design-system.md) for
desktop work or the [mobile guide](../../../mobile/AGENTS.md) for mobile work.
Follow the [delivery workflow](../../../docs/agents/workflow.md) for validation.

1. Name the user's task, the next action, and how they can recover. Start with
   the shortest supported path. Show detailed choices and setup instructions
   where the user needs them. Keep errors beside their controls.
2. Find the closest existing screen and its shared controls. Compose those
   controls with semantic colors and tokens. Keep the primary action easy to
   find. Use a short label that describes its effect. Use borders, icons, and
   motion only when they clarify an action, state, or relationship.
3. Check the flow in its actual shell. Use keyboard or touch as applicable.
   Cover relevant empty, loading, failure, and retry states. Check focus,
   long text, compact windows, and reduced motion. Tell the user which platform
   you could verify.

Read [interaction checks](references/interaction.md) when layout, focus, or
state transitions change. Read [motion](references/motion.md) only when working
on animation or its performance. Use the existing [prototype skill](../prototype/SKILL.md)
for an interaction experiment.

This method adapts selected ideas from [Emil Kowalski's skills](https://github.com/emilkowalski/skills/tree/64eb3deb9a5fbfa041faf783e0bc3fd635872e9c)
and [taste-skill](https://github.com/Leonxlnx/taste-skill/tree/f6b76575f949707b4e3c37cd86cb44b0b98643e8).
See the [source audit](../../../docs/agents/skill-audit.md) for mapping and notices.
