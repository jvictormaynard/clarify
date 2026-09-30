# Local model profiles, compute devices, and background recognition

Implemented 2026-09-06; background recognition revised 2026-09-30.
Applies to the Qt desktop runtime.

## Profiles

Settings offers Fast (Whisper Base), Balanced (Small), and Quality (Medium).
These names describe resource/quality goals, not measured accuracy guarantees.
Models are multilingual and pinned to a Hugging Face revision with exact size and SHA-256. Each model/backend has its own removable installation. The original Small CPU installation remains usable. No model is downloaded during dictation or on settings selection.

CUDA uses the pinned whisper.cpp v1.9.1 Windows package plus the official NVIDIA cuBLAS 11.11.3.6 archive. Both archives and extracted files are verified. The upstream CUDA package alone omits cuBLAS. NVIDIA terms are linked before installation and the original cuBLAS license is retained. GPU libraries are downloaded only with explicit installation, not bundled in the app executable.

## CPU and GPU

CPU is available on supported Windows x64 hardware. NVIDIA devices are discovered with a bounded local query. CUDA startup must report actual CUDA backend use; merely finding a GPU or a healthy HTTP server is insufficient. CUDA failures fall back to the same installed model on CPU. Missing CPU assets produce an installation error; there is no automatic cloud fallback.

The Measure CPU/GPU speed button uses packaged synthetic English audio, a warmup, and three timed runs of each installed engine. Automatic chooses GPU only when its median is at least 10 percent faster. A local cache is invalidated by model/runtime hashes and CPU/GPU/driver identity. Without a valid measurement, Automatic selects CPU. Measurement is cancellable and sends no audio to the network. Measure while no dictation is in progress. Repeat after power-mode or system changes.

AMD, Intel GPU, and Apple GPU acceleration are not implemented. They must not be presented as supported CUDA devices. This release does not introduce a new platform build.

## Experimental processing during recording

The option stays OFF by default and requires a selected NVIDIA CUDA backend.
CPU recording still prepares the model in the background. Existing settings
retain their explicit opt-in or opt-out. This uses Whisper requests during
capture; it does not add a native streaming model or a cloud transcription call.

The worker reads the recorder's original mono PCM16 16 kHz WAV. A low-energy
pause of at least one second permits a snapshot after at least three seconds
of new audio. Each request contains the complete recorded prefix. Its result
replaces the previous snapshot; separately decoded speech is never joined.
This retains the full decoder context. Pending audio is bounded to 60 seconds,
and the background prefix to 30 minutes. A limit disables background recognition
for that recording and leaves the normal full-recording path available.

No partial text is pasted. At Stop, the final recording must match the exact
cached PCM prefix by SHA-256. Only a complete snapshot with a near-silent tail
can be reused. The tail must have RMS below 25 and peak amplitude no more than
100 on the signed PCM16 scale. A voiced tail, changed or unsupported audio,
backlog, empty result, or recognition error uses the original full recording.
Finalization has an eight-second cooperative cancellation budget. Stopping the
decoder and loading it again can add further delay. User cancellation is kept
separate from cancellation of a speculative request. Same-audio retry remains
available.

The 2026-09-30 real-time replay test rejected independent chunks as a default:
word errors increased in three of four English/Portuguese recordings lasting
63 to 188 seconds. Full-prefix snapshots keep the original recognition context,
but a voiced tail still needs a full request. Very quiet speech, missing final
pauses, decoder load, and continuous speech require further evaluation.
Background recognition therefore remains an experiment and can increase delay.

## Dictation cleanup

The official Groq `openai/gpt-oss-20b` and `openai/gpt-oss-120b` routes use
`reasoning_effort=low` for dictation cleanup. Other models, custom endpoints,
selected-text rewriting, and translation keep their existing request settings.
The completion budget scales with transcript length. A `length` finish reason
rejects incomplete output and uses the original transcript through the existing
recovery path.

