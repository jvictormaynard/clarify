"""Bounded, opt-in recovery of overlapping speech on the macOS system track."""

from collections import defaultdict, deque
from dataclasses import dataclass
import ctypes as C
from difflib import SequenceMatcher
from itertools import combinations, groupby
import logging
import os
import queue
import threading
import time

from local_asr import ManifestAsset
from local_asr_live import MAX_CHUNK, RATE

try:
    from .meeting_speakers import _timed_words
except ImportError:
    from meeting_speakers import _timed_words

LOG = logging.getLogger(__name__)

REVISION = "abd8b1268dfded6b0e972ddae4c2dd6a3faf4f8a"
REPOSITORY = "https://huggingface.co/ipsilondev/MossFormer2-SS-16K-ONNX"
MODEL = ManifestAsset(
    "overlap",
    "model.int8.onnx",
    f"{REPOSITORY}/resolve/{REVISION}/model.int8.onnx",
    90_943_046,
    "1776c854784a2400feb7582ac4e9f922073cd706cb4fd216c98abad937d642b1",
    "Apache-2.0",
    f"{REPOSITORY}/tree/{REVISION}",
)
EMBEDDING_REVISION = "ff1ac5bca8ef11e90662b879aa923979e0bd277b"
EMBEDDING_REPOSITORY = "https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34"
EMBEDDING_MODEL = ManifestAsset(
    "overlap-speakers",
    "voxceleb_resnet34.onnx",
    f"{EMBEDDING_REPOSITORY}/resolve/{EMBEDDING_REVISION}/voxceleb_resnet34.onnx",
    26_534_127,
    "9fea6516d7ad6bf0a76c7689f5a49b65d330fad6dde96c91bb4435ffbfe056a1",
    "CC BY 4.0",
    f"{EMBEDDING_REPOSITORY}/tree/{EMBEDDING_REVISION}",
)
MAX_PENDING = 2
MAX_ARCHIVE_BATCHES = 2
CACHE_SECONDS = 75
MAX_CLIP_MS = 3600
MAX_SECONDS = 20
STRIDE_SECONDS = 0.8
BIN_MS = 20
BIN_FRAMES = RATE * BIN_MS // 1000


@dataclass(frozen=True)
class OverlapRange:
    start: float
    end: float


@dataclass(frozen=True)
class OverlapClip(OverlapRange):
    pcm: bytes
    fringes: tuple = ()
    anchors: tuple = ()


