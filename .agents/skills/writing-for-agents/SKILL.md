---
name: writing-for-agents
description: "Create, simplify, or consolidate repository skills, AGENTS.md, and agent workflow documentation."
---

# Write effective agent guidance

Read the existing instruction chain and identify the decision each rule changes.
Use [documentation rules](../../../docs/agents/workflow.md#documentation-that-lasts)
and [file retention](../../../docs/agents/workflow.md#files-and-evidence).
Keep one authority per fact: AGENTS routes, the workflow owns execution, and
specialized documents own architecture, design, CI, and publication.

A skill needs a distinct trigger and method. Delete routing-only wrappers or
merge overlapping methods. Update all routes, invocation metadata, and the
upstream inventory when removing an entrypoint; preserve original hashes and
licenses. Do not add a new skill merely to rename shared policy.

Prefer short decision rules with an observable result over fixed interviews,
mandatory document chains, repeated command lists, and canned outputs. Remove
stale accounts instead of appending a new implementation log. Keep useful limits
on data, isolation, compatibility, review, and publication.

Validate metadata, links, local scope, attribution, and inventory with
`python scripts/check_agent_skills.py`. Use the creator's validator when
available. Walk through a small edit, a behavior fix, a high-risk change, and
an unavailable-platform case. Check that each route reaches the right evidence
without producing unnecessary repository files or permission loops.

Use deterministic checks for mechanical rules and reviewer judgment for semantic
value. Do not add tests that match prose or a new linter for an existing check.
Report instruction checks as such; measure actual deliveries before claiming
a speed or quality improvement.
