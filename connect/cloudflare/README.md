# Clarify Connect control plane

This Worker issues and consumes account-authorized tunnel grants. Audio and text
go through the computer's sealed endpoint. This Worker has no processing route,
HTTP proxy, Quick Tunnel fallback, usage debit, or paid expansion operation.

`POST /v1/connect/grants` requires a private `X-Session-Token` and exactly
`{computer_id, certificate_sha256, hpke_public_key, origin_port}`. One fixed
`GET CLARIFY_API_URL/v1/account` checks the existing active, verified account.
The reply contains `{schema_version:1, grant, expires_at, control_url, hostname}`.
The grant has 32 random bytes, expires after 240 seconds, and is stored as SHA-256.
A new grant replaces the previous unused grant for that computer.

`POST /v1/connect/claim` accepts exactly `{grant}` once and returns
`{schema_version:1, hostname, token, origin_port}`. The connector token is never
stored in D1. Neither the session nor the administrator token reaches the
computer. Each HTTP operation and body read has a 5-second deadline. Incoming
JSON is limited to 4 KiB, account JSON to 16 KiB, and Cloudflare JSON to 2 MiB.
Redirects are rejected. Responses use `Cache-Control: no-store`. Code emits no logs.

The hostname is `c-<lowercase unpadded Base32 SHA256(raw HPKE key)>.victormaynard.com`.
Tunnel ingress uses exactly that hostname, `http://127.0.0.1:<origin_port>`, and
a final `http_status:404` rule. DNS is a proxied CNAME to the allocated tunnel.
The same owner, computer UUID, and HPKE key can change ports with the same tunnel.
Foreign tunnels and DNS records are never adopted or overwritten.

SQL admission enforces 3 computers per account and at most 900 globally. The
configured global limit can be lower. Reserved, expired, blocked, and uncertain
rows still count. Ownership and key bindings do not change. The account identity
is hashed; email and account usage are discarded. D1 batches are transactions,
and this code uses the primary database without read replication.

A durable global lock serializes claims. Before a create, an authenticated
`GET /accounts/{id}/tunnels` must return a complete count below the configured
limit. A missing count, incomplete page, collision, or rejected read blocks that
computer. The grant is consumed before any Cloudflare mutation. A lost reply or
failed write after mutation marks the computer uncertain and retains the lock.
A terminated Worker can leave `claiming` with the same lock. There is no retry,
lock expiry, deletion, or automatic reconciliation. The operator must inspect
Cloudflare and D1 before repairing state. Do not clear a lock while its operation
can still run. Unrelated operators can change the account after the count check.

`wrangler.toml` is OFF, has no routes, and uses invalid placeholder IDs. The
coordinator must set the real account, zone, D1 binding, HTTPS account API origin,
and server-only `CF_API_TOKEN`; apply the migration; bind only the approved
`clarify-connect.victormaynard.com` control hostname; then enable the Worker.
The token needs account tunnel read/write and zone DNS read/write access. Keep
the free plans and account limits. This directory does not authorize a deploy.

Run local tests from the repository root with Node 22.14 or later:

```sh
node --test connect/cloudflare/test/*.test.mjs
```

Tests use `node:test` and built-in `node:sqlite` with the real migration and bound
SQL. HTTP is simulated; real `fetch` fails the test. Node 22 emits an experimental
SQLite warning. No packages, credentials, network, or Cloudflare resources are
needed. Local tests do not prove D1 deployment, DNS, TLS, or cellular access.

API references: [D1 batches](https://developers.cloudflare.com/d1/worker-api/d1-database/#batch),
[tunnel inventory](https://developers.cloudflare.com/api/resources/zero_trust/subresources/tunnels/methods/list/),
[tunnel creation](https://developers.cloudflare.com/api/resources/zero_trust/subresources/tunnels/subresources/cloudflared/methods/create/).
