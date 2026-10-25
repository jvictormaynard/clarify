# Audit of Matt Pocock's skills for Clarify

Audit date: 2026-09-27.

Source: [mattpocock/skills, pinned commit c55ee460](https://github.com/mattpocock/skills/tree/c55ee46073ed923f86ce59a5eb3b6d895095d1b7).

The source contains **38 skill entrypoints**: 18 engineering, 7 productivity,
4 misc, and 9 in-progress. Every `SKILL.md` was inspected; relevant companion
references and executable helpers were inspected where they affected a decision.
The deprecated bucket has no skill entrypoint at this commit.

**27 skills were adapted, 11 were excluded, one Clarify delivery coordinator was
added, and the existing release skill was revised.** At that audit, the project
had 29 skills. All are regular versioned files in `.agents/skills/`. No global
skill or global agent configuration was installed or changed.

This is a curated adaptation, not a mirror. Each imported skill is now specific
to Clarify. Unused upstream templates and references were removed from the new
copies; the original file hashes remain in
[upstream-lock.json](../../.agents/skills/upstream-lock.json).

## Judgment used in the audit

The useful ideas are deep modules, clear owners, observable feedback, verifiable
slices, separate requirements/engineering reviews, source-based research, and
durable decision records. Popularity or author reputation does not establish
fitness for this repository.

The source also contains rules that conflict with Clarify's needs:
- Approval of each test boundary and exhaustive design interviews slows already
  authorized work.
- Automatically deleting old internal tests risks losing lifecycle, migration,
  platform, and security evidence.
- Requiring multiple agents for every routine wording edit adds unnecessary
  cost. Independent implementation and consequential reviews now follow the
  explicit project instructions when delegation tools are supported.
- Foreign vocabulary rules reject valid services, gateways, repositories, and
  thin Qt/Tauri adapters.
- Automatic commits, tracker posts, assignments, closure, and unconditional merge
  continuation exceed some tasks.
- CDN-dependent reports and assumed TypeScript package layouts add unrelated
  infrastructure.
- Generic Bash secret/environment writes are unsuitable for the DPAPI product
  credential boundary.

The adaptations use the [project workflow](workflow.md), actual
[architecture](../architecture.md), current contribution checks, and existing
Windows release contract. They choose routine technical details autonomously and
reserve user questions for material unresolved decisions.

## Complete inventory and decision

Each source link identifies the exact audited `SKILL.md`. The local skill has the
same name where adopted.

### engineering

| Source skill | Decision | Reason or adaptation |
| --- | --- | --- |
| [ask-matt](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/ask-matt/SKILL.md) | Adapted | Keep a small task router; remove mandatory interview/spec/context-reset chains. |
| [code-review](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/code-review/SKILL.md) | Adapted | Review requirements and engineering separately; include dirty/new files; use the project's required fresh reviewers when supported and disclose fallback self-review. |
| [codebase-design](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/codebase-design/SKILL.md) | Adapted | Keep deep-module judgment; preserve Clarify services, gateways, platform seams, and resource ownership instead of enforcing foreign vocabulary. |
| [diagnosing-bugs](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/diagnosing-bugs/SKILL.md) | Adapted | Keep reproducible evidence and hypotheses; allow source investigation without a live reproduction and avoid rigid phase/hypothesis counts. |
| [domain-modeling](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/domain-modeling/SKILL.md) | Adapted | Use the existing architecture contract and a small project glossary; record only durable decisions. |
| [grill-with-docs](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/grill-with-docs/SKILL.md) | Adapted | Resolve material uncertainty and record accepted decisions; omit exhaustive interviews and repeated approvals. |
| [implement](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/implement/SKILL.md) | Adapted | Coordinate complete local delivery; remove unconditional commits and mandatory test-seam approval. |
| [improve-codebase-architecture](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/improve-codebase-architecture/SKILL.md) | Adapted | Audit multiple architecture dimensions and real hotspots; remove mandatory subagents/CDN reports and speculative consolidation. |
| [prototype](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/prototype/SKILL.md) | Adapted | Use Python, QML, or React according to the question; isolate data; remove automatic archival branches and issue writes. |
| [research](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/research/SKILL.md) | Adapted | Use primary sources and pinned versions; remove mandatory background agents. |
| [resolving-merge-conflicts](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/resolving-merge-conflicts/SKILL.md) | Adapted | Preserve both intents and unrelated work; stage only conflict paths; allow authorized abort/recovery. |
| [setup-matt-pocock-skills](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/setup-matt-pocock-skills/SKILL.md) | Adapted | Maintain the already configured project; remove global installation paths, default label creation, and repeated setup interviews. |
| [tdd](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/tdd/SKILL.md) | Adapted | Choose existing boundaries autonomously; permit safe refactoring and justified invariant tests; preserve existing coverage. |
| [to-spec](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/to-spec/SKILL.md) | Adapted | Create proportional acceptance criteria with useful code pointers; draft locally and publish only when requested. |
| [to-tickets](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/to-tickets/SKILL.md) | Adapted | Keep verifiable slices and blocking edges; avoid mandatory reapproval or tracker publication. |
| [triage](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/triage/SKILL.md) | Adapted | Read full issue context and reproduce claims; discover current labels; default to read-only recommendations. |
| [wayfinder](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/wayfinder/SKILL.md) | Adapted | Keep a decision map only for large uncertain work; remove fixed session limits, mandatory agents, and automatic tracker writes. |
| [wizard](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/engineering/wizard/SKILL.md) | Adapted | Use manual steps only when necessary; choose native shell; remove generic plaintext secret-writing Bash template. |

### productivity

| Source skill | Decision | Reason or adaptation |
| --- | --- | --- |
| [grill-me](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/productivity/grill-me/SKILL.md) | Adapted | Keep a focused project interview; avoid turning the product checkout into a personal planning workspace. |
| [grilling](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/productivity/grilling/SKILL.md) | Adapted | Resolve consequential ambiguities; inspect facts locally; replace exhaustive frontier confirmation with bounded decision questions. |
| [handoff](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/productivity/handoff/SKILL.md) | Adapted | Keep verified progress and source pointers; remove mandatory harness changes or agent/task creation. |
| [teach](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/productivity/teach/SKILL.md) | Excluded | Treats the repository as a stateful teaching workspace and adds lessons/mission records unrelated to product delivery. |
| [to-questionnaire](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/productivity/to-questionnaire/SKILL.md) | Adapted | Draft focused contributor questions; scope artifacts to the project and separate drafting from sending. |
| [wait-what](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/productivity/wait-what/SKILL.md) | Adapted | Use simple English or Portuguese and resume the active objective after explaining. |
| [writing-for-agents](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/productivity/writing-for-agents/SKILL.md) | Adapted | Keep precise triggers, progressive disclosure, and observable completion; validate local scope and provenance. |

### misc

| Source skill | Decision | Reason or adaptation |
| --- | --- | --- |
| [git-guardrails-claude-code](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/misc/git-guardrails-claude-code/SKILL.md) | Excluded | Depends on Claude hooks, offers global installation, blocks all pushes, and uses bypassable command-text patterns; project Git rules cover authorized safe operations. |
| [migrate-to-shoehorn](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/misc/migrate-to-shoehorn/SKILL.md) | Excluded | Adds a TypeScript-specific test package without a demonstrated need and defaults to a production dependency install. |
| [scaffold-exercises](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/misc/scaffold-exercises/SKILL.md) | Excluded | Assumes an AI Hero course directory and CLI that Clarify does not use. |
| [setup-pre-commit](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/misc/setup-pre-commit/SKILL.md) | Adapted | Reuse .githooks/pre-commit and Ruff; remove default Husky/Prettier installation and full-suite commit hooks. |

### in-progress

| Source skill | Decision | Reason or adaptation |
| --- | --- | --- |
| [claude-handoff](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/in-progress/claude-handoff/SKILL.md) | Excluded | Depends on Claude's background-agent CLI and duplicates the local handoff workflow. |
| [implement-spec](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/in-progress/implement-spec/SKILL.md) | Excluded | Duplicates delivery and ticket execution while requiring multiple implementer/merger agents, PR writes, and automatic worktree cleanup. |
| [loop-me](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/in-progress/loop-me/SKILL.md) | Excluded | Models personal recurring routines and introduces workflows/*.md, which conflicts with Clarify's product workflow terminology. |
| [pr](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/in-progress/pr/SKILL.md) | Adapted | Use the repository PR format and proportional evidence; preserve credits without requiring fixed danger/diagram sections. |
| [retro](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/in-progress/retro/SKILL.md) | Adapted | Improve local workflow from demonstrated failures; remove global-instruction edits and unconditional new tooling. |
| [setup-ts-deep-modules](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/in-progress/setup-ts-deep-modules/SKILL.md) | Excluded | Assumes a src/packages layout and adds dependency-cruiser plus an example package; Clarify has Python/Qt owners and a small Settings frontend. |
| [writing-beats](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/in-progress/writing-beats/SKILL.md) | Excluded | Interactive article composition has no distinct role in the requested engineering workflow. |
| [writing-fragments](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/in-progress/writing-fragments/SKILL.md) | Excluded | Unstructured authoring fragments add a separate writing process without improving code delivery. |
| [writing-shape](https://github.com/mattpocock/skills/blob/c55ee46073ed923f86ce59a5eb3b6d895095d1b7/skills/in-progress/writing-shape/SKILL.md) | Excluded | Paragraph-by-paragraph article shaping is outside the project's engineering workflow. |

## Local integration

- [AGENTS.md](../../AGENTS.md) routes relevant tasks to skills and preserves
  project owners, data isolation, checks, and simple English/Portuguese.
- [clarify-delivery](../../.agents/skills/clarify-delivery/SKILL.md) coordinates
  inspection, implementation, validation, repair, and review.
- [Workflow](workflow.md) sets scope and proportional validation.
- [Domain](domain.md) provides a small glossary; implementation remains in the
  architecture document. ADRs are created only for real durable decisions.
- The architecture recording section now names the current Qt capture owners
  and keeps the separate legacy recording implementations explicit.
- [Tracker](issue-tracker.md) uses GitHub as canonical storage and local drafts
  when appropriate. No labels, issues, PRs, or comments were created during setup.
- [clarify-release](../../.agents/skills/clarify-release/SKILL.md) retains version,
  CI, track-specific assets, hashes, and provenance gates. It uses a dedicated
  current-base release worktree and preserves the starting checkout. Other
  release procedures follow the current remote contract.
- [Skill validator](../../scripts/check_agent_skills.py) runs in the root check
  command and both CI test platforms. Its isolated tests are part of the Python
  suite. It adds no runtime dependency or application build input.

The adopted skills permit normal implicit discovery. This intentionally replaces
the source's manual-only policies where present: the requested project workflow
needs the agent to select relevant skills autonomously. Specific capability and
trigger descriptions guide routing; an implicit invocation grants no external
mutation permission.
The existing release skill remains available with its original invocation metadata.

[Official Codex documentation](https://developers.openai.com/codex/skills) describes
repository discovery through `.agents/skills`, including subdirectories up to the
Git root, and explicit/implicit invocation. Newly installed local skills are
available on the next turn; a restart can resolve a stale skill list. The guide
and coordinator remain direct file routes for an environment without discovery.

## Provenance and maintenance

The manifest records the source repository, immutable SHA, license hash, every
skill decision, and SHA-256 hashes of all original files in every skill folder,
including excluded skills. It does not pin the adapted local bytes: local skills
are intended to evolve under version control.

The [upstream MIT license](../../.agents/skills/licenses/mattpocock-skills-MIT.txt)
preserves Matt Pocock's notice. The adapted PR skill also retains the upstream
[Dex Horthy/HumanLayer credits](../../.agents/skills/pr/CREDITS.md).
These are development instructions, not bundled application components.

For an upstream update:
1. Fetch the intended commit into an isolated temporary checkout.
2. Review changed skill bodies, metadata, references, and helpers.
3. Reapply only useful changes while preserving Clarify's contracts.
4. Update the inventory and original hashes, then validate locally.
5. Review and version the diff through the normal requested Git workflow.

Do not run an automatic overwrite or the upstream global linking script.

## Instruction walkthroughs

These are semantic walkthroughs of the written instructions, not independent
agent execution or measured productivity results.

| Representative request | Route and checked decision |
| --- | --- |
| Fix a late workflow result after cancellation | Delivery + diagnosis/TDD; test real publication and stale-operation behavior with controlled gateways |
| Add an OpenAI-compatible provider | Design + TDD; extend the typed registry/adapter and reuse the HTTP policy |
| A saved Settings value is missing in the UI | Trace repository, Python bridge, and rendering; include relevant isolated Playwright tests |
| Adjust pill geometry | Keep the current component owner; use QML/Windows DPI evidence and preserve focus |
| Audit architecture without changing code | Evidence-backed candidates across ownership, UX, functionality, tests, and delivery; no automatic refactor |
| Improve instruction wording | Validate metadata/references; no new product test for matching prose |
| Review an unfinished branch | Fix the source boundary and include staged, unstaged, and new files; report self-review honestly |
| Resolve an in-progress rebase | Preserve both contracts, stage only conflict paths, and keep recovery available |
| Publish a Community release | Explicit community preflight, green exact source/CI/tag, portable-only assets, downloaded hashes/provenance |
| Request an issue breakdown | Draft coherent slices with blockers; publish only under a tracker mutation request |

The walkthroughs confirm that the written routes preserve scope and avoid known
instruction conflicts. Their effectiveness still needs evidence from future
deliveries. The validator cannot prove agent judgment, runtime quality, or native
Windows acceptance.

## Validation record

Run `python scripts/check_agent_skills.py` for local metadata, links, regular-file
scope, license integrity, and inventory coverage. Its scalar checks target this
project's metadata format; use the creator's YAML validator for full skill
frontmatter validation.

Run `python scripts/check_agent_skills.py --upstream <pinned-checkout>` to also
compare the upstream Git SHA, every source entrypoint, and all recorded original
file hashes. A CI run needs no network access to the source repository.

Validation on 2026-09-27:

- All 29 local skills passed the creator's frontmatter validator and YAML UI
  metadata checks. Both CI platform definitions include the project validator.
- All 38 upstream entrypoints and every recorded source-file hash matched the
  pinned checkout. Local references, regular-file scope, and license integrity passed.
- The 16 validator tests passed on Windows and Linux. They cover broken and
  escaping references, global symlinks, inventory conflicts, mutable source refs,
  invocation policy, and license changes.
- `npm run check`, Ruff lint/format checks for the new Python files, and
  `git diff --check` passed.
- The full Windows Python suite ran 1,163 tests with five platform skips. It found
  one failure: a newly added `check:skills` alias violated the existing maintenance
  command allowlist. That alias was removed; validation stays inside `check` and CI.
  The final retest of repository and validator modules passed all 42 tests. The
  full suite was not repeated after that narrow correction; the retest also covers
  the final validator reference-scheme fix and its additional test.

No remote CI, application rebuild, deployment, or release was requested or run.
No runtime behavior, dependency lock, or bundled product payload changed.

## Parallel-worktree adaptation, 2026-10-13

The Lana delivery skill and development loop supplied the reference for
fresh `origin/main` worktrees, proportional validation, fixed candidates, and
separate requirements/engineering review. Clarify retains its own authorization,
PR, privacy, platform, and release contracts. Lana's direct push-to-main rule
and infrastructure procedures were not imported.

Parallel work uses AGENTS.md, the existing workflow, and focused changes to
delivery, review, and instruction-maintenance skills. A separate worktree skill
would duplicate delivery coordination, so none is added. Native Git commands
provide preparation and freshness checks; no worktree generator is added.

The upstream commit, source hashes, and license remain unchanged. The existing
local skill framework was reused without copying unfinished product changes.
The current remote release contract was retained instead of the older local
draft. Its skill now uses the shared worktree rules and preserves the starting
checkout instead of forcing it back to `main`.
The existing local corrections for configured Python and observed deployment
paths are preserved in the current release skill and contract.
Descriptions and bodies omit repeated project-only prefixes; AGENTS.md owns scope.
See [the workflow](workflow.md#worktrees-and-parallel-work) for delegation and
integration. No global agent configuration or model setting is changed.

Publication routes are platform-specific: the existing release skill owns
desktop, while the mobile guide and iOS workflow own TestFlight. A coordinator
reserves each platform's versions/builds after integration and verifies actual
availability. Desktop and mobile version numbers remain independent.
The operational desktop path is Community. The signed path is documented as
blocked because its manual workflow conflicts with the preflight's tag-trigger
expectation and the unconditional Community tag trigger. Workflow repair is
outside this instruction-only integration.

Windows CI exposed Git's CRLF conversion of the pinned upstream license. The
existing `.gitattributes` notice policy now also keeps skill licenses as LF,
preserving their exact hashes. A real-Git checkout regression failed before the
rule and passed afterward. The focused checks passed 43 tests on Linux and all
17 validator tests on Windows; the license hash check was not weakened.

## Humanizer integration, 2026-10-25

[Humanizer](../../.agents/skills/humanizer/SKILL.md) is installed from
[blader/humanizer, commit 8c307f36](https://github.com/blader/humanizer/tree/8c307f367c91bd974002f10f2be2965d642c13df),
version 3.1.0. Its
[source record](../../.agents/skills/humanizer/UPSTREAM.json) pins the commit and
SHA-256 hashes of the original entrypoint, invocation metadata, and license.
The [MIT notice](../../.agents/skills/licenses/blader-humanizer-MIT.txt) preserves
Siqi Chen's copyright.

The local copy retains the upstream editing process and examples. Its description
uses the project's single-line metadata format. A short integration note links
the project workflow and language rules, selects embedded output, and preserves
localization placeholders, technical terms, accessibility meaning, and product
behavior. Invocation metadata explicitly permits implicit use.

[AGENTS.md](../../AGENTS.md) requires Humanizer whenever an agent writes, edits,
translates, or reviews project prose. This includes public and user-facing copy
in the application, emails, websites, documentation, release notes, support
replies, and project communications, in every language and for short changes.
This instruction governs writing and review; sending or publishing text still
requires the authorization defined in the project workflow.

The Matt Pocock inventory remains pinned to its audited source. Humanizer is
listed under `project_skills` because it has a separate source record. The
installation contains the skill entrypoint, invocation metadata, source record,
and license notice. All files are local to the repository.

Instruction checks cover a short Portuguese interface label with a localization
placeholder, an email with factual dates, website copy about sponsorship, and a
technical document with commands. In each case, agents must apply Humanizer while
preserving supported claims and executable text. These are instruction checks;
they do not establish measured writing quality or runtime behavior.
