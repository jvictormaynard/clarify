# Contributor and agent guide

- Use ASD-STE100 Simplified Technical English with João Victor. When he writes
  Portuguese, use simple controlled Portuguese with the same technical precision.
- Read and apply `.agents/skills/humanizer/SKILL.md` whenever you write, edit,
  translate, or review prose for this project. This is required for public and
  user-facing text, including application copy, emails, websites, documentation,
  release notes, support replies, and project communications. Apply it in every
  language, including short text changes. Preserve facts, technical meaning, and
  localization placeholders.

- Production Qt code and QML assets: `clarify/desktop/`.
- React/Tauri Settings: `desktop/`.
- Provider, storage, and workflow contracts: focused Python modules at the root.
- `app.py` and `spikes/` support legacy compatibility and historical measurements;
  do not add product features there or remove persisted-data migrations blindly.
- Read `CONTRIBUTING.md` and `docs/architecture.md` before structural changes.
- Use the pinned requirements and npm/Cargo lockfiles. Runtime Qt needs
  `PySide6-Essentials`, not the full `PySide6`/Addons distribution.
- Keep tests isolated from real profiles, microphones, provider keys and audio.
- Run checks for the affected contracts as defined in `docs/ci-delivery.md`.
  Python behavior needs the Python suite; Settings changes need web and bridge
  tests. Packaging changes also need the Windows build and embedded-payload checks.
- Never include `.env`, local configuration, keys or recordings in commits.
- A passing CI is not manual Windows acceptance. Follow the repository release
  procedure and document open gates before publishing.

## Delivery workflow

- For an authorized feature, fix, or refactor, read
  `.agents/skills/clarify-delivery/SKILL.md` and follow
  `docs/agents/workflow.md`. Complete implementation, applicable checks, repair,
  and review before reporting completion.
- Inspect source and existing tests before asking for technical facts. Decide
  routine reversible implementation details autonomously. Ask only for missing
  decisions that affect product behavior, compatibility, data, or task scope.
- Preserve the starting branch, unrelated edits, user profiles, and existing
  demo artifacts. Stage only files belonging to an authorized Git operation.
- Start every implementation in a distinct linked worktree from freshly fetched
  `origin/main`. Verify its directory, task branch, and current-base ancestry
  before edits and delivery. Never use stale local `main` or silently continue
  after a failed fetch. Use native Git as defined in `docs/agents/workflow.md`.
- Commit, push, PR, merge, tracker writes, and publication follow the user's
  request and prior authorization. A skill does not grant those permissions.
- For independent implementation tasks, delegate to parallel subagents when
  supported. Give every writer its own worktree and bounded ownership. The
  coordinator owns integration and final validation. Keep dependent tasks serial.
  Follow the review requirements in `docs/agents/workflow.md`. If delegation is
  unavailable, report the limitation and use sequential self-review passes.

## Project skills

Skills are versioned regular files in `.agents/skills/` and apply only to Clarify.
Keep installation, configuration, and updates inside this repository.

| Work | Read when needed |
| --- | --- |
| Interface, ownership, or dependency changes | `.agents/skills/codebase-design/SKILL.md` and `docs/architecture.md` |
| Changed behavior or regression | `.agents/skills/tdd/SKILL.md` |
| Unclear or intermittent failure | `.agents/skills/diagnosing-bugs/SKILL.md` |
| Final change review or review-only request | `.agents/skills/code-review/SKILL.md` |
| Requested architecture survey | `.agents/skills/improve-codebase-architecture/SKILL.md` |
| Terminology or durable design decision | `.agents/skills/domain-modeling/SKILL.md` and `docs/agents/domain.md` |
| Issue/spec/ticket work | `docs/agents/issue-tracker.md` and the matching local skill |
| Desktop release, tag, or publication | `.agents/skills/clarify-release/SKILL.md` |
| CI/CD, native Railway autodeploy, or release automation | `docs/ci-delivery.md`, then `docs/server-delivery.md` or `docs/release-automation.md` |
| iOS build or TestFlight publication | `mobile/README.md` and `.github/workflows/ios-testflight.yml` |
| Agent guidance or upstream skill update | `.agents/skills/writing-for-agents/SKILL.md` and `docs/agents/skill-audit.md` |

Load only the skills relevant to the task. Use `ask-matt` when workflow selection
is unclear. `python scripts/check_agent_skills.py` checks local metadata,
references, scope, attribution, and the upstream inventory; CI runs it in the repository checks job. This check does not prove an agent's judgment or native UI acceptance.
