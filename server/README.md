# Optional shared Clarify account

This service and the desktop/iOS clients are public under the root MIT license.
Production keys, database contents, backups and administrator access are private.
The private business dashboard is documented in [ADMIN.md](ADMIN.md).
See the [privacy notice and account deletion instructions](../PRIVACY.md).
The server is optional: local inference and personal provider keys still work
without an account. The iOS app currently supports personal Groq keys, not local
inference. Accounts share vocabulary, hosted audio allowance and new account
transcriptions. Pre-upgrade records and guest history stay on their original
device. Account snippets have a separate synchronized library; guest snippets
and personal provider keys stay on their original device. Signing in does not
upload guest snippets. Account
history uses [bounded, idempotent synchronization](../docs/history-sync.md).

## Run and verify

Use Python 3.12, PostgreSQL 16 or later, and ffmpeg. From the repository root:

```sh
python3 -m venv server/.venv
server/.venv/bin/pip install --require-hashes -r server/requirements.txt
# Set DATABASE_URL to an isolated test database, not a production database.
CLARIFY_DEVELOPMENT=1 server/.venv/bin/python server/manage.py test cloud.service.tests
python3 mobile/scripts/sync-prompts.py --check
```

SQLite is available for development only. Concurrency tests require PostgreSQL.
Tests use fake provider responses, synthetic silent audio and in-memory email.
No provider key, real recording or real profile is required.

Build the container from the repository root:

```sh
docker build -f server/Dockerfile -t clarify-account .
docker run --env-file server/.env -p 8080:8080 clarify-account
```

Set the fields in `server/.env.example` in the host's private secret store.
Use a dedicated database and Groq project/key. Never ship these values in clients.
Start-up runs serialized migrations and creates the allauth database cache.
Place the service behind a TLS reverse proxy which overwrites forwarded headers.
Set its public host in `ALLOWED_HOSTS`. Limit request bodies to 25 MiB at ingress.
`GET /health` checks database connectivity. Only that path is exempt from the
application's HTTPS redirect, for private host probes.

On Railway, also include `healthcheck.railway.app` in `ALLOWED_HOSTS`; Railway
uses that host for its deployment probe. Keep the generated service domain
and the verified custom domain in the same explicit list. Do not use `*`.

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
Before enabling hosted inference, approve a global budget and check Groq's own
project spending/rate limits. Both registration and hosted inference default off;
the monthly budget defaults to zero. Account quota defaults to 300 audio minutes
per UTC calendar month. These are beta controls, not a promise of a paid plan.

## Client protocol

Native clients use django-allauth headless email codes. A successful authenticated
session uses `X-Session-Token`; it is never a Groq key. Codes expire after 10
minutes. Sessions expire after 14 days and logout revokes the session. Clients
send the device UI language as `Accept-Language` (`pt`, `en`, or `es`). Both new
and existing accounts receive a localized code email without a subject prefix
or browser link. Unsupported device languages use English.

| Request | Purpose |
| --- | --- |
| `POST /_allauth/app/v1/auth/continue` | Enter or create a passwordless account with `email`; confirm with `code/confirm` |
| `POST /_allauth/app/v1/auth/signup` | Start signup with `email` |
| `POST /_allauth/app/v1/auth/email/verify` | Confirm signup with six-digit `key` |
| `POST /_allauth/app/v1/auth/code/request` | Request login code with `email` |
| `POST /_allauth/app/v1/auth/code/confirm` | Confirm login with six-digit `code` |
| `DELETE /_allauth/app/v1/auth/session` | Revoke current session |
| `GET /v1/account` | Account identity and shared allowance |
| `DELETE /v1/account` | Delete account with `{"confirm":true}` |
| `GET /v1/usage` | Shared allowance for this account |
| `GET /v1/dictionary` | This account's vocabulary and revision |
| `PUT /v1/dictionary` | Replace vocabulary using `revision` and `entries` |
| `GET /v1/snippets` | This account's snippet library and revision |
| `PUT /v1/snippets` | Replace snippets using `revision` and `entries` |
| `POST /v1/history/sync` | Synchronize bounded new account records and deletions with a durable cursor |
| `POST /v1/dictations` | Multipart `audio`, UUID `operation_id`, optional `language`; returns updated allowance |
| `POST /v1/text` | Fixed rewrite or translation: UUID `operation_id`, `action`, `text`, `language`; returns updated allowance |

