"""Real Qt Quick/QML entrypoint for Clarify dictation."""

from __future__ import annotations

import os
import sys
from enum import Enum
from functools import partial
from pathlib import Path

# Frozen batch recognition workers must exit before Qt or profile startup.
if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()

# Source autostart executes this file directly from ``clarify/desktop`` while
# the root-level workflow modules remain package imports.  Put the repository
# root on ``sys.path`` before importing either the Qt or application modules.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from PySide6.QtCore import QTimer, QUrl, Qt  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from shared.localization import translate  # noqa: E402

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402


def _can_capture_settings_shortcut(workflow, voice_translation, audio_batch, practice):
    # Idle practice permits editing its shortcut, while account changes stay blocked.
    return (
        workflow.state.phase.value
        in {"ready", "completed", "failed", "cancelled", "microphone_unavailable"}
        and not voice_translation.active
        and not audio_batch.running
        and not practice.busy
    )


def _branding_icon_path() -> Path:
    """Resolve the bundled branding icon for source and frozen launches."""

    roots: list[Path] = []
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        roots.append(Path(bundled_root))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(_REPOSITORY_ROOT)

    seen: set[Path] = set()
    relative_path = Path("assets") / "branding" / "clarify.ico"
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        candidate = root / relative_path
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        f"Clarify branding icon was not found under: {', '.join(map(str, roots))}"
    )


def _load_branding_icon() -> QIcon:
    """Load a non-null QIcon for native application windows."""

    icon = QIcon(str(_branding_icon_path()))
    if icon.isNull():
        raise RuntimeError("Clarify branding icon could not be loaded")
    return icon


def _qml_root() -> Path:
    """Resolve the QML asset directory for source and frozen launches."""

    roots: list[Path] = []
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        roots.append(Path(bundled_root))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.extend(
        (Path(__file__).resolve().parent, _REPOSITORY_ROOT / "clarify" / "desktop")
    )

    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        candidate = root / "qml"
        if (candidate / "AudioFilesWindow.qml").is_file():
            return candidate

    raise FileNotFoundError(
        f"Clarify QML assets were not found under: {', '.join(map(str, roots))}"
    )


try:
    from .qml_audio_batch import QmlAudioFileImportController  # noqa: E402
    from .qml_bridge import QmlWorkflowBridge  # noqa: E402
    from .qml_settings import QmlSettingsController  # noqa: E402
    from .qml_computer import create_computer_controller  # noqa: E402
    from .qml_updates import QmlUpdateController  # noqa: E402
    from .qml_electron import (  # noqa: E402
        ElectronDesktopProcess,
        ElectronQtShell,
        desktop_executable,
    )
    from .qml_status import QmlStatusPillController  # noqa: E402
    from .qml_voice_translation import (  # noqa: E402
        QmlVoiceTranslationProvider,
        create_qml_voice_translation_controller,
    )
    from .qml_runtime import (  # noqa: E402
        QtRuntimeError,
        QtStatisticsGateway,
        QtWorkflowScheduler,
        create_real_workflow_runtime,
        create_runtime_repositories,
    )
    from .macos_hotkeys import MacGlobalHotkeyBackend, default_hotkeys  # noqa: E402
    from .qt_shell import QtSingleInstanceGuard, WindowsGlobalHotkeyBackend  # noqa: E402
except ImportError:  # PyInstaller analyzes this file as a standalone entry point.
    from qml_audio_batch import QmlAudioFileImportController  # noqa: E402
    from qml_bridge import QmlWorkflowBridge  # noqa: E402
    from qml_settings import QmlSettingsController  # noqa: E402
    from qml_computer import create_computer_controller  # noqa: E402
    from qml_updates import QmlUpdateController  # noqa: E402
    from qml_electron import (  # noqa: E402
        ElectronDesktopProcess,
        ElectronQtShell,
        desktop_executable,
    )
    from qml_status import QmlStatusPillController  # noqa: E402
    from qml_voice_translation import (  # noqa: E402
        QmlVoiceTranslationProvider,
        create_qml_voice_translation_controller,
    )
    from qml_runtime import (  # noqa: E402
        QtRuntimeError,
        QtStatisticsGateway,
        QtWorkflowScheduler,
        create_real_workflow_runtime,
        create_runtime_repositories,
    )
    from macos_hotkeys import MacGlobalHotkeyBackend, default_hotkeys  # noqa: E402
    from qt_shell import QtSingleInstanceGuard, WindowsGlobalHotkeyBackend  # noqa: E402


