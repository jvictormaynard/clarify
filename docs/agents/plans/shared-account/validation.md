# Shared account validation

Review base and starting HEAD: `3cfe52203a85a5479dc627979d5f3fb316640d08`
(`codex/ios-testflight`). Work is isolated on `codex/clarify-cloud`; the original
dirty checkout and existing TestFlight build 16 were preserved.

## Local evidence

- Windows Python suite: 1,214 tests passed, 5 skipped, with a temporary AppData
  profile and no real keys, microphone or recordings. Subsequent account/capture
  repairs passed 69 focused account, provider, Qt Settings and lifecycle tests.
- Server: 22 tests passed on a disposable PostgreSQL 16 cluster. This includes
  account/email flows, account isolation, revision conflicts, admission races,
  cost bounds, idempotency, audio validation and the daily email send ceiling.
- Settings: TypeScript/frontend build and 17 isolated Playwright tests passed.
  Native Windows Settings executable compiled; dependency inventory generated.
- Mobile: TypeScript, lint (one existing dependency warning), 13 JavaScript
  tests and Expo dependency checks passed. Canonical prompt generation is current.
- Migration drift, Ruff and whitespace checks passed. Changed files were scanned
  for provider keys/private key blocks without printing potential secrets.

## Sequential self-review

Requirements pass: optional account, separate local/BYOK routes, account-scoped
dictionary sync/conflict choice, verified login, logout/deletion, hosted allowance
and bounded dictation are implemented. History and snippets stay local. No paid
fallback, billing, social login or generic model proxy was added.

Engineering pass: checked credential ownership, sync races, stale publication,
capture versus account changes, server cost/allowance locks, upload bounds,
leases, retention and account deletion. Repaired first-sync concurrent edits,
session expiry, account/capture exclusion, local session cleanup after deletion,
and shared-module imports after Gunicorn exec.

## External checks and open gates

Resend: existing `victormaynard.com` domain verified; Free transactional plan
confirmed. A dedicated domain-restricted sending key is stored outside the repo
with Windows DPAPI. SMTP authentication and NOOP passed; live email acceptance
is recorded below. Clarify defaults to 50 send
attempts per UTC day because the Resend quota is shared with other projects.

GitHub run `38102687650` passed: PostgreSQL tests, container build/start/health,
Swift native tests and full unsigned iOS app/extension compilation. Linux and
Windows test jobs passed in `38102658699`; Windows packaging acceptance is tracked
separately. Manual native Windows/iPhone acceptance is still required.

A dedicated Railway API and PostgreSQL service are deployed. API deployment
`ffe6f56c-d087-403c-9c6e-7ca0fd0e0650` reached `SUCCESS`; the generated HTTPS
domain returned database health `200`. The custom domain
`clarify-api.victormaynard.com` has a valid certificate and correct public DNS.
Its HTTPS health returned `200` with TLS validation using the resolved public IP;
the local Windows DNS resolver still held a negative result at that point.
Desktop and iOS now default to that custom endpoint.

With the user's approval, one real verification email was delivered through
Resend to a temporary account. Signup was enabled only in the private test
process, with public signup left disabled. Live HTTPS checks passed for email
confirmation, verified account access, vocabulary read/write, stale revision
rejection (`409`), usage, anonymous access rejection, disabled funded processing,
account deletion (`204`) and rejection of the deleted session. The temporary
account, code capture, session and temporary registered SSH key were removed.

The initial email used allauth's default host-based wording. Custom signup and
login templates now contain the Clarify name, code and instructions to enter the
code in the mobile or desktop app, without a URL or browser instruction. The
PostgreSQL authentication tests check both email types; all 22 server tests pass.

Public signup and hosted inference remain disabled. A dedicated Groq key and
approved global budget are still required. No new TestFlight release is claimed.
Device activation/dictation, multi-device acceptance, live quota exhaustion and
database backup/restore remain gates before public launch.