All `/v1` routes require an active session and a verified primary email. The
server derives account ownership from that session. It rejects caller-supplied
owner IDs, provider URLs, prompts, models and token settings. There is no chat,
completion or general provider proxy. Fixed processing is Whisper Large V3 Turbo
followed by GPT OSS 20B. `shared/dictation_prompt.json` is generated from the
canonical desktop prompt by `mobile/scripts/sync-prompts.py`.

Speech recognition receives only enabled canonical dictionary spellings, joined
with commas and bounded to 896 characters without splitting a term. Aliases and
pronunciations remain stored but are not sent as recognition instructions.
Rewriting retains its separate vocabulary context and canonical prompt. A
rewrite failure still returns the recognized transcript successfully.

Snippets have a spoken `trigger`, literal `replacement`, `enabled` flag and
`case_sensitive` flag. The account library allows up to 512 entries, 256
characters per trigger and 4,096 characters per saved replacement. Its normalized
entry array must fit 262,144 UTF-8 bytes when encoded as compact JSON with
literal Unicode (no ASCII escaping). The server returns `snippets_too_large`
without changing the revision when this aggregate limit is exceeded. Local
guest libraries retain their existing per-entry limits.

Snippet writes use optimistic revisions; a stale write returns
`snippet_conflict`. The independent library prevents older dictionary clients
from erasing snippets. Account deletion removes the library. Only enabled
triggers join bounded recognition/refinement hints. Saved replacements never enter recognition hints. A standalone spoken trigger
inserts its exact saved text without a rewrite request. Other matches are
substituted once before refinement. The provider receives the substituted source,
not the full library, and may adjust wording and formatting. Refinement failure
returns the substituted source. The original recognized transcript stays unchanged.
Triggers produced by refinement are never substituted. Hosted clients use the returned final `text` without expanding it
again; `snippet_expanded: true` marks an applied expansion even when
`rewritten` is false. Idempotent retries return the saved result and do not
expand it again.

The complete rendered JSON UTF-8 dictation response, including original text,
expanded text and usage, is limited to 393,216 bytes. Measurement includes the
renderer escaping for Unicode line and paragraph separators. An expansion above this
limit returns `422 snippet_result_too_large` with phase `processing`; no partial
text is returned or cached. The operation settles once at the conservative
reservation and its bounded error is replayed without another provider call or
audio charge. Clients show the error and do not publish text to the clipboard.
For a snippet-expanded result, the original transcript and final text must each
fit 32,768 UTF-8 bytes. This retains compatibility with the existing account
history record. A larger field returns the same bounded error before success;
the server does not truncate text or change the history schema.

Processing errors return a bounded `code`, `phase`, validated `operation_id`,
and updated `usage`. Empty recognition is `422 no_speech` with phase
`transcription`; it does not mean microphone authorization failed. Upstream
recognition errors or malformed recognition results are `502
transcription_failed`. Selected-text provider failures are `502
text_processing_failed` with phase `text`. Unexpected internal processing
failures retain `502 processing_failed` with phase `processing`. Audio
validation and admission retain their existing codes. Authentication and
pre-validation failures can omit the operation identifier. Clients must map
known codes to local messages and must not display arbitrary provider text.

Application diagnostics record only code, phase and operation identifier, never
exception text, recordings, transcripts or provider responses. A failed paid
operation retains conservative accounting and is never retried automatically;
the error classification does not refund allowance or repeat inference.

Signing in automatically connects vocabulary. Each account has a separate local
cache; logout restores guest vocabulary. Sync combines independent edits and
preserves deletions. A same-word conflict requires a choice; revision mismatches
never silently overwrite the server. Sync runs after login and local edits, then
at most once per minute while the app is active or before hosted dictation.
Failed attempts also use the cooldown. Processing responses update consumption
without a separate usage request. This version does not push changes in real time.