class OverlapCandidates:
    """Keep only verified excerpts and their mixed transcript blocks in memory."""

    def __init__(self):
        self.clips = []
        self.blocks = {}
        self.pairs = {}
        self.archive = deque(maxlen=MAX_ARCHIVE_BATCHES)
        self.anchors = {}
        self.revision = 0
        self.handled_ms = 0
        self.retired_before = 0.0
        self.dropped = 0

    def _remember_anchors(self, base, window, slots, tracked):
        # Retain three short, distinct clean turns for each of four recent IDs.
        # The references and the separated signals never leave memory.
        self.anchors = {
            speaker: [item for item in items if item[1] >= base - 20]
            for speaker, items in self.anchors.items()
        }
        for (slot, speaker), bins in groupby(
            enumerate(zip(slots, tracked)), key=lambda item: item[1]
        ):
            bins = list(bins)
            if not slot or not speaker or len(bins) < 54:
                continue
            first, last = bins[0][0] + 4, bins[-1][0] - 3
            last = min(last, first + 120)
            start, end = base + first * 0.02, base + last * 0.02
            a, b = first * BIN_FRAMES, last * BIN_FRAMES
            if window.known.count(1, a, b) < (b - a) * 0.98:
                continue
            items = self.anchors.setdefault(speaker, [])
            overlaps = [item for item in items if item[0] < end and start < item[1]]
            if any(item[1] - item[0] >= end - start - 0.02 for item in overlaps):
                continue
            items[:] = [item for item in items if item not in overlaps]
            items.append((start, end, window.system[2 * a : 2 * b]))
            items.sort(key=lambda item: item[1])
            del items[:-3]
        self.anchors = dict(
            sorted(
                ((speaker, items) for speaker, items in self.anchors.items() if items),
                key=lambda group: group[1][-1][1],
            )[-4:]
        )

    def observe(self, origin, window, voices, recent_blocks, slots=(), tracked=()):
        base_ms = round(origin * 1000) + window.start * BIN_MS
        base = origin + window.start * BIN_MS / 1000
        self._remember_anchors(base, window, slots, tracked)
        ids = {slot: speaker for slot, speaker in zip(slots, tracked) if speaker}
        found = []
        pairs = sorted(
            (
                max(left.start, right.start),
                min(left.end, right.end),
                left.speaker,
                right.speaker,
            )
            for left, right in combinations(voices, 2)
            if left.speaker != right.speaker
            and min(left.end, right.end) - max(left.start, right.start) >= 400
        )
        for first, last, left, right in pairs:
            cursor = self.handled_ms - base_ms
            if last - max(first, cursor) < 400:
                continue
            begin = max(first - 350, cursor)
            if begin < 0 and last - first >= MAX_CLIP_MS:
                begin = 0
            end = min(last + 250, begin + MAX_CLIP_MS)
            start_frame, end_frame = begin * RATE // 1000, end * RATE // 1000
            if (
                begin < 0
                or window.start * BIN_MS + begin < 0
                or end_frame > len(window.known)
                or window.known.count(1, start_frame, end_frame)
                < (end_frame - start_frame) * 0.95
                or any(
                    voice.speaker not in (left, right)
                    and voice.start < end
                    and voice.end > begin
                    for voice in voices
                )
            ):
                continue
            self.handled_ms = base_ms + end
            if len(self.clips) >= MAX_PENDING:
                self.dropped += 1
                continue
            start, stop = base + begin / 1000, base + end / 1000
            speakers = (ids.get(left), ids.get(right))
            fringes = []
            references = ()
            if all(speakers) and speakers[0] != speakers[1]:
                for i in range((begin + BIN_MS - 1) // BIN_MS, end // BIN_MS):
                    # Use only bins strictly inside one voice and outside the
                    # other. Energy and lane margins are checked after separation.
                    if i >= len(slots) or tracked[i] not in speakers:
                        continue
                    a, b = i * BIN_FRAMES, (i + 1) * BIN_FRAMES
                    if window.known.count(1, a, b) == BIN_FRAMES:
                        fringes.append((tracked[i], a - start_frame, b - start_frame))
                references = tuple(
                    (
                        speaker,
                        tuple(
                            pcm
                            for _, pcm in sorted(
                                (
                                    (max(start - tail, head - stop), pcm)
                                    for head, tail, pcm in self.anchors.get(speaker, ())
                                    if (
                                        start - 25 <= tail <= start
                                        or stop <= head <= stop + 25
                                    )
                                ),
                                key=lambda sample: sample[0],
                            )[:2]
                        ),
                    )
                    for speaker in speakers
                )
            clip = OverlapClip(
                start,
                stop,
                window.system[2 * start_frame : 2 * end_frame],
                tuple(fringes),
                references,
            )
            self.clips.append(clip)
            found.append(clip)
            for block in recent_blocks:
                self.remember(block)
        return found

    def complete(self, clip, pair):
        if clip not in self.clips:
            return False
        self.clips.remove(clip)
        if not pair:
            return False
        span = OverlapRange(clip.start, clip.end)
        self.pairs[span.start] = (span, pair)
        self.revision += 1
        return True

    def discard(self, clip):
        if clip in self.clips:
            self.clips.remove(clip)
            self.dropped += 1

    def clear_interval(self):
        self.dropped += len(self.clips)
        self.clips.clear()
        self.pairs.clear()
        self.blocks.clear()
        self.archive.clear()
        # Bounded clean references can still support IDs matched on Resume.

    def retire(self, before):
        """Detach stable text from its rolling snapshots for the next save."""
        if before > self.retired_before:
            self.retired_before = before
            self.handled_ms = max(self.handled_ms, round(before * 1000))
            for clip in self.clips[:]:
                if clip.start < before:
                    self.discard(clip)
            closed = {
                start: block
                for start, block in self.blocks.items()
                if block.end <= before
            }
            affected = [
                (span, pair)
                for span, pair in self.pairs.values()
                if any(_intersects(span, block) for block in closed.values())
                or (
                    span.end <= before
                    and not any(
                        _intersects(span, block) for block in self.blocks.values()
                    )
                )
            ]
            # Validate both original blocks when a clip crosses a boundary.
            # Retain its range for the newer block until that block closes.
            if affected:
                retiring = {span.start for span, _ in affected}
                valid = [
                    (span, pair)
                    for span, pair in _projectable(self.pairs.values(), self.blocks)
                    if span.start in retiring
                ]
            else:
                valid = []
            if view := _view(valid, closed):
                self.archive.append(view)
            self.blocks = {
                start: block
                for start, block in self.blocks.items()
                if start not in closed
            }
            for span, pair in affected:
                if (span, pair) not in valid or not any(
                    _intersects(span, block) for block in self.blocks.values()
                ):
                    del self.pairs[span.start]
        return self.archived_view()

    def archived_view(self):
        view = None
        for batch in self.archive:
            view = merge_views(view, batch)
        return view

    def remember(self, block):
        if any(_intersects(span, block) for span in self.clips) or self.pairs_for(
            block
        ):
            self.blocks[block.start] = block

    def pairs_for(self, block):
        return [
            (span, pair)
            for span, pair in self.pairs.values()
            if _intersects(span, block)
        ]

    def project(self, block):
        if block is None or not block.text or not (affected := self.pairs_for(block)):
            return None
        return _project(block, affected)

    def view(self, pairs=None):
        if pairs is None:
            pairs = self.pairs.values()
        return merge_views(self.archived_view(), _view(pairs, self.blocks))


def pressure_normal():
    """Read Darwin's current memory-pressure level without starting a process."""
    try:
        sysctl = C.CDLL(None).sysctlbyname
        sysctl.argtypes = [
            C.c_char_p,
            C.c_void_p,
            C.POINTER(C.c_size_t),
            C.c_void_p,
            C.c_size_t,
        ]
        sysctl.restype = C.c_int
        level = C.c_int()
        size = C.c_size_t(C.sizeof(level))
        return (
            sysctl(
                b"kern.memorystatus_vm_pressure_level",
                C.byref(level),
                C.byref(size),
                None,
                0,
            )
            == 0
            and level.value == 1
        )
    except (AttributeError, OSError):
        return False


class RecoveryBudget:
    def __init__(self, *cancel):
        self.cancel = cancel
        self.deadline = time.monotonic() + MAX_SECONDS

    def remaining(self):
        return max(0, self.deadline - time.monotonic())

    def is_set(self):
        return any(event.is_set() for event in self.cancel) or not self.remaining()


def _open_onnx(path, threads):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.enable_mem_pattern = False
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return ort, ort.InferenceSession(
        str(path), options, providers=["CPUExecutionProvider"]
    )


def _fringe_speakers(clip, tracks):
    import numpy as np

    signals = [
        np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        for pcm in (clip.pcm, *tracks)
    ]
    wins = defaultdict(list)
    for speaker, start, end in clip.fringes:
        mix, *lanes = [signal[start:end].copy() for signal in signals]
        mix -= mix.mean()
        norm = np.linalg.norm(mix)
        if norm < 240 * np.sqrt(len(mix)):
            continue
        scores = []
        for lane in lanes:
            lane -= lane.mean()
            scale = float(np.linalg.norm(lane) * norm)
            scores.append(abs(float(mix @ lane)) / scale if scale else 0)
        best = int(scores[1] > scores[0])
        if scores[best] >= 0.65 and scores[best] - scores[1 - best] >= 0.25:
            wins[speaker].append(best)
    labels = [None, None]
    for speaker, lanes in wins.items():
        if len(lanes) >= 4 and all(lane == lanes[0] for lane in lanes):
            if labels[lanes[0]] is not None:
                return (None, None)
            labels[lanes[0]] = speaker
    return tuple(labels)


def _match_embeddings(scores, speakers):
    # Require independent evidence on both lanes and a one-to-one assignment.
    best = [max(range(len(speakers)), key=row.__getitem__) for row in scores]
    if len(set(best)) != 2:
        return (None, None)
    for lane, owner in enumerate(best):
        score = scores[lane][owner]
        alternate = max(value for i, value in enumerate(scores[lane]) if i != owner)
        if score < 0.45 or score - max(alternate, scores[1 - lane][owner]) < 0.15:
            return (None, None)
    return tuple(speakers[index] for index in best)


class SpeakerEmbedding:
    def __init__(self, path):
        import numpy as np

        _, self.session = _open_onnx(path, 1)
        self.np = np
        self.window = np.hamming(400).astype(np.float32)
        hz = np.arange(256) * (RATE / 512)

        def mel(frequency):
            return 1127 * np.log1p(frequency / 700)

        edges = np.linspace(mel(20), mel(RATE / 2), num=82)
        lower, peak, upper = edges[:-2], edges[1:-1], edges[2:]
        frequencies = mel(hz)[:, None]
        self.filters = np.maximum(
            0,
            np.minimum(
                (frequencies - lower) / (peak - lower),
                (upper - frequencies) / (upper - peak),
            ),
        ).astype(np.float32)

    def embedding(self, pcm):
        np = self.np
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        if len(audio) < 400:
            return None
        frames = np.lib.stride_tricks.sliding_window_view(audio, 400)[::160].copy()
        frames -= frames.mean(axis=1, keepdims=True)
        energy = np.mean(frames**2, axis=1)
        voiced = frames[energy >= max(160**2, float(np.max(energy)) * 0.0016)]
        if len(voiced) < 45:
            return None
        voiced[:, 1:] -= 0.97 * voiced[:, :-1]
        voiced[:, 0] *= 0.03
        power = abs(np.fft.rfft(voiced * self.window, 512, axis=1)[:, :256]) ** 2
        features = np.log(np.maximum(power @ self.filters, np.finfo(np.float32).eps))
        features -= features.mean(axis=0)
        result = self.session.run(["embs"], {"feats": features[None]})[0][0]
        scale = np.linalg.norm(result)
        return result / scale if np.isfinite(scale) and scale > 0 else None

    def match(self, anchors, tracks, budget):
        refs, speakers = [], []
        for speaker, clips in anchors:
            vectors = [self.embedding(clip) for clip in clips if not budget.is_set()]
            if len(vectors) != 2 or any(vector is None for vector in vectors):
                return (None, None)
            reference = sum(vectors)
            scale = self.np.linalg.norm(reference)
            if not scale:
                return (None, None)
            refs.append(reference / scale)
            speakers.append(speaker)
        lanes = [self.embedding(pcm) for pcm in tracks if not budget.is_set()]
        if len(lanes) != 2 or any(lane is None for lane in lanes) or budget.is_set():
            return (None, None)
        return _match_embeddings(
            [[float(lane @ ref) for ref in refs] for lane in lanes], speakers
        )


class Separator:
    def __init__(self, path):
        # The Windows runtime does not include these optional macOS dependencies.
        import numpy as np

        self.ort, self.session = _open_onnx(path, min(6, os.cpu_count() or 2))
        if [
            (node.name, node.shape, node.type) for node in self.session.get_inputs()
        ] != [("inputs", ["N", "sequence_length"], "tensor(float)")] or [
            (node.name, node.shape, node.type) for node in self.session.get_outputs()
        ] != [
            ("spk0", ["N", "sequence_length"], "tensor(float)"),
            ("spk1", ["N", "sequence_length"], "tensor(float)"),
        ]:
            raise ValueError("Unexpected overlap model input or output")
        self.np = np

    def separate(self, pcm, budget):
        np = self.np
        mix = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        if not 0 < len(mix) <= MAX_CLIP_MS * RATE // 1000 or budget.is_set():
            return ()
        run = self.ort.RunOptions()
        done = threading.Event()

        def cancel_run():
            while not done.wait(0.05):
                if budget.is_set() or not pressure_normal():
                    run.terminate = True
                    return

        watcher = threading.Thread(
            target=cancel_run, name="MeetingOverlapCancel", daemon=True
        )
        watcher.start()
        try:
            tracks = self.session.run(["spk0", "spk1"], {"inputs": mix[None, :]}, run)
        finally:
            done.set()
            watcher.join()
        if budget.is_set() or any(
            track.shape != (1, len(mix)) or not np.isfinite(track).all()
            for track in tracks
        ):
            return ()

        def rms(samples):
            return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))

        powers = [rms(track) for track in tracks]
        if min(powers) <= max(1e-10, max(powers) * 0.08):
            return ()
        target = rms(mix)
        streams = []
        for track, power in zip(tracks, powers):
            gain = min(target / power, 8, 0.98 / float(np.max(np.abs(track))))
            streams.append(np.rint(track * gain * 32768).astype("<i2").tobytes())
        return streams


