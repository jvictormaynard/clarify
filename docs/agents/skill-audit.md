# Skill sources and adaptation decisions

The installed skills are a curated set of project methods, not an upstream
mirror. [AGENTS.md](../../AGENTS.md) owns task routing and the
[engineering workflow](workflow.md) owns execution. A source inventory is not a
reason to install every upstream skill.

## Provenance and maintenance

[upstream-lock.json](../../.agents/skills/upstream-lock.json) is the complete
Matt Pocock source inventory. It records the immutable source commit, original
file hashes, each adaptation or exclusion, and the reason. Excluded skills
remain in the record after their local entrypoints are removed. The manifest
pins original source bytes, not the evolving local adaptations.

Source: [mattpocock/skills at c55ee460](https://github.com/mattpocock/skills/tree/c55ee46073ed923f86ce59a5eb3b6d895095d1b7).
The [MIT notice](../../.agents/skills/licenses/mattpocock-skills-MIT.txt)
preserves Matt Pocock's copyright. The adapted PR skill retains
[Dex Horthy/HumanLayer credits](../../.agents/skills/pr/CREDITS.md).

[Humanizer](../../.agents/skills/humanizer/SKILL.md) has its own
[source record](../../.agents/skills/humanizer/UPSTREAM.json), pinned to
[blader/humanizer 3.1.0 at 8c307f36](https://github.com/blader/humanizer/tree/8c307f367c91bd974002f10f2be2965d642c13df).
Its [MIT notice](../../.agents/skills/licenses/blader-humanizer-MIT.txt)
preserves Siqi Chen's copyright. AGENTS requires it for project prose in every
language. It does not grant permission to send or publish that prose.

The delivery and release skills are project methods. Release operations follow
the current [release automation](../release-automation.md) and
[release contract](../../.agents/skills/clarify-release/references/release-contract.md),
not historical accounts in this audit.

## Adaptation criteria

Keep methods that resolve a distinct project need: ownership and interface
design, diagnosis, regression proof, review, planning on request, and publication.
Consolidate wrappers that only route to another skill. The manifest records
the retired router, implementation wrapper, interview wrappers, and explanation
wrapper with their replacement.

Preserve normal architecture terms and thin adapters with a real platform,
lifecycle, typing, or security purpose. Do not import mandatory interviews,
test-boundary approvals, document chains, global setup, automatic tracker writes,
or automatic publication from upstream.

[T3 Code's working rules at 15fe283](https://github.com/pingdotgg/t3code/blob/15fe2832727893cbdd2214383f9f971474849695/AGENTS.md)
inform the local rules for distinct test value, durable documentation, and
external PR evidence. Clarify retains its shared validation plan, profile
isolation, independent review, and native/release gates. Temporary experiments
and validation logs stay outside the repository; Git and PR history record
completed changes.

## Validation

Run [the skill validator](../../scripts/check_agent_skills.py) for metadata,
local references, regular-file scope, license integrity, and inventory coverage.
Use the creator's validator when available. Its YAML checks complement this
project's metadata format.

The optional command `python scripts/check_agent_skills.py --upstream <checkout>`
also checks the pinned source commit and every original file hash. Routine local
and CI validation need no upstream network access. The shared [policy task](../ci-delivery.md)
runs the repository checks.

Before an upstream update, inspect the immutable source in a temporary checkout,
compare changed bodies and resources, retain useful project adaptations, update
only affected provenance, and run the checks. Never run a global linking script
or unattended overwrite. Skills remain regular versioned repository files.

After changing behavior in the instructions, walk through representative tasks
and review the routes and evidence requirements. Keep temporary walkthrough
results with task evidence. Metadata checks and written walkthroughs do not
prove agent judgment, native acceptance, or measured delivery improvements.
