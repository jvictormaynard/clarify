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
with Windows DPAPI. SMTP authentication and NOOP passed. This does not establish
email delivery through a deployed signup flow. Clarify defaults to 50 send
attempts per UTC day because the Resend quota is shared with other projects.

GitHub CI must compile the iOS native module/app/extensions, run Linux/Windows
checks and build/start the server container. Windows embedded-payload checks and
manual native Windows/iPhone acceptance remain separate gates.

No live Clarify account service, default client endpoint, public signup or new
TestFlight release is claimed here. Hosted inference stays disabled until a
dedicated Groq key and approved global budget exist. Staging must verify real
email delivery, account isolation, sync, quota exhaustion, session revocation,
account deletion and database backup/restore before public launch.
