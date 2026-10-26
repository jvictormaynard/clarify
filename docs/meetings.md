# Desktop meetings

Open **Meetings** from the pill menu. Set a title and select **New meeting**.
Capture starts only after this action. Windows captures the default communication
microphone and default audio output as separate sources. Each source shows its
state, level and warning. The feature does not identify people or remove echo.
It can capture the same speech twice when speakers feed the microphone.

The recording indicator stays visible when the meeting area closes. Select
**Stop** to close both capture sources before processing the final audio. Select
**Cancel** to stop capture and reject pending results. The current job keeps the
processing lock until its worker exits. Other capture tools, account changes and
updates remain blocked during this interval. Closing Clarify stops both capture
workers. A bounded HTTP call can finish after cancellation, but cannot publish
its result or remove audio.

Transcription uses chunks of up to 30 seconds per source. Capture stops after
4 hours. A device change or disconnection stops the affected source and shows a
warning; the other source can continue. Start a new meeting to use a new default
device. This first version has no automatic device reconnect.

Personal notes save separately from transcription and summary. A source change
marks the previous summary as out of date. Generating or cancelling a summary
keeps personal notes and the previous summary. The fixed summary policy permits
only supported facts, decisions and tasks. It forbids invented people, owners,
deadlines and speaker identities. Review generated text before use.

A summary accepts at most 64,000 UTF-8 bytes of source, including transcript,
timestamps and personal notes. Personal notes accept up to 16,000 UTF-8 bytes.
Capture duration does not guarantee that the full meeting fits one summary.
Larger sources remain intact and can be exported. There is no truncation or
multi-part summary in this version.

When signed in, transcription and summaries use the account service's fixed
meeting routes and shared allowance. An expired managed session requires
sign-in again. It cannot use a saved personal key. Without an account, capture
uses the saved transcription route. Summary has its own meeting preference,
disabled by default. Select a text provider and model in the meeting area before
starting a new meeting. This preference does not change selected-text rewriting.
Provider credentials remain with the existing configuration and secret owners.

Language and provider/model metadata are saved with each meeting. Jobs take a
connection snapshot. Retrying a chunk after restart keeps its original language
and route. An uncertain hosted request keeps the same operation UUID. A confirmed
terminal response can allow a new operation only on an explicit retry; that new
attempt can consume allowance again.

Meeting records stay in `meetings/meetings.sqlite3` under the desktop data
directory. The database uses transactions, foreign keys and schema version 1.
Owner scopes are guest or a hash of account endpoint and user ID. Guest meetings
are never assigned to an account or uploaded at sign-in. Meetings do not use
dictation history or its synchronization protocol.

Audio stays in `meetings/audio/<meeting-id>/<chunk-id>.wav`. A committed transcript
permits removal of its audio file. Failed, cancelled and interrupted chunks stay
available for retry or explicit meeting deletion. Startup recovers complete WAV
data from an interrupted capture. A corrupt or newer database is preserved and
processing fails closed. Back up the data before using a compatible app version
to recover it. Export and copy include the personal notes, summary and transcript.

## Server contract

`POST /v1/meetings/transcriptions` accepts multipart `audio`, UUID `operation_id`
and `language`. The decoded duration must be 250 ms to 30 s. The upload is limited
to 12 MiB and the transcript to 32,000 UTF-8 bytes. A valid silent chunk returns
an empty transcript. It does not run dictation cleanup or snippet substitution.

`POST /v1/meetings/summary` accepts JSON with UUID `operation_id`, `source` and
`language`. Source is limited to 64,000 UTF-8 bytes. Both routes reject additional
fields, require a verified account, use type-specific fingerprints and reserve
the existing shared quota before provider work. Cost authorization and settlement
remain with the ledger. Repeated operations replay a bounded saved result during
the existing result retention period. These routes have no Django migration and
do not change current desktop or iOS endpoints.

## Windows acceptance still required

Fixture checks use temporary stores, synthetic audio and fake providers. The
native fixture renders the actual QML window without a microphone or account.
These checks do not prove real-device acceptance.

| Check | Required evidence before release |
| --- | --- |
| Microphone and system output | Both sources record independently; levels and timestamps match playback |
| One source fails | Failure is visible and the other source continues |
| Default device changes | Affected source stops with a warning; no silent switch |
| Stop, cancel and quit | Streams close; pending results cannot publish; failed audio remains |
| Long capture and crash recovery | Bounded chunks, stable memory/disk use and recoverable partial WAV data |
| Valid and expired session | Managed quota is used; expiry has no personal-key fallback |
| Account transition | Work and pending notes block the change; records remain in their original scope |
| Retry after network loss | Stable language, route and UUID; no repeated charge for the same operation |
| Summary and manual notes | Edits mark summaries stale; errors and cancellation preserve previous content |
| Copy and export | Correct scoped content, Unicode and no automatic insertion into another app |
| DPI and keyboard | Readable layout at 100%, 125%, 150% and 200%; keyboard access to all actions |

The PR is for code review. It does not authorize a release, deployment or
installation over the user's Clarify.
