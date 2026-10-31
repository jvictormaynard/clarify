# Clarify engineering workflow

This is the shared execution policy for this repository and its worktrees.
Skills add a method when needed; they do not grant permissions or add mandatory
planning stages. Command ownership stays in [CI delivery](../ci-delivery.md).

## Scope and autonomy

Inspect the request, current Git state, affected source, and existing tests.
Read linked issues and their relevant comments, criteria, dependencies, and
attachments. State the observable outcome and material assumptions. Work from
the complete request, not just its title.

Choose routine reversible technical details within the task. Ask only when
missing information changes product behavior, persisted compatibility, data
ownership, scope, or a costly design choice. Continue independent work while
waiting; silence is not approval. A clarification or status question does not
cancel the active task unless the user says so.

Preserve unrelated work and the starting checkout. Commit, push, PR creation,
merge, tracker changes, account changes, deployment, and publication follow the
user's request and prior authorization. Prepare a reviewable local result before
asking for any missing delivery approval. Never erase profiles, force-move a
published tag, or use secrets as fixtures.

## Worktrees and parallel work

Use native Git for the repository's filesystem: Windows Git for Windows paths,
Linux Git for WSL paths. Give every command an explicit working directory.

Before implementation:

1. Inspect status, branch, top-level path, Git directory, and the worktree list.
   Reuse the assigned isolated task worktree if it meets the checks below.
2. Fetch `origin` successfully and resolve `origin/main` to an exact SHA.
   Do not continue from cached refs after a failed fetch.
3. If a worktree is needed, create a distinct linked worktree outside existing
   worktrees, on a new task branch from that SHA. Use `codex/<slug>` for manually
   created branches; a tool-assigned task branch is also valid.
4. Verify the top-level path is the intended worktree, its Git directory differs
   from the shared common directory, and its branch is neither detached nor
   `main`. Check `git merge-base --is-ancestor origin/main HEAD`.

Fetch again before final integration/review and before delivery. Record the
path, branch, base/HEAD SHAs, dirty paths, and UTC fetch time in task evidence.
An ancestry failure needs investigation or safe integration of current main.
Do not reset, clean, stash, or overwrite existing work to make the check pass.
Freshness is proven at the recorded fetch time, not continuously.

Delegate independent implementation outcomes when tools support it. Use one
writer for a small or tightly coupled change. Give each writer a separate
current-base worktree, owned paths, acceptance criteria, shared interfaces,
checks, governing instructions, and permitted Git actions. Use the environment's
worktree delegation facility when it provides checkout isolation. Serialize
competing changes to schemas, locks, migrations, and release metadata.

Workers verify their directory before edits. They do not edit sibling worktrees,
publish, integrate other workers, or start more agents without assignment.
Do not share writable profiles, test databases, build outputs, recordings, or
ports. Read-only reviewers can inspect one fixed candidate without a new worktree.
If delegation is unavailable, use sequential passes and report the limit.

The coordinator integrates explicit task diffs in dependency order and validates
the complete result. Use a separate integration worktree for independent feature
branches. Preserve worker changes until integration is verified. If the base or
candidate changes, repeat affected checks and review. Remove only task-owned
temporary resources after preserving results; keep dirty or unrelated worktrees.

## Ownership and affected paths

[Architecture](../architecture.md) owns module responsibilities, provider/storage
contracts, data, platform behavior, and packaging. Read [Contributing](../../CONTRIBUTING.md)
before structural work. Keep domain decisions outside QML and React renderers.

Trace the changed contract through callers, effects, and consumers. Check the
applicable entry points, desktop/Settings/mobile/server clients, provider routes,
connection modes, persisted state, and reverse actions. Add separate coverage
only when a layer has its own failure risk. Do not expand into unrelated clients.

Preserve stale-result rejection, accepted publication ownership, once-only usage
accounting, focus-safe clipboard effects, audio cleanup, atomic persistence,
migrations, and read-only handling of newer schemas. BYOK and Local Whisper keep
their own routes; local processing has no implicit cloud fallback. Reuse the
existing owners rather than adding a parallel service for the same decision.

## Validation by affected contract