if os.environ.get("CLARIFY_IMPORT_SMOKE_TEST") == "1":
    # Validate the collected QML plugins too, without a user profile, recorder,
    # hotkeys or visible window. Python imports alone cannot detect missing QML.
    QQuickStyle.setStyle("Basic")
    smoke_app = QApplication([])
    smoke_engine = QQmlApplicationEngine()
    smoke_engine.loadData(b"""
        import QtQuick 6.5
        import QtQuick.Controls 6.5
        import QtQuick.Layouts 6.5
        import QtQuick.Dialogs 6.5
        import QtQuick.Window 6.5
        ApplicationWindow {
            visible: false; width: 400; height: 120
            RowLayout {
                Button { text: "Test" }
                TextField { text: "Test" }
                ComboBox { model: ["Test"] }
                Switch { checked: true }
                ProgressBar { value: 0.5 }
            }
            FileDialog {}
        }
    """)
    smoke_app.processEvents()
    raise SystemExit(0 if smoke_engine.rootObjects() else 2)


class ShellStartResult(Enum):
    """Describe the shell outcome without conflating setup errors and peers."""

    STARTED = "started"
    SECONDARY_INSTANCE = "secondary_instance"
    SETUP_FAILED = "setup_failed"


def _start_shell_if_available(shell) -> ShellStartResult:
    """Start single-instance and hotkey ownership independently of presentation."""
    try:
        if not shell.start():
            return ShellStartResult.SECONDARY_INSTANCE
    except Exception as error:
        # QtShell.start() has already removed any partially-created tray or
        # hotkey resources.  It deliberately keeps the instance guard owned so
        # this fallback runtime remains single-instance until shutdown.
        print(
            f"Clarify QML shell unavailable: {error}",
            file=sys.stderr,
        )
        return ShellStartResult.SETUP_FAILED

    return ShellStartResult.STARTED


def _register_qml_context(engine, workflow, settings, audio_batch=None) -> None:
    """Expose only the controllers consumed by the native file-import panel."""
    context = engine.rootContext()
    context.setContextProperty("workflow", workflow)
    context.setContextProperty("settings", settings)
    if audio_batch is not None:
        context.setContextProperty("audioBatch", audio_batch)


def _connect_preference_sync(bridge, settings) -> None:
    """Synchronize Settings and home preferences with explicit ownership.

    Settings edits remain a draft until its Save action. Home mode/language
    changes are the only bridge-originated updates and persist immediately.
    The guard prevents the Settings-to-bridge reflection from being mistaken
    for a new home edit and saving the draft recursively.
    """

    syncing_from_settings = False

    def sync_bridge_from_settings() -> None:
        nonlocal syncing_from_settings
        syncing_from_settings = True
        try:
            bridge.setMode(settings.mode)
            bridge.setLanguage(settings.language)
        finally:
            syncing_from_settings = False

    def persist_home_preference(setter, persister, value) -> None:
        if not setter(value):
            return
        if not syncing_from_settings:
            persister(value)

    settings.configChanged.connect(sync_bridge_from_settings)
    bridge.modeChanged.connect(
        lambda: persist_home_preference(
            settings.setMode,
            settings.persistMode,
            bridge.mode,
        )
    )
    bridge.languageChanged.connect(
        lambda: persist_home_preference(
            settings.setLanguage,
            settings.persistLanguage,
            bridge.language,
        )
    )


def _hidden_start_requested(arguments: list[str]) -> bool:
    """Accept the supported background launch mode and reject other flags."""

    if not arguments:
        return False
    if arguments == ["--hidden"]:
        return True
    raise ValueError("unsupported launch arguments")


class _AudioFilesWindowVisibility:
    """Only file imports retain a native panel; all workflow UI is Electron."""

    def __init__(self, bridge, window):
        self._bridge = bridge
        self._window = window
        bridge.surfaceChanged.connect(self.sync)
        self.sync()

    def sync(self):
        visible = self._bridge.surface == "files"
        self._window.setProperty("presentationVisible", visible)
        if visible:
            self._window.show()
            self._window.raise_()
            self._window.requestActivate()


