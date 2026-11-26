"""Rolling speaker evidence for captured PCM."""

from collections import Counter, defaultdict
from contextlib import ExitStack
from copy import copy
from dataclasses import dataclass, field
from itertools import groupby
import logging
import queue
import struct
import threading
import time

from local_asr_live import RATE

try:
    from .meeting_overlap import open_speaker_embedding, pressure_normal
    from .meeting_speaker_pace import SpeakerPace
    from .meeting_speakers import (
        CONTEXT_SECONDS,
        Sortformer,
        _timed_words,
        _unique_voice,
    )
except ImportError:
    from meeting_overlap import open_speaker_embedding, pressure_normal
    from meeting_speaker_pace import SpeakerPace
    from meeting_speakers import (
        CONTEXT_SECONDS,
        Sortformer,
        _timed_words,
        _unique_voice,
    )


LOCAL_MICROPHONE = -1
SYSTEM_AUDIO = -2
AMBIGUOUS = 0
STRIDE_SECONDS = 6
WINDOW_SECONDS = STRIDE_SECONDS + CONTEXT_SECONDS
BIN_MS = 20
BIN_FRAMES = RATE * BIN_MS // 1000
WINDOW_FRAMES = WINDOW_SECONDS * RATE
CONTEXT_BINS = CONTEXT_SECONDS * 1000 // BIN_MS
LOG = logging.getLogger(__name__)

PROFILE_SPEAKERS = 8
PROFILE_ANCHORS = 4
PROFILE_FLOOR = 0.68
PROFILE_MARGIN = 0.15
PROFILE_DUPLICATE = 0.995
NOVEL_CEILING = 0.55
CLEAN_GUARD = 5
CLEAN_MIN = 60
CLEAN_MAX = 120
PROFILE_WAIT = 0.28
FALLBACK_BINS = 160
_PROFILE_SLOT = threading.Lock()


@dataclass
class EmbeddingJob:
    pcm: bytes
    deadline: float
    done: threading.Event = field(default_factory=threading.Event)
    vector: object = None


class ProfileInference:
    """Own optional inference outside the recorder and the timing worker."""

    def __init__(self, assets, end, abort):
        self.assets, self.end, self.abort = assets, end, abort
        self.closed = threading.Event()
        self.ready = threading.Event()
        self.jobs = queue.Queue(1)
        self.thread = None
        self.deadline = 0.0

    def is_set(self):
        return self.closed.is_set() or self.end.is_set() or self.abort.is_set()

    def prepare(self):
        self.deadline = time.monotonic() + PROFILE_WAIT
        if self.thread is None and not self.is_set() and pressure_normal():
            # A prior interval may still be leaving a native call.
            if _PROFILE_SLOT.acquire(blocking=False):
                try:
                    self.thread = threading.Thread(
                        target=self._run, name="MeetingVoiceProfiles", daemon=True
                    )
                    self.thread.start()
                except RuntimeError as error:
                    _PROFILE_SLOT.release()
                    self.close()
                    LOG.warning(
                        "Meeting speaker profiles unavailable (%s)",
                        type(error).__name__,
                    )

    def close(self):
        self.closed.set()
        try:
            self.jobs.get_nowait()
        except queue.Empty:
            pass

    def embedding(self, pcm):
        if (
            not self.ready.is_set()
            or self.is_set()
            or time.monotonic() >= self.deadline
        ):
            return None
        job = EmbeddingJob(pcm, self.deadline)
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            return None
        while not self.is_set():
            remaining = job.deadline - time.monotonic()
            if remaining <= 0:
                break
            if job.done.wait(min(remaining, 0.01)):
                if not self.is_set() and time.monotonic() < job.deadline:
                    return job.vector
                break
        return None

    def _run(self):
        try:
            if self.is_set() or not pressure_normal():
                return
            model = open_speaker_embedding(self.assets, self)
            if model is None or self.is_set():
                return
            self.ready.set()
            while not self.is_set():
                try:
                    job = self.jobs.get(timeout=0.05)
                except queue.Empty:
                    continue
                try:
                    if (
                        not self.is_set()
                        and time.monotonic() < job.deadline
                        and pressure_normal()
                    ):
                        vector = model.embedding(job.pcm)
                        if not self.is_set() and time.monotonic() < job.deadline:
                            job.vector = vector
                finally:
                    job.done.set()
        except Exception as error:
            if not self.is_set():
                LOG.warning(
                    "Meeting speaker profiles unavailable (%s)", type(error).__name__
                )
        finally:
            self.ready.clear()
            self.close()
            _PROFILE_SLOT.release()


