# Writing styles by Windows application

Open Settings → Dictation → Application writing styles. Enter the full path to
an `.exe`, or use the last external application remembered by Clarify. Select
a style and save the rule. Clarify does not open or run the selected file.

Natural keeps the speaker's vocabulary and tone. Informal uses everyday
language without adding slang or emojis. Organized groups expressed points
into paragraphs and explicit enumerations into lists. Each style must preserve
meaning, names, numbers, conditions, negations and uncertainty.

Rules apply to the next dictation. Clarify fixes the application and style at
the start. Changing focus or editing a rule during recording does not change
that operation. If focus changes, the existing safe insertion path keeps the
result available for manual paste.

Remove a rule to restore Default. Default adds no style instruction and keeps
personal workflow prompts. Unknown targets also use Default. Full executable
paths distinguish separate installations. Matching ignores Windows path case
and preserves Unicode names. Rules stay on this device; the account service
receives only the style ID, never the application path or window contents.

A style does not change the provider, account, endpoint, cleanup level or local
cloud permission. Preserve words and Minimal changes do not use generative
editing. Local transcription without cloud editing permission does not apply
a style. Standalone snippets remain exact. If editing fails, Clarify keeps the
recognized text with its snippet expansions and reports that the style was not
applied. The capsule labels selection during capture and confirms application
only after successful editing.

Settings schema 4 stores the rules. Its migration preserves cleanup choices and
personal prompts. Earlier schema readers can read compatible values but refuse
to save a schema 4 file. This prevents a downgrade from erasing application rules.
