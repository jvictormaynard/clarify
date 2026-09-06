# Local model profiles, compute devices, and experimental pause processing

Implemented 2026-09-06. Applies to the Qt desktop runtime.

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

The option is OFF by default. This is pause-based Whisper processing, not a native streaming ASR model. It reads the same mono PCM16 16 kHz WAV written by the recorder. A conservative low-energy pause of at least one second permits a split after at least three seconds of audio. Speech is never split merely because a timer expires. The buffer is bounded to 60 seconds and the segment list to 128 entries. The decoder runs serially.

No partial text is pasted. At stop, the full final WAV must match the exact committed PCM prefix. The remaining tail is decoded and joined with completed segments. Changed/unsupported audio, backlog, empty chunks, and segment errors discard partial results and retain the normal full-audio path. Cancellation follows the recording lifecycle. Success still has no result window, and explicit same-audio retry is preserved.

Chunk boundaries can change wording, punctuation, and language recognition. Multilingual quality evaluation is still required before enabling this by default. Continuous speech without a safe pause may see no streaming benefit.

## Validation and limits

Windows tests cover profile isolation, configuration persistence, cache invalidation, CPU fallback, cancellation, exact PCM preservation across segments, final-audio mismatch, missing pauses, and bounded backlog. Existing provider, recorder, workflow, settings, clipboard, and recovery suites also run.

Real runtime test: Ryzen 7 6800H / RTX 3070 Ti Laptop 8 GB, synthetic English audio lasting about 9.3 seconds, Whisper Small. Warm median: CPU 2923 ms; CUDA 187 ms. GPU cold startup took about 5.5 seconds in a separate run. These are local model request timings, not full stop-to-paste latency and not results for other hardware.

A growing-WAV replay with two copies of the synthetic sample reused two segments and finished about 271 ms after input completion. The replay fed data faster than real time. Its wording/punctuation differed across segments, so it does not establish transcription quality. Base CPU was also installed and decoded the sample successfully, but produced more word errors; this single synthetic sample does not establish language accuracy. Medium was checked through its pinned manifest and installer tests, not a full model inference run. All profiles still require broader real-audio benchmarks; do not extrapolate Small results to them.

Final focused suites: 567 passing tests in the renamed checkout and 578 in the deployed recovery-capable checkout. Ruff and scoped git diff whitespace checks passed. The local model card was loaded in Qt and rendered with the new selectors and experimental toggle.

Sources:
- https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.1
- https://huggingface.co/ggerganov/whisper.cpp/tree/80da2d8bfee42b0e836fc3a9890373e5defc00a6
- https://developer.download.nvidia.com/compute/cuda/redist/redistrib_11.8.0.json
- https://docs.nvidia.com/cuda/archive/11.8.0/eula/index.html