@dataclass(eq=False)
class CleanAnchor:
    start: int
    end: int
    vector: object
    remembered: bool = False


class SpeakerProfiles:
    """Bounded normalized references for one active meeting."""

    def __init__(self):
        self.anchors = {}

    def remember(self, speaker, samples, *, seed_until=None, competitors=()):
        for sample in samples:
            if sample.remembered:
                continue
            sample.remembered = True
            refs = self.anchors.get(speaker, ())
            if any(
                float(sample.vector @ other.vector) >= PROFILE_FLOOR
                for other in competitors
            ):
                continue
            alternative = max(
                (
                    float(sample.vector @ vector)
                    for owner, anchors in self.anchors.items()
                    if owner != speaker
                    for vector in anchors
                ),
                default=-1,
            )
            if refs:
                scores = sorted(
                    (float(sample.vector @ ref) for ref in refs), reverse=True
                )
                support = scores[min(1, len(scores) - 1)]
                if (
                    scores[0] >= PROFILE_DUPLICATE
                    or support < PROFILE_FLOOR
                    or support - alternative < PROFILE_MARGIN
                ):
                    continue
            elif (
                seed_until is None
                or sample.start > seed_until
                or alternative >= NOVEL_CEILING
            ):
                # The first reference must come from the original appearance.
                continue
            self.anchors.pop(speaker, None)
            self.anchors[speaker] = (*refs, sample.vector)[-PROFILE_ANCHORS:]
            if len(self.anchors) > PROFILE_SPEAKERS:
                evicted = next(
                    (
                        owner
                        for owner, vectors in self.anchors.items()
                        if len(vectors) < 2
                    ),
                    next(iter(self.anchors)),
                )
                del self.anchors[evicted]

    def resolve(self, fresh, reserved, samples):
        if not fresh or not self.anchors:
            return {}, set(fresh)
        # A weak or incomplete profile can veto a match. Two independent
        # references must support every clean sample in a slot to make a claim.
        strengths, peaks = {}, {}
        for slot, excerpts in samples.items():
            if not excerpts:
                continue
            strengths[slot] = support = {}
            peaks[slot] = best = {}
            for speaker, refs in self.anchors.items():
                scores = [
                    sorted(
                        (
                            float(sample.vector @ ref)
                            for ref in refs
                            if ref is not sample.vector
                        ),
                        reverse=True,
                    )
                    for sample in excerpts
                ]
                best[speaker] = max((row[0] for row in scores if row), default=-1)
                support[speaker] = min(
                    row[1] if len(row) >= 2 else -1 for row in scores
                )

        claimed = set(reserved.values())
        matched, novel = {}, set()
        for slot in fresh:
            if slot not in strengths:
                continue
            support, best = strengths[slot], peaks[slot]
            if max(best.values()) < NOVEL_CEILING and not any(
                sample.remembered for sample in samples[slot]
            ):
                novel.add(slot)
                continue
            speaker = max(support, key=support.__getitem__)
            score = support[speaker]
            alternative = max(
                (peak for other, peak in best.items() if other != speaker), default=-1
            )
            competitor = max(
                (row[speaker] for other, row in peaks.items() if other != slot),
                default=-1,
            )
            if (
                speaker not in claimed
                and score >= PROFILE_FLOOR
                and score - max(alternative, competitor) >= PROFILE_MARGIN
            ):
                matched[slot] = speaker
        return matched, novel