def _decode(open_session, language, pcm, budget, clip):
    live = open_session(language, None)
    try:
        for start in range(0, len(pcm), MAX_CHUNK):
            live.feed(
                pcm[start : start + MAX_CHUNK],
                timeout=budget.remaining(),
                cancel_event=budget,
            )
        result = live.finish(timeout=budget.remaining(), cancel_event=budget)
    finally:
        live.cancel()
        # The native worker keeps its engine session until native code returns.
        # Optional recovery must release the meeting even if that takes longer.
        live.done.wait(timeout=budget.remaining() if not budget.is_set() else 0)
    text = result.text.strip()
    if len(text.split()) < 3 or not result.tokens:
        return None
    start = min(clip.end, clip.start + result.tokens[0].start / 1000)
    end = min(clip.end, clip.start + result.tokens[-1].end / 1000)
    if not clip.start <= start < end:
        return None
    return {"start": start, "end": end, "text": text, "overlap": True}


def _word(value):
    return "".join(char for char in value.casefold() if char.isalnum())


def _words(text):
    return [_word(word) for word in text.split()]


def _repeated(words, other):
    """Find a repeated clause, with room for one ASR word error at either edge."""
    best = SequenceMatcher(None, words, other, autojunk=False).find_longest_match()
    if best.size < 3 or best.size * 2 < len(other):
        return range(0)
    first, last = best.a, best.a + best.size
    before, after = best.b - 1, best.b + best.size
    if (
        first > 0
        and before >= 0
        and SequenceMatcher(None, words[first - 1], other[before]).ratio() >= 0.7
    ):
        first -= 1
    if (
        last < len(words)
        and after < len(other)
        and SequenceMatcher(None, words[last], other[after]).ratio() >= 0.7
    ):
        last += 1
    return range(first, last)


