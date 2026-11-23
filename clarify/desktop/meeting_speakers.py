"""Bounded, meeting-local speaker attribution with the pinned Sortformer model."""

from __future__ import annotations

from array import array
from collections import Counter, defaultdict
from contextlib import contextmanager
import ctypes as C
from dataclasses import dataclass
import os
from pathlib import Path
import queue
import re
import sys
import tempfile
import threading
import time

from local_asr import LocalASRCancelledError, ManifestAsset, _sha256
from local_asr_live import Load, RATE, _check

REVISION = "60ebab3ef7cae9869be0abcde13360347e96ba03"
REPOSITORY = (
    "https://huggingface.co/handy-computer/diar_streaming_sortformer_4spk-v2.1-gguf"
)
MODEL = ManifestAsset(
    "speakers",
    "diar_streaming_sortformer_4spk-v2.1-Q8_0.gguf",
    f"{REPOSITORY}/resolve/{REVISION}/diar_streaming_sortformer_4spk-v2.1-Q8_0.gguf",
    139_310_336,
    "a5dacdc650790266c7a362e54e6bf51952015487edaa606c4e11632bc32442a9",
    "NVIDIA Open Model License",
    f"{REPOSITORY}/tree/{REVISION}",
)

WINDOW_SECONDS = 20
CONTEXT_SECONDS = 8
CONTEXT_BYTES = 2 * RATE * CONTEXT_SECONDS


class SpeakerAssets:
    def __init__(self, folder: Path, installer, *, model=MODEL, revision=REVISION):
        self.model = model
        self.path = folder / revision / model.filename
        self.installer = installer

    def available(self):
        try:
            return self.path.stat().st_size == self.model.size
        except OSError:
            return False

    def install(self, progress, cancel):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=self.path.parent, prefix=".install-"
        ) as tmp:
            staged = Path(tmp) / self.model.filename
            self.installer._download(self.model, staged, progress, cancel)
            if cancel.is_set():
                raise LocalASRCancelledError("Meeting model installation cancelled")
            os.replace(staged, self.path)

    def verify(self, cancel):
        if (
            not self.available()
            or _sha256(self.path, cancel_check=cancel.is_set) != self.model.sha256
        ):
            raise ValueError("Invalid meeting model")
        return self.path


class _SessionParams(C.Structure):
    _fields_ = [("size", C.c_uint64), ("threads", C.c_int32)]


class _Segment(C.Structure):
    _fields_ = [
        ("size", C.c_uint64),
        ("start", C.c_int64),
        ("end", C.c_int64),
        ("speaker", C.c_int32),
        ("confidence", C.c_float),
    ]


_ABORT = C.CFUNCTYPE(C.c_bool, C.c_void_p)


@dataclass(frozen=True)
class Voice:
    start: int
    end: int
    speaker: int


