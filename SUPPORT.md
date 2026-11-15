# Support

## Usage questions

Before opening an issue:

1. Read the installation and provider sections in [README.md](README.md).
2. Check [docs/development.md](docs/development.md) if running from source.
3. Search existing GitHub issues for the error or model ID.
4. Confirm that the selected provider key validates in **Models**.

If the problem remains, open a bug report with your Windows version,
Clarify version or commit, installation method, provider, model ID, and
sanitized error text.

## Keep secrets out of support requests

Never post:

- API keys or authorization headers;
- `%APPDATA%\Clarify\config.json` without fully redacting keys;
- private transcripts or selected text;
- provider request or response bodies containing personal content;
- personal Windows paths when they are not necessary.

Replace keys with `<redacted>` and reduce examples to the smallest synthetic
input that still reproduces the issue.

## Local diagnostic report

In **Data and privacy**, select **Generate diagnostics**. Review the report,
then select **Save diagnostics** to save a JSON file on your computer. Share it
only after review. Clarify does not send the report automatically.

The report contains the application version, environment, and technical error
metadata. It does not include your configuration, dictation history, or provider
request and response bodies.

## What belongs elsewhere

- Vulnerabilities: follow [SECURITY.md](SECURITY.md).
- Feature ideas: use the feature request template.
- Code changes: read [CONTRIBUTING.md](CONTRIBUTING.md) and open a pull request.
- Provider billing, quotas, or account access: contact that provider directly.