def _project(block, recovered):
    # Resolve word positions against the mixed transcript before pruning repeated
    # text. The original text and speaker turns remain in the database.
    timed = _timed_words(block.text, block.tokens)
    if not timed:
        return None
    words = block.text.split()
    normalized = [_word(word) for word in words]
    if len(timed) != len(words):
        return None
    turns = block.turns or [
        {"start": block.start, "end": block.end, "text": block.text}
    ]
    if [word for turn in turns for word in turn["text"].split()] != words:
        return None
    omit = set()
    for clip, pair in recovered:
        # Timestamp emissions can lag the PCM. Text agreement is also required.
        first = next(
            (
                i
                for i, (_, start, _) in enumerate(timed)
                if block.start + start / 1000 >= clip.start
            ),
            len(words),
        )
        last = next(
            (
                i
                for i in range(first, len(words))
                if block.start + timed[i][1] / 1000 >= clip.end + 0.4
            ),
            len(words),
        )
        for turn in pair:
            omit.update(
                first + i
                for i in _repeated(normalized[first:last], _words(turn["text"]))
            )
    if not omit:
        return turns
    result = []
    offset = 0
    for turn in turns:
        stop = offset + len(turn["text"].split())
        if omit.isdisjoint(range(offset, stop)):
            result.append(turn)
        else:
            if turn.get("speaker") == -1:
                return None
            # Keep the same labels on surviving phrases at their original times.
            start = offset
            while start < stop:
                if start in omit:
                    start += 1
                    continue
                end = start + 1
                while end < stop and end not in omit:
                    end += 1
                text_end = len(block.text) if end == len(words) else timed[end][0]
                start_time = max(turn["start"], block.start + timed[start][1] / 1000)
                end_time = min(turn["end"], block.start + timed[end - 1][2] / 1000)
                if end_time <= start_time:
                    return None
                result.append(
                    {
                        **turn,
                        "start": start_time,
                        "end": end_time,
                        "text": block.text[timed[start][0] : text_end].strip(),
                    }
                )
                start = end
        offset = stop
    return result


