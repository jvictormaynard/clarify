# Contributing to Clarify

Thank you for helping improve Clarify. Contributions are welcome from
first-time and experienced open-source contributors.

## Good first contributions

- Reproduce and document a bug
- Improve installation or troubleshooting instructions
- Add or refine an interface translation
- Add tests around provider routing or workflow safety
- Improve accessibility, keyboard behavior, or DPI handling
- Support another compatible transcription or refinement provider

Large UI rewrites, new resident services, or broad dependency changes should be
discussed in an issue first. Clarify is intentionally lightweight and
focus-safe.

## Before opening an issue

1. Search existing issues.
2. Confirm the problem on the newest release or current default branch.
3. Remove API keys, selected text, transcripts, personal paths, and provider
   request bodies from screenshots and logs.
4. For provider failures, include the provider, model ID, endpoint type
   (official or custom), HTTP status, and sanitized error message.

Use the bug or feature template so maintainers receive enough context to act.
For usage questions, follow [SUPPORT.md](SUPPORT.md). Report vulnerabilities
privately as described in [SECURITY.md](SECURITY.md).

## Development setup

Choose the setup for your change. Settings design and documentation
contributions do not need a native Windows build or an Apple account.

### Settings design or web behavior

Use Python 3.12 and Node.js 22. Rust, Visual Studio and WebView2 are needed only
for native Settings builds. On Windows, prepare the locked Python environment:

```powershell
.\scripts\setup.ps1 -Dev
cd desktop
npm ci
npm run build
$env:CLARIFY_TEST_PYTHON = (Resolve-Path ..\.venv\Scripts\python.exe).Path
$env:CLARIFY_TEST_FIXTURE = (Resolve-Path ..\tests\web_settings_fixture.py).Path
$env:CLARIFY_TEST_BROWSER = 'chromium'
npx --no-install playwright install chromium
npm test
```

When running tests in multiple worktrees, assign each run a different
`CLARIFY_TEST_PORT` (the default is `1420`). The test server fails if that port
is occupied. Each worktree keeps its own dependencies and build outputs.

The browser tests use a temporary Python controller with fake providers. They
need no user profile, account, provider key, microphone or native executable.
Linux contributors can use the same checks with the Linux lock and interpreter;
see the `settings` job in [CI](.github/workflows/ci.yml) for runtime packages and
`playwright install --with-deps chromium`. Record screenshots for visual changes.

### Python, QML or native Windows behavior

On Windows:

```powershell
git clone https://github.com/jvictormaynard/clarify.git
cd clarify
.\scripts\setup.ps1 -Dev
.\scripts\build-settings.ps1
$env:CLARIFY_SETTINGS_EXECUTABLE = (Resolve-Path .\dist\clarify-settings.exe).Path
.\.venv\Scripts\python.exe scripts/run_tests.py discover -s tests -v
.\.venv\Scripts\python.exe clarify\desktop\qml_app.py
```

Read [docs/development.md](docs/development.md) for builds, platform notes, and
the full Windows acceptance checklist. Read
[docs/architecture.md](docs/architecture.md) before moving responsibilities
between modules.

Settings development needs Node.js 22, Rust MSVC, Visual Studio C++ Build Tools,
the Windows SDK, and WebView2. End users do not need these build tools.
Use `desktop/src/` for Settings, `clarify/desktop/qml/` for the pill, and the
root provider modules for ASR and text processing. `clarify/desktop/` contains
the production Qt adapters. Do not add features to legacy `app.py` or the
historical comparison tools under `spikes/`.

For a small first contribution, see the [contributor map and acceptance
criteria](docs/release-readiness.md).

## Making a change