class Sortformer:
    def __init__(self, lib, model, session):
        self.lib, self.model, self.session = lib, model, session
        self.deadline = float("inf")

    @classmethod
    @contextmanager
    def open(cls, lib, path, cancel):
        pointer = C.c_void_p
        for name, args, result in (
            ("diarize_session_params_init", [C.POINTER(_SessionParams)], None),
            (
                "diarize_session_init",
                [pointer, C.POINTER(_SessionParams), C.POINTER(pointer)],
                C.c_int,
            ),
            ("diarize_session_free", [pointer], None),
            ("diarize_set_abort_callback", [pointer, _ABORT, pointer], None),
            ("diarize_run", [pointer, C.POINTER(C.c_float), C.c_int, pointer], C.c_int),
            ("diarize_n_segments", [pointer], C.c_int),
            ("speaker_segment_init", [C.POINTER(_Segment)], None),
            ("diarize_get_segment", [pointer, C.c_int, C.POINTER(_Segment)], C.c_int),
        ):
            function = getattr(lib, "transcribe_" + name)
            function.argtypes, function.restype = args, result
        model, session = pointer(), pointer()
        load = Load()
        lib.transcribe_model_load_params_init(C.byref(load))
        load.backend = 4  # CPU_ACCEL
        try:
            _check(
                lib.transcribe_model_load_file(
                    os.fsencode(path), C.byref(load), C.byref(model)
                )
            )
            params = _SessionParams()
            lib.transcribe_diarize_session_params_init(C.byref(params))
            params.threads = 2
            _check(
                lib.transcribe_diarize_session_init(
                    model, C.byref(params), C.byref(session)
                )
            )
            instance = cls(lib, model, session)
            abort = _ABORT(
                lambda _: cancel.is_set() or time.monotonic() >= instance.deadline
            )
            lib.transcribe_diarize_set_abort_callback(session, abort, None)
            yield instance
        finally:
            if session.value:
                lib.transcribe_diarize_session_free(session)
            if model.value:
                lib.transcribe_model_free(model)

    def voices(self, pcm):
        values = array("h")
        values.frombytes(pcm)
        if sys.byteorder != "little":
            values.byteswap()
        normalized = (C.c_float * len(values))(*(sample / 32768 for sample in values))
        # Leave room for microphone packets queued while this optional pass runs.
        self.deadline = time.monotonic() + 4
        status = self.lib.transcribe_diarize_run(
            self.session, normalized, len(values), None
        )
        if time.monotonic() >= self.deadline:
            raise TimeoutError("Speaker attribution exceeded its capture budget")
        _check(status)
        result = []
        for i in range(self.lib.transcribe_diarize_n_segments(self.session)):
            row = _Segment()
            self.lib.transcribe_speaker_segment_init(C.byref(row))
            _check(
                self.lib.transcribe_diarize_get_segment(self.session, i, C.byref(row))
            )
            if row.speaker > 0 and row.end > row.start:
                result.append(Voice(row.start, row.end, row.speaker))
        return result


def _unique_voice(voices, point):
    found = {voice.speaker for voice in voices if voice.start <= point < voice.end}
    return next(iter(found)) if len(found) == 1 else None


def _timed_words(text, tokens):
    # Nemotron returns timestamped raw token pieces. Reassemble their UTF-8 bytes
    # before checking that the displayed text and the timing table agree.
    offsets = []
    compact = bytearray()
    for token in tokens:
        chunk = bytes(byte for byte in token.text if byte not in b" \t\r\n")
        compact.extend(chunk)
        offsets.extend([(token.start, token.end)] * len(chunk))
    words = list(re.finditer(r"\S+", text))
    if b"".join(word[0].encode("utf-8") for word in words) != compact:
        return []
    cursor = 0
    result = []
    for word in words:
        end = cursor + len(word[0].encode("utf-8"))
        start_ms, end_ms = offsets[cursor][0], offsets[end - 1][1]
        if end_ms <= start_ms:
            return []
        result.append((word.start(), start_ms, end_ms))
        cursor = end
    return result


