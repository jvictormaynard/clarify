# Contributor and agent guide

Use ASD-STE100 Simplified Technical English with João Victor. When he writes
Portuguese, use simple controlled Portuguese with the same technical precision.
Read and apply [humanizer](.agents/skills/humanizer/SKILL.md) when writing, editing,
translating, or reviewing project prose, including short copy and communications.
Preserve facts, technical meaning, and localization placeholders.

## Work from the affected contract

- Python/Qt workflow controllers and QML recovery views live in `clarify/desktop/`;
  the Electron shell and React Settings/pill live in `desktop/`.
  Focused root Python modules own providers, storage, and workflows.
- `app.py` and `spikes/` retain legacy compatibility and measurements. Do not add
  product features there or remove persisted-data migrations without evidence.
- Read [architecture](docs/architecture.md) and [contribution guidance](CONTRIBUTING.md)
  before changing ownership, interfaces, or dependencies.
- Before desktop UI work, read [the desktop design system](docs/desktop-design-system.md).
  Reuse its tokens and components. Verify the rendered result, responsive layout,
  keyboard focus, and affected states. It also defines native Qt/QML shell limits.
- Trace every affected entry point, client, provider route, persisted state, and
  reverse action. A path that works in one UI does not prove the shared feature.

## Deliver the requested work

Use [clarify-delivery](.agents/skills/clarify-delivery/SKILL.md) for an authorized
feature, fix, or refactor. The [engineering workflow](docs/agents/workflow.md) owns
scope, worktrees, test selection, file retention, review, and completion.

- Inspect source and existing tests first. Decide routine reversible details.
  Ask only when missing information changes behavior, compatibility, data, or scope.
- Preserve the starting branch, unrelated edits, user profiles, and demo artifacts.
  Use an isolated linked worktree from freshly fetched `origin/main`; reuse a
  valid assigned task worktree. Stage only explicit authorized paths.
- Delegate independent implementation outcomes when supported, with one worktree
  per writer and bounded ownership. Keep dependent work serial. The coordinator
  integrates and validates; reviewers inspect the fixed candidate read-only.
- Use the pinned requirements and npm/Cargo lockfiles. Qt needs
  `PySide6-Essentials`, not the full `PySide6`/Addons distribution.
- Follow the [shared validation plan](docs/ci-delivery.md) for focused quick local
  checks and complete affected validation in remote CI. The
  [workflow](docs/agents/workflow.md#validation-by-affected-contract) defines when
  to repeat checks and collect direct UI proof. Tests use isolated profiles and
  fake providers, keys, and audio.
- Apply [test retention](docs/agents/workflow.md#tests-worth-retaining): keep only
  necessary regression coverage, reuse cases, and leave one-time probes temporary.
- Keep PR-only captures, logs, runtime state, and scratch files outside Git.
  Attach visual evidence to the PR. Follow [file retention](docs/agents/workflow.md#files-and-evidence)
  before adding documentation, tests, or evidence files.
- Commit, push, PR creation, merge, tracker writes, deployment, and publication
  follow the user's request and prior authorization. Skills grant no permissions.
- Passing CI is not manual Windows acceptance or a release. Report open gates
  before publication; never commit secrets, local profiles, keys, or recordings.

## Load a skill when its method is needed

Do not run a chain of skills as a checklist. Read only the relevant entrypoint
and the conditional reference that resolves the current question.

| Work | Route |
| --- | --- |
| Feature, fix, or refactor | `clarify-delivery` |
| Unclear failure or measured regression | `diagnosing-bugs` |
| Changed behavior with a useful regression test | `tdd` |
| Interface or dependency design | `codebase-design` and `docs/architecture.md` |
| Final review or review-only request | `code-review` |
| Requested architecture survey | `improve-codebase-architecture` |
| Product ambiguity or requested design interview | `grilling`; `domain-modeling` for durable decisions |
| Large effort with unresolved decisions | `wayfinder` |
| Spec, issue, ticket, or questionnaire request | Matching `to-*` or `triage` skill and `docs/agents/issue-tracker.md` |
| Uncertain external fact or experiment | `research` or `prototype` |
| PR description or continuation | `pr` or `handoff` |
| Merge/rebase conflict | `resolving-merge-conflicts` |
| Required manual setup | `wizard` |
| Agent guidance, upstream skills, or hooks | `writing-for-agents`, `setup-matt-pocock-skills`, or `setup-pre-commit` |
| Requested retrospective or repeated delivery failure | `retro` |
| Desktop release, tag, or publication | `clarify-release` |
| CI/CD or server/client release automation | `docs/ci-delivery.md`, then `docs/server-delivery.md` or `docs/release-automation.md` |
| iOS build or TestFlight | `mobile/README.md` and `.github/workflows/ios-testflight.yml` |

Skills are regular versioned files in `.agents/skills/`. Keep changes inside this
repository. `python scripts/check_agent_skills.py` checks their metadata, links,
scope, attribution, and inventory. The [source audit](docs/agents/skill-audit.md)
records adaptation decisions. These checks do not prove agent judgment or UI acceptance.
