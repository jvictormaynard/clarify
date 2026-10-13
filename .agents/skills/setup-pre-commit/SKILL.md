---
name: setup-pre-commit
description: "Inspect or repair project commit hooks and their checks when hook work is requested."
---

Follow the [project workflow](../../../docs/agents/workflow.md); it defines scope, authorization, validation, and completion.

# Maintain Clarify commit hooks

Read `.githooks/pre-commit`, `scripts/format_staged.py`, `package.json`, and the current CI workflow before making a change.

The repository already has a Python/Ruff staged-file formatter and `npm run setup-hooks` for local `core.hooksPath`. Keep that mechanism unless the task shows a concrete missing check. Preserve partially staged files and unrelated edits.

Use existing locked tools. Keep commit-time feedback focused and fast; broad tests and Windows packaging belong in the relevant validation gates. A hook complements CI and does not replace it.

Install hooks only for the current repository. Do not add Husky, lint-staged, Prettier, or global Git configuration by default. Verify changes in an isolated temporary Git repository with a real failing and passing case. Commit only within the user's Git authorization.
