# Dictionary and voice snippets

Clarify keeps user vocabulary and snippets in a non-secret profile file:

- Windows: `%APPDATA%\Clarify\dictionary.json`
- Linux/macOS development runs: `~/.clarify/dictionary.json`

The file is independent from `config.json` and the provider secret store.  It
contains no API credentials and is never added to usage statistics.  Writes are
validated, flushed, and atomically replaced, so a process interruption cannot
leave a partially written document in place.

## Versioned format

The current format is schema version `1`:

```json
{
  "schema_version": 1,
  "dictionary": [
    {
      "term": "OpenWhispr",
      "pronunciation": "open whisper",
      "aliases": ["Open Whisper"],
      "enabled": true
    }
  ],
  "snippets": [
    {
      "trigger": ";meet",
      "replacement": "Agenda:\n1. Confirm scope\n2. Share notes",
      "enabled": true,
      "case_sensitive": false
    }
  ]
}
```

The first unversioned document (`schema_version` omitted) is migrated in
memory to version 1 when loaded.  Unknown future versions are rejected for
import and are never overwritten by a save.  Entries are bounded to 512
dictionary entries and 512 snippets.  Terms, aliases, pronunciation, and
triggers are single-line Unicode strings with a 256-character limit;
aliases are stored as separate strings and may contain commas.  The Settings
editor shows one alias per line so punctuation round-trips without ambiguity;
replacements may contain Unicode and newlines up to 4096 characters. Legacy local
files can contain empty replacements. New snippet editors and account libraries
require nonblank saved text.

`LocalDictionarySnippetsRepository.import_json()` parses and validates the
complete document before replacing the active file.  Invalid JSON, duplicate
terms/triggers, wrong field types, oversized values, and future schema
versions therefore leave the previous profile unchanged.  `export_json()` and
`export_to()` emit the canonical, human-readable document while preserving
entry ordering.

## Account snippets

Desktop Settings has a separate **Snippets** page. On iOS, open **Dictionary →
Snippets**. Add a distinctive spoken phrase and its saved text, then save. Both
interfaces support search, editing, enable/disable and deletion. Desktop drafts
use the existing Save/Discard bar. A draft is bound to the account where it began;
a session or account change cannot save it into another account or the guest profile.

Guest snippets remain on their device. Account snippets have an endpoint/account
cache and synchronize through authenticated `GET/PUT /v1/snippets`, with separate
optimistic revisions from vocabulary. Signing in does not upload guest snippets.
Independent edits merge. A same-trigger conflict requires a choice; failed sync
preserves local edits. Deleting an account removes its server library and that
account's local cache, without deleting guest snippets.

Account entries have the same per-entry limits plus a **256 KiB** aggregate bound
for compact UTF-8 JSON. Oversized saves are rejected without truncation. The
hosted original transcript and expanded text each have a **32 KiB UTF-8** limit,
which matches the current synchronized-history protocol. The rendered response
also has a **384 KiB** transport bound. Excessive expansion returns an explicit
processing error and is not inserted, truncated or automatically retried.

Hosted snippets are applied once on the server, including when rewriting fails.
Clients use the returned final text and never expand it again. Personal desktop
routes apply snippets locally. The saved replacement keeps its spelling, line
breaks and literal placeholders. Replacement text is never executed or expanded
recursively. Trigger phrases can be recognition hints; saved replacements are
not sent as provider context. Expanded text can enter history when history is enabled.

## Matching behavior

A standalone trigger tolerates recognizer punctuation and spacing and inserts the
exact saved text before rewriting. Inside a longer phrase,
`DictionarySnippetService.expand()` scans left-to-right and only considers
enabled snippets.  Input and triggers use canonical Unicode NFC matching, so
precomposed and decomposed forms (for example `café` and `cafe\u0301`) behave
the same while the original combining sequence is consumed as one unit.  NFC
composition boundaries are derived from the active Unicode database, rather
than a script-specific list, so starter-to-starter scripts remain covered as
the runtime's Unicode version evolves.  A trigger must be separated from
adjacent Unicode letters/numbers and `_`;
punctuation at either side is allowed.  Matching is case-insensitive by
default, or exact when `case_sensitive` is true.  When triggers overlap, the
longest trigger wins and equal-length triggers retain the order in the file.
The input is bounded to one million characters by default and matching walks a
prefix trie instead of checking every rule at every character.  The result is
produced without executing replacement text as code; expanded output is
subject to the same configured character bound.

Enabled dictionary entries produce an optional, provider-neutral transcription
context.  It is bounded to 4096 characters and keeps the stored order. Adapters
receive context through the typed `TranscriptionRequest`. Groq ASR uses only
enabled canonical spellings, up to 896 characters without partial terms. It
omits an empty prompt and does not send transcription route prompts, chat
instructions, aliases or pronunciation hints to Whisper. Rewrite and refinement
prompts remain unchanged.
Local Whisper receives canonical spellings (up to 896 characters) in the
whisper.cpp `/inference` `prompt` field, with `max_context=224` and
`carry_initial_prompt=true`. The pinned v1.9.1 server clears text history for
each request. Empty dictionaries keep `max_context=0`. Pause-stream segments
and the final tail receive the vocabulary captured at stream creation.
Optional transcript refinement receives a separate bounded JSON vocabulary
with instructions to preserve supported spellings, never add missing terms,
and treat entries as data. Pronunciation and aliases remain recognition hints,
not exact replacement rules; Whisper receives only canonical spellings.
The HTTP
diagnostics boundary logs only provider metadata and redacts request bodies,
so dictionary content and credentials are not written to provider logs.

## Settings workflow

The current React/Tauri Settings window exposes **Dicionário**: add a word or
phrase with Enter, search, edit, enable/disable, or remove it. Optional aliases
and pronunciation appear in a disclosure. Changes remain drafts across tab
navigation and use the existing floating Save/Discard bar. Saving updates the
same service used by the running transcription pipeline; no restart is needed.
Dictionary edits preserve existing snippets. Saving validates and atomically
replaces the dictionary file; an error leaves its active in-memory value intact.
The UI explains provider context limits and cloud disclosure. No model is trained.

The legacy Settings window exposes the local profile under **Dictionary**. It can
search terms, aliases, pronunciation metadata, snippet triggers, and
replacement text; add or edit either item; enable/disable entries; and delete
individual rows.  The **Reset all** action clears both collections only after
confirmation.  Every change is validated and atomically persisted before the
UI reports success.

The same page includes a snippet preview, plus JSON **Import** and **Export**
actions.  Import uses the all-or-nothing validation boundary described above,
so malformed or future-schema documents cannot replace the active profile.
The profile remains local and is excluded from usage statistics and provider
diagnostics.  Windows manual acceptance of the complete workflow is still a
release-check item; it does not change the documented file format or runtime
guarantees.
