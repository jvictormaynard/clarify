# Clarify business administration

The read-only dashboard uses the account service and its existing PostgreSQL
ledger. It does not collect desktop local/BYOK activity or load transcripts,
dictionary contents, audio, provider keys, or session tokens into analytics.

## Private configuration

Set `CLARIFY_ADMIN_HOST` to `clarify-admin.victormaynard.com` and include that
host in the existing explicit `ALLOWED_HOSTS` list. Set `CLARIFY_ADMIN_EMAILS`
to the operator's verified account email in the hosting secret store. An empty
host or owner list grants no administrative access. Staff and superuser flags
alone do not grant access. Do not commit actual operator configuration.

Attach the subdomain to the existing service at port 8080. Add the exact CNAME
and ownership TXT records returned by the hosting provider, then verify HTTPS.
The dashboard is `/admin/`; `/` redirects there on this host. Administrative
routes are unavailable on the native API host. Native API routes are unavailable
on the administrative host, except the database health probe `/health`.

Browser authentication reuses allauth email codes, with eight digits for the
admin host. Native clients retain six-digit codes. Admin requests are limited
to three codes per email per ten-minute rate window, in addition to existing
global, IP, email and daily sending limits. Each challenge has five atomic
confirmation attempts across workers and expires after ten minutes. The
challenge proof binds the code, nonce, email and user. A successful confirmation
grants eight hours of admin scope; polling does not renew it. Signing out revokes
the session. Native tokens cannot use pending or authenticated admin sessions,
and native sessions alone cannot acquire admin scope.

Cookies are host-only, with Secure in production and HttpOnly for the session.
CSRF protects browser mutations. Responses disable caching and framing and
restrict scripts, styles and network requests to the same origin. The UI stores
no tokens in browser storage. Keep TLS and the existing proxy-header trust
configuration intact. Application authorization also applies when traffic
reaches the origin without a CDN.

## Metric definitions

- Registered users are current accounts; deleted accounts are not counted.
- Active users and audio require an operation with confirmed completion.
  Attempt counts also include running and uncertain operations. An uncertain
  operation does not prove failure or absence of provider charges.
- The funnel uses accounts created in the selected period. Return means a
  confirmed operation on two distinct UTC dates, not long-term retention.
- Periods include today and use UTC. The comparison uses the same elapsed
  duration shifted back by the selected number of days. Details are retained
  for 31 days; the 30-day view cannot compare with an earlier 30-day period.
- Period costs sum the conservative operation ledger. Monthly budget values
  use the durable budget ledger, independent of the selected period. Reserved
  cost is separate. Linear projection is an estimate, not a spending promise.
- There is no billing integration: costs are not revenue, profit, or margin.

## Validation and deployment

Run the isolated server suite with `server/scripts/test-postgres.py`, including
cross-client session rejection, code expiry, CSRF, authorization revocation,
atomic concurrent attempt limits and analytics privacy. Run the repository
Python suite and JavaScript syntax checks. Check desktop and mobile layout,
filters, user detail, empty/error states, logout, stale responses and re-login.

After deployment, verify the exact source, terminal deployment success, database
health, HTTPS, unauthenticated denial, security headers and assets. Test owner
login without publishing the code or session. Keep code review, automated
tests, deployment status and observed production behavior as separate evidence.
