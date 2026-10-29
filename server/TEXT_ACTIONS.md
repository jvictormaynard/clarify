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

`POST /v1/text-actions/execute` accepts exactly `operation_id` (UUID),
`action_id`, positive `action_revision`, `text`, and `language`. Source text
must be nonblank and at most 16000 UTF-8 bytes. Languages are `auto`, `pt`,
`en`, `es`, `de`, and `ru`. Translation requires an explicit language.
The result contains `text`, `usage`, `action_id`, `action_name`, and
`action_revision`. The server selects its fixed text model and credentials.
An action prompt is an authorized user instruction. Selected text remains
source data. Custom actions can summarize. Only translation replaces the
literal `{lang}` placeholder; other braces remain literal. The explicit
translation target takes precedence over prompt language instructions.

Missing, disabled, and stale actions return `text_action_missing` (404),
`text_action_disabled` (409), and `text_action_stale` (409). A missing translation
target returns `text_action_language_required` (400). Invalid libraries and
execution requests return `invalid_text_actions` and `invalid_text_request`
(400). Definition checks occur before ledger reservation or provider work.

Execution uses the existing text rate limit, funding admission, cumulative
cost authorization, settlement, diagnostics, and result retention. The
fingerprint includes operation type, action ID, action revision, source, and
language. Within the existing five-minute result retention, a retry returns
the accepted text and identity even after action edits or deletion. Usage is
refreshed through the existing usage contract. Changed input with the same
operation ID returns `operation_conflict` (409). An expired result returns
`operation_expired` (410). A running operation returns `operation_pending`
(409). Provider failures use the existing safe text diagnostics and settle
known or conservatively estimated paid work. Output is at most 64000 UTF-8
bytes and must be a complete, nonblank response.

`POST /v1/dictations` also accepts multipart fields `text_action_id` and
`text_action_revision` together. `text_action_language` is optional except
for translation. Its language set is the same as execution. These fields are
part of the fingerprint. The server resolves the account-owned snapshot
before provider work. The selected action replaces the existing LLM refinement
pass after one snippet expansion. Standalone snippets and cleanup policies
that disallow refinement still bypass it. Writing style applies to the action's
result without changing the task or translation target. A failed or unaffordable
refinement keeps the expanded original text and original transcript. Action
results contain `text_action_id`, `text_action_name`, and
`text_action_revision`, plus refinement provenance. The existing history and
response bounds still apply. Old dictation requests and `/v1/text` keep their
existing behavior.

## Output preferences

`GET /v1/account` advertises `output_preferences_supported: true`. Dictation
accepts an optional `output_language` independently of the recognition `language`.
Output choices are `auto`, `pt`, `en`, `es`, `de` and `ru`. Recognition can remain
automatic while the editor produces a different output language. `writing_style`
accepts `formal`, `casual` and `very_casual`; legacy `natural`, `informal` and
`organized` retain their existing meaning. Text execution and `/v1/text` also
accept optional `writing_style`, applied within the existing paid transform.
Custom action tasks and explicit selected-text translation targets remain intact.

Each explicit preference participates in the operation fingerprint. Omitting all
new fields keeps the old fingerprint and behavior. Dictation returns
`output_language_requested`, `output_language_applied` and
`output_language_status`, alongside the existing style provenance. Unavailable
or failed refinement preserves the original text with an unapplied status.
Standalone snippets retain their exact saved text and report `standalone` with
no applied preference. Output preferences do not enable a disabled refinement
policy, add a provider fallback, bypass funding admission or repeat a POST.