For agent implementation, read [AGENTS.md](AGENTS.md) and the
[project workflow](docs/agents/workflow.md). Use a linked worktree from freshly
fetched `origin/main`. Independent writers use separate worktrees; follow the
[parallel-work rules](docs/agents/workflow.md#worktrees-and-parallel-work) for setup
and integration.

1. Fork the repository and create a focused branch from the default branch.
2. Keep unrelated refactors out of the same pull request.
3. Add or update tests when behavior changes.
4. Update user documentation when installation, shortcuts, providers, privacy,
   or configuration changes.
5. Run the checks below.
6. For native integration changes, build and test the Windows executable when
   your environment supports it. Report unavailable platform checks in the PR.
   Maintainers complete native acceptance before publication.

Use clear commit messages. Conventional prefixes such as `fix:`, `feat:`,
`docs:`, `test:`, and `chore:` are encouraged but not required.

## Checks for your change

CI selects checks from the complete PR diff. No special branch prefix, label,
paid service or secret is required. Pushes to a branch with an open PR run one
PR workflow. Maintainers may need to approve a first-time fork's workflow run.

- Documentation: run `python scripts/check_agent_skills.py` when changing agent
  guidance, and `git diff --check`. No product build is needed.
- Settings design: run the frontend build and isolated browser tests above.
  Rust and the portable EXE are not required for a frontend-only PR.
- Python or QML: run the Python suite and relevant QML checks. CI tests Python
  behavior on Linux and Windows.
- Mobile TypeScript: run `npm ci` and `npm run check` in `mobile/`. CI also checks
  the iOS JavaScript bundle with bounded worker concurrency. Native source, config, plugins and dependencies
  additionally select macOS tests and an unsigned native build.
- Server: use the isolated database tests in [server/README.md](server/README.md).
- Dependencies or packaging: run the corresponding locked checks and native
  build. MSI lifecycle checks apply to installer inputs, not ordinary design PRs.

For Python changes, use the configured interpreter:

```powershell
.\.venv\Scripts\python.exe scripts/run_tests.py discover -s tests -v
```

The runner creates a temporary process profile before test discovery, removes
inherited provider credentials and sets `CLARIFY_SKIP_DOTENV=1`. It accepts the
same arguments as `unittest`; no arguments run full discovery. See the
[focused example](docs/development.md#checks) for a single test file.

The [CI policy](docs/ci-delivery.md) defines the checks and branch-protection
migration. Unknown inputs select full validation. Manual CI runs remain available
for a complete diagnostic. Native builds use public tools on GitHub-hosted
runners; fork PRs receive no publication credentials.

Dependency intent is kept in `requirements.txt` and `requirements-dev.txt`;
the generated platform locks (`requirements-lock-linux.txt` and
`requirements-lock-windows.txt`) are the shared inputs for setup, CI, packaging,
and releases. If intent changes, regenerate each lock on its matching runner
with `python -m piptools compile --strip-extras --output-file=...` and include
both resulting diffs. Do not add an audit exception without a reviewed rationale
in `dependency-audit.json`.

Commit `desktop/package-lock.json` and `desktop/src-tauri/Cargo.lock` when
changing their dependencies. Dependabot covers both ecosystems. Browser tests
do not prove native Windows focus, hotkeys, tray behavior or WebView2 integration.

For packaging-related changes:

```powershell
.\scripts\build.ps1
```

For native Windows behavior and release acceptance, check the built executable,
including affected focus, shortcuts, tray, transparency and DPI behavior. A
frontend-only PR can use browser evidence; list any native checks left for the
maintainer. CI never publishes a client simply because a contribution passes.

## Pull requests

A useful pull request:

- explains the user-visible problem and solution;
- links the related issue when one exists;
- lists the exact validation performed;
- includes screenshots or a short recording for visual changes;
- calls out platform-specific limitations;
- contains no secrets or personal user data;
- keeps generated executables, `.env`, and local config files out of Git.

Maintainers may ask for a smaller scope when a change mixes unrelated concerns.
Review is collaborative, and specific technical disagreement is welcome when it
stays respectful and evidence-based.

`main` requires a pull request, resolved review conversations, and passing checks
against the current base. The selective workflow reports `CI required`; see the
[protection migration](docs/ci-delivery.md#branch-protection-migration) when the
repository still requires the previous three unconditional Desktop checks. Force pushes and branch deletion are disabled,
including for administrators. A second person's approval is not required for
this single-maintainer repository; this does not replace the release gates.

## Translations

When adding a new interface language:

1. Add the language and accessible labels in the QML surface under `clarify/desktop/qml/`.
2. Translate every key in the interface catalog.
3. Add tests showing that the catalog is complete and the flag renders.
4. Check controls at normal and scaled DPI because translated labels vary in
   length.

## Licensing

By submitting a contribution, you agree that it may be distributed under the
project's [MIT License](LICENSE). Do not submit code, images, icons, or other
material that you do not have permission to redistribute. Identify any
third-party material and its license in the pull request.
