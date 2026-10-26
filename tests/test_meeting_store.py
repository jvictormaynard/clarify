import sqlite3
from contextlib import closing
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from shared.meeting_contract import MeetingError
from meeting_store import MeetingStore


class MeetingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MeetingStore(self.temp.name, clock=lambda: 100)
        self.meeting = self.store.create("guest", "Fixture")
        self.mid = self.meeting["id"]

    def chunk(self):
        cid, path = self.store.open_chunk("guest", self.mid, "system", 1200)
        with wave.open(str(path), "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * 16000)
        self.store.finish_chunk("guest", self.mid, cid, 1000)
        return cid, path

    def test_scope_is_required_for_every_read_and_write(self):
        other = "account:" + "a" * 64
        self.assertEqual(self.store.list(other), [])
        for action in (
            lambda: self.store.get(other, self.mid),
            lambda: self.store.save_notes(other, self.mid, "bad"),
            lambda: self.store.delete(other, self.mid),
        ):
            with self.assertRaises(MeetingError):
                action()
        self.assertEqual(self.store.get("guest", self.mid)["notes"], "")

    def test_transcript_commit_precedes_audio_delete_and_retry_is_idempotent(self):
        cid, path = self.chunk()
        self.store.chunk_failed("guest", self.mid, cid)
        self.assertTrue(path.exists())
        self.store.save_transcript("guest", self.mid, cid, "Source")
        self.assertFalse(path.exists())
        self.store.save_transcript("guest", self.mid, cid, "Changed retry")
        saved = self.store.get("guest", self.mid)
        self.assertEqual(saved["chunks"][0]["transcript"], "Source")
        self.assertEqual(saved["revision"], 1)

    def test_failed_database_commit_keeps_audio(self):
        cid, path = self.chunk()
        with patch.object(
            self.store, "_owned", side_effect=MeetingError("meeting.store_error")
        ):
            with self.assertRaises(MeetingError):
                self.store.save_transcript("guest", self.mid, cid, "source")
        self.assertTrue(path.exists())

    def test_notes_summary_and_revision_are_independent(self):
        self.store.save_notes("guest", self.mid, "My note")
        op, revision, source = self.store.summary_request("guest", self.mid)
        self.assertIn("My note", source)
        self.assertEqual(op, self.store.summary_request("guest", self.mid)[0])
        self.store.save_summary("guest", self.mid, revision, "Previous summary")
        self.store.save_notes("guest", self.mid, "Later note")
        with self.assertRaises(MeetingError):
            self.store.save_summary("guest", self.mid, revision, "Late summary")
        saved = self.store.get("guest", self.mid)
        self.assertEqual(saved["notes"], "Later note")
        self.assertEqual(saved["summary"], "Previous summary")
        self.assertTrue(saved["summary_stale"])
        self.assertNotEqual(op, self.store.summary_request("guest", self.mid)[0])

    def test_recovery_finalizes_partial_wav_and_freezes_end_time(self):
        cid, path = self.chunk()
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute("UPDATE chunks SET state='capturing'")
        self.store.recover("guest")
        saved = self.store.get("guest", self.mid)
        self.assertEqual(saved["state"], "interrupted")
        self.assertEqual(saved["chunks"][0]["duration_ms"], 1000)
        self.assertEqual(saved["chunks"][0]["state"], "pending")
        self.assertTrue(path.exists())
        self.store.clock = lambda: 200
        self.store.end("guest", self.mid)
        self.assertEqual(self.store.get("guest", self.mid)["ended"], 100)

    def test_summary_compare_and_update_rejects_a_concurrent_notes_commit(self):
        self.store.save_notes("guest", self.mid, "original")
        _, revision, _ = self.store.summary_request("guest", self.mid)
        self.store.save_summary("guest", self.mid, revision, "previous summary")
        owned = self.store._owned

        def notes_commit(db, owner, meeting_id):
            row = owned(db, owner, meeting_id)
            with closing(sqlite3.connect(self.store.path)) as concurrent, concurrent:
                concurrent.execute(
                    "UPDATE meetings SET notes='new note',revision=revision+1 WHERE id=?",
                    (meeting_id,),
                )
            return row

        with patch.object(self.store, "_owned", side_effect=notes_commit):
            with self.assertRaises(MeetingError):
                self.store.save_summary("guest", self.mid, revision, "stale result")
        saved = self.store.get("guest", self.mid)
        self.assertEqual(saved["notes"], "new note")
        self.assertEqual(saved["summary"], "previous summary")

    def test_newer_or_corrupt_database_is_not_replaced(self):
        for raw in (b"broken database", None):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "meetings.sqlite3"
                if raw:
                    path.write_bytes(raw)
                else:
                    with closing(sqlite3.connect(path)) as db, db:
                        db.execute("PRAGMA user_version=100")
                original = path.read_bytes()
                with self.assertRaises(MeetingError):
                    MeetingStore(directory)
                self.assertEqual(path.read_bytes(), original)
