"""Meeting lifecycle, session revalidation, cancellation and durable publication."""

import threading
import time
import json

from meeting_capture import MeetingCapture
from shared.meeting_contract import MAX_MEETING_SECONDS, MeetingError
from provider_http import CancellationToken


class MeetingWorkflow:
    def __init__(
        self,
        store,
        provider,
        *,
        source_factory,
        capture_factory=MeetingCapture,
        clock=time.monotonic,
        can_start=lambda: True,
    ):
        self.store, self.provider = store, provider
        self.source_factory, self.capture_factory, self.clock = (
            source_factory,
            capture_factory,
            clock,
        )
        self.can_start = can_start
        self._lock = threading.RLock()
        self._thread = None
        self._capture = None
        self._cancel = CancellationToken()
        self._stop = threading.Event()
        self._closed = False
        self._identity = None
        self.selected = ""
        self.phase = "idle"
        self.error = ""
        self.language = "auto"
        self._started = None
        self._duration = 0
        self._recovered = set()
        self._routes = None

    @property
    def active(self):
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def _check(self, expected):
        self._cancel.raise_if_cancelled()
        self.provider.validate(expected)

    def snapshot(self):
        identity = self.provider.identity()
        with self._lock:
            if not self.active and identity.owner not in self._recovered:
                self.store.recover(identity.owner)
                self._recovered.add(identity.owner)
            meetings = self.store.list(identity.owner)
            if self.selected not in {row["id"] for row in meetings}:
                self.selected = meetings[0]["id"] if meetings else ""
            selected = (
                self.store.get(identity.owner, self.selected) if self.selected else None
            )
            capture = self._capture
            duration = (
                int(self.clock() - self._started)
                if self.phase == "recording" and self._started is not None
                else self._duration
            )
            return {
                "phase": self.phase,
                "active": self.active,
                "error": self.error,
                "meetings": meetings,
                "selected": selected,
                "duration": duration,
                "sources": capture.snapshot() if capture else {},
                "managed": identity.managed,
                "context": identity.owner + ":" + str(identity.generation),
                "notesRoute": self.store.notes_route(identity.owner).__dict__,
            }

    def select(self, meeting_id):
        with self._lock:
            if self.active:
                return False
            self.store.get(self.provider.identity().owner, meeting_id)
            self.selected = meeting_id
            self.error = ""
            return True

    def _launch(self, action, meeting_id=None):
        with self._lock:
            if self.active or self._closed or not self.can_start():
                raise MeetingError("meeting.busy")
            self.provider.acquire()
            try:
                expected = self.provider.identity()
                persisted = None
                if meeting_id:
                    meeting = self.store.get(expected.owner, meeting_id)
                    persisted = json.loads(meeting["routes"])
                    self.language = meeting["language"]
                    self.selected = meeting_id
                self._routes = self.provider.snapshot(
                    expected, persisted or None, self.store.notes_route(expected.owner)
                )
                self._identity = expected
                self._cancel = CancellationToken()
                self._stop = threading.Event()
                self.error = ""
                self.phase = "starting"
                if action == "record":
                    self.selected = ""
                    self._capture = None
                self._thread = threading.Thread(
                    target=self._run,
                    args=(action, expected),
                    name="meeting-processing",
                    daemon=True,
                )
                self._thread.start()
            except Exception:
                self.provider.release()
                raise

    def start(self, title="", language="auto"):
        with self._lock:
            if self.active:
                raise MeetingError("meeting.busy")
            self.language = language
            # The worker creates the record only after acquiring the account
            # change guard and validating the route.
            self._title = title
            self._launch("record")

    def retry(self):
        self._launch("retry", self.selected)

    def summarize(self):
        self._launch("summary", self.selected)

    def stop(self):
        self._stop.set()
        with self._lock:
            capture = self._capture
        if capture:
            capture.stop()
            if self._started is not None and self.phase == "recording":
                self._duration = int(self.clock() - self._started)
                self.phase = "processing"

    def cancel(self):
        with self._lock:
            self._cancel.cancel()
            self._stop.set()
            capture = self._capture
        if capture:
            capture.stop()

    def shutdown(self):
        self._closed = True
        self.cancel()
        # Capture is already closed. The bounded HTTP call can finish late, but
        # its cancelled token cannot publish or remove retained audio.
        if self._thread:
            self._thread.join(timeout=0.2)

    def _process(self, expected, attempted):
        for chunk in self.store.get(expected.owner, self.selected)["chunks"]:
            if chunk["state"] not in {"pending", "failed"} or chunk["id"] in attempted:
                continue
            attempted.add(chunk["id"])
            self._check(expected)
            try:
                path = self.store.audio_path(self.selected, chunk["id"])
                if not path.is_file():
                    raise MeetingError("meeting.audio_damaged")
                # Failed uncertain requests reuse the same operation UUID.
                text = self.provider.transcribe(
                    expected, self._routes, chunk, path, self.language, self._cancel
                )
                self._check(expected)
                self.store.save_transcript(
                    expected.owner, self.selected, chunk["id"], text
                )
            except Exception as error:
                self._check(expected)
                code = (
                    error.code
                    if isinstance(error, MeetingError)
                    else "meeting.processing_error"
                )
                self.store.chunk_failed(
                    expected.owner,
                    self.selected,
                    chunk["id"],
                    code,
                    retry_operation=getattr(error, "retry_operation", False),
                )
                self.error = code
                if code in {
                    "meeting.sign_in",
                    "meeting.scope_changed",
                    "meeting.allowance",
                }:
                    raise

    def _run(self, action, expected):
        mid = ""
        try:
            self._check(expected)
            if action == "record":
                self.selected = mid = self.store.create(
                    expected.owner,
                    self._title,
                    language=self.language,
                    routes=self._routes.persisted() if self._routes else {},
                )["id"]
                self._started = self.clock()
                self._duration = 0
                self.phase = "recording"
                self._capture = self.capture_factory(
                    self.store, expected.owner, mid, source_factory=self.source_factory
                )
                self._capture.start()
                attempted = set()
                while not self._stop.wait(0.2):
                    self._check(expected)
                    if (
                        not self._capture.alive
                        or self.clock() - self._started >= MAX_MEETING_SECONDS
                    ):
                        break
                    self._process(expected, attempted)
                self._capture.stop()
                if self.phase == "recording":
                    self._duration = int(self.clock() - self._started)
                self.store.end(expected.owner, mid)
                self.phase = "processing"
                self._check(expected)
                self._process(expected, attempted)
            elif action == "retry":
                self.phase = "processing"
                self.store.prepare_retry(expected.owner, self.selected)
                self._process(expected, set())
            else:
                self.phase = "summarizing"
                operation, revision, source = self.store.summary_request(
                    expected.owner, self.selected
                )
                text = self.provider.summarize(
                    expected,
                    self._routes,
                    operation,
                    source,
                    self.language,
                    self._cancel,
                )
                self._check(expected)
                self.store.save_summary(expected.owner, self.selected, revision, text)
            self.phase = "stopped"
        except Exception as error:
            if self.phase == "recording" and self._started is not None:
                self._duration = int(self.clock() - self._started)
            if action == "summary" and getattr(error, "retry_operation", False):
                self.store.allow_summary_retry(expected.owner, self.selected)
            self.phase = "cancelled" if self._cancel.cancelled else "failed"
            self.error = (
                ""
                if self._cancel.cancelled
                else error.code
                if isinstance(error, MeetingError)
                else "meeting.processing_error"
            )
        finally:
            try:
                if self._capture:
                    self._capture.stop()
                if mid:
                    self.store.end(expected.owner, mid, self.phase)
            finally:
                self.provider.release()

    def save_notes(self, meeting_id, context, text):
        identity = self.provider.identity()
        if (
            context != identity.owner + ":" + str(identity.generation)
            or meeting_id != self.selected
        ):
            raise MeetingError("meeting.scope_changed")
        if self.active:
            self.provider.validate(self._identity)
        self.store.save_notes(identity.owner, meeting_id, text)

    def delete(self):
        if self.active:
            raise MeetingError("meeting.busy")
        self.store.delete(self.provider.identity().owner, self.selected)
        self.selected = ""

    def export(self):
        row = self.store.get(self.provider.identity().owner, self.selected)
        transcript = "\n".join(
            f"[{c['start_ms'] / 1000:.1f}s {c['source']}] {c['transcript']}"
            for c in row["chunks"]
            if c["state"] == "transcribed"
        )
        return {
            "title": row["title"],
            "notes": row["notes"],
            "summary": row["summary"],
            "transcript": transcript,
        }