def _recover_clip(separator, embedding, open_session, language, budget, clip):
    streams = separator.separate(clip.pcm, budget)
    if len(streams) != 2 or budget.is_set() or not pressure_normal():
        return None
    pair = [_decode(open_session, language, pcm, budget, clip) for pcm in streams]
    if not all(pair):
        return None
    left, right = pair
    if (
        min(left["end"], right["end"]) - max(left["start"], right["start"]) < 0.2
        or SequenceMatcher(None, _words(left["text"]), _words(right["text"])).ratio()
        >= 0.65
    ):
        return None
    speakers = (None, None)
    if clip.fringes:
        speakers = _fringe_speakers(clip, streams)
    if not all(speakers) and embedding is not None and len(clip.anchors) == 2:
        matched = embedding.match(clip.anchors, streams, budget)
        if all(not known or known == match for known, match in zip(speakers, matched)):
            speakers = matched
    for turn, speaker in zip(pair, speakers):
        if speaker:
            turn["speaker"] = speaker
    return pair if not budget.is_set() and pressure_normal() else None


def merge_views(saved, current):
    if not saved or not current:
        return current or saved
    turns = {
        (turn["start"], turn["end"], turn["text"]): turn
        for turn in saved["turns"] + current["turns"]
    }
    return {
        "turns": list(turns.values()),
        "blocks": saved["blocks"] | current["blocks"],
    }


