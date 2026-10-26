"""Transactional local meetings, explicitly scoped to a guest or account."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import json
import time
import uuid
import wave

from shared.meeting_contract import (
    MAX_NOTES_BYTES,
    MAX_SOURCE_BYTES,
    MAX_TRANSCRIPT_BYTES,
    MeetingError,
    bounded,
)

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE meetings (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
 created REAL NOT NULL, ended REAL, state TEXT NOT NULL,
 language TEXT NOT NULL DEFAULT 'auto', routes TEXT NOT NULL DEFAULT '{}',
 notes TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0,
 summary TEXT NOT NULL DEFAULT '', summary_revision INTEGER NOT NULL DEFAULT -1,
 summary_operation TEXT NOT NULL DEFAULT '', pending_revision INTEGER NOT NULL DEFAULT -1
);
CREATE INDEX meeting_owner_created ON meetings(owner, created DESC);
CREATE TABLE chunks (
 id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
 source TEXT NOT NULL, start_ms INTEGER NOT NULL, duration_ms INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL, transcript TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
 operation_id TEXT NOT NULL, retry_operation INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX meeting_chunks ON chunks(meeting_id, start_ms, source);
CREATE TABLE preferences (owner TEXT PRIMARY KEY, notes_route TEXT NOT NULL);
PRAGMA user_version=1;
"""


