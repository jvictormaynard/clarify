# Dictation cleanup

Settings → Dictation contains a cleanup level. Personal-provider Settings also
shows the same control in Text → Refinement. Both controls save one preference
through the existing atomic configuration transaction.

| Level | Behavior |
| --- | --- |
| Preserve words (`preserve`) | Return recognized words without a generative editing request. |
| Minimal changes (`light`) | Collapse runs of ASCII spaces and tabs, and trim outer spaces and tabs. Keep line breaks, words, punctuation, numbers, hesitations, repetitions, uncertainty and spoken corrections. |
| Improve clarity (`clarity`) | Use the configured refinement route and its existing faithful editing instructions. |
| Current default (absent or `null`) | Keep the previous workflow, including route enablement and multimodal processing. |

These options control editing after recognition. Speech recognition can still
make errors. The examples describe the policy; fixture tests do not establish
speech accuracy or language quality.

Dictionary entries remain bounded recognition hints. They are not forced word
replacements. A standalone snippet inserts the exact saved replacement and
bypasses editing in every level. Other snippets expand once. Minimal changes
adjusts spaces before expansion, so it does not alter saved replacement text.
Clarity receives the expanded source; its output is never expanded again.

`shared/dictation_policy.py` owns the enum and frozen policy. Desktop resolves
the preference before starting recognition. Explicit levels separate recognition
from editing, including multimodal providers. `raw_text` retains the recognition
response. `text` is the final usable text; `refined_text` retains a changed result
or expanded snippet under the existing contract.

`cleanup_level_requested` and `cleanup_level_applied` are optional result and
workflow-state fields. Legacy operations leave both unset. A disabled refinement
route, local inference without cloud permission, or a standalone snippet reports
applied `preserve`. A refinement failure also reports applied `preserve`, retains
the expanded source and sets `refinement_failed`. A disabled route is not a
provider failure. The level never grants cloud permission or selects a provider.
Selected-text rewriting and translation keep their separate contracts.

The hosted multipart field `cleanup_level` accepts only `preserve`, `light` or
`clarity`. Omitting it preserves the old behavior and fingerprint, including for
iOS. Explicit levels participate in the operation fingerprint. A replay with a
different level conflicts; it cannot reuse or replace another saved result.
Hosted responses include the requested/applied levels and bounded refinement
attempt/failure flags for explicit requests. The desktop rejects missing or
mismatched explicit policy responses. It does not retry or switch providers.

Configuration schema 3 adds the optional preference. The migration from schema
2 is idempotent and leaves the preference unset. Existing schema-2 readers load
newer files read-only and refuse saves. Downgrading does not permit editing that
file. No database or history migration is required.
