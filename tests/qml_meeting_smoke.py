"""Render meetings with synthetic data and no recorder, account, or profile."""

import os
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QUrl, QTimer, QPointF, Qt, QMetaObject, QObject  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from clarify.desktop.qml_localization import ClarifyTranslator  # noqa: E402
from clarify.desktop.qml_meetings import QmlMeetingController  # noqa: E402
from meeting_store import MeetingStore  # noqa: E402
from meeting_workflow import MeetingWorkflow  # noqa: E402
from shared.meeting_contract import MeetingIdentity, MeetingError  # noqa: E402


def main():
    QQuickStyle.setStyle("Basic")
    if "--export" in sys.argv:
        QApplication.setAttribute(Qt.AA_DontUseNativeDialogs)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    translator = ClarifyTranslator(language="pt")
    app.installTranslator(translator)
    with tempfile.TemporaryDirectory(prefix="meeting-ui-fixture-") as directory:
        store = MeetingStore(directory)
        mid = store.create("guest", "Revisar o prototipo", language="pt")["id"]
        cid, _ = store.open_chunk("guest", mid, "system", 0)
        store.finish_chunk("guest", mid, cid, 1000)
        store.save_transcript(
            "guest", mid, cid, "Vamos testar a recuperacao antes de publicar."
        )
        store.save_notes("guest", mid, "Validar as duas fontes no Windows.")
        _, revision, _ = store.summary_request("guest", mid)
        store.save_summary(
            "guest",
            mid,
            revision,
            "Resumo do teste.\n\nDecisoes: testar a recuperacao.\n\nTarefas: validar as duas fontes.",
        )
        store.end("guest", mid)
        if "--pages" in sys.argv:
            created = store.get("guest", mid)["created"]
            with store._connection() as db:
                db.executemany(
                    "INSERT INTO meetings(id,owner,title,created,state) VALUES(?,?,?,?,?)",
                    [
                        (
                            str(uuid.uuid4()),
                            "guest",
                            f"Fixture {n}",
                            created + n + 1,
                            "stopped",
                        )
                        for n in range(200)
                    ],
                )
        provider = Mock()
        provider.identity.return_value = MeetingIdentity("guest", 0, False)

        @contextmanager
        def publication(expected):
            if provider.identity() != expected:
                raise MeetingError("meeting.scope_changed")
            yield

        provider.publication = publication
        provider.workflows.registry.metadata = (
            SimpleNamespace(
                provider_id="openai",
                display_name="OpenAI",
                default_text_model="gpt-4o-mini",
                supports=lambda capability: True,
            ),
        )
        workflow = MeetingWorkflow(store, provider, source_factory=Mock())
        workflow.selected = mid
        if "--chatgpt" in sys.argv:
            from provider_registry import build_provider_registry
            from provider_types import ProviderConnection
            from workflow_config import WorkflowRoute

            session = Mock()
            session.snapshot.return_value = {
                "connected": True,
                "planEnabled": True,
                "accountId": "fixture-account",
                "generation": 1,
            }
            provider.workflows.registry = build_provider_registry(
                chatgpt_session=session
            )
            provider.workflows._connection.side_effect = lambda route: (
                ProviderConnection("", "https://api.openai.com/v1", route.account_id)
            )
            store.save_notes_route(
                "guest",
                WorkflowRoute("chatgpt", "fixture-z", account_id="fixture-account"),
            )
        controller = QmlMeetingController(workflow)
        if "--chatgpt" in sys.argv:
            catalog = Mock()
            catalog.chatgptTextCatalog = {
                "accountId": "fixture-account",
                "generation": 1,
                "models": [
                    {"id": "fixture-z", "label": "First account model"},
                    {"id": "fixture-a", "label": "Second account model"},
                ],
            }
            controller.bindModelCatalog(catalog)
            controller.refresh()
        if "--recording" in sys.argv:
            controller._timer.stop()
            workflow._thread = Mock()
            workflow._thread.is_alive.return_value = True
            controller._state = {
                **controller.state,
                "phase": "recording",
                "active": True,
                "duration": 73,
                "sources": {
                    "microphone": {"state": "recording", "level": 0.55, "warning": ""},
                    "system": {
                        "state": "failed",
                        "level": 0,
                        "warning": "meeting.device_changed",
                    },
                },
            }
        engine = QQmlApplicationEngine()
        messages = []
        engine.warnings.connect(
            lambda warnings: messages.extend(w.toString() for w in warnings)
        )
        engine.rootContext().setContextProperty("meetings", controller)
        qml = ROOT / "clarify/desktop/qml"
        engine.addImportPath(str(qml))
        engine.load(QUrl.fromLocalFile(str(qml / "MeetingWindow.qml")))
        engine.load(QUrl.fromLocalFile(str(qml / "MeetingIndicator.qml")))
        if len(engine.rootObjects()) != 2:
            print("\n".join(messages))
            return 1
        window = engine.rootObjects()[0]
        window.show()
        window.requestActivate()
        output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
        failures = []

        def verify():
            try:
                if "--chatgpt" in sys.argv:
                    QMetaObject.invokeMethod(window, "saveNotes")
                    picker = window.findChild(QObject, "meetingNoteModelPicker")
                    assert picker is not None and picker.property("visible")
                    assert picker.property("count") == 2
                    assert picker.property("currentValue") == "fixture-z"
                    picker.setProperty("currentIndex", 1)
                    assert picker.property("currentValue") == "fixture-a"
                    assert controller.saveNotesRoute(
                        controller.state["context"],
                        "chatgpt",
                        picker.property("currentValue"),
                        True,
                    ), controller.state["error"]
                    assert store.notes_route("guest").model_id == "fixture-a"
                    assert store.notes_route("guest").account_id == "fixture-account"
                if "--export" in sys.argv:
                    controller._timer.stop()
                    QMetaObject.invokeMethod(window, "saveNotes")
                    assert not window.property("notesDirty")
                    dialog = window.findChild(QObject, "meetingExportDialog")
                    assert dialog is not None
                    dialog.setProperty("currentFolder", QUrl.fromLocalFile(directory))
                    target = Path(directory) / "export.md"
                    target_url = QUrl.fromLocalFile(str(target))
                    account_owner = "account:" + "a" * 64
                    account = store.create(account_owner, "Account export")["id"]
                    store.save_notes(account_owner, account, "Account manual note")
                    store.end(account_owner, account)

                    def switch_export(owner, generation, selected):
                        provider.identity.return_value = MeetingIdentity(
                            owner, generation, owner != "guest"
                        )
                        workflow.selected = selected
                        controller.refresh()
                        app.processEvents()

                    def request_export():
                        dialog.setProperty("selectedFile", target_url)
                        assert QMetaObject.invokeMethod(window, "requestExport")
                        app.processEvents()
                        assert dialog.property("visible")
                        assert dialog.property("meetingId") == workflow.selected

                    # Social login has been started while still guest; its
                    # fixture completion changes the session after opening.
                    request_export()
                    switch_export(account_owner, 1, account)
                    assert not dialog.property("visible")
                    assert dialog.property("meetingId") == ""
                    QMetaObject.invokeMethod(dialog, "accept")
                    assert not target.exists()

                    request_export()
                    switch_export("guest", 2, mid)
                    assert not dialog.property("visible")
                    QMetaObject.invokeMethod(dialog, "accept")
                    assert not target.exists()

                    switch_export(account_owner, 3, account)
                    request_export()
                    switch_export("guest", 4, mid)
                    switch_export(account_owner, 5, account)
                    assert not dialog.property("visible")
                    QMetaObject.invokeMethod(dialog, "accept")
                    assert not target.exists()

                    switch_export("guest", 6, mid)
                    request_export()
                    other = store.create("guest", "Other export")["id"]
                    store.save_notes("guest", other, "Other manual note")
                    store.end("guest", other)
                    workflow.select(other)
                    controller.refresh()
                    assert dialog.property("meetingId") == mid
                    dialog.setProperty("selectedFile", target_url)
                    QMetaObject.invokeMethod(dialog, "accept")
                    app.processEvents()
                    assert target.exists(), controller.state["error"]
                    exported = target.read_text(encoding="utf-8")
                    assert "Validar as duas fontes no Windows." in exported
                    assert "Other manual note" not in exported
                    assert "Account manual note" not in exported
                    assert store.get("guest", other)["notes"] == "Other manual note"
                if "--delete" in sys.argv:
                    controller._timer.stop()
                    QMetaObject.invokeMethod(window, "saveNotes")
                    assert not window.property("notesDirty")
                    dialog = window.findChild(QObject, "meetingDeleteDialog")
                    assert dialog is not None
                    account_owner = "account:" + "a" * 64
                    account = store.create(account_owner)["id"]
                    store.end(account_owner, account)

                    def switch(owner, generation, selected):
                        provider.identity.return_value = MeetingIdentity(
                            owner, generation, owner != "guest"
                        )
                        workflow.selected = selected
                        controller.refresh()
                        app.processEvents()

                    def request_delete():
                        assert QMetaObject.invokeMethod(window, "requestDelete")
                        app.processEvents()
                        assert dialog.property("visible"), (
                            controller.state,
                            window.property("notesId"),
                            window.property("notesContext"),
                            window.property("notesDirty"),
                            dialog.property("context"),
                            dialog.property("meetingId"),
                        )

                    switch(account_owner, 1, account)
                    request_delete()
                    assert dialog.property("meetingId") == account
                    switch("guest", 2, mid)
                    QTest.qWait(250)
                    assert not dialog.property("visible")
                    assert dialog.property("meetingId") == ""
                    QMetaObject.invokeMethod(dialog, "accept")
                    assert store.get("guest", mid)["id"] == mid
                    assert store.get(account_owner, account)["id"] == account

                    switch(account_owner, 3, account)
                    request_delete()
                    switch("guest", 4, mid)
                    switch(account_owner, 5, account)
                    QTest.qWait(250)
                    assert not dialog.property("visible")
                    QMetaObject.invokeMethod(dialog, "accept")
                    assert store.get(account_owner, account)["id"] == account

                    switch("guest", 6, mid)
                    request_delete()
                    other = store.create("guest", "Other selection")["id"]
                    store.save_notes("guest", other, "Keep this manual note")
                    store.end("guest", other)
                    workflow.select(other)
                    controller.refresh()
                    assert dialog.property("meetingId") == mid
                    QMetaObject.invokeMethod(dialog, "accept")
                    app.processEvents()
                    assert all(row["id"] != mid for row in store.list("guest"))
                    assert workflow.selected == other
                    assert store.get("guest", other)["notes"] == "Keep this manual note"
                if "--pages" in sys.argv:
                    button = window.findChild(QQuickItem, "meetingNextPage")
                    assert button is not None and button.isEnabled()
                    point = button.mapToScene(
                        QPointF(button.width() / 2, button.height() / 2)
                    ).toPoint()
                    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
                    app.processEvents()
                    assert controller.state["page"] == 1
                    assert controller.state["selected"]["id"] == mid
                if output:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    window.grabWindow().save(str(output))
                window.close()
                app.processEvents()
                assert not window.isVisible()
                assert not workflow._cancel.cancelled
            except Exception:
                import traceback

                failures.append(traceback.format_exc())
            finally:
                controller.shutdown()
                app.quit()

        QTimer.singleShot(500, verify)
        app.exec()
        if messages or failures:
            print("\n".join(messages + failures))
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
