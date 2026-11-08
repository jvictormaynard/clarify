# Account history synchronization

New transcriptions created while signed in belong to that account. Guest/BYOK
history and all pre-upgrade records remain local and are never uploaded. Existing
local records remain visible on their original device. Account caches are scoped
by server endpoint and user ID; signing out restores local history. Account
deletion removes only that account's cache. Audio and credentials are not history.

## Wire contract

`POST /v1/history/sync` uses the existing verified session and account rate limit.
The request has `cursor` (nonnegative integer), `upserts` (up to 50 entries),
`deletes` (up to 50 entry IDs), and optional `clearID` (UUID). Empty arrays are
valid and request remote changes only. The serialized request is bounded to
400 KiB in addition to the entry counts; the existing 512 KiB request limit
remains unchanged. A clear request contains no upserts or
deletes. Its stable UUID makes retrying a clear operation idempotent.

An entry contains exactly these fields:

```json
{
  "id": "c1a78d70-bec1-4a5b-b191-6dd374e00ce5",
  "createdAt": 1792067053.8,
  "transcript": "Original speech",
  "text": "Revised text",
  "rewritten": true,
  "sourceDevice": "desktop"
}
```

IDs are case-sensitive ASCII letters, digits, hyphens or underscores, 1–128
characters. Times are finite Unix seconds, greater than zero and less than
4102444800. Each text field is at most 32768 UTF-8 bytes; `text` is nonblank.
`rewritten` is a boolean. Device is `mobile` or `desktop`. An entry is immutable:
replaying the same ID/payload is a no-op; different content returns HTTP 409
`history_conflict` without applying the batch. Do not silently replace a record.

The response is `{ "cursor": 0, "hasMore": false, "entries": [], "deleted": [] }`.
It contains at most 20 changes and 400 KiB of encoded JSON, ordered by an
account-owned monotonic revision. Pagination reads the current state of each ID,
not an append-only log of old payloads: an ID deleted by clear or delete is
always returned as a tombstone, never as its earlier text.
The returned cursor advances only through those changes. No changes means the
request cursor is retained. A cursor ahead of the account revision is invalid.
Applying a successful response acknowledges its submitted batch even if the
response page has not reached those entries yet. Clients drain pages and pending
work in bounded bursts and resume automatically; no manual sync button is needed.

Each batch is atomic and account-scoped. Deletes create durable tombstones even
for unknown IDs. A tombstone always wins over a stale upsert. Clear removes all
server-known records once, leaving tombstones; a replay must not erase subsequent
records. Send a pending clear before new upserts. Never infer deletions from an
entry missing in a page, local retention, or a failed request.

Server storage is bounded to 20 MiB of live encoded entries, 50,000 durable
entry IDs and 10,000 clear operation IDs per account. A batch exceeding a bound
returns HTTP 507 `history_full` atomically. Clients keep unsent records locally;
delete/clear can free live text space. These independent storage bounds do not
consume or change the account's audio allowance.

## Client ownership and recovery

Save new results and pending changes before any network request. Persist received
changes, acknowledgements and cursor atomically. Preserve pending work on network
failure, app restart and unsupported/old servers. Reject results from a different
session/account/endpoint before applying them. An authentication failure must not
move account history into guest storage or silently switch providers.

Synchronize after login, new results and explicit deletes, and when returning to
the foreground. Coalesce concurrent requests, use a bounded interval for remote
polling (about 60 seconds), and avoid requests in guest mode. History failures
must not fail transcription or block microphone use. Account storage retains the
original device label and timestamps; local display remains chronological.

Pre-upgrade records have no trustworthy account owner. The user chose on
2026-10-16 to keep them local and synchronize only new account records. Do not
infer an owner from the account signed in at upgrade, text content, or current
processing mode.