class MeetingVoices:
    """Match source IDs only where consecutive windows share actual speech."""

    def __init__(self, recognizer, next_speaker):
        self.recognizer = recognizer
        self.next_speaker = next_speaker
        self.tail = b""
        self.previous = []
        self.last_end = None

    def label(self, pcm, base, duration, text, tokens):
        if self.last_end != base:
            self.tail, self.previous = b"", []
        self.last_end = duration
        offset = len(self.tail) * 1000 // (2 * RATE)
        audio = self.tail + pcm
        voices = self.recognizer.voices(audio)
        counts = defaultdict(Counter)
        for point in range(10, offset, 20):
            old = _unique_voice(self.previous, point)
            new = _unique_voice(voices, point)
            if old is not None and new is not None:
                counts[new][old] += 20
        observed = dict.fromkeys(
            voice.speaker for voice in voices if voice.end > offset
        )
        eligible = {}
        for speaker, candidates in counts.items():
            ranks = candidates.most_common()
            if (
                ranks
                and ranks[0][1] >= 400
                and (len(ranks) == 1 or ranks[0][1] >= 3 * ranks[1][1])
            ):
                eligible[speaker] = ranks[0][0]
        claims = Counter(eligible.values())
        mapping = {}
        for speaker in observed:
            match = eligible.get(speaker)
            if match is not None and claims[match] == 1:
                mapping[speaker] = match
            else:
                mapping[speaker] = self.next_speaker
                self.next_speaker += 1
        self.tail = bytes(audio[-CONTEXT_BYTES:])
        tail_start = (len(audio) - len(self.tail)) * 1000 // (2 * RATE)
        self.previous = [
            Voice(
                max(0, voice.start - tail_start),
                voice.end - tail_start,
                mapping[voice.speaker],
            )
            for voice in voices
            if voice.end > tail_start and voice.speaker in mapping
        ]

        words = _timed_words(text, tokens)
        if not words:
            return []
        groups = []
        for position, start, end in words:
            # RNNT punctuation and final tokens can extend into a silent gap.
            # Attribute near the onset and require a unique voice in that area.
            votes = Counter(
                _unique_voice(voices, offset + point)
                for point in range(start + 10, min(end, start + 200), 20)
            )
            if not votes or set(votes) == {None}:
                near = {
                    voice.speaker
                    for voice in voices
                    if voice.start < offset + start + 100
                    and voice.end > offset + start - 100
                }
                votes = Counter({next(iter(near)) if len(near) == 1 else None: 1})
            speaker, count = votes.most_common(1)[0]
            if count * 2 <= votes.total():
                speaker = None
            label = mapping.get(speaker)
            start_s = min(duration, base + start / 1000)
            end_s = min(duration, base + end / 1000)
            if groups and groups[-1][3] == label:
                groups[-1][2] = end_s
            else:
                groups.append([position, start_s, end_s, label])
        return (
            [
                {
                    "start": start,
                    "end": end,
                    "text": text[
                        position : groups[index + 1][0]
                        if index + 1 < len(groups)
                        else len(text)
                    ].strip(),
                    "speaker": speaker,
                }
                for index, (position, start, end, speaker) in enumerate(groups)
            ]
            if any(group[3] is not None for group in groups)
            else []
        )


class SpeakerWorker:
    """An optional pass with at most one waiting window. Audio never waits for it."""

    def __init__(self, library, assets, resume, next_speaker, abort, publish, failed):
        self.abort = abort
        self.jobs = queue.Queue(1)
        self.finished = threading.Event()
        self.labeling = None
        self.thread = threading.Thread(
            target=self._run,
            args=(library, assets, resume, next_speaker, publish, failed),
            name="MeetingSpeakers",
            daemon=True,
        )
        self.thread.start()

    def submit(self, pcm, start, end, text, tokens):
        if self.finished.is_set() or self.abort.is_set() or not tokens:
            return
        try:
            self.jobs.put_nowait((pcm, start, end, text, tokens))
        except queue.Full:
            # The plain transcript remains available for this window. Its
            # absence resets overlap matching at the next window we process.
            pass

    def close(self):
        self.finished.set()
        self.thread.join()
        labeling = self.labeling
        if labeling is None:
            return ()
        return (
            labeling.tail,
            labeling.previous,
            labeling.next_speaker,
            labeling.last_end,
        )

    def _run(self, library, assets, resume, next_speaker, publish, failed):
        try:
            path = assets.verify(self.abort)
            with Sortformer.open(library, path, self.abort) as recognizer:
                labeling = self.labeling = MeetingVoices(recognizer, next_speaker)
                if resume:
                    labeling.tail, labeling.previous, saved_next, labeling.last_end = (
                        resume
                    )
                    labeling.next_speaker = max(saved_next, next_speaker)
                while not self.abort.is_set():
                    try:
                        pcm, start, end, text, tokens = self.jobs.get(timeout=0.05)
                    except queue.Empty:
                        if self.finished.is_set() and self.jobs.empty():
                            return
                        continue
                    turns = labeling.label(pcm, start, end, text, tokens)
                    if turns and not self.abort.is_set():
                        publish(start, end, text, turns)
        except Exception as error:
            self.labeling = None
            if not self.abort.is_set():
                failed(error)
        finally:
            self.finished.set()