@dataclass(frozen=True)
class SourceWindow:
    start: int  # 20 ms bins from the start of this capture interval
    microphone: bytes
    system: bytes
    known: bytes  # one byte per frame, zero when the tap supplied no sample


@dataclass(frozen=True)
class SourceContext:
    system: bytes
    anchors: tuple[int | None, ...]
    next_speaker: int = 1
    profiles: SpeakerProfiles | None = None


class SourceBuffer:
    def __init__(self, context=None):
        system = context.system if context is not None else b""
        # The previous system tail supports speaker continuity after pause.
        # It does not provide microphone or tap availability evidence.
        self.microphone = bytearray(len(system))
        self.system = bytearray(system)
        self.known = bytearray(len(system) // 2)
        self.frames = self.submitted = 0

    def append(self, microphone, system, valid):
        frames = len(microphone) // 2
        self.microphone.extend(microphone)
        self.system.extend(system)
        self.known.extend(b"\x01" * valid + bytes(frames - valid))
        self.frames += frames
        # Retain the complete leading bin so all windows share a time grid.
        drop = (len(self.known) - WINDOW_FRAMES) // BIN_FRAMES * BIN_FRAMES
        if drop > 0:
            del self.microphone[: 2 * drop]
            del self.system[: 2 * drop]
            del self.known[:drop]

    def paused_context(self, previous_start, previous, next_speaker, profiles=None):
        return _paused_context(
            self.system, self.frames, previous_start, previous, next_speaker, profiles
        )

    def snapshot(self, *, final=False, stride=STRIDE_SECONDS):
        pending = self.frames - self.submitted
        if pending < (BIN_FRAMES if final else stride * RATE):
            return None
        self.submitted = self.frames
        return SourceWindow(
            (self.frames - len(self.known)) // BIN_FRAMES,
            bytes(self.microphone),
            bytes(self.system),
            bytes(self.known),
        )


def _paused_context(
    pcm,
    frames,
    previous_start,
    previous,
    next_speaker,
    profiles=None,
    *,
    include_prior=False,
):
    end = frames // BIN_FRAMES
    # Align the old end with the start of the resumed interval.
    available = len(pcm) // (2 * BIN_FRAMES) if include_prior else end
    tail_bins = min(available, CONTEXT_BINS)
    if not tail_bins or not previous:
        return SourceContext(b"", (), next_speaker, profiles)
    tail = len(pcm) - 2 * (frames % BIN_FRAMES)
    return SourceContext(
        bytes(pcm[tail - 2 * tail_bins * BIN_FRAMES : tail]),
        tuple(
            previous[point - previous_start]
            if previous_start <= point < previous_start + len(previous)
            else None
            for point in range(end - tail_bins, end)
        ),
        next_speaker,
        profiles,
    )


@dataclass(frozen=True)
class MixedWindow:
    start: int
    pcm: bytes


class MixedBuffer:
    """Retain the latest mono PCM on the same time grid as the source timeline."""

    def __init__(self, context):
        self.pcm = bytearray(context.system if context is not None else b"")
        self.frames = 0

    def append(self, pcm):
        self.pcm.extend(pcm)
        self.frames += len(pcm) // 2
        drop = (len(self.pcm) // 2 - WINDOW_FRAMES) // BIN_FRAMES * BIN_FRAMES
        if drop > 0:
            del self.pcm[: 2 * drop]

    def snapshot(self, *, max_frames=WINDOW_FRAMES):
        frames = min(len(self.pcm) // 2, max_frames + self.frames % BIN_FRAMES)
        return MixedWindow(
            (self.frames - frames) // BIN_FRAMES,
            bytes(memoryview(self.pcm)[-2 * frames :]),
        )

    def paused_context(self, *anchors):
        return _paused_context(self.pcm, self.frames, *anchors, include_prior=True)


def _activity(pcm, count, threshold):
    for index in range(count):
        start = 2 * index * BIN_FRAMES
        energy = sum(
            value * value
            for (value,) in struct.iter_unpack(
                "<h", pcm[start : start + 2 * BIN_FRAMES]
            )
        )
        yield energy >= BIN_FRAMES * threshold**2


class SourceVoices:
    def __init__(self, next_speaker, context):
        self.previous = context.anchors if context is not None else ()
        self.previous_start = -len(self.previous)
        self.next_speaker = max(
            next_speaker,
            context.next_speaker if context is not None else 1,
            1 + max((anchor or 0 for anchor in self.previous), default=0),
        )
        self.profiles = (
            context.profiles
            if context is not None and context.profiles is not None
            else SpeakerProfiles()
        )
        self.embedding = None
        self.recent = []
        self.seed_until = {}

    def _samples(self, window, slots, mic, system):
        self.recent = [sample for sample in self.recent if sample.end > window.start]
        samples = defaultdict(list)
        clean = [None if local else slot for slot, local in zip(slots, mic)]
        first_bin = 0
        for slot, group in groupby(clean):
            head = first_bin
            first_bin += sum(1 for _ in group)
            if slot is None:
                continue
            end = first_bin
            first = max(head + CLEAN_GUARD, -window.start)
            last = min(end - CLEAN_GUARD, first + CLEAN_MAX)
            # Wait for the end of short turns. This avoids embedding longer
            # versions of the same speech in successive rolling windows.
            if last - first < CLEAN_MIN or (
                end == len(slots) and last - first < CLEAN_MAX
            ):
                continue
            a, b = first * BIN_FRAMES, last * BIN_FRAMES
            if (
                sum(system[first:last]) * 2 < last - first
                or window.known.count(1, a, b) * 100 < (b - a) * 98
            ):
                continue
            start, stop = window.start + first, window.start + last
            prior = [
                sample
                for sample in self.recent
                if sample.start < stop and start < sample.end
            ]
            if prior:
                samples[slot].extend(
                    sample
                    for sample in prior
                    if window.start + head <= sample.start
                    and sample.end <= window.start + end
                )
                continue
            vector = self.embedding.embedding(window.system[2 * a : 2 * b])
            if vector is not None:
                sample = CleanAnchor(start, stop, vector)
                self.recent.append(sample)
                samples[slot].append(sample)
        return samples

    def _match(self, start, raw, samples=None, *, final=False):
        votes = defaultdict(Counter)
        overlap_start = max(start, self.previous_start)
        overlap_end = min(start + len(raw), self.previous_start + len(self.previous))
        for tick in range(overlap_start, overlap_end):
            old = self.previous[tick - self.previous_start]
            new = raw[tick - start]
            if old is not None and new is not None:
                votes[new][old] += 1
        eligible = {}
        for slot, candidates in votes.items():
            ranks = candidates.most_common(2)
            if ranks[0][1] >= 20 and (
                len(ranks) == 1 or ranks[0][1] >= 3 * ranks[1][1]
            ):
                eligible[slot] = ranks[0][0]
        claims = Counter(eligible.values())
        mapping, fresh = {}, []
        for slot, count in Counter(raw).items():
            if slot is None:
                continue
            match = eligible.get(slot)
            if match is not None and claims[match] == 1:
                mapping[slot] = match
            elif count >= 20 and not any(hits >= 10 for hits in votes[slot].values()):
                fresh.append(slot)
        first = {}
        for index, slot in enumerate(raw, start):
            if slot is not None:
                first.setdefault(slot, index)
        if samples is not None:
            matched, novel = self.profiles.resolve(fresh, mapping, samples)
            mapping.update(matched)
        else:
            novel = fresh
        for slot in fresh:
            if slot in mapping or (
                slot not in novel
                and not final
                and start + len(raw) - first[slot] < FALLBACK_BINS
            ):
                continue
            speaker = mapping[slot] = self.next_speaker
            self.next_speaker += 1
            self.seed_until[speaker] = first[slot] + CLEAN_MIN
        if samples is not None:
            for slot, speaker in mapping.items():
                self.profiles.remember(
                    speaker,
                    samples.get(slot, ()),
                    seed_until=self.seed_until.get(speaker),
                    competitors=[
                        sample
                        for other, clips in samples.items()
                        if other != slot
                        for sample in clips
                    ],
                )
        tracked = tuple(mapping.get(slot) for slot in raw)
        # Keep earlier anchors through an inconclusive revision so a single
        # window cannot erase continuity for the next overlapping window.
        self.previous = tuple(
            speaker
            if speaker is not None or not overlap_start <= start + index < overlap_end
            else self.previous[start + index - self.previous_start]
            for index, speaker in enumerate(tracked)
        )
        self.previous_start = start
        self.seed_until = {
            speaker: end for speaker, end in self.seed_until.items() if end >= start
        }
        return tracked

    def analyze_mixed(self, window, recognizer):
        voices = recognizer.voices(window.pcm)
        active = [
            {voice.speaker for voice in voices if voice.start <= point < voice.end}
            for point in range(
                BIN_MS // 2, len(window.pcm) // (2 * BIN_FRAMES) * BIN_MS, BIN_MS
            )
        ]
        slots = [
            next(iter(speakers)) if len(speakers) == 1 else None for speakers in active
        ]
        tracked = self._match(window.start, slots)
        return [
            AMBIGUOUS if len(speakers) > 1 else speaker
            for speakers, speaker in zip(active, tracked)
        ]

    def analyze(
        self, window, recognizer, observe=None, *, final=False, remote_only=False
    ):
        count = len(window.known) // BIN_FRAMES
        mic = list(_activity(window.microphone, count, 260))
        system = list(_activity(window.system, count, 160))
        known = [
            window.known.count(1, i * BIN_FRAMES, (i + 1) * BIN_FRAMES)
            >= BIN_FRAMES // 2
            for i in range(count)
        ]
        voice = []
        if recognizer is not None and any(system):
            voice = recognizer.voices(window.system)
        slots = [_unique_voice(voice, i * BIN_MS + BIN_MS // 2) for i in range(count)]
        embedding = self.embedding
        lane = embedding if isinstance(embedding, ProfileInference) else None
        samples = {} if embedding is not None else None
        if embedding is not None and voice and (lane is None or not lane.is_set()):
            try:
                if lane is not None:
                    lane.prepare()
                samples = self._samples(window, slots, mic, system)
                if lane is not None and lane.is_set():
                    samples = {}
            except Exception as error:
                LOG.warning(
                    "Meeting speaker profiles unavailable (%s)", type(error).__name__
                )
                self.embedding = None
                self.recent.clear()
        remote = self._match(window.start, slots, samples, final=final)
        if observe is not None and voice:
            observe(window, voice, slots, remote)
        labels = []
        for i in range(count):
            # A guard interval covers clock skew and acoustic echo. Mixed
            # speech and possible echo have the same outcome: no assignment.
            local = sum(mic[max(0, i - 3) : i + 4]) >= 2
            nearby_system = system[max(0, i - 10) : i + 11]
            coverage = known[max(0, i - 10) : i + 11]
            if local and not remote_only:
                enough_coverage = len(coverage) == 21 and sum(coverage) >= 18
                label = (
                    LOCAL_MICROPHONE
                    if enough_coverage and not any(nearby_system)
                    else AMBIGUOUS
                )
            else:
                label = (
                    remote[i]
                    if known[i] and any(system[max(0, i - 3) : i + 4])
                    else None
                )
            labels.append(label)
        return labels


class SourceTimeline:
    """Revise attribution on the same time grid without retaining PCM."""

    def __init__(self, origin):
        self.origin = origin
        self.labels = {}

    def update(self, start, labels):
        self.labels.update(
            (i, speaker) for i, speaker in enumerate(labels, start) if i >= 0
        )
        # Cover active and recently finalized ASR blocks only.
        oldest = start + len(labels) - 75 * 1000 // BIN_MS
        self.labels = {i: speaker for i, speaker in self.labels.items() if i >= oldest}

    def turns(self, base, duration, text, tokens, *, source=None, timing_text=None):
        if not text:
            return []
        fallback = {"mic": LOCAL_MICROPHONE, "system": SYSTEM_AUDIO}.get(source)
        timing_text = (
            timing_text if timing_text and timing_text.startswith(text) else text
        )
        words = _timed_words(timing_text, tokens)
        offset = round((base - self.origin) * 1000)
        groups = []
        for position, start, end in words:
            if position >= len(text):
                break
            bins = range(
                (offset + start) // BIN_MS,
                (offset + min(end, start + 160) + 19) // BIN_MS,
            )
            votes = Counter(self.labels.get(i) for i in bins if source != "mic")
            known = [speaker for speaker in votes if speaker]
            speaker = (
                known[0]
                if not votes[AMBIGUOUS]
                and len(known) == 1
                and votes[known[0]] * 3 >= 2 * votes.total()
                else None
            )
            start_s = min(duration, base + start / 1000)
            # RNNT can extend the last token to the next emission or to EOF.
            # Stop a labeled turn at the last contiguous matching source bin.
            if speaker is not None:
                matching_end = max(i for i in bins if self.labels.get(i) == speaker) + 1
                while (
                    matching_end * BIN_MS < offset + end
                    and self.labels.get(matching_end) == speaker
                ):
                    matching_end += 1
                end = min(end, matching_end * BIN_MS - offset)
            elif source:
                speaker = fallback
                # A token can extend to the next emission, including silence.
                end = min(end, start + 1200)
            end_s = min(duration, base + end / 1000)
            if (
                groups
                and groups[-1][3] == speaker
                and (not source or start_s <= groups[-1][2] + 0.4)
            ):
                groups[-1][2] = end_s
            else:
                groups.append([position, start_s, end_s, speaker])
        if not groups and source:
            return [
                {
                    "start": base,
                    "end": duration,
                    "text": text,
                    "speaker": fallback,
                    "source": source,
                }
            ]
        if not any(group[3] is not None for group in groups):
            return []
        return [
            {
                "start": start,
                "end": end,
                "text": text[
                    position : groups[i + 1][0] if i + 1 < len(groups) else len(text)
                ].strip(),
                "speaker": speaker,
                **({"source": source} if source else {}),
            }
            for i, (position, start, end, speaker) in enumerate(groups)
        ]


class SourceSpeakerWorker:
    """Run whole-window Sortformer independently of live recognition."""

    def __init__(
        self,
        library,
        assets,
        next_speaker,
        context,
        abort,
        publish,
        failed,
        *,
        observe=None,
        embedding_assets=None,
        capture_end=None,
        remote_only=False,
    ):
        self.remote_only = remote_only
        self.jobs = queue.Queue(1)
        self.finished = threading.Event()
        self.labeling = SourceVoices(next_speaker, context)
        self.inference = (
            ProfileInference(embedding_assets, capture_end, abort)
            if embedding_assets is not None and capture_end is not None
            else None
        )
        self.thread = threading.Thread(
            target=self._run,
            args=(library, assets, abort, publish, failed, observe),
            name="MeetingSourceSpeakers",
            daemon=True,
        )
        self.thread.start()

    def submit(self, window):
        if window is None or self.finished.is_set():
            return
        try:
            self.jobs.get_nowait()
        except queue.Empty:
            pass
        self.jobs.put_nowait(window)

    def close(self):
        if self.inference is not None:
            self.inference.close()
        self.finished.set()
        self.thread.join()
        return (
            self.labeling.previous_start,
            self.labeling.previous,
            self.labeling.next_speaker,
            self.labeling.profiles,
        )

    def _run(self, library, assets, abort, publish, failed, observe):
        labeling = self.labeling
        with ExitStack() as stack:
            recognizer = None
            if assets is not None:
                try:
                    recognizer = stack.enter_context(
                        Sortformer.open(library, assets.verify(abort), abort)
                    )
                except Exception as error:
                    if not abort.is_set():
                        failed(error)
            inference = self.inference
            if (
                recognizer is not None
                and inference is not None
                and inference.assets.available()
            ):
                labeling.embedding = inference
                inference.prepare()
            try:
                while not abort.is_set():
                    try:
                        window = self.jobs.get(timeout=0.05)
                    except queue.Empty:
                        if self.finished.is_set() and self.jobs.empty():
                            return
                        continue
                    try:
                        labels = labeling.analyze(
                            window,
                            recognizer,
                            observe,
                            remote_only=self.remote_only,
                            final=self.finished.is_set()
                            or (inference is not None and inference.end.is_set()),
                        )
                    except Exception as error:
                        if abort.is_set():
                            return
                        failed(error)
                        stack.close()
                        recognizer = None
                        labels = labeling.analyze(
                            window, None, remote_only=self.remote_only
                        )
                    if not abort.is_set():
                        publish(window.start, labels)
            except Exception as error:
                if not abort.is_set():
                    failed(error)
            finally:
                if inference is not None:
                    inference.close()
                self.finished.set()


_MIXED_NATIVE_SLOT = threading.Lock()


class MixedCancellation:
    def __init__(self, pace):
        self.pace = pace
        self.job = None

    def is_set(self):
        return self.pace.is_set() or (
            self.job is not None and not self.pace.accepts(self.job)
        )


class MixedSpeakerWorker:
    """Own optional Windows inference without blocking the main ASR lane."""

    def __init__(
        self,
        library,
        assets,
        next_speaker,
        context,
        stopped,
        publish,
        failed,
        *,
        anchors=None,
    ):
        self.pace = SpeakerPace(stopped=stopped)
        self.unavailable = False
        labeling = SourceVoices(next_speaker, context)
        if anchors is not None:
            labeling.previous_start, labeling.previous, labeling.next_speaker = anchors
        self.thread = threading.Thread(
            target=self._run,
            args=(library, assets, labeling, publish, failed),
            name="MeetingMixedSpeakers",
            daemon=True,
        )
        self.thread.start()

    def _run(self, library, assets, labeling, publish, failed):
        pace = self.pace
        cancel = MixedCancellation(pace)
        consecutive_timeouts = 0
        with ExitStack() as owner, ExitStack() as native:
            path = recognizer = None
            try:
                while not pace.is_set():
                    job = pace.take()
                    if job is None:
                        continue
                    if not pace.accepts(job):
                        pace.complete(job)
                        continue
                    if path is None:
                        # A cancelled interval may still own its native session.
                        if not _MIXED_NATIVE_SLOT.acquire(blocking=False):
                            pace.complete(job, timed_out=True)
                            continue
                        owner.callback(_MIXED_NATIVE_SLOT.release)
                        # Verification shares the interval lifetime. An admitted
                        # job can lose its generation while verification runs.
                        path = assets.verify(pace)
                    cancel.job = job
                    timed_out = False
                    try:
                        if not pace.accepts(job):
                            continue
                        if recognizer is None:
                            recognizer = native.enter_context(
                                Sortformer.open(library, path, cancel)
                            )
                        if cancel.is_set():
                            continue
                        candidate = copy(labeling)
                        candidate.seed_until = labeling.seed_until.copy()
                        labels = candidate.analyze_mixed(job.window, recognizer)
                    except TimeoutError as error:
                        native.close()
                        recognizer = None
                        if not cancel.is_set():
                            timed_out = True
                            consecutive_timeouts += 1
                            if consecutive_timeouts == 2:
                                self.unavailable = True
                                failed(error)
                                return
                    except Exception:
                        if not cancel.is_set():
                            raise
                        native.close()
                        recognizer = None
                    else:
                        consecutive_timeouts = 0
                        if not cancel.is_set() and publish(
                            job,
                            labels,
                            (
                                candidate.previous_start,
                                candidate.previous,
                                candidate.next_speaker,
                            ),
                        ):
                            labeling = candidate
                    finally:
                        cancel.job = None
                        pace.complete(job, timed_out=timed_out)
            except Exception as error:
                if not pace.is_set():
                    self.unavailable = True
                    failed(error)
            finally:
                pace.close()
