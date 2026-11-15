# Support

## Usage questions

Before opening an issue:

1. Read the installation and provider sections in [README.md](README.md).
2. Check [docs/development.md](docs/development.md) if running from source.
3. Search existing GitHub issues for the error or model ID.
4. When using a personal key, confirm it validates in **Models and services**.

If the problem remains, open a bug report with your Windows version,
Clarify version or commit, installation method, provider, model ID, and
sanitized error text.

## Opening and updating the Windows app

Check the installed version in **Settings → About** and compare it with the
[latest published release](https://github.com/jvictormaynard/clarify/releases/latest).
The version in source code can be newer than the Windows download.

Closing or minimizing can leave Clarify in the system tray. Use the tray icon
or the configured visibility shortcut (default **Alt+R**) to restore it. A
PyInstaller launcher and child process are one logical app instance.

When an update is downloaded, save or discard drafts, finish recording and
close the Clarify Settings window. Hiding or minimizing can retain unsaved edits
and prevent the restart. Do not delete your profile or keys to troubleshoot an
update. Include the update status message in a bug report.

## Keep secrets out of support requests

Never post:

- API keys or authorization headers;
- `%APPDATA%\Clarify\config.json` without fully redacting keys;
- private transcripts or selected text;
- provider request or response bodies containing personal content;
- personal Windows paths when they are not necessary.

Replace keys with `<redacted>` and reduce examples to the smallest synthetic
input that still reproduces the issue.

## What belongs elsewhere

- Vulnerabilities: follow [SECURITY.md](SECURITY.md).
- Feature ideas: use the feature request template.
- Code changes: read [CONTRIBUTING.md](CONTRIBUTING.md) and open a pull request.
- Provider billing, quotas, or account access: contact that provider directly.
