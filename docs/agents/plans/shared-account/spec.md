# Optional Clarify account and hosted dictation

## Decision and repository ownership

Keep the existing public `jvictormaynard/clarify` MIT monorepo. Desktop,
mobile, server, API contracts, prompts, migrations, tests and self-hosting
instructions are public. There is no separate closed backend or local-only
product fork. Each application can use a funded account, BYOK or its existing
local processing. iOS does not yet offer local models.

Production keys, account data, recordings, database backups, administrator
access, deployment credentials and operational abuse decisions are private.
Store credentials in the hosting secret store. Do not create an empty private
operations repository; create one only if actual restricted operational files
need version control. Public source does not grant access to the funded API.

## First increment

- Email account, verified email, expiring/revocable sessions, logout and deletion.
- Login is optional and independent of the processing choice.
- Shared dictionary with explicit first sync and optimistic revisions. Preserve
  local entries and desktop snippets; never silently overwrite concurrent edits.
- Fixed hosted dictation operation: audio -> Groq Whisper turbo -> GPT OSS 20B
  editorial rewrite. Use the canonical desktop rules and preserve raw text on
  rewrite failure. No general-purpose chat proxy or client-selected models.
- Shared server-owned monthly audio allowance and usage from hosted operations.
- Local history remains local. No existing history or BYOK key is uploaded.
- Self-host the same server with your own credentials.

## Boundaries

`server/` owns accounts, authorization, the shared dictionary, resource checks,
quota reservations, provider usage and the funded Groq key. Use Django LTS,
django-allauth headless, and PostgreSQL. Sessions and password/email flows come
from the authentication library. Use one API service and one database.

Desktop keeps audio capture, cancellation, snippets, clipboard/focus safety and
local/BYOK workflows. iOS keeps capture and keyboard communication in Swift;
the keyboard never receives an account session or provider key. Clients store
sessions in DPAPI/Keychain. Account state never contains credentials in UI
snapshots or ordinary configuration.

## Security and resource acceptance

- Authenticate before audio parsing; derive all owners from the session.
- Verified email required for funded processing. Enforce registration/login
  limits, per-account request and concurrency limits, global parallelism, clip
  size/duration/output limits and a global monetary ceiling.
- Decode/re-encode bounded uploads; reject URLs and extra request controls.
- Reserve allowance and maximum cost atomically before provider calls, including
  in-flight operations. Fail closed. Keep uncertain provider cost reserved.
- Idempotency is per account and content. Repeated IDs cannot duplicate calls
  or retrieve another user's output. Completed text expires; audio is temporary.
- Never log request bodies, audio, transcript, dictionary, password, session or
  keys. No outbound network in tests.
- Revision conflicts preserve both copies and require explicit resolution.
- Local/BYOK processing does not consume funded allowance and has no automatic
  paid fallback.

## Rollout and later work

Hosted inference is disabled until a dedicated production Groq key, email sender
and explicit budget are configured. Default beta allowance: 300 audio minutes
per account per UTC calendar month; production global budget defaults to zero.
This allowance is configurable, not a promise of unlimited free access.

Later: explicit opt-in history sync, payment entitlements, Sign in with ChatGPT,
and device attestation. None are required to use local/BYOK modes.

The iOS previous-app return experiment uses private APIs authorized only for
TestFlight. Public App Store distribution must exclude that experiment. Build,
deployment, TestFlight and manual device acceptance are separate gates.

## Validation

Use synthetic audio and fake providers. Test unauthenticated/unverified access,
cross-account isolation, logout/deletion, revision conflict, unsafe inputs,
concurrent quota reservations, idempotency, timeout/partial failure, real decoded
duration, token accounting and cost ceilings. Run desktop Python and Settings
checks, mobile lint/typecheck/unit/native checks and isolated PostgreSQL tests.
Do not treat browser tests or CI as manual Windows/iPhone acceptance.