def _intersects(span, block):
    return span.start < block.end and block.start < span.end


def _projectable(recovered, blocks):
    compatible = [
        (span, pair)
        for span, pair in recovered
        if all(
            _project(block, [(span, pair)]) is not None
            for block in blocks.values()
            if _intersects(span, block)
        )
    ]
    # Reject conflicts in their own block. A risky projection here must
    # leave other blocks and their recovered speech available.
    while compatible:
        for block in blocks.values():
            affected = [
                (span, pair) for span, pair in compatible if _intersects(span, block)
            ]
            if len(affected) > 1 and _project(block, affected) is None:
                rejected = {span.start for span, _ in affected}
                compatible = [
                    (span, pair)
                    for span, pair in compatible
                    if span.start not in rejected
                ]
                break
        else:
            break
    return compatible


def _view(recovered, blocks):
    recovered = _projectable(recovered, blocks)
    if not recovered:
        return None
    replacements = {}
    for start, block in blocks.items():
        affected = [
            (clip, pair)
            for clip, pair in recovered
            if clip.start < block.end and block.start < clip.end
        ]
        if affected:
            rows = _project(block, affected)
            if rows is None:
                return None
            if len(rows) != 1 or rows[0]["text"] != block.text or block.turns:
                replacements[str(start)] = rows
    return {
        "turns": [turn for _, pair in recovered for turn in pair],
        "blocks": replacements,
    }


