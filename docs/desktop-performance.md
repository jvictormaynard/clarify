# Desktop responsiveness

This work covers the React/Tauri Settings window and the Python/Qt desktop
runtime. The Settings window uses dark neutral surfaces and action controls,
preserving the pill layout, passive focus behavior,
workflow commands and saved data. Choice controls save their preference directly;
free-text drafts retain contextual Save/Discard. Mobile is
outside this work.

## Ownership boundaries

- Device discovery shares one pending worker; lifecycle commands remain ordered.
  An asynchronous IPC call does not itself move native work off the Qt thread.
- Settings sends changed fields, retains unchanged React references and skips
  identical updates. Draft comparisons do not serialize large libraries on
  every microphone level update.
- Each poll patch publishes one state update. Saves, account changes, recording
  transitions and errors retain their ordering and validation.
- Audio backend initialization is deferred to its worker. Hidden Settings
  windows pause periodic refreshes. The production host remains Tauri/WebView2;
  Python and Qt retain workflow and audio ownership.

## Confirmed mechanisms

The original Settings loop requested the complete state every second, or every
100 ms during a microphone test. Each response included dictionary and snippet
text, even on the Dictation page. Python serialized that data on the Qt thread;
the native pipe, JSON decoder, and React then received fresh copies.

The `poll` method now returns only top-level fields that differ from its previous
poll. It retains one baseline. Initial state and command replies remain complete.
Command replies do not move the poll baseline. Full replies retain a bounded
set of changed field names until the next
poll. This also delivers completion when a transient command value returns to
the baseline between polls. The frontend uses the same queue
for polls, commands, and history reads, retains unchanged references, and falls
back to a full read after a poll error. The first poll, a changed library, and
full commands can still carry a large payload. Every poll still reads the
allowlisted properties; this is not a second configuration store.
User-operation pending state excludes telemetry and belongs to the action, not
the entire window. The page and sidebar have no shared disabled fieldset.
Transactions serialize multi-command mutations without blocking local navigation.
Local navigation does not publish a captured snapshot over a newer poll result.
Text drafts stay in the frontend until explicit save; preference writes preserve
those drafts. Event-gated and microtask regressions cover these overlapping paths.

Microphone enumeration previously ran in the Settings constructor and in the
refresh action on the Qt thread. The real call path reached PortAudio device and
host API queries. A controlled slow query stopped the Qt heartbeat. Discovery
now runs on a shared pending worker and publishes immutable results through a
queued signal. Refresh keeps the previous inventory. Shutdown rejects late
results without waiting for a device driver. The controller does not retain a
closed window through the worker. A query that never returns remains bounded
to that worker; the driver API has no cancellation operation.

The pill also sampled capture readiness under a lock held during process launch,
and performed WAV reads from its Qt timer. Readiness now comes from one worker
and the Qt getter reads cached signals. Process launch stays outside the shared
lock. Each capture has its own identity, so a cancelled late launch is terminated
and cannot replace a later recording. Cancelled temporary audio is cleaned again
after that launch finishes.
On Windows, the readiness read handle shares delete access. Cancellation can
unlink the owned WAV during the read; Windows completes deletion when the
handle closes. A regression holds a real Windows read handle during cancel.

The waveform's optional PortAudio stream previously opened before recording
startup became terminal. Stop and Undo finalization therefore waited for this
presentation stream. A separate, bounded meter worker now owns native stream
open/start/stop/close. Finalization detaches the meter without waiting. Late
streams close once and cannot publish levels to a later capture. Audio backend
loading is lazy and shared. A permanently blocked native stream operation can
retain one optional worker; native audio APIs offer no safe forced cancellation.
The voice-translation module uses this loader from its recording worker too.
A fresh-process regression imports the production entrypoint and checks that
neither startup imports nor recording construction initialize PortAudio.
Voice VAD startup retains ownership until native stream startup returns. Stop
and cancellation remain terminal while backend loading, device selection,
stream construction, or stream start is pending. Late streams close through
their startup owner and cannot reopen the microphone after finalization.

## Measurements

These are isolated development measurements on 2026-10-25. They use fake audio,
temporary repositories, and no real provider, profile, key, or recording. They
do not measure the user's Windows device driver or establish that the reported
Windows hang has been reproduced.

For the browser case, the actual controller held 512 snippets with 4096 ASCII
characters per replacement. Dictation stayed open and a fake backend published
levels. Each sample lasted eight seconds. The table compares two warm runs on
each version. The probe measured the round trip through the local fixture and
the JSON length of returned state, without pipe envelopes or full user commands.

| Warm browser case | Before | After |
| --- | --- | --- |
| Median periodic round trip | 64.1–65.6 ms | 8.1–8.2 ms |
| 95th percentile round trip | 75.3–82.5 ms | 9.8–12.6 ms |
| Returned state in eight seconds | 88.0–92.3 million JSON characters | 1968 JSON characters |
| 95th percentile frame interval | 16.8 ms | 16.7–16.8 ms |

An earlier first run had a 151.1 ms median and a 100.1 ms frame percentile. It is
kept separate from the warm comparison. The warm frame result does not show a
frame-rate improvement; the clear measured change is the work and data required
for each periodic response.

