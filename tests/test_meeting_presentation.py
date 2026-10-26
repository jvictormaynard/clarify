import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import uuid

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from clarify.desktop.qml_meetings import create_qml_meetings
from clarify.desktop.qml_app import _capture_idle
from clarify_account import AccountService
from secret_store import PlaintextFileSecretStore


class MeetingPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_factory_and_copy_export_use_only_fixture_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account = AccountService(
                root, secrets=PlaintextFileSecretStore(root / "secrets.json")
            )
            runtime = SimpleNamespace(
                account=account,
                dictionary_service=Mock(),
                provider_registry=Mock(metadata=()),
                repositories=Mock(),
                copy_result=Mock(),
                scheduler=SimpleNamespace(run_dispatch=lambda cb: cb()),
            )
            updating = [False]
            controller = create_qml_meetings(
                runtime,
                can_start=lambda: True,
                workflow_config=Mock(),
                editing_allowed=lambda: not updating[0],
            )
            self.addCleanup(controller.shutdown)
            self.assertIsNotNone(controller.workflow)
            with patch.object(controller.workflow.store, "recover") as recovery:
                controller.refresh()
                recovery.assert_not_called()
                controller.activate()
                recovery.assert_called_once()
            mid = controller.workflow.store.create("guest", "Fixture")["id"]
            controller.workflow.store.save_notes("guest", mid, "Personal fixture")
            controller.workflow.store.end("guest", mid)
            controller.workflow.selected = mid
            controller.refresh()
            self.assertTrue(controller.copy())
            self.assertIn("Personal fixture", runtime.copy_result.call_args.args[0])
            output = root / "export.md"
            self.assertTrue(
                controller.exportFile(QUrl.fromLocalFile(str(output)).toString())
            )
            self.assertIn("Personal fixture", output.read_text(encoding="utf-8"))
            updating[0] = True
            controller.refresh()
            self.assertFalse(controller.state["editingAllowed"])
            self.assertFalse(
                controller.saveNotes(mid, controller.state["context"], "late edit")
            )
            self.assertEqual(
                controller.workflow.store.get("guest", mid)["notes"], "Personal fixture"
            )
            updating[0] = False
            controller.refresh()
            controller.setNotesPending(True)
            self.assertTrue(controller.blocks_processing)
            controller.setNotesPending(False)
            self.assertFalse(controller.blocks_processing)
            self.assertFalse(controller.saveNotes(mid, "guest:stale", "incorrect"))
            self.assertEqual(
                controller.workflow.store.get("guest", mid)["notes"], "Personal fixture"
            )

    def test_expired_session_draft_can_be_saved_only_in_its_original_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            account = AccountService(
                root, secrets=PlaintextFileSecretStore(root / "secrets.json")
            )
            account._state.update(user_id=str(uuid.uuid4()), mode="hosted")
            runtime = SimpleNamespace(
                account=account,
                dictionary_service=Mock(),
                provider_registry=Mock(metadata=()),
                repositories=Mock(),
                copy_result=Mock(),
                scheduler=SimpleNamespace(run_dispatch=lambda cb: cb()),
            )
            controller = create_qml_meetings(
                runtime, can_start=lambda: True, workflow_config=Mock()
            )
            self.addCleanup(controller.shutdown)
            owner = controller.workflow.provider.identity().owner
            mid = controller.workflow.store.create(owner)["id"]
            controller.workflow.store.end(owner, mid)
            controller.activate()
            context = controller.state["context"]
            controller.setNotesPending(True)
            account._state.pop("user_id")
            account._generation += 1
            controller.refresh()
            self.assertFalse(controller.saveNotes(mid, context, "pending draft"))
            self.assertTrue(controller.blocks_processing)
            self.assertTrue(controller.preserveDraft(mid, context, "pending draft"))
            controller.setNotesPending(False)
            self.assertFalse(controller.blocks_processing)
            self.assertEqual(
                controller.workflow.store.get(owner, mid)["notes"], "pending draft"
            )
            self.assertEqual(controller.workflow.store.list("guest"), [])

    def test_composition_excludes_each_processing_owner_and_unsaved_notes(self):
        path = Path(__file__).resolve().parents[1] / "clarify/desktop/qml_app.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        main = next(
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"
        )
        names = {
            "settings_work_busy",
            "capture_idle",
            "external_processing_allowed",
            "settings_processing_allowed",
            "meetings_can_start",
            "practice_can_start",
        }
        nodes = [
            n for n in main.body if isinstance(n, ast.FunctionDef) and n.name in names
        ]
        settings = SimpleNamespace(
            **{
                name: False
                for name in (
                    "microphoneTestBusy",
                    "microphoneInventoryBusy",
                    "localAsrBusy",
                    "localBenchmarkBusy",
                    "providerBusy",
                )
            },
            routeModelStatus="idle",
        )
        environment = dict(
            _capture_idle=_capture_idle,
            settings=settings,
            practice=SimpleNamespace(blocks_processing=False, busy=False),
            voice_translation=SimpleNamespace(active=False),
            audio_batch=SimpleNamespace(running=False),
            bridge=SimpleNamespace(start_pending=False),
            meetings=SimpleNamespace(blocks_processing=False),
            workflow_service=SimpleNamespace(
                state=SimpleNamespace(phase=SimpleNamespace(value="ready"))
            ),
            runtime=SimpleNamespace(recording_audio=SimpleNamespace(busy=False)),
            updates=SimpleNamespace(installing=False),
        )
        exec(
            compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"),
            environment,
        )
        self.assertTrue(environment["meetings_can_start"]())
        environment["updates"].installing = True
        self.assertFalse(environment["meetings_can_start"]())
        environment["updates"].installing = False
        for owner, field in (
            ("practice", "blocks_processing"),
            ("voice_translation", "active"),
            ("audio_batch", "running"),
            ("bridge", "start_pending"),
            ("meetings", "blocks_processing"),
            ("settings", "microphoneTestBusy"),
            ("settings", "localAsrBusy"),
            ("settings", "providerBusy"),
        ):
            target = environment[owner]
            setattr(target, field, True)
            self.assertFalse(environment["meetings_can_start"](), (owner, field))
            setattr(target, field, False)
        environment["meetings"].blocks_processing = True
        self.assertFalse(environment["external_processing_allowed"]())
        self.assertFalse(environment["practice_can_start"]())
        self.assertFalse(environment["settings_processing_allowed"]())
        environment["meetings"].blocks_processing = False
        environment["runtime"].recording_audio.busy = True
        self.assertFalse(environment["meetings_can_start"]())
        self.assertFalse(environment["external_processing_allowed"]())