def open_speaker_embedding(assets, budget):
    if assets and assets.available() and not budget.is_set():
        try:
            return SpeakerEmbedding(assets.verify(budget))
        except Exception as error:
            if not budget.is_set():
                LOG.warning(
                    "Meeting speaker model unavailable (%s)",
                    type(error).__name__,
                )
    return None


def recover(candidates, assets, open_session, language, budget, embedding_assets=None):
    """Finish unresolved clips after Stop with a bounded, text-only projection."""
    pending = candidates.clips[:]
    if not pending or budget.is_set() or not pressure_normal():
        return candidates.view()
    separator = Separator(assets.verify(budget))
    embedding = open_speaker_embedding(embedding_assets, budget)
    pairs = dict(candidates.pairs)
    for clip in pending:
        if budget.is_set() or not pressure_normal():
            break
        pair = _recover_clip(separator, embedding, open_session, language, budget, clip)
        if pair:
            pairs[clip.start] = (OverlapRange(clip.start, clip.end), pair)
    return candidates.view(pairs.values())


class LiveRecovery:
    """Warm one worker, hold one private model, and never wait on a producer."""

    def __init__(self, decoder, assets, embedding_assets, language, abort, complete):
        self.jobs = queue.Queue(MAX_PENDING)
        self.lock = threading.Lock()
        self.outstanding = 0
        self.abort = abort
        self.cancel = threading.Event()
        self.finished = threading.Event()
        self.closed = threading.Event()
        self.thread = threading.Thread(
            target=self._run,
            args=(decoder, assets, embedding_assets, language, complete),
            name="MeetingLiveOverlap",
            daemon=True,
        )
        self.thread.start()

    def submit(self, clip):
        with self.lock:
            if (
                self.closed.is_set()
                or self.abort.is_set()
                or self.outstanding >= MAX_PENDING
            ):
                return False
            self.jobs.put_nowait(clip)
            self.outstanding += 1
            return True

    def close(self, *, drain=False):
        with self.lock:
            self.closed.set()
            if not drain:
                self.cancel.set()

    def _run(self, decoder, assets, embedding_assets, language, complete):
        budget = warm = RecoveryBudget(self.abort, self.cancel)
        stage = "separator setup"
        try:
            if warm.is_set() or not pressure_normal():
                return
            separator = Separator(assets.verify(warm))
            embedding = open_speaker_embedding(embedding_assets, warm)
            if warm.is_set() or not pressure_normal():
                return
            stage = "decoder setup"
            with decoder(warm) as open_session:
                stage = "inference"
                while not self.abort.is_set() and not self.cancel.is_set():
                    try:
                        clip = self.jobs.get(timeout=0.05)
                    except queue.Empty:
                        if self.closed.is_set() and self.jobs.empty():
                            return
                        continue
                    pair = None
                    budget = RecoveryBudget(self.abort, self.cancel)
                    try:
                        if not budget.is_set() and pressure_normal():
                            pair = _recover_clip(
                                separator,
                                embedding,
                                open_session,
                                language,
                                budget,
                                clip,
                            )
                    except Exception as error:
                        if not budget.is_set() and pressure_normal():
                            LOG.warning(
                                "Meeting overlap inference failed (%s)",
                                type(error).__name__,
                            )
                    with self.lock:
                        self.outstanding -= 1
                    if not self.abort.is_set() and not self.cancel.is_set():
                        complete(clip, pair if not budget.is_set() else None)
                    del clip
        except Exception as error:
            if not budget.is_set() and pressure_normal():
                LOG.warning(
                    "Meeting overlap %s failed (%s)", stage, type(error).__name__
                )
        finally:
            self.close(drain=True)
            # A setup failure leaves queued clips unprocessed. The controller
            # still owns those clips and can retry with a new worker.
            while True:
                try:
                    self.jobs.get_nowait()
                except queue.Empty:
                    break
            self.finished.set()
