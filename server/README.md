# Optional shared Clarify account

This service and the desktop/iOS clients are public under the root MIT license.
Production keys, database contents, backups and administrator access are private.
The private business dashboard is documented in [ADMIN.md](ADMIN.md).
See [sponsored usage and public finances](../docs/finances.md) for allocation,
operator commands and the public transparency page. Stripe registration is
deferred until a business account is available.
See the [privacy notice and account deletion instructions](../PRIVACY.md).
The server is optional: local inference and personal provider keys still work
without an account. The iOS app processes through an explicitly paired
computer. Signing in alone does not enable processing. Personal models and
provider keys remain on that computer. Accounts share vocabulary, action
definitions and account transcriptions. Pre-upgrade records and guest history stay on their original
device. Account snippets have a separate synchronized library; guest snippets
and personal provider keys stay on their original device. Signing in does not
upload guest snippets. Account
history uses [bounded, idempotent synchronization](../docs/history-sync.md).
Account-owned text actions use a separate [versioned catalog and execution
protocol](TEXT_ACTIONS.md). Device shortcuts and processing profiles stay local.

## Run and verify

Use Python 3.12, PostgreSQL 16 or later, and ffmpeg. From the repository root:

```sh
python3 -m venv server/.venv
server/.venv/bin/pip install --require-hashes -r server/requirements.txt
# Set DATABASE_URL to an isolated test database, not a production database.
CLARIFY_DEVELOPMENT=1 server/.venv/bin/python server/manage.py test cloud.service.tests
```

On Windows, use the same hashed lock in PowerShell:

```powershell
py -3.12 -m venv server/.venv
server/.venv/Scripts/python.exe -m pip install --require-hashes -r server/requirements.txt
$env:CLARIFY_DEVELOPMENT = "1"
# Set DATABASE_URL to an isolated test database before running the suite.
server/.venv/Scripts/python.exe server/manage.py test cloud.service.tests --noinput
```

The Windows dependency check in CI resolves this lock without starting services.
It does not replace the PostgreSQL tests or Linux container acceptance. The
production `server/start.py` entry point uses Gunicorn and runs on Linux.

SQLite is available for development only. Concurrency tests require PostgreSQL.
Tests use fake provider responses, synthetic silent audio and in-memory email.
No provider key, real recording or real profile is required.

Build the container from the repository root:

```sh
docker build -f server/Dockerfile -t clarify-account .
docker run --env-file server/.env -p 8080:8080 clarify-account
```

Set the fields in `server/.env.example` in the host's private secret store.
Use a dedicated database. The account service needs no inference provider key.
Never ship server credentials in clients.
Start-up runs serialized migrations and creates the allauth database cache.
Place the service behind a TLS reverse proxy which overwrites forwarded headers.
Set its public host in `ALLOWED_HOSTS`. Limit request bodies to 25 MiB at ingress.
`GET /health` checks database connectivity. Only that path is exempt from the
application's HTTPS redirect, for private host probes.

On Railway, also include `healthcheck.railway.app` in `ALLOWED_HOSTS`; Railway
uses that host for its deployment probe. Keep the generated service domain
and the verified custom domain in the same explicit list. Do not use `*`.
See [server delivery on Railway](../docs/server-delivery.md) for native GitHub
autodeploy from `main`, Wait for CI, watch paths, and deployment verification.

