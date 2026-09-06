# Dictation refinement validation

2026-09-06: direct text refinement through QtProviderGateway._refine_transcript,
using the configured Groq openai/gpt-oss-20b local-ASR refinement route.
Synthetic inputs only; no recording, clipboard delivery, or user history involved.

The previous instruction preserved both Wednesday and Thursday in a scheduling
self-correction. The updated dictation instruction resolves explicit replacements
before applying the general detail-preservation rule. It applies to refined
transcripts and multimodal prompt dictation, not selected-text editing or raw
transcription. No new model call or hardware requirement was added.

Manual Portuguese checks, one request per case:

| Input intent | Observed output |
| --- | --- |
| Schedule Wednesday, actually Thursday | Thursday only; original request preserved |
| Schedule Wednesday, no, actually Thursday | Thursday only; original request preserved |
| Send three copies to Ana, no five, actually seven | Seven copies to Ana |
| Do not schedule Wednesday; Thursday also unavailable | Both restrictions preserved |
| Wednesday or Thursday; not sure | Both alternatives and uncertainty preserved |
| First review contract, second send proposal to Ana, third confirm time | Three separate list items in order |
| She said: actually I liked Wednesday | Quoted statement preserved |

Observed refinement time: 0.83-1.13 seconds per request for these short texts.
This is not total dictation latency or a general benchmark. Model outputs can
vary; these checks do not establish correctness for all dictations or providers.
Existing runtime suite: 38 tests passed.
