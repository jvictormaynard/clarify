# Dictation latency

The first performance changes preserve the configured provider and model. They
require no GPU, no new model download, and no automatic cloud fallback.

## Implemented behavior

- After microphone capture starts, the workflow prepares the selected local
  engine on a recording-owned background worker. It sends no audio or cloud
  request. Preparation failure is best effort; the normal request reports errors.
- The preparation lease keeps the engine alive throughout the recording. Stop,
  cancel, failure, and shutdown release the lease. Cancellation reaches model
  startup. Hosts with less than 1 GiB of available RAM skip speculative loading.
- Idle retention is 60 seconds on unknown or constrained hosts, 5 minutes with
  at least 8 GiB total / 2 GiB available RAM, and 10 minutes with at least 16 GiB
  total / 6 GiB available RAM. The idle watcher checks memory every 15 seconds.
  Reduced available memory shortens retention; it does not interrupt inference.
- Recording finalization waits for the recorder process to exit before reading
  the WAV. The redundant 300 ms sleep is removed; the process wait remains.
- Clipboard delivery runs before statistics persistence. Focus checks and the
  copy-only fallback remain owned by the existing clipboard adapter.

## Measurements

Successful dictation usage events include a numeric `latency_ms` object. It
contains only allowlisted finite nonnegative durations, never text, audio,
paths, URLs, prompts, or credentials. These are local statistics, not telemetry.

- `capture_finalize_ms`: stop dispatch through finalized audio, including queue wait.
- `provider_ms`: complete provider gateway call.
- `asr_ms`: speech recognition request, including transport and model preparation.
- `model_start_ms`: local startup/health/verification wait inside the request.
  Work already completed during recording is intentionally outside this interval.
- `inference_ms`: local inference request and result collection.
- `refinement_ms`: optional subsequent text model call.
- `text_cleanup_ms`: local text expansion.
- `delivery_ms`: clipboard transaction, including its focus and restore checks.
- `stop_to_delivery_ms`: stop dispatch through successful paste/copy transaction.
  Failed clipboard transactions do not report a successful delivery total.

Nested durations overlap: do not sum all fields. ASR includes model startup and
inference; provider includes ASR, refinement, and text cleanup. Delivery total
also includes workflow/UI scheduling and excludes subsequent statistics writes.
On explicit retry, the total begins at retry dispatch and excludes time spent
waiting for the user to choose Retry. Recording duration remains a separate field.

## Local validation, 2026-09-05

Windows, AMD Ryzen 7 6800H, CPU execution, whisper.cpp v1.9.1, Whisper Small.
A synthetic English WAV at 16 kHz mono has 9.289 seconds. Three alternating
cold/prepared pairs used the same audio and unchanged decoding parameters.

| Request | Median | Range |
| --- | ---: | ---: |
| Engine unloaded at request start | 4.684 s | 4.652â€“4.778 s |
| Engine prepared before request | 2.933 s | 2.931â€“2.943 s |

The median reduction is 37.4%. This measures the local engine
request, not full stop-to-paste latency. Preparation shifts model loading into
the recording interval; it does not make inference faster. Very short recordings
may still wait for loading. An earlier cold run took 5.620 seconds, which also
shows why a single measurement is insufficient.

All six transcripts were identical. The sample still contains an existing
recognition error, so this is a timing regression check, not a quality benchmark.
No user recordings or paid API requests were used. Hardware policy branches are
covered by deterministic tests; actual performance was measured on one CPU host.
The focused Windows suites passed 518 tests in the renamed source and 528 in
the source matching the installed application. Ruff and the changed-file
whitespace check passed. A temporary statistics repository also verified that
only the allowlisted timing fields survive persistence.

## Remaining performance and quality work

Native streaming, GPU backend selection, model profiles, and dictionary-aware
local decoding are not enabled by these changes. Validate them separately with
real Portuguese, mixed-language speech, names, numbers, pauses, and short clips.
Use identical audio across CPU-only, integrated-GPU and dedicated-GPU hosts.
Report stop-to-delivery median and p95, memory use, first-use versus warm behavior,
word errors and semantic omissions. No speed target is a product guarantee until
it is measured on the supported hardware and language matrix.