class MeetingStore:
    def __init__(self, directory, *, clock=time.time):
        self.directory = Path(directory)
        self.path = self.directory / "meetings.sqlite3"
        self.clock = clock
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            with self._connection() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise MeetingError("meeting.newer_schema")
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise MeetingError("meeting.store_error")
                if version == 0:
                    if db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchone():
                        raise MeetingError("meeting.store_error")
                    db.executescript("BEGIN IMMEDIATE;" + SCHEMA + "COMMIT;")
                # Refuse a structurally different early candidate instead of
                # treating its version marker as permission to write new data.
                db.execute(
                    "SELECT id,owner,title,created,ended,state,language,routes,notes,revision,summary,summary_revision,summary_operation,pending_revision FROM meetings LIMIT 0"
                )
                db.execute(
                    "SELECT id,meeting_id,source,start_ms,duration_ms,state,transcript,error,operation_id,retry_operation FROM chunks LIMIT 0"
                )
                db.execute("SELECT owner,notes_route FROM preferences LIMIT 0")
        except sqlite3.Error:
            raise MeetingError("meeting.store_error") from None

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        except sqlite3.Error:
            raise MeetingError("meeting.store_error") from None
        finally:
            db.close()

    @staticmethod
    def _owned(db, owner, meeting_id):
        row = db.execute(
            "SELECT * FROM meetings WHERE id=? AND owner=?", (meeting_id, owner)
        ).fetchone()
        if row is None:
            raise MeetingError("meeting.scope_changed")
        return row

    def create(self, owner, title="", *, language="auto", routes=None):
        if owner != "guest" and not (owner.startswith("account:") and len(owner) == 72):
            raise MeetingError("meeting.scope_changed")
        bounded(title, 512)
        meeting_id = str(uuid.uuid4())
        with self._connection() as db:
            db.execute(
                "INSERT INTO meetings(id,owner,title,created,state,language,routes) VALUES(?,?,?,?,?,?,?)",
                (
                    meeting_id,
                    owner,
                    title,
                    self.clock(),
                    "recording",
                    language,
                    json.dumps(routes or {}),
                ),
            )
        return self.get(owner, meeting_id)

    def list(self, owner, *, offset=0):
        with self._connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM meetings WHERE owner=? AND state!='deleting' ORDER BY created DESC,id DESC LIMIT 200 OFFSET ?",
                    (owner, max(0, int(offset))),
                )
            ]

    def count(self, owner):
        with self._connection() as db:
            return db.execute(
                "SELECT COUNT(*) FROM meetings WHERE owner=? AND state!='deleting'",
                (owner,),
            ).fetchone()[0]

    def get(self, owner, meeting_id):
        with self._connection() as db:
            row = dict(self._owned(db, owner, meeting_id))
            row["chunks"] = [
                dict(chunk)
                for chunk in db.execute(
                    "SELECT * FROM chunks WHERE meeting_id=? ORDER BY start_ms,source,id",
                    (meeting_id,),
                )
            ]
            row["summary_stale"] = (
                bool(row["summary"]) and row["summary_revision"] != row["revision"]
            )
            return row

    def audio_path(self, meeting_id, chunk_id):
        # UUID-only paths prevent a persisted relative path from escaping storage.
        meeting_id, chunk_id = str(uuid.UUID(meeting_id)), str(uuid.UUID(chunk_id))
        return self.directory / "audio" / meeting_id / (chunk_id + ".wav")

    def open_chunk(self, owner, meeting_id, source, start_ms):
        if source not in {"microphone", "system"} or start_ms < 0:
            raise MeetingError("meeting.capture_error")
        chunk_id = str(uuid.uuid4())
        with self._connection() as db:
            self._owned(db, owner, meeting_id)
            db.execute(
                "INSERT INTO chunks(id,meeting_id,source,start_ms,state,operation_id) VALUES(?,?,?,?,?,?)",
                (chunk_id, meeting_id, source, int(start_ms), "capturing", chunk_id),
            )
        path = self.audio_path(meeting_id, chunk_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        return chunk_id, path

    def finish_chunk(self, owner, meeting_id, chunk_id, duration_ms):
        with self._connection() as db:
            self._owned(db, owner, meeting_id)
            db.execute(
                "UPDATE chunks SET duration_ms=?,state='pending' WHERE id=? AND meeting_id=? AND state='capturing'",
                (int(duration_ms), chunk_id, meeting_id),
            )

    def chunk_failed(
        self,
        owner,
        meeting_id,
        chunk_id,
        code="meeting.processing_error",
        *,
        retry_operation=False,
    ):
        with self._connection() as db:
            self._owned(db, owner, meeting_id)
            db.execute(
                "UPDATE chunks SET state='failed',error=?,retry_operation=? WHERE id=? AND meeting_id=? AND state!='transcribed'",
                (code, int(retry_operation), chunk_id, meeting_id),
            )

    def prepare_retry(self, owner, meeting_id):
        with self._connection() as db:
            self._owned(db, owner, meeting_id)
            for row in db.execute(
                "SELECT id FROM chunks WHERE meeting_id=? AND state='failed' AND retry_operation=1",
                (meeting_id,),
            ).fetchall():
                db.execute(
                    "UPDATE chunks SET operation_id=?,retry_operation=0 WHERE id=?",
                    (str(uuid.uuid4()), row["id"]),
                )

    def allow_summary_retry(self, owner, meeting_id):
        with self._connection() as db:
            self._owned(db, owner, meeting_id)
            db.execute(
                "UPDATE meetings SET pending_revision=-1 WHERE id=?", (meeting_id,)
            )

    def notes_route(self, owner):
        from workflow_config import WorkflowRoute

        with self._connection() as db:
            row = db.execute(
                "SELECT notes_route FROM preferences WHERE owner=?", (owner,)
            ).fetchone()
            return (
                WorkflowRoute.from_mapping(json.loads(row[0]))
                if row
                else WorkflowRoute(enabled=False)
            )

    def save_notes_route(self, owner, route):
        from dataclasses import asdict

        with self._connection() as db:
            db.execute(
                "INSERT INTO preferences(owner,notes_route) VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET notes_route=excluded.notes_route",
                (owner, json.dumps(asdict(route))),
            )

    def save_transcript(self, owner, meeting_id, chunk_id, transcript):
        bounded(transcript, MAX_TRANSCRIPT_BYTES)
        with self._connection() as db:
            self._owned(db, owner, meeting_id)
            changed = db.execute(
                "UPDATE chunks SET state='transcribed',transcript=?,error='' WHERE id=? AND meeting_id=? AND state!='transcribed'",
                (transcript, chunk_id, meeting_id),
            ).rowcount
            if changed:
                db.execute(
                    "UPDATE meetings SET revision=revision+1 WHERE id=?", (meeting_id,)
                )
        # Only a confirmed committed transcript permits audio removal.
        try:
            self.audio_path(meeting_id, chunk_id).unlink(missing_ok=True)
            return True
        except OSError:
            # Keep the committed reference so recovery can finish this cleanup.
            return False

    def save_notes(self, owner, meeting_id, notes):
        bounded(notes, MAX_NOTES_BYTES)
        with self._connection() as db:
            if self._owned(db, owner, meeting_id)["state"] == "deleting":
                raise MeetingError("meeting.delete_pending")
            db.execute(
                "UPDATE meetings SET notes=?,revision=revision+1 WHERE id=? AND notes!=?",
                (notes, meeting_id, notes),
            )

    def end(self, owner, meeting_id, state="stopped"):
        with self._connection() as db:
            self._owned(db, owner, meeting_id)
            db.execute(
                "UPDATE meetings SET state=?,ended=COALESCE(ended,?) WHERE id=?",
                (state, self.clock(), meeting_id),
            )

    def summary_request(self, owner, meeting_id):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._owned(db, owner, meeting_id)
            chunks = db.execute(
                "SELECT source,start_ms,transcript FROM chunks WHERE meeting_id=? AND state='transcribed' ORDER BY start_ms,source,id",
                (meeting_id,),
            ).fetchall()
            transcript = "\n".join(
                f"[{c['start_ms'] / 1000:.1f}s {c['source']}] {c['transcript']}"
                for c in chunks
            )
            source = "TRANSCRIPT\n" + transcript + "\nPERSONAL NOTES\n" + row["notes"]
            bounded(source, MAX_SOURCE_BYTES)
            if not transcript.strip() and not row["notes"].strip():
                raise MeetingError("meeting.no_source")
            operation = (
                row["summary_operation"]
                if row["pending_revision"] == row["revision"]
                else str(uuid.uuid4())
            )
            db.execute(
                "UPDATE meetings SET summary_operation=?,pending_revision=? WHERE id=?",
                (operation, row["revision"], meeting_id),
            )
            return operation, row["revision"], source

    def save_summary(self, owner, meeting_id, revision, text):
        bounded(text, MAX_SOURCE_BYTES)
        with self._connection() as db:
            self._owned(db, owner, meeting_id)
            changed = db.execute(
                "UPDATE meetings SET summary=?,summary_revision=? WHERE id=? AND owner=? AND revision=?",
                (text, revision, meeting_id, owner, revision),
            ).rowcount
            if not changed:
                raise MeetingError("meeting.summary_changed")

    def recover(self, owner):
        """Recover this scope only; never upload or reassign local records."""
        cleanup_pending = False
        with self._connection() as db:
            meetings = [
                dict(row)
                for row in db.execute(
                    "SELECT id,state FROM meetings WHERE owner=?", (owner,)
                )
            ]
        for meeting in meetings:
            if meeting["state"] == "deleting":
                try:
                    self.delete(owner, meeting["id"])
                except (OSError, MeetingError):
                    cleanup_pending = True
                continue
            if meeting["state"] == "recording":
                self.end(owner, meeting["id"], "interrupted")
            for chunk in self.get(owner, meeting["id"])["chunks"]:
                path = self.audio_path(meeting["id"], chunk["id"])
                if chunk["state"] == "transcribed":
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        cleanup_pending = True
                elif chunk["state"] == "capturing":
                    try:
                        with wave.open(str(path)) as audio:
                            duration = audio.getnframes() * 1000 // audio.getframerate()
                        if duration < 1:
                            raise ValueError()
                        self.finish_chunk(owner, meeting["id"], chunk["id"], duration)
                    except (OSError, EOFError, ValueError, wave.Error):
                        self.chunk_failed(
                            owner, meeting["id"], chunk["id"], "meeting.audio_damaged"
                        )
        return cleanup_pending

    def delete(self, owner, meeting_id):
        meeting = self.get(owner, meeting_id)
        with self._connection() as db:
            self._owned(db, owner, meeting_id)
            db.execute("UPDATE meetings SET state='deleting' WHERE id=?", (meeting_id,))
        try:
            for chunk in meeting["chunks"]:
                self.audio_path(meeting_id, chunk["id"]).unlink(missing_ok=True)
        except OSError:
            raise MeetingError("meeting.delete_pending") from None
        with self._connection() as db:
            self._owned(db, owner, meeting_id)
            db.execute(
                "DELETE FROM meetings WHERE id=? AND state='deleting'", (meeting_id,)
            )
