"""Meeting export uses fixture accounts, files and a fake clipboard only."""

import tempfile
import threading
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QSaveFile, QUrl
from PySide6.QtWidgets import QApplication

from clarify.desktop.qml_meetings import create_qml_meetings
from clarify_account import AccountService
from secret_store import PlaintextFileSecretStore
from shared.localization import translate


class MeetingExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.account = AccountService(
            self.root, secrets=PlaintextFileSecretStore(self.root / "secrets.json")
        )
        self.clipboard = Mock()
        runtime = SimpleNamespace(
            account=self.account,
            dictionary_service=Mock(),
            provider_registry=Mock(metadata=()),
            repositories=Mock(),
            copy_result=self.clipboard,
            scheduler=SimpleNamespace(run_dispatch=lambda cb: cb()),
        )
        self.controller = create_qml_meetings(
            runtime, can_start=lambda: True, workflow_config=Mock()
        )
        self.addCleanup(self.controller.shutdown)
        self.workflow = self.controller.workflow
        self.store = self.workflow.store
        self.controller.activate()

    def session(self, user_id=None):
        # Simulate only the local completion/invalidation boundary of login.
        # No browser, HTTP, token, credential or real account is used.
        with self.account._lock:
            self.account._state.pop("user_id", None)
            self.account._state.pop("mode", None)
            if user_id:
                self.account._state.update(user_id=user_id, mode="hosted")
            self.account._generation += 1

    def meeting(self, text):
        owner = self.workflow.provider.identity().owner
        mid = self.store.create(owner, text)["id"]
        self.store.save_notes(owner, mid, text)
        self.store.end(owner, mid)
        self.workflow.selected = mid
        self.controller.refresh()
        return mid, self.controller.state["context"]

    def export(self, mid, context, path):
        return self.controller.exportFile(
            mid, context, QUrl.fromLocalFile(str(path)).toString()
        )

    def test_session_change_never_creates_or_overwrites_a_file(self):
        user = str(uuid.uuid4())
        for before, after in ((None, user), (user, None), (user, user)):
            with self.subTest(before=before, after=after):
                self.session(before)
                mid, context = self.meeting("Original export")
                # Covers a pending social login completing after the guest
                # dialog, logout to guest, and a new session for the same user.
                self.session(after)
                self.meeting("Never redirect to this meeting")
                missing = self.root / "missing.md"
                existing = self.root / "existing.md"
                existing.write_text("Keep this file", encoding="utf-8")
                with patch("clarify.desktop.qml_meetings.QSaveFile") as writer:
                    self.assertFalse(self.export(mid, context, missing))
                    self.assertFalse(self.export(mid, context, existing))
                    writer.assert_not_called()
                self.assertFalse(missing.exists())
                self.assertEqual(existing.read_text(encoding="utf-8"), "Keep this file")

    def test_selection_change_exports_only_original_id_and_stale_metadata(self):
        mid, context = self.meeting("Original personal note")
        owner = self.workflow.provider.identity().owner
        _, revision, _ = self.store.summary_request(owner, mid)
        self.store.save_summary(owner, mid, revision, "Previous summary")
        self.store.save_notes(owner, mid, "Original personal note changed")
        other, _ = self.meeting("Other selected personal note")
        output = self.root / "original.md"
        self.assertTrue(self.export(mid, context, output))
        text = output.read_text(encoding="utf-8")
        self.assertIn("Original personal note changed", text)
        self.assertIn("Previous summary", text)
        self.assertIn(translate("meeting.summary_stale"), text)
        self.assertNotIn("Other selected personal note", text)
        self.assertEqual(self.workflow.selected, other)

    def test_session_is_revalidated_when_acquiring_guard_before_file_creation(self):
        mid, context = self.meeting("Original export")
        publication = self.workflow.provider.publication

        @contextmanager
        def changed_before_guard(expected):
            self.session(str(uuid.uuid4()))
            with publication(expected):
                yield

        with patch.object(self.workflow.provider, "publication", changed_before_guard):
            with patch("clarify.desktop.qml_meetings.QSaveFile") as writer:
                self.assertFalse(self.export(mid, context, self.root / "late.md"))
                writer.assert_not_called()

    def test_export_rejects_id_from_another_owner_before_writing(self):
        self.session(str(uuid.uuid4()))
        account_mid, _ = self.meeting("Account-only material")
        self.session()
        _, guest_context = self.meeting("Guest material")
        with patch("clarify.desktop.qml_meetings.QSaveFile") as writer:
            self.assertFalse(
                self.export(account_mid, guest_context, self.root / "wrong.md")
            )
            writer.assert_not_called()

    def test_account_guard_covers_atomic_file_commit(self):
        mid, context = self.meeting("Original export")
        entered, changed = threading.Event(), threading.Event()

        def change_session():
            entered.set()
            self.session(str(uuid.uuid4()))
            changed.set()

        worker = threading.Thread(target=change_session)
        output = self.root / "guarded.md"
        file = QSaveFile(str(output))

        def commit():
            worker.start()
            self.assertTrue(entered.wait(1))
            self.assertFalse(changed.wait(0.05))
            return file.commit()

        wrapper = Mock(wraps=file)
        wrapper.commit.side_effect = commit
        with patch("clarify.desktop.qml_meetings.QSaveFile", return_value=wrapper):
            self.assertTrue(self.export(mid, context, output))
        worker.join(2)
        self.assertTrue(changed.is_set())
        self.assertIn("Original export", output.read_text(encoding="utf-8"))

    def test_failed_atomic_commit_preserves_existing_file(self):
        mid, context = self.meeting("Original export")
        output = self.root / "existing.md"
        output.write_text("Keep this file", encoding="utf-8")
        file = QSaveFile(str(output))
        wrapper = Mock(wraps=file)
        wrapper.commit.return_value = False
        with patch("clarify.desktop.qml_meetings.QSaveFile", return_value=wrapper):
            self.assertFalse(self.export(mid, context, output))
        # The wrapper kept the native QSaveFile alive. Finish its cancelled
        # transaction and prove the failed path cannot publish its bytes.
        self.assertFalse(file.commit())
        self.assertEqual(output.read_text(encoding="utf-8"), "Keep this file")

    def test_queued_copy_is_not_redirected_or_published_after_session_change(self):
        mid, _ = self.meeting("Original copy")
        callbacks = []
        self.controller._dispatch = callbacks.append
        self.assertTrue(self.controller.copy())
        self.session(str(uuid.uuid4()))
        self.meeting("Never copy this account")
        callbacks.pop(0)()
        self.clipboard.assert_not_called()
        self.assertEqual(self.controller.state["error"], "meeting.scope_changed")

    def test_queued_copy_keeps_original_id_after_selection_change(self):
        self.meeting("Original copy")
        callbacks = []
        self.controller._dispatch = callbacks.append
        self.assertTrue(self.controller.copy())
        self.meeting("Other selected material")
        callbacks.pop(0)()
        self.assertIn("Original copy", self.clipboard.call_args.args[0])
        self.assertNotIn("Other selected material", self.clipboard.call_args.args[0])