Use `scripts/ci.py --plan` for the complete candidate, including new and dirty
files. Run focused checks while editing, then execute the selected local checks
once the candidate is stable. [CI delivery](../ci-delivery.md#local-validation)
owns commands, selection, platform requirements, and terminal results. Do not
maintain a second command matrix in a skill.

Python behavior requires the selected Python suite and relevant static checks.
Settings changes require unit, browser/bridge, and production build/boot checks.
Packaging inputs require Windows build and embedded-payload checks. A wording
change needs policy/reference validation and `git diff --check`, not a product
build. Do not run every component or repeat a full suite by habit. Broaden checks
for a new change, failure, dependency risk, or unresolved concern. Never omit a
selected gate merely because a focused check passed.

Use the configured interpreter and locked dependencies. A Windows virtual
environment is not a Linux environment. Initialize temporary profiles before
product imports; use fake providers, clocks, schedulers, clipboard and secret
stores, and audio fixtures. Tests must not access personal profiles, real keys,
microphones, or recordings. Reuse `tests/web_settings_fixture.py` for Settings.

For desktop UI work, verify the rendered result, responsive layout, focus, and
affected states under the design system. Use before/after captures for visual
changes and a short recording when motion or timing matters. State native
Windows acceptance separately. Static Swift checks on Windows do not prove
iOS behavior. Environment failures and unavailable platforms remain unexecuted
gates; repair in-scope failures and report unrelated failures with evidence.

## Tests worth retaining

Before adding a test, name the concrete future regression it will catch. Use
one independent expected result at the lowest boundary that reaches the defect.
Extend an existing case, table, or fixture before adding a new case or file.
A unit and an integration test may both be useful when they protect different
contracts; do not duplicate the same assertion through wrappers and clients.

Keep coverage for routing, permissions, persistence, migrations, parsing,
cancellation, concurrency, resource ownership, and other behavior that can fail.
Logic/data/state fixes need a regression that fails for the reported symptom
before the fix and passes afterward. An import or environment error is not red
evidence. Prefer controlled clocks, barriers, and observable milestones to sleeps.

Do not retain tests that only restate types, implementation steps, trivial
callback wiring, copy text, or fixed markup. Pure spacing, color, and alignment
changes normally use captures; focus, keyboard, state, and persistence changes
can need behavior tests. Smoke runs and diagnostic experiments can be necessary
during implementation without becoming repository test files.

Keep existing tests until their distinct risk is accounted for. Remove or merge
a redundant test when equivalent coverage remains; explain the covered risk.
Platform, migration, and security checks can justify internal assertions. Call
counts matter when they prove a real contract such as once-only publication.

## Files and evidence

Every added file needs a purpose after the PR lands.

- Keep PR-only screenshots, recordings, logs, timing reports, diagnostic scripts,
  implementation plans, research drafts, and handoffs in a task-owned OS temporary
  directory outside the worktree. Return the path when local evidence is useful.
- For a requested PR, upload captures and link them in the description. CI output
  belongs in CI artifacts. If upload is unavailable, preserve local evidence and
  state that limit; do not commit it as a fallback.
- Runtime profiles, databases, recordings, credentials, and build outputs stay out
  of Git. Reserved output directories are ignored as a safety net, not a storage
  requirement. Do not force-add their contents.
- Shipped assets, test fixtures with a distinct contract, and images used by
  maintained user documentation can belong in Git. Explain that lasting purpose.
  Do not ban image or data extensions globally or delete existing demo artifacts.
- A request for a spec, plan, questionnaire, or report can be answered in the
  conversation or a temporary file. Create a repository artifact when explicitly
  requested, or retain only the accepted durable decision in its existing owner.

Before review, inspect staged, unstaged, and new files. Remove task-owned
temporary instrumentation and accidental output. Check each retained test and
document against these rules. `git add .` is not a substitute for this review.

## Documentation that lasts

Update documentation when a user task, operational procedure, accepted decision,
or hard-to-discover cross-component constraint changes. Put it in the existing
owner. Ask what a maintainer or user would get wrong without the text.

Do not narrate control flow, list fields and methods, duplicate source catalogs,
append PR summaries, or preserve completed implementation checklists. Use a short
nearby comment for a local reason that code cannot show. Rewrite or remove stale
text instead of appending a second account. New pages need a distinct durable
purpose. User docs explain tasks and non-obvious behavior in product language,
without implementation or contributor-tool details.

Keep one authority per rule. `AGENTS.md` routes work, this workflow owns execution,
skills add specialized methods, and the existing architecture, design, CI, and
release documents own their contracts. [Tracker rules](issue-tracker.md) govern
drafts and authorized issue changes.

## Review and completion

Record base/HEAD SHAs and all dirty paths. Review the complete candidate in two
passes: requirements/compatibility/scope, then engineering and test quality.
Trace beyond the diff when needed. Report actionable defects with a location,
failure scenario, and repair direction, not speculative checklist requests.

Treat credentials/permissions, persistence/migrations, provider routing, workflow
concurrency, clipboard/audio/ASR ownership, and update or publication policy as
high-risk boundaries.

An isolated wording change needs self-review. Changed behavior in adjacent
modules needs one fresh read-only reviewer. High-risk boundaries, broad independent
features, or substantial delivery-rule changes need two: requirements and
engineering. Reviewers receive the same fixed candidate, request, rules, and
terminal check results; they do not write, run mutating checks, or delegate.
Repair confirmed findings and rerun affected checks. Disclose unavailable review.

Finish the requested level: local work needs a reviewable diff and terminal local
results; PR work needs the exact source and accurate description; merge needs
required checks/reviews for the actual candidate and verified merge state.
Report the outcome, relevant evidence, and material open gates. Never call a
running check, pending CI, or unverified deployment complete.

## Publication

Validation and publication are separate. CI passing does not prove manual
Windows acceptance, Apple availability, or a public release. Each platform has
one publication coordinator after feature integration.

For desktop, follow [clarify-release](../../.agents/skills/clarify-release/SKILL.md)
and [release automation](../release-automation.md): dedicated preparation, exact
source/version/tag, terminal CI, accepted immutable assets, downloaded hashes,
and provenance. Publish only the verified candidate bytes.

For iOS, follow [mobile/README.md](../../mobile/README.md) and the
[iOS workflow](../../.github/workflows/ios-testflight.yml). Verify available build
numbers before reservation, keep app/extensions aligned, and use validation mode
without publication. Authorized publication needs the immutable source/tag,
native checks, signed IPA, successful upload, Apple processing, and intended
TestFlight group availability. App Store submission and public availability
are separate actions that reuse the verified Apple build.

For server delivery, inspect the actual connected repository, branch, native
Railway autodeploy, `Wait for CI`, source paths, and healthcheck. Follow
[server delivery](../server-delivery.md). An automation change does not authorize
production activation.

## Instruction maintenance

Keep skills as regular repository files and preserve source pins and licenses
in the [skill audit](skill-audit.md). Validate metadata, links, inventory, and
attribution with `python scripts/check_agent_skills.py`. Use the creator's
validator when available. Exercise realistic task routes after a rule change.
These checks do not establish measured agent speed, judgment, or native acceptance.
