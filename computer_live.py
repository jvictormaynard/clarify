"""Peer-owned PCM transport; ComputerHost owns durable admission and publication."""

import base64
import hashlib
import io
import threading
import time
import wave

from computer_host import _APIError, _digest, _json, _uuid
from connect.webrtc.live import LiveRecognition
from provider_types import TranscriptionResult


def _wav(pcm):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "none"))
        stream.writeframes(pcm)
    return output.getvalue()


class _Session:
    def __init__(self, work, metadata, fingerprint):
        self.work = work
        self.metadata = metadata
        self.fingerprint = fingerprint
        self.lock = threading.RLock()
        self.ready = threading.Event()
        self.finish = threading.Event()
        self.done = threading.Event()
        self.response = None
        self.live = None
        self.pcm = bytearray()
        self.partial = ""
        self.sent_partial = ""
        self.started = time.monotonic()


class ComputerLivePeer:
    """Bounded peer resources, never a second operation or publication registry.

    Frames are copied PCM16 mono at 16 kHz, at most 80 ms. A finish request
    supplies the SHA256 and byte count of all captured PCM. Replays must use
    the same metadata and digest. Unsupported routes retain explicit WAV use.
    """

    def __init__(self, host):
        self.host = host
        self.lock = threading.RLock()
        self.sessions = {}
        self.closed = False

    def __call__(self, authorization, action, operation_id, body=None):
        try:
            if not isinstance(authorization, str):
                raise _APIError(400, "invalid_request")
            device = self.host._authenticate(authorization)
            operation = _uuid(operation_id)
            key = (device, operation)
            if action == "cancel":
                self.host._cancel(*key)
                return {"status": 200, "body": {"cancelled": True}}
            with self.lock:
                if self.closed:
                    raise _APIError(410, "peer_closed")
                session = self.sessions.get(key)
                if action == "start":
                    if (
                        not isinstance(body, dict)
                        or len(_json(body)) > 4096
                        or "audio_wav" in body
                        or "operation_id" in body
                    ):
                        raise _APIError(400, "invalid_request")
                    metadata = {**body, "operation_id": operation}
                    # Reuse wire preference validation without claiming dummy audio.
                    self.host._validated(
                        "dictations",
                        {
                            **metadata,
                            "audio_wav": base64.b64encode(_wav(b"\0\0")).decode(),
                        },
                    )
                    fingerprint = _digest(
                        _json({"route": "live_pcm16_16000", **metadata})
                    )
                    if session:
                        if fingerprint != session.fingerprint:
                            raise _APIError(409, "operation_conflict")
                        raise _APIError(
                            409,
                            "operation_in_progress"
                            if not session.done.is_set()
                            else "session_unavailable",
                        )
                    if len(self.sessions) >= 4096:
                        raise _APIError(429, "session_limit")
                    work, prepared, cached = self.host._admit(
                        device,
                        "dictations",
                        metadata,
                        operation,
                        fingerprint,
                        live=True,
                    )
                    if work is None:
                        raise _APIError(409, "session_unavailable")
                    session = _Session(work, metadata, fingerprint)
                    self.sessions[key] = session
                    session.worker = threading.Thread(
                        target=self._run,
                        args=(key, session, prepared),
                        name="computer-live",
                    )
                    try:
                        session.worker.start()
                    except Exception:
                        self.sessions.pop(key)

                        def failed_start():
                            raise RuntimeError("Live worker could not start")

                        self.host._execute(
                            device,
                            "dictations",
                            metadata,
                            operation,
                            metadata["language"],
                            None,
                            work,
                            prepared,
                            recognize=failed_start,
                        )
                elif session is None:
                    raise _APIError(409, "session_unavailable")
            if action == "start":
                if not session.ready.wait(5):
                    self.host._cancel(*key)
                    raise _APIError(503, "not_ready")
                if session.done.is_set():
                    if session.response["status"] == 200:
                        raise _APIError(409, "session_unavailable")
                    return session.response
                return {
                    "status": 200,
                    "body": {
                        "started": True,
                        "format": "pcm16_mono_16000",
                        "max_frame_bytes": 2560,
                        "max_batch_frames": 8,
                    },
                }
            with session.lock:
                if session.work.token.cancelled:
                    raise _APIError(409, "operation_cancelled")
                if action == "feed":
                    if session.finish.is_set() or session.done.is_set():
                        raise _APIError(409, "session_unavailable")
                    frames = (
                        body.get("frames")
                        if isinstance(body, dict) and set(body) == {"frames"}
                        else [body]
                    )
                    if not isinstance(frames, list) or not 1 <= len(frames) <= 8:
                        raise ValueError("invalid_frame_batch")
                    decoded = []
                    for offset, frame in enumerate(frames):
                        if (
                            not isinstance(frame, dict)
                            or set(frame) != {"sequence", "data"}
                            or type(frame["sequence"]) is not int
                            or frame["sequence"] != session.live.sequence + offset
                            or not isinstance(frame["data"], str)
                            or len(frame["data"]) > 3416
                        ):
                            raise ValueError("invalid_frame")
                        data = base64.b64decode(frame["data"], validate=True)
                        if not 0 < len(data) <= 2560 or len(data) % 2:
                            raise ValueError("invalid_pcm_frame")
                        decoded.append((frame["sequence"], data))
                    if (
                        session.live.total_bytes + sum(len(data) for _, data in decoded)
                        > 9600000
                    ):
                        raise ValueError("recording_too_large")
                    for sequence, data in decoded:
                        session.live.feed(sequence, data)
                        session.pcm.extend(data)
                    reply = {"accepted": decoded[-1][0]}
                    partial = session.partial
                    if partial != session.sent_partial:
                        reply["partial"] = partial
                        session.sent_partial = partial
                    return {"status": 200, "body": reply}
                if action == "partial":
                    if session.done.is_set():
                        raise _APIError(409, "session_unavailable")
                    return {"status": 200, "body": {"partial": session.partial}}
                if action != "finish":
                    raise _APIError(400, "invalid_action")
                if (
                    not isinstance(body, dict)
                    or set(body) != {"sha256", "bytes"}
                    or type(body["bytes"]) is not int
                ):
                    raise ValueError("invalid_digest")
                if session.finish.is_set():
                    if body != session.finish_metadata:
                        raise _APIError(409, "operation_conflict")
                else:
                    if (
                        body
                        != {
                            "sha256": session.live.digest.hexdigest(),
                            "bytes": session.live.total_bytes,
                        }
                        or not session.live.total_bytes
                    ):
                        raise ValueError("digest_mismatch")
                    session.finish_metadata = body.copy()
                    session.finish.set()
            if not session.done.wait(40):
                self.host._cancel(*key)
                raise _APIError(409, "operation_cancelled")
            with self.lock:
                if self.closed:
                    raise _APIError(410, "peer_closed")
                with self.host._lock:
                    self.host._authenticate(authorization)
                    if (
                        session.work.token.cancelled
                        or session.work.generation is not self.host._generation
                    ):
                        raise _APIError(409, "operation_cancelled")
                    if session.response["status"] != 200:
                        return session.response
                    row = self.host._db.execute(
                        "SELECT content_hash,state FROM operations WHERE device_id=? AND operation_id=?",
                        key,
                    ).fetchone()
                    return {
                        "status": 200,
                        "body": self.host._cached(key, row, session.fingerprint),
                    }
        except _APIError as error:
            return {"status": error.status, "body": {"error": error.code}}
        except Exception:
            if "session" in locals() and session is not None:
                session.work.token.cancel()
            return {"status": 400, "body": {"error": "invalid_live_request"}}

    def _run(self, key, session, prepared):
        def recognize():
            try:
                return recognize_and_process()
            finally:
                if session.live:
                    session.live.session.cancel()
                    native = session.live.session
                    if hasattr(native, "worker"):
                        native.worker.join()

        def recognize_and_process():
            session.work.token.raise_if_cancelled()
            engine = self.host.processor.live_engine(prepared)

            def partial(result):
                # One cumulative snapshot; no output side effect or unbounded queue.
                session.partial = result.text

            session.live = LiveRecognition(
                engine,
                session.metadata["language"],
                admitted=True,
                cancel_event=session.work.token._event,
                on_partial=partial,
            )
            session.ready.set()
            while not session.finish.wait(0.05):
                session.work.token.raise_if_cancelled()
                if time.monotonic() - session.started > 300:
                    session.work.token.cancel()
            session.work.token.raise_if_cancelled()
            final = session.live.finish()
            # Native receipt is in milliseconds. Verify its complete sample
            # duration and the digest of the exact immutable frames fed to it.
            if (
                abs(final.received_seconds * 32000 - session.finish_metadata["bytes"])
                >= 32
                or session.live.digest.hexdigest() != session.finish_metadata["sha256"]
                or hashlib.sha256(session.pcm).hexdigest()
                != session.finish_metadata["sha256"]
            ):
                raise ValueError("consumed_pcm_mismatch")
            return self.host.processor.process_dictation(
                _wav(session.pcm),
                session.metadata["language"],
                session.work.token,
                prepared=prepared,
                pretranscribed=TranscriptionResult(
                    final.text, "local_asr", "nemotron-3.5-streaming"
                ),
            )

        try:
            self.host._execute(
                key[0],
                "dictations",
                session.metadata,
                key[1],
                session.metadata["language"],
                None,
                session.work,
                prepared,
                recognize=recognize,
            )
            session.response = {"status": 200}
        except _APIError as error:
            session.response = {"status": error.status, "body": {"error": error.code}}
        finally:
            if session.live:
                session.live.session.cancel()
                native = session.live.session
                if hasattr(native, "worker"):
                    native.worker.join()
            with session.lock:
                session.live = None
                session.pcm.clear()
                session.partial = ""
                session.done.set()
                session.ready.set()

    def close(self):
        with self.lock:
            self.closed = True
            sessions = list(self.sessions.values())
            for session in sessions:
                if not session.done.is_set():
                    session.work.token.cancel()
        for session in sessions:
            session.worker.join()