The beta uses Resend Free for outbound codes. Verify `victormaynard.com` in
Resend and add the requested DNS records in Cloudflare, preserving existing
mail records. SMTP uses `smtp.resend.com:465`, implicit TLS, user `resend`, and a
private sending key restricted to this domain. See the official
[SMTP reference](https://resend.com/docs/send-with-smtp). The free plan allows
100 emails per day and 3,000 per month, including resends. Monitor this quota
before expanding registration. This quota is shared with other projects in the
same Resend team. Clarify caps send attempts at 50 per UTC day by default;
failed sends also consume this conservative limit. Adjust
`CLARIFY_DAILY_EMAIL_LIMIT` only after checking the team's remaining allowance.
Do not send real messages from tests.

Before opening registration, test code delivery and logout with a test account.
Registration defaults off. Inference is retired independently of the historical
funding flags and budgets. The source retains accounting migrations and finance
records; a funded allocation cannot reopen processing endpoints.

## Client protocol

Native clients use django-allauth headless email codes. A successful authenticated
session uses `X-Session-Token`; it is never a Groq key. Codes expire after 10
minutes. Sessions expire after 14 days and logout revokes the session. Clients
send the device UI language as `Accept-Language` (`pt`, `en`, or `es`). Both new
and existing accounts receive a localized code email without a subject prefix
or browser link. Unsupported device languages use English.

Google, Microsoft and GitHub signup/login use a PKCE-bound one-time browser
handoff for desktop and iOS. See [social sign-in configuration and protocol](SOCIAL_AUTH.md)
for provider registration, server secrets, native continuation and acceptance gates.

| Request | Purpose |
| --- | --- |
| `POST /_allauth/app/v1/auth/continue` | Enter or create a passwordless account with `email`; confirm with `code/confirm` |
| `POST /_allauth/app/v1/auth/signup` | Start signup with `email` |
| `POST /_allauth/app/v1/auth/email/verify` | Confirm signup with six-digit `key` |
| `POST /_allauth/app/v1/auth/code/request` | Request login code with `email` |
| `POST /_allauth/app/v1/auth/code/confirm` | Confirm login with six-digit `code` |
| `DELETE /_allauth/app/v1/auth/session` | Revoke current session |
| `GET /v1/account` | Account identity; `hosted_inference_available: false` |
| `DELETE /v1/account` | Delete account with `{"confirm":true}` |
| `GET /v1/usage` | Retired: HTTP 410, `inference_retired` |
| `GET /v1/dictionary` | This account's vocabulary and revision |
| `PUT /v1/dictionary` | Replace vocabulary using `revision` and `entries` |
| `GET /v1/snippets` | This account's snippet library and revision |
| `PUT /v1/snippets` | Replace snippets using `revision` and `entries` |
| `POST /v1/history/sync` | Synchronize bounded new account records and deletions with a durable cursor |
| `POST /v1/dictations` | Retired: HTTP 410, `inference_retired` |
| `POST /v1/text` | Retired: HTTP 410, `inference_retired` |
| `GET /v1/text-actions`, `PUT /v1/text-actions` | Read or replace revision-controlled action definitions |
| `POST /v1/text-actions/execute` | Retired: HTTP 410, `inference_retired` |

Account library `/v1` routes require an active session and a verified primary
email. The server derives ownership from that session. The retirement middleware
returns `410 {"code":"inference_retired","update_required":true}` for processing
and usage routes before body parsing, authentication, admission or provider work.
There is no provider proxy or hosted fallback. Updated clients execute account
text-action definitions with their own personal profile on the computer.

Snippets have a spoken `trigger`, literal `replacement`, `enabled` flag and
`case_sensitive` flag. The account library allows up to 512 entries, 256
characters per trigger and 4,096 characters per saved replacement. Its normalized
entry array must fit 262,144 UTF-8 bytes when encoded as compact JSON with
literal Unicode (no ASCII escaping). The server returns `snippets_too_large`
without changing the revision when this aggregate limit is exceeded. Local
guest libraries retain their existing per-entry limits.

Snippet writes use optimistic revisions; a stale write returns
`snippet_conflict`. The independent library prevents older dictionary clients
from erasing snippets. Account deletion removes the library. Recognition, snippet substitution and optional editing run on the user's
computer. Account definitions synchronize independently of processing profiles.
For personal execution and output preferences, see [account text actions](TEXT_ACTIONS.md)
and the [computer processing contract](../docs/computer-connection.md).

Signing in connects vocabulary. Each account has a separate local cache; logout
restores guest vocabulary. Sync combines independent edits and preserves deletions.
A same-word conflict requires a choice; revision mismatches never overwrite the
server silently. Failed attempts retain the existing cooldown. This version does
not push library changes in real time.

`GET /transparency/` and `GET /v1/public/finances` are public. They publish
normalized financial records without account or donor identifiers. They do not
expose administrator access or processing endpoints.

## Bounds and retention

- Processing routes reject input before parsing or provider work. Updated clients
  send audio and processing text to the paired computer or selected provider.
- Vocabulary and snippets use bounded libraries and revision-controlled writes.
  A library is data; it cannot grant server inference or select credentials.
- `/v1/history/sync` stores account records until explicitly deleted. Bounded
  storage and permanent tombstones prevent stale uploads from restoring them.
  Synchronization does not call a provider.
- Historical cost, reservation and funding records remain for audit. Retired
  processing endpoints cannot create a new reservation. Legacy cached processing
  results and operation metadata retain their existing cleanup policy. Account
  deletion removes identity, libraries, history and synchronization metadata and
  detaches historical accounting records. Configure backup retention separately.
- No transcripts, audio, credentials, HTTP headers or provider error bodies in
  application/access logs. The default proxy limiter uses the connection peer,
  not untrusted forwarding headers. Behind a shared proxy, this is conservative
  and can limit multiple users together. Verify trustworthy ingress IP handling
  before widening the beta; do not blindly trust `X-Forwarded-For`.

Open code does not grant access to the hosted service. Security rests on account
verification, ownership checks, bounded inputs, atomic limits and server secrets.
Self-hosters configure account delivery, limits and database. Inference remains
on each user's computer or selected provider.

## Release gates

Native Railway delivery uses the connected repository and `main`, the existing
Dockerfile, and `/health`. The [delivery guide](../docs/server-delivery.md)
records the activation steps and the open usage v2 compatibility, first migration,
and funding rollout gates. The 2026-10-25 read-only inspection found
`config.source.checkSuites=false`, so Wait for CI still needs activation and
verification. The source connection does not establish that autodeploy is enabled.

The **Server recovery image** workflow has a manual `publish_server_image` option,
off by default. Only an explicit dispatch in `jvictormaynard/clarify` can publish
to `ghcr.io/jvictormaynard/clarify-server`. This recovery path pins commit
`ced75d817decd55e7ed6f350e34e008b59f9cb26` and its reviewed Git archive hash.
It exports only 49 allowlisted source files, runs isolated PostgreSQL tests,
builds the existing Dockerfile, checks startup and database health, and verifies
the image files before login or push. The image contains 47 source files:
`.dockerignore` is not copied and `server/.env.example` is excluded by Docker.
No runtime credentials, profiles or recordings enter the build context.

Canonical `CI` owns ordinary server and iOS validation. The recovery workflow
checks the pinned image by default. Publication requires its explicit option
on `main`. Registry login uses only the temporary
workflow token through stdin; the image has a unique run/attempt tag. The artifact
records its digest, source SHA and source manifest. No Railway credentials or
service configuration are used. Publishing an image does not deploy it; whether
this route avoids the current snapshot failure still needs controlled live
verification. Changing this recovery source pin requires a new review.

Server tests, desktop Python/Settings checks and iOS native compilation must pass.
Live email, device pairing, account isolation, inference retirement,
session revocation and account deletion need staging acceptance. No automatic
TestFlight upload is part of this change. The public iOS release must validate
keyboard activation and return to the source app under the
[iOS release procedure](../mobile/README.md).
Public launch also needs an accurate privacy policy, account deletion instructions
and a tested backup/restore policy. Apple login and billing are separate increments.