Cleanup preserves unique intended facts, names, numbers, negations, conditions,
and separate events. It removes accidental duplicates and resolves clear spoken
self-corrections. Word-error rate applies to raw ASR; it cannot judge a valid
editorial rewrite. Long-input recovery still rejects severe compression, except
when the output keeps the exact words of every unique sentence in source order.
This permits large exact duplicate removal without accepting a short title.

The revised policy passed 33 live content checks across English and Portuguese,
including one-to-three-minute text, repeated blocks, independent shipments,
dates, names, quantities, negations, uncertain alternatives, and twenty exact
repetitions. These checks and manual inspection support the tested cases; they
do not prove quality for every possible dictation.

## Historical validation (2026-09-06)

Windows tests cover profile isolation, configuration persistence, cache invalidation, CPU fallback, cancellation, exact PCM preservation across segments, final-audio mismatch, missing pauses, and bounded backlog. Existing provider, recorder, workflow, settings, clipboard, and recovery suites also run.

Real runtime test: Ryzen 7 6800H / RTX 3070 Ti Laptop 8 GB, synthetic English audio lasting about 9.3 seconds, Whisper Small. Warm median: CPU 2923 ms; CUDA 187 ms. GPU cold startup took about 5.5 seconds in a separate run. These are local model request timings, not full stop-to-paste latency and not results for other hardware.

A growing-WAV replay with two copies of the synthetic sample reused two segments and finished about 271 ms after input completion. The replay fed data faster than real time. Its wording/punctuation differed across segments, so it does not establish transcription quality. Base CPU was also installed and decoded the sample successfully, but produced more word errors; this single synthetic sample does not establish language accuracy. Medium was checked through its pinned manifest and installer tests, not a full model inference run. All profiles still require broader real-audio benchmarks; do not extrapolate Small results to them.

Final focused suites: 567 passing tests in the renamed checkout and 578 in the deployed recovery-capable checkout. Ruff and scoped git diff whitespace checks passed. The local model card was loaded in Qt and rendered with the new selectors and experimental toggle.

Sources:
- https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.1
- https://huggingface.co/ggerganov/whisper.cpp/tree/80da2d8bfee42b0e836fc3a9890373e5defc00a6
- https://developer.download.nvidia.com/compute/cuda/redist/redistrib_11.8.0.json
- https://docs.nvidia.com/cuda/archive/11.8.0/eula/index.html


## Unified model installation (2026-09-06)

Settings now installs a model as one unit: CPU runtime, plus CUDA runtime and
cuBLAS when a compatible NVIDIA device is detected. Installation then benchmarks
the installed CPU and GPU devices using bundled synthetic audio. Automatic picks
the lowest median time from three warm runs (after a warmup). No cloud call is
made. Manual device selection is still available.

CPU and CUDA installers reuse matching model weights from the other profile,
checking size and SHA-256 before use. On the same filesystem the new installation
uses a hard link, so both paths share disk storage and either installation can
be removed without breaking the other link. If hard links are unavailable the
installer copies the verified file instead; no network model download is needed.
All published files still pass the existing final integrity verification.

Existing CPU installations can use Optimize CPU/GPU to add missing support and
measure speed. The model is reused. Settings reports a maximum download size;
actual download is lower when assets already exist. GPU installation failure
keeps CPU available and reports a retry option. Cancellation stops setup and
prevents starting a later measurement. A recording request can cancel measurement.
Removal through Settings removes both runtime installations for the selected model.

Windows validation: 153 installer/product/profile/settings tests passed. Updated
adapter unit tests pin CPU selection so the host calibration cannot start a real
GPU engine during a unit test. Medium CPU/CUDA models verified as the same file
with os.path.samefile, and both installations passed their integrity checks.
On this host, bundled sample medians were CPU 13335.52 ms and GPU 439.16 ms.
These are warm ASR sample timings, not complete dictation/refinement latency.
Automatic selected cuda:0. Other hardware must use its own measurement.
