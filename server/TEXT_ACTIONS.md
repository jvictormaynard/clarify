# Account text actions

The account service stores action definitions. It does not store device
shortcuts, processing profiles, endpoints, models, or credentials in an action.
The existing authentication and verified-email rules apply to every endpoint.

`GET /v1/text-actions` returns `revision` and `actions`. Each action contains
`id`, `name`, `prompt`, `kind`, `enabled`, and server-owned `revision`.
The first read or write creates Rewrite (`rewrite`) and Translation
(`translation`) at action revision 1 and library revision 0. An empty saved
library stays empty.

`PUT /v1/text-actions` accepts `expected_revision` and `actions`. Each write
action contains exactly `id`, `name`, `prompt`, `kind`, and `enabled`.
A replacement increments the library revision. Only changed definitions
increment their action revisions. A new ID starts at 1. An ID removed and
later restored continues its previous revision sequence. Deleted definitions
are removed; only their ID and last revision remain until account deletion.
A stale write returns HTTP 409 with `code: text_actions_conflict` and the
current `revision` and `actions` at the top level. No partial write occurs.

Limits are 64 actions; IDs of 1 to 64 ASCII letters, digits, `_` or `-`;
nonblank names up to 80 characters; nonblank prompts up to 8192 UTF-8 bytes;
and 256 KiB for the complete compact UTF-8 read representation. Unknown
fields, duplicate IDs, invalid types and invalid kinds are rejected.
Kinds are `rewrite`, `translation`, and `custom`. Revision values are integers,
not booleans. They use the database's nonnegative signed 64-bit range.

## Personal execution

`POST /v1/text-actions/execute`, `/v1/text` and `/v1/dictations` are retired.
They return HTTP 410 with `code: inference_retired` and `update_required: true`
before reading input, reserving quota or calling a provider. Account action
reads and revision-controlled writes remain available. A saved definition does
not grant processing authority.

Desktop resolves the accepted account action revision against a personal local
profile, subscription connection or user-selected provider. Computer processing
freezes the definition, personal route and output preferences at admission.
A stale account identity or revision cannot publish a result. Optional editing
failure preserves the recognized transcript through the existing recovery path.
The computer protocol owns the supported output preferences and bounds; the
account service does not advertise an execution capability.