Managed selected-text processing uses the canonical rewrite/translation prompts
in `shared/text_prompts.json`, generated by the same prompt sync script. Text
input is limited to 16,000 UTF-8 bytes, with fixed actions, languages and model.
It uses the same authenticated ownership, idempotency, global cost reservations,
concurrency and monthly operation limits as audio, plus six text requests per
account per minute. Text operations do not consume audio minutes. There is no
caller-supplied prompt, model, URL or tool option.

## Bounds and retention

- Audio: 24 MiB, 250 ms through 5 minutes. Decode locally to mono 16 kHz WAV;
  validate actual duration. No remote media URLs or playlists. Temporary audio
  is removed after the request. Container restarts clear abandoned temp files.
- Vocabulary: 512 entries, shared validation with desktop, bounded provider
  context. It is input data and cannot change provider instructions.
- One in-flight operation per account, four globally by default, six dictations
  per account per minute, and 2,000 per account per month. Atomic PostgreSQL
  admission prevents quota and budget races across workers and month boundaries.
- Every operation reserves its worst-case provider cost before provider work.
  Actual usage includes completion/reasoning tokens and the ASR minimum charge.
  Failed or uncertain provider work retains the conservative cost reservation;
  it is not automatically refunded or retried.
- Duplicate operation ID and identical content reuse a result for five minutes.
  Different content is rejected. Expired IDs cannot repeat paid work while the
  operation record exists. Clients must reuse their UUID when retrying.
- Processing result text is cached for five minutes, then swept within roughly
  one minute. This retry cache is independent of synchronized account history.
  `/v1/history/sync` stores new account transcriptions until explicitly deleted.
  Each account has bounded storage; permanent tombstones prevent stale uploads
  from restoring deleted entries. History synchronization does not call a
  provider or change audio allowance. Operation metadata is removed after 31 days;
  monthly aggregate cost records remain for budget accounting. Account deletion
  removes the user, dictionary, account history and synchronization metadata,
  removes cached processing text/content hashes and
  detaches accounting records. Backup retention must be configured by the host.
- No transcripts, audio, credentials, HTTP headers or provider error bodies in
  application/access logs. The default proxy limiter uses the connection peer,
  not untrusted forwarding headers. Behind a shared proxy, this is conservative
  and can limit multiple users together. Verify trustworthy ingress IP handling
  before widening the beta; do not blindly trust `X-Forwarded-For`.

Open code does not grant access to the hosted service. Security rests on account
verification, ownership checks, bounded inputs, atomic limits and server secrets.
Self-hosters configure their own credentials, limits and database.

## Release gates

The **Shared account** workflow has a manual `publish_server_image` option,
off by default. Only an explicit dispatch in `jvictormaynard/clarify` can publish
to `ghcr.io/jvictormaynard/clarify-server`. This recovery path pins commit
`ced75d817decd55e7ed6f350e34e008b59f9cb26` and its reviewed Git archive hash.
It exports only 49 allowlisted source files, runs isolated PostgreSQL tests,
builds the existing Dockerfile, checks startup and database health, and verifies
the image files before login or push. The image contains 47 source files:
`.dockerignore` is not copied and `server/.env.example` is excluded by Docker.
No runtime credentials, profiles or recordings enter the build context.

The dispatch skips the ordinary server/iOS jobs and uses a separate image job.
PR jobs retain read-only permissions. Registry login uses only the temporary
workflow token through stdin; the image has a unique run/attempt tag. The artifact
records its digest, source SHA and source manifest. No Railway credentials or
service configuration are used. Publishing an image does not deploy it; whether
this route avoids the current snapshot failure still needs controlled live
verification. Changing this recovery source pin requires a new review.

Server tests, desktop Python/Settings checks and iOS native compilation must pass.
Live email, device activation/dictation, account isolation, quota exhaustion,
session revocation and account deletion need staging acceptance. No automatic
TestFlight upload is part of this change. The existing private-API app-return
experiment is limited to TestFlight; remove it before a public App Store release.
Public launch also needs an accurate privacy policy, account deletion instructions
and a tested backup/restore policy. Google/Apple login and billing
are separate increments.
