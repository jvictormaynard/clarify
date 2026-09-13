# Recovery after optional refinement failure

The Qt dictation runtime preserves a successful ASR transcript when the optional
refinement route fails, has an invalid configuration, or returns empty/invalid
text. This applies to cloud dictation and to local ASR with explicitly enabled
refinement. Transcription-only and successful refinement keep their existing behavior.

The fallback returns the exact original transcript. It skips snippet expansion
on that fallback so no additional transformation can replace the recovered text.
It does not repeat ASR, start another recording, or automatically retry refinement.
Provider cancellation still propagates; a cancelled token is checked before a
result can return. Workflow operation ownership and clipboard focus checks still
control publication.

`TranscriptionResult.refinement_failed` carries only a boolean. The workflow maps
it to the fixed status key `refinement_failed`. No exception text, provider response
or credentials enter that status. The existing non-focus-taking pill shows
“Refinement failed. Original text is available.” for five seconds. No result
window is opened by this change. The next operation resets the warning.

When history is enabled, the record has status `partial`, the original text,
the attempted route identifiers, and the fixed error key. It has no refined text.
Disabled history remains disabled. This status describes processing; it does not
claim that an external application accepted a paste.

Validation uses fake providers, temporary history and the actual QML component
loaded offscreen. It covers empty output, provider errors, configuration errors,
cancellation, local-refinement opt-in, one ASR call, unchanged original text,
focus-change copy fallback, history and warning reset. No real microphone or paid
API call is needed. Installed Windows acceptance is separate from these tests.

Validation on 2026-09-06: 407 tests passed on Windows Python 3.12 / PySide6 6.11.1
across recovery, QML, runtime, workflows, clipboard, providers, history and HTTP.
Ruff, Python compilation and the scoped whitespace check passed. The existing
settings interaction harness now scrolls controls into view before clicking.
The installed application was not replaced.