def _capture_idle(workflow, audio, bridge=None, voice=None, batch=None) -> bool:
    """Permit Settings recovery while retaining terminal retry and undo audio."""
    return (
        workflow.state.phase.value
        in {
            "ready",
            "completed",
            "failed",
            "cancelled",
            "microphone_unavailable",
        }
        and not audio.busy
        and (bridge is None or not bridge.start_pending)
        and (voice is None or not voice.active)
        and (batch is None or not batch.running)
    )


def _connect_shutdown(
    app,
    shell,
    runtime,
    voice_translation=None,
    audio_batch=None,
    *,
    stop_shell=True,
) -> None:
    """Stop shell-owned native resources before the workflow runtime."""

    if voice_translation is not None:
        app.aboutToQuit.connect(voice_translation.cancel)
    if audio_batch is not None:
        app.aboutToQuit.connect(audio_batch.cancel)
    if stop_shell:
        app.aboutToQuit.connect(shell.stop)
    app.aboutToQuit.connect(runtime.shutdown)


def _record_voice_translation_usage(
    statistics,
    config,
    state,
    duration_seconds,
) -> None:
    """Record one production-schema event through the UI-free Qt gateway."""

    statistics.record_voice_translation(config, state, duration_seconds)


def main(argv: list[str] | None = None) -> int:
    """Start the shared engine and its required Electron presentation."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) == 2 and arguments[0] == "--apply-portable-update":
        from portable_update_windows import run_portable_update_helper
        from version import __version__

        return run_portable_update_helper(Path(arguments[1]), __version__)
    try:
        start_hidden = _hidden_start_requested(arguments)
    except ValueError:
        print(
            "Clarify QML accepts only the optional --hidden launch flag.",
            file=sys.stderr,
        )
        return 2

    # The platform-native Controls style can inject light Windows hover and
    # popup surfaces into the otherwise dark frameless shell.  Basic keeps the
    # controls deterministic so the QML palette owns every interaction state.
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Clarify")
    app.setOrganizationName("Clarify")
    try:
        from .qml_localization import install_translations
    except ImportError:
        from qml_localization import install_translations
    install_translations(app)

    electron_path = desktop_executable()
    if electron_path is None:
        QMessageBox.critical(
            None,
            "Clarify",
            translate(
                "A interface do Clarify não foi encontrada. Reinstale o aplicativo."
            ),
        )
        return 1

    instance_guard = None
    if sys.platform == "darwin":
        profile = Path(
            os.environ.get("CLARIFY_DATA_DIR", "").strip() or Path.home() / ".clarify"
        ).resolve()
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.environ["CLARIFY_DATA_DIR"] = str(profile)
        instance_guard = QtSingleInstanceGuard(lock_path=profile / "desktop.lock")
        if not instance_guard.acquire():
            return 0
    scheduler = QtWorkflowScheduler(app)
    try:
        if instance_guard is None:
            runtime = create_real_workflow_runtime(scheduler)
        else:
            runtime = create_real_workflow_runtime(
                scheduler,
                repositories=create_runtime_repositories(
                    hotkey_defaults=default_hotkeys()
                ),
            )
    except QtRuntimeError as error:
        if instance_guard is not None:
            instance_guard.release()
        print(f"Clarify QML startup failed: {error}", file=sys.stderr)
        return 2

    workflow_service = runtime.workflow_service
    repositories = runtime.repositories
    if repositories is None:
        if instance_guard is not None:
            instance_guard.release()
        runtime.shutdown()
        print(
            "Clarify QML startup failed: runtime repositories are missing",
            file=sys.stderr,
        )
        return 2

    loaded_config = repositories.config.load()
    usage_statistics = QtStatisticsGateway(repositories)
    settings = None
    practice = None
    voice_translation = None
    audio_batch = None
    bridge = None
    updates = None

    def settings_work_busy() -> bool:
        return settings is not None and (
            settings.microphoneTestBusy
            or settings.microphoneInventoryBusy
            or settings.localAsrBusy
            or settings.localBenchmarkBusy
            or settings.providerBusy
            or settings.routeModelStatus == "loading"
            or getattr(settings, "chatgptState", {}).get("busy", False)
        )

    def capture_idle() -> bool:
        return _capture_idle(
            workflow_service,
            runtime.recording_audio,
            bridge,
            voice_translation,
            audio_batch,
        )

    def external_processing_allowed() -> bool:
        return (
            (practice is None or not practice.blocks_processing)
            and not settings_work_busy()
            and not runtime.recording_audio.busy
        )

    def settings_processing_allowed() -> bool:
        return (practice is None or not practice.busy) and capture_idle()

    voice_translation = create_qml_voice_translation_controller(
        repositories.config.load,
        runtime.recording_audio,
        runtime.clipboard,
        scheduler,
        on_usage=partial(_record_voice_translation_usage, usage_statistics),
        provider=QmlVoiceTranslationProvider(
            repositories.config.load,
            registry=runtime.provider_registry,
            account=runtime.account,
            dictionary_service=runtime.dictionary_service,
        ),
        parent=app,
        processing_allowed=lambda: external_processing_allowed() and capture_idle(),
    )
    audio_batch = QmlAudioFileImportController(
        runtime.audio_batch_service,
        selection_factory=runtime.audio_file_selection,
        scheduler=scheduler,
        copy_runner=runtime.copy_result,
        dispatch_runner=scheduler.run_dispatch,
        processing_allowed=lambda: external_processing_allowed() and capture_idle(),
        parent=app,
    )

    def toggle_voice_translation() -> bool:
        """Toggle the dedicated voice route from the global hotkey."""

        if workflow_service.state.phase.value != "ready":
            return False
        if voice_translation.active:
            return (
                voice_translation.stop()
                if voice_translation.phase == "recording"
                else voice_translation.cancel()
            )
        if not external_processing_allowed() or not capture_idle():
            return False
        target = runtime.clipboard.capture_target()
        if target is None:
            return False
        bridge.setTargetExecutable(target.executable or "")
        return voice_translation.startForTarget(target)

    try:
        from .qml_quick_paste import QuickPasteController
    except ImportError:
        from qml_quick_paste import QuickPasteController

    quick_paste = QuickPasteController(
        runtime.clipboard,
        scheduler.run_dispatch,
        app.allWindows,
        lambda: shell.hide_window(),
        parent=app,
    )
    try:
        from .dictation_practice import PracticeController, practice_readiness
        from .practice_local_model import LocalModelReadiness
    except ImportError:
        from dictation_practice import PracticeController, practice_readiness
        from practice_local_model import LocalModelReadiness

    def practice_can_start() -> bool:
        return capture_idle() and not settings_work_busy()

    local_practice_model = LocalModelReadiness(
        scheduler, changed=lambda: settings.practiceStateChanged.emit()
    )
    app.aboutToQuit.connect(local_practice_model.close)
    practice = PracticeController(
        runtime.practice_workflow,
        language=lambda: repositories.config.load().ui.language,
        readiness=lambda: practice_readiness(
            settings, practice_can_start, local_practice_model.ready
        ),
        refresh_readiness=local_practice_model.invalidate,
        can_open=lambda: capture_idle() and not settings.microphoneTestBusy,
        identity=runtime.account.history_identity,
        stop_microphone_test=lambda: settings.stopMicrophoneTest(),
    )
    bridge = QmlWorkflowBridge(
        workflow_service,
        app_config=loaded_config,
        dispatch_runner=scheduler.run_dispatch,
        copy_runner=runtime.copy_result,
        voice_translation_handler=toggle_voice_translation,
        voice_translation_controller=voice_translation,
        audio_batch_controller=audio_batch,
        target_provider=quick_paste.capture_target,
        paste_runner=quick_paste.paste,
        processing_allowed=lambda: (
            external_processing_allowed()
            and not voice_translation.active
            and not audio_batch.running
        ),
        parent=app,
    )
    hotkeys = None

    def apply_qml_hotkeys(settings) -> None:
        if hotkeys is not None:
            hotkeys.reconfigure(settings)

    def capture_qml_hotkeys(active: bool) -> None:
        if hotkeys is not None:
            hotkeys.set_capture_active(active)

    def reprocess_recording(path):
        # Recovery is an explicit new request using the current account/route.
        # Never capture or paste into the focused History window.
        if not settings_processing_allowed():
            return False
        state = workflow_service.state
        if state.phase.value in {"completed", "failed", "cancelled"}:
            workflow_service.finish(state.operation_id)
        if workflow_service.state.phase.value != "ready":
            return False
        recording = runtime.recording_audio.create_recovery_session(path)
        if recording is None:
            return False
        accepted = workflow_service.recover_dictation(
            recording, repositories.config.load().ui_language
        )
        if not accepted:
            recording.cancel()
        return accepted

    settings = QmlSettingsController(
        repositories,
        parent=app,
        microphone_backend=runtime.recording_audio.recorder,
        hotkey_applier=apply_qml_hotkeys,
        hotkey_capture_changed=capture_qml_hotkeys,
        text_action_service=getattr(runtime.account, "desktop_text_actions", None),
        text_action_provider=workflow_service._provider,
        text_action_runner=lambda action_id: bridge.runTextAction(action_id),
        dictionary_service=getattr(runtime, "dictionary_service", None),
        account_service=getattr(runtime, "account", None),
        processing_allowed=settings_processing_allowed,
        recording_reprocessor=reprocess_recording,
        account_can_change=lambda: (
            workflow_service.state.phase.value
            in {"ready", "completed", "failed", "cancelled", "microphone_unavailable"}
            and not voice_translation.active
            and not audio_batch.running
            and not practice.blocks_processing
        ),
        hotkey_can_change=lambda: _can_capture_settings_shortcut(
            workflow_service, voice_translation, audio_batch, practice
        ),
    )
    settings.bindPractice(practice)
    app.applicationStateChanged.connect(
        lambda state: (
            runtime.request_history_sync()
            if state == Qt.ApplicationState.ApplicationActive
            else None
        )
    )

    def update_restart_blocker() -> str:
        if settings.dirty or settings.providerDirty:
            return "Salve ou descarte as alterações para atualizar."
        if practice.open:
            return "Feche a prática de ditado para atualizar."
        if settings.microphoneTestBusy:
            return "Pare o teste do microfone para atualizar."
        if settings.localAsrBusy or settings.localBenchmarkBusy:
            return "Aguarde a tarefa do modelo local terminar para atualizar."
        if settings.providerBusy or getattr(settings, "chatgptState", {}).get(
            "busy", False
        ):
            return "Aguarde a conexão com o provedor terminar para atualizar."
        if voice_translation.active or audio_batch.running:
            return "Conclua as tarefas em andamento para atualizar."
        if web_settings.blocks_update():
            return "Feche a janela do Clarify para aplicar a atualização."
        if (
            workflow_service.state.phase.value != "ready"
            or bridge.surface not in {"idle", "success"}
            or bridge.feedbackVisible
        ):
            return "Conclua a gravação ou o processamento e feche o resultado para atualizar."
        return ""

    updates = QmlUpdateController(
        automatic=loaded_config.automatic_updates,
        restart_blocker=update_restart_blocker,
        restart=app.quit,
        parent=app,
    )
    settings.bindUpdates(updates)

    def sync_updates():
        updates.setAutomatic(repositories.config.load().automatic_updates)

    settings.saved.connect(sync_updates)
    settings.loaded.connect(sync_updates)
    branding_icon = _load_branding_icon()
    app.setWindowIcon(branding_icon)
    status_pill = QmlStatusPillController(
        bridge,
        runtime.recording_audio.recorder,
        fallback_icon=branding_icon,
        parent=app,
    )
    _connect_preference_sync(bridge, settings)
    engine = QQmlApplicationEngine()
    _register_qml_context(
        engine,
        bridge,
        settings,
        audio_batch=audio_batch,
    )

    qml_root = _qml_root()
    engine.addImportPath(str(qml_root))
    engine.load(QUrl.fromLocalFile(str(qml_root / "AudioFilesWindow.qml")))
    window = next(
        (
            root
            for root in engine.rootObjects()
            if root.objectName() == "audioFilesWindow"
        ),
        None,
    )
    if window is None:
        if instance_guard is not None:
            instance_guard.release()
        runtime.shutdown()
        return 1

    if sys.platform in {"win32", "darwin"}:
        from text_actions import native_bindings

        bindings = (
            settings._text_actions.bindings()
            if settings.textActionContext
            else native_bindings(repositories.config.load(), ())
        )
        if sys.platform == "darwin":
            hotkeys = MacGlobalHotkeyBackend(bindings, parent=app)
            hotkeys.availabilityChanged.connect(settings.setUnavailableHotkeys)
        else:
            hotkeys = WindowsGlobalHotkeyBackend(app, settings=bindings, parent=app)
    if hotkeys is not None:

        def sync_escape():
            hotkeys.set_recording_active(
                practice.busy or bridge.surface in {"recording", "translation_picker"}
            )

        bridge.surfaceChanged.connect(sync_escape)
        practice.subscribe(sync_escape)
        sync_escape()

    failure_dialog = None

    def desktop_unavailable():
        nonlocal failure_dialog
        if failure_dialog is not None:
            return
        failure_dialog = QMessageBox(app.activeWindow())
        failure_dialog.setWindowTitle("Clarify")
        failure_dialog.setIcon(QMessageBox.Critical)
        failure_dialog.setText(
            translate(
                "Não foi possível iniciar a interface do Clarify.", settings.uiLanguage
            )
        )
        failure_dialog.setInformativeText(
            translate(
                "Tente abrir a interface novamente ou feche o Clarify. Os áudios salvos continuam no histórico.",
                settings.uiLanguage,
            )
        )
        failure_dialog.setStandardButtons(QMessageBox.Retry | QMessageBox.Close)
        failure_dialog.button(QMessageBox.Retry).setText(
            translate("Tentar novamente", settings.uiLanguage)
        )
        failure_dialog.button(QMessageBox.Close).setText(
            translate("Fechar", settings.uiLanguage)
        )

        def respond(result):
            nonlocal failure_dialog
            failure_dialog.deleteLater()
            failure_dialog = None
            if result == QMessageBox.Retry:
                web_settings.retry()
            else:
                app.quit()

        failure_dialog.finished.connect(respond)
        failure_dialog.open()

    web_settings = ElectronDesktopProcess(
        settings, bridge, status_pill, desktop_unavailable, app, app
    )
    quick_paste.excluded_executable = lambda: str(electron_path)

    runtime.recording_audio.before_recording = settings.stopPlaybackBeforeRecording
    web_settings.process.finished.connect(settings.releaseRecordingPlayback)

    shell = ElectronQtShell(
        window,
        desktop=web_settings,
        instance_guard=instance_guard,
        hotkeys=hotkeys,
        visibility_hotkey_allowed=lambda: not bridge.recording and not practice.busy,
        parent=app,
    )
    shell.hotkeyTriggered.connect(
        lambda action: (
            (practice.handle_hotkey(action) or bridge.handleHotkey(action))
            if not updates.installing
            else None
        )
    )
    bridge.resultRequested.connect(shell.show_window)
    files_visibility = _AudioFilesWindowVisibility(bridge, window)
    bridge.settingsRequested.connect(web_settings.show)
    app.aboutToQuit.connect(web_settings.shutdown)
    _ = files_visibility
    macos = instance_guard is not None
    if macos:
        app.aboutToQuit.connect(quick_paste.timer.stop)
        app.aboutToQuit.connect(hotkeys.stop)
    _connect_shutdown(
        app, shell, runtime, voice_translation, audio_batch, stop_shell=not macos
    )
    app.aboutToQuit.connect(settings.shutdown)
    app.aboutToQuit.connect(updates.shutdown)
    if macos:
        app.aboutToQuit.connect(shell.stop)

    shell_result = _start_shell_if_available(shell)
    if shell_result is ShellStartResult.SECONDARY_INSTANCE:
        runtime.shutdown()
        return 0
    runtime.computer = create_computer_controller(runtime, parent=app)
    settings.bindComputer(runtime.computer)
    runtime.computer.initialize()
    web_settings.start(visible=not start_hidden)
    app.setQuitOnLastWindowClosed(False)
    from portable_update_windows import acknowledge_portable_update
    from version import __version__

    QTimer.singleShot(0, lambda: acknowledge_portable_update(__version__))
    updates.start()
    if settings.onboardingRequired:
        QTimer.singleShot(0, bridge.openSettings)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