A second probe used the real controller, recorder, adapter, and Qt event loop.
An event gate delayed a fake device query by 350 ms. Three repetitions produced:

| Controlled Qt case | Before | After |
| --- | --- | --- |
| Controller construction | 352.6–353.3 ms | 1.9–2.4 ms |
| Refresh call | 350.8–351.1 ms | 0.01–0.60 ms |
| Maximum Qt heartbeat gap | 351–357 ms | 5.1–5.9 ms |

The device query still has its full delay. The changed owner lets the Qt loop
continue during that delay. Event-gated regression tests also check coalescing,
worker-only loading, Qt-thread publication, draft preservation, and shutdown.

A recorder probe held fake process launch and meter open separately. Capture
sampling during the held launch fell from 351 ms to 0.008–0.022 ms; maximum Qt
heartbeat gaps fell from 353 ms to 5.3–5.9 ms. Undo finalization returned in
0.8–1.1 ms while meter open remained held. Regressions also gate readiness file
reads, late process publication, rapid restart, stale callbacks, and native
stream close. These results use fake native operations and do not measure a
real Windows microphone.

## Memory and native acceptance

A native WebView probe completed 100 fake microphone start/stop cycles
per frontend version, with garbage collection and a sample every 20 cycles.
It compared the retained pre-delta Settings executable with the responsiveness candidate
using the isolated Python fixture. These are frontend measurements, not a
comparison of the original and final complete Windows application. These samples
precede the current shared controls and palette; they measure the state and
lifecycle changes, not the current control implementation.

| Native WebView sample | Retained frontend | Updated frontend |
| --- | --- | --- |
| Initial JavaScript heap | 3.67 MB | 3.67 MB |
| Heap after 100 cycles | 5.74 MB | 5.21 MB |
| Document count, all samples | 1 | 1 |
| Nodes after initial sample | 410 | 410 |
| Listener samples | 201, 197, 197, 340, 340, 340 | 201, 197, 197, 197, 197, 197 |

The final three heap samples were 5.14, 5.16 and 5.21 MB. Both versions closed
cleanly. These short samples do not prove or exclude a leak or establish the
cause of the listener-count difference. Small-data native snapshot round trips
were 10.9–18.9 ms before and 11.6–27.8 ms after; this probe does not show a native
round-trip improvement. Fixture-plus-WebView startup took 6.1 and 5.1 seconds;
these single observations are not isolated cold-start measurements.

One initial attempt ended microphone preview before the expected checkpoint.
A traced retry reached the fixture's 90-second lifetime limit near the end of
the run. The completed run extended only that temporary fixture guard to 300
seconds; product timeouts and source were unchanged. The initial interruption
was not reproduced in that completed run.

Native smoke samples showed summed working sets of about 460–496 MB across nine
processes. They include shared pages counted more than once and are neither
unique resident memory nor a JavaScript heap/leak measurement.

The performance probes above preceded the shared-control migration. They are
historical evidence for the state and audio lifecycle changes. They do not
establish acceptance of later component or palette changes.

Validate each complete candidate with the Python suite, isolated Settings tests,
TypeScript/Vite build, dependency inventory, Windows executable and embedded
payload checks, and separate requirements and engineering reviews. Record the
candidate identity, terminal results, and open checks in its delivery report.
A pending build or an earlier candidate's result is not final evidence.

Manual acceptance of real audio devices, prolonged use, DPI, global shortcuts,
tray, transparency, and passive pill focus remains separate. A successful
fake-backend test does not establish real-device startup latency.

## Installed build observation, 2026-10-25

A read-only Windows process probe sampled the installed shared-control build
from 05:08:06 to 05:13:06 UTC, every ten seconds (31 samples). Its executable
SHA-256 was `5533ca466240776f0c65476d2446c4eebf3ff1826bd0959c1c9627916b0de17a`.
This observation preceded the contextual-save and operation-local UI changes.
The probe did not open windows, start capture, invoke providers or inspect
profile contents. The user continued normal use during the observation.

CPU accumulated at least 36.94 CPU-seconds, averaging 0.77% when normalized to
16 logical processors; the highest interval average was 2.88%. Short-lived
processes can exit between samples, so some CPU work can be missed. The observed
Clarify 3D engine reached 3%; this is an engine counter, not total system GPU use.

Summed working sets ranged from 181.24 to 266.40 MiB and ended at 261.25 MiB.
Shared pages can be counted more than once. Summed private bytes went from
533.50 to 590.53 MiB, with a 620.41 MiB maximum and both rises and falls.
The main Python/Qt process stayed near 280 MiB of private memory; one WebView2
process accounted for about 56.71 MiB of the net increase. Aggregate handles
ended at 9,695 versus 9,706 initially; thread counts began and ended at 276.

These samples describe only this five-minute interval. They cannot reconstruct
previous peaks, measure continuous retained-heap growth, or prove or exclude a
leak. Real-device acceptance reported by the user covered microphone preview
and startup without a not-responding warning; it does not replace prolonged
memory observation or acceptance of later builds.
