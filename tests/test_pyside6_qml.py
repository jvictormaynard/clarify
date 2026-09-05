import ast
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    from PySide6.QtCore import QObject, QTimer, Signal
    from PySide6.QtGui import QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication
    from spikes.pyside6 import qml_app
    from spikes.pyside6.qml_app import (
        ShellStartResult,
        _connect_preference_sync,
        _connect_shutdown,
        _branding_icon_path,
        _load_branding_icon,
        _qml_root,
        _record_voice_translation_usage,
        _register_qml_context,
        _WorkflowWindowVisibility,
        _hidden_start_requested,
        _show_translation_picker_if_needed,
        _sync_recording_escape_hotkey,
        _start_shell_if_available,
    )
    from spikes.pyside6.qml_bridge import QmlWorkflowBridge
    from spikes.pyside6.qml_status import (
        QmlStatusPillController,
        _packaged_app_icon,
        _pillow_data_url,
    )
    from spikes.pyside6.qml_settings import QmlSettingsController
except (ImportError, ModuleNotFoundError):
    PYSIDE6_AVAILABLE = False
    QObject = object

    def Signal(*args, **kwargs):
        return None
else:
    PYSIDE6_AVAILABLE = True


ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT / "spikes" / "pyside6"
QML_ROOT = SPIKE / "qml"


class PySide6QmlFrontendTests(unittest.TestCase):
    @unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is required")
    def test_pill_transition_and_expiry_offscreen(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tests/qml_pill_transition_smoke.py")],
            cwd=ROOT,
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
            capture_output=True,
            text=True,
            timeout=40,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: one native capsule", result.stdout)

    @unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is required")
    def test_dropdown_alignment_offscreen(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tests/qml_select_alignment_smoke.py")],
            cwd=ROOT,
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: dropdown text", result.stdout)

    @unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is required")
    def test_model_settings_render_and_interactions_offscreen(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tests/qml_model_settings_smoke.py")],
            cwd=ROOT,
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
            capture_output=True,
            text=True,
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: full QML settings render", result.stdout)

    def test_qml_entrypoint_and_assets_are_present(self):
        entrypoint = SPIKE / "qml_app.py"
        self.assertTrue(entrypoint.is_file())
        entrypoint_source = entrypoint.read_text(encoding="utf-8")

        qml_files = sorted(QML_ROOT.rglob("*.qml"))
        self.assertTrue(qml_files, "the QML frontend must contain QML assets")
        self.assertTrue((QML_ROOT / "AppButton.qml").is_file())
        group_source = (QML_ROOT / "SettingsGroup.qml").read_text(encoding="utf-8")
        self.assertIn("background: null", group_source)
        self.assertNotIn("border.color", group_source)
        local_model_source = (QML_ROOT / "LocalModelCard.qml").read_text(
            encoding="utf-8"
        )
        self.assertIn("background: null", local_model_source)
        self.assertNotIn(
            "background: Rectangle { color: visualTheme.card", local_model_source
        )
        self.assertFalse((QML_ROOT / "PilotButton.qml").exists())
        main_files = [path for path in qml_files if path.name.casefold() == "main.qml"]
        self.assertEqual(main_files, [QML_ROOT / "Main.qml"])
        qml_source = "\n".join(path.read_text(encoding="utf-8") for path in qml_files)

        self.assertIn("ApplicationWindow", qml_source)
        self.assertIn("State", qml_source)
        self.assertIn("Transition", qml_source)
        self.assertRegex(qml_source, r"(Behavior|NumberAnimation|OpacityAnimator)")
        self.assertRegex(qml_source, r"Accessible\.(name|description)")
        self.assertIn("Accessible.name: workflow.status", qml_source)
        self.assertIn("Accessible.name: workflow.result", qml_source)
        self.assertNotIn('Accessible.name: "Prototype result text"', qml_source)

        theme_source = (QML_ROOT / "Theme.qml").read_text(encoding="utf-8")
        for value in ("#0a0a0a", "#050505", "#1c1c1c", "#ffffff", "#666666"):
            self.assertIn(value, theme_source)
        self.assertIn("readonly property int windowWidth: 380", theme_source)
        self.assertIn("readonly property int windowHeight: 48", theme_source)
        self.assertIn("readonly property int fadeDuration: 180", theme_source)
        self.assertIn("readonly property real uiScale: 1.1", theme_source)

        main_source = (QML_ROOT / "Main.qml").read_text(encoding="utf-8")
        self.assertIn('objectName: "clarifyVoiceMainWindow"', main_source)
        self.assertIn('objectName: "appPages"', main_source)
        self.assertNotIn("PilotButton", main_source)
        status_pill_source = (QML_ROOT / "StatusPill.qml").read_text(encoding="utf-8")
        self.assertIn('color: "transparent"', main_source)
        self.assertIn(
            "Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint", main_source
        )
        self.assertIn("Layout.preferredWidth: 36", main_source)
        self.assertIn("Layout.preferredWidth: 78", main_source)
        self.assertIn("Layout.preferredWidth: 48", main_source)
        self.assertIn("Layout.preferredWidth: 26", main_source)
        self.assertNotIn("#72a7ff", qml_source)
        self.assertNotIn("#4f83e8", qml_source)
        self.assertIn('source: "flags/" + workflow.language + ".svg"', main_source)
        self.assertIn('iconSource: "icons/settings.svg"', main_source)
        self.assertIn('iconSource: "icons/x.svg"', main_source)
        self.assertNotIn('text: "☰"', main_source)
        self.assertNotIn('text: "—"', main_source)
        rounded_flag_source = (QML_ROOT / "RoundedFlag.qml").read_text(encoding="utf-8")
        self.assertIn("property url source", rounded_flag_source)
        self.assertIn("ctx.clip()", rounded_flag_source)
        self.assertIn("ctx.quadraticCurveTo", rounded_flag_source)
        self.assertIn("implicitWidth: 24", rounded_flag_source)
        self.assertIn("implicitHeight: 18", rounded_flag_source)
        self.assertIn("onImageLoaded: requestPaint()", rounded_flag_source)
        self.assertNotIn("border.width", rounded_flag_source)
        self.assertEqual(main_source.count("RoundedFlag {"), 1)
        select_source = (QML_ROOT / "SearchSelect.qml").read_text(encoding="utf-8")
        self.assertEqual(select_source.count("RoundedFlag {"), 2)
        for language in ("en", "pt", "es", "de", "ru"):
            flag_source = (QML_ROOT / "flags" / f"{language}.svg").read_text(
                encoding="utf-8"
            )
            self.assertIn('viewBox="0 0 640 480"', flag_source)
            self.assertIn('id="flag-icons-', flag_source)
            self.assertNotIn('id="clarify-rounded"', flag_source)
        self.assertIn('Accessible.name: "Language: "', main_source)
        self.assertIn(
            "readonly property var supportedLanguages: [\n"
            '                                "en", "pt", "es", "de", "ru"\n'
            "                            ]",
            main_source,
        )
        for language, name in (
            ("en", "English"),
            ("pt", "Portuguese"),
            ("es", "Spanish"),
            ("de", "German"),
            ("ru", "Russian"),
        ):
            self.assertIn(f'"{language}": "{name}"', main_source)
        self.assertIn(
            "var currentIndex = supportedLanguages.indexOf(workflow.language)",
            main_source,
        )
        self.assertIn(
            "var nextIndex = (currentIndex + 1) % supportedLanguages.length",
            main_source,
        )
        self.assertNotIn('languageCode === "EN"', main_source)
        self.assertIn(
            "property string languageCode: workflow.language.toUpperCase()",
            main_source,
        )
        self.assertIn(
            'property bool promptMode: workflow.mode === "prompt"', main_source
        )
        self.assertNotIn("languageCode = languageCode ===", main_source)
        self.assertNotIn("homePage.promptMode = !homePage.promptMode", main_source)
        self.assertIn('Accessible.name: "Mode: "', main_source)
        self.assertIn("root.startSystemMove()", main_source)
        self.assertGreaterEqual(main_source.count("DragHandler"), 2)
        self.assertIn("TapHandler", main_source)
        self.assertIn("Layout.fillHeight: true", main_source)
        self.assertIn("settingsScroll.contentItem.contentY = 0", main_source)
        self.assertIn("palette.highlightedText: theme.text", main_source)
        self.assertIn('QQuickStyle.setStyle("Basic")', entrypoint_source)
        self.assertIn("property bool successVisible: false", status_pill_source)
        self.assertIn("readonly property bool requestedVisible", status_pill_source)
        self.assertIn("Behavior on opacity", status_pill_source)
        self.assertIn("interval: 850", status_pill_source)
        self.assertIn('workflow.surface === "success"', status_pill_source)
        self.assertIn("successVisible", status_pill_source)
        self.assertIn("pillStatus.audioLevel", status_pill_source)
        self.assertIn("pillStatus.targetIcon", status_pill_source)
        self.assertIn("Screen.devicePixelRatio", status_pill_source)
        self.assertIn("scale: pill.dpiCompensation", status_pill_source)
        self.assertIn("readonly property int designWidth: 156", status_pill_source)
        self.assertIn("readonly property int designHeight: 46", status_pill_source)
        self.assertIn("sourceSize.width: 64", status_pill_source)
        self.assertIn("Theme { id: theme }", status_pill_source)
        self.assertIn("Repeater", status_pill_source)
        self.assertIn("model: 12", status_pill_source)
        self.assertIn('workflow.surface === "recording"', status_pill_source)
        self.assertIn('workflow.surface === "processing"', status_pill_source)
        self.assertIn("Qt.WindowDoesNotAcceptFocus", status_pill_source)
        self.assertIn("Screen.height - height - 80", status_pill_source)
        self.assertNotIn("StatusPill {", main_source)
        self.assertIn('qml_root / "StatusPill.qml"', entrypoint_source)
        self.assertIn('root.objectName() == "workflowStatusPill"', entrypoint_source)
        self.assertIn("property bool presentationVisible: false", main_source)
        self.assertIn("presentationVisible", entrypoint_source)
        self.assertIn("Behavior on opacity", main_source)
        self.assertNotIn("card.opacity", main_source)
        self.assertNotIn("pages.opacity", main_source)
        self.assertIn("copyResetTimer", main_source)
        self.assertIn("copyResetTimer.restart()", main_source)
        self.assertIn("function onCopyCompleted(success)", main_source)
        self.assertIn("onClicked: workflow.copyResult()", main_source)
        self.assertNotIn("id: resultButton", main_source)
        self.assertNotIn('text: "View"', main_source)
        self.assertNotIn("workflow.showResult()", main_source)
        self.assertIn("onVisibleChanged: resetCopyConfirmation()", main_source)
        self.assertIn('resultPage.copyLabel = "Copy"', main_source)
        self.assertIn("workflow.stopRecording()", main_source)
        self.assertIn("workflow.cancelRecording()", main_source)
        self.assertIn('workflow.surface === "error"', main_source)
        self.assertIn("Dismiss workflow error", main_source)
        self.assertIn("workflow.reset()", main_source)
        self.assertIn("workflow.setLanguage", main_source)
        self.assertIn("workflow.setMode", main_source)
        self.assertIn("workflow.copyResult()", main_source)
        self.assertIn("modelData.text", main_source)
        self.assertIn("SettingsArea", main_source)
        area_source = (QML_ROOT / "SettingsArea.qml").read_text(encoding="utf-8")
        self.assertIn("selectByMouse: true", area_source)
        self.assertIn("audioBatch.copyFile(fileResultRow.modelData.path)", main_source)
        self.assertIn('text: "Select text to reuse"', main_source)
        self.assertNotIn("Global shortcuts and settings will be connected", main_source)
        self.assertIn('objectName: "settingsPage"', main_source)
        self.assertIn('objectName: "settingsSidebar"', main_source)
        self.assertIn('objectName: "settingsSidebarDivider"', main_source)
        button_source = (QML_ROOT / "AppButton.qml").read_text(encoding="utf-8")
        self.assertIn("property int contentAlignment", button_source)
        self.assertIn("property url iconSource", button_source)
        self.assertIn("property int iconSize", button_source)
        self.assertIn("source: control.iconSource", button_source)
        self.assertIn("anchors.verticalCenter: parent.verticalCenter", button_source)
        self.assertIn(
            'x: control.text === "" ? (parent.width - width) / 2 : 0',
            button_source,
        )
        self.assertIn("horizontalAlignment: control.contentAlignment", button_source)
        self.assertIn("contentAlignment: Text.AlignLeft", main_source)
        self.assertIn("readonly property var sectionItems", main_source)
        self.assertIn('iconSource: "icons/" + modelData.icon', main_source)
        self.assertNotIn("iconText", main_source)
        self.assertEqual(main_source.count("SearchSelect {"), 9)
        self.assertNotIn("ComboBox {", main_source)
        self.assertNotIn("TextField {", main_source)
        self.assertNotIn("CheckBox {", main_source)
        self.assertEqual(main_source.count("SettingsField {"), 9)
        self.assertEqual(main_source.count("SettingsSwitch {"), 3)
        self.assertIn(
            "onRefreshRequested: settings.refreshMicrophoneInventory()", main_source
        )
        self.assertNotIn("indicator: Label", main_source)
        self.assertNotIn('text: "⌄"', main_source)
        self.assertNotIn('text: "↻"', main_source)
        indicator_source = (QML_ROOT / "DropdownIndicator.qml").read_text(
            encoding="utf-8"
        )
        self.assertIn('source: "icons/chevron-down.svg"', indicator_source)
        self.assertIn("width: 16", indicator_source)
        self.assertIn("height: 16", indicator_source)
        self.assertNotIn("implicitWidth", indicator_source)
        self.assertNotIn("implicitHeight", indicator_source)
        self.assertIn("required property Theme visualTheme", select_source)
        self.assertIn("required property int index", select_source)
        self.assertIn("required property var modelData", select_source)
        self.assertIn("width: results.width", select_source)
        self.assertIn("highlighted: results.currentIndex === index", select_source)
        icon_dir = QML_ROOT / "icons"
        self.assertTrue(icon_dir.is_dir())
        for icon_name in (
            "settings.svg",
            "keyboard.svg",
            "audio-lines.svg",
            "mic.svg",
            "server.svg",
            "route.svg",
            "sparkles.svg",
            "x.svg",
            "chevron-down.svg",
            "refresh.svg",
        ):
            icon_source = (icon_dir / icon_name).read_text(encoding="utf-8")
            self.assertIn('<svg xmlns="http://www.w3.org/2000/svg"', icon_source)
            self.assertIn('viewBox="0 0 24 24"', icon_source)
            self.assertIn('stroke="#ffffff"', icon_source)
        self.assertIn(
            '{ "label": "Shortcuts", "icon": "keyboard.svg" }',
            main_source,
        )
        self.assertIn(
            '{ "label": "Dictation", "icon": "mic.svg" }',
            main_source,
        )
        self.assertIn("function selectSection(index)", main_source)
        self.assertNotIn("cardFadeTimer", main_source)
        self.assertNotIn("settingsSectionFadeTimer", main_source)
        for section_object in (
            "generalSettingsSection",
            "shortcutSettingsSection",
            "recordingSettingsSection",
            "integrationsSettingsSection",
            "workflowSettingsSection",
        ):
            self.assertIn(f'objectName: "{section_object}"', main_source)
        for section_label in (
            "General",
            "Text",
            "Models & services",
            "Dictation",
            "Cleanup",
            "Rewrite",
            "Translation",
        ):
            self.assertIn(f'"label": "{section_label}"', main_source)
        self.assertNotIn('"label": "Providers"', main_source)
        self.assertNotIn('"label": "Routes"', main_source)
        self.assertNotIn('"label": "Local refinement"', main_source)
        self.assertNotIn("speechWorkflowItems", main_source)
        self.assertIn('objectName: "cleanupContextBox"', main_source)
        self.assertIn('objectName: "advancedRecordingGroup"', main_source)
        self.assertEqual(qml_source.count("LocalModelCard {"), 1)
        self.assertNotIn('text: "Workflow route"', main_source)
        self.assertNotIn('text: "Scope"', main_source)
        self.assertIn("function selectWorkflowScope(scope)", main_source)
        self.assertIn(
            "settingsPage.workflowDescription(settings.selectedScope)", main_source
        )
        self.assertIn(
            "settingsPage.workflowToggleLabel(settings.selectedScope)", main_source
        )
        self.assertIn("settings.providerName(id)", main_source)
        tab_start = main_source.index('objectName: "textWorkflowTabs"')
        tab_end = main_source.index("SettingsRow {", tab_start)
        tab_source = main_source[tab_start:tab_end]
        self.assertNotIn("Layout.fillWidth: true", tab_source)
        self.assertNotIn("iconSource:", tab_source)
        self.assertNotIn("iconSize:", tab_source)
        self.assertIn(
            "Layout.preferredWidth: tabTextMetrics.advanceWidth + 20", tab_source
        )
        self.assertIn("TextMetrics", tab_source)
        recording_title = 'title: "Audio"'
        recording_section = main_source[
            main_source.index("id: recordingSettingsSection") :
        ]
        recording_title_index = recording_section.index(recording_title)
        self.assertNotIn("height: 1", recording_section[:recording_title_index])
        for binding in (
            "settings.mode",
            "settings.language",
            "settings.autostart",
            "settings.historyEnabled",
            "settings.historyRetentionDays",
            "settings.microphoneDevices",
            "settings.selectedMicrophoneId",
            "settings.microphoneStatus",
            "settings.microphoneTestStatus",
            "settings.recordingControls",
            "settings.refreshMicrophoneInventory()",
            "settings.testMicrophone()",
            "settings.setRecordingControls",
            "settings.selectedScope",
            "settings.routeProviderId",
            "settings.routeModelId",
            "settings.routePrompt",
            "settings.routeCustomEndpoint",
            "settings.routeEnabled",
            "settings.providerIds",
            "settings.selectedProviderId",
            "settings.providerApiKey",
            "settings.providerBaseUrl",
            "settings.validateProvider()",
            "settings.installLocalAsr()",
            "settings.removeLocalAsr()",
            "settings.lastError",
            "settings.dirty",
            "settings.load()",
            "settings.save()",
            "settings.hotkeyActions",
            "settings.captureHotkey",
            "settings.resetHotkey",
            "settings.resetAllHotkeys",
            "settings.setHotkeyActivationMode",
            "hotkeyCaptureItem.forceActiveFocus()",
        ):
            self.assertIn(
                binding, qml_source.replace("settingsController.", "settings.")
            )
        self.assertIn(
            "def hotkeyDefinitions",
            (SPIKE / "qml_settings.py").read_text(encoding="utf-8"),
        )
        self.assertIn("settings.hotkeyCaptureAction", main_source)
        self.assertIn('title: "Shortcuts"', main_source)
        self.assertIn('workflow.surface === "translation_picker"', main_source)
        self.assertIn('objectName: "translationPickerPage"', main_source)
        self.assertIn("workflow.translationOptions", main_source)
        self.assertIn("workflow.chooseTranslation(modelData.code)", main_source)
        self.assertIn("workflow.cancelTranslation()", main_source)
        self.assertNotIn("Alt+L", main_source)

    def test_qml_entrypoint_uses_qt_quick_and_stays_production_isolated(self):
        source = (SPIKE / "qml_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])

        self.assertIn("PySide6", imported_roots)
        self.assertNotIn("app", imported_roots)
        self.assertNotIn("provider_adapters", imported_roots)
        self.assertNotIn("provider_registry", imported_roots)
        self.assertNotIn("requests", imported_roots)
        self.assertNotIn("sounddevice", imported_roots)
        self.assertNotIn("windows_hotkeys", imported_roots)
        self.assertNotIn("windows_clipboard", imported_roots)
        self.assertIn("QQmlApplicationEngine", source)
        self.assertIn("QApplication", source)
        self.assertNotIn("QGuiApplication", source)
        self.assertIn("QSystemTrayIcon", source)
        self.assertIn("QIcon", source)
        self.assertIn("_branding_icon_path", source)
        self.assertIn("branding_icon = _load_branding_icon()", source)
        self.assertIn("icon=branding_icon", source)
        self.assertIn("QmlStatusPillController", source)
        self.assertIn("_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]", source)
        self.assertIn("sys.path.insert(0, str(_REPOSITORY_ROOT))", source)
        self.assertIn("create_real_workflow_runtime", source)
        self.assertIn("QmlSettingsController", source)
        self.assertIn("loaded_config = repositories.config.load()", source)
        self.assertIn("app_config=loaded_config", source)
        self.assertIn('setContextProperty("settings", settings)', source)
        self.assertIn("runtime.repositories", source)
        self.assertIn("QtShell", source)
        self.assertIn("WindowsGlobalHotkeyBackend", source)
        self.assertIn('if sys.platform == "win32"', source)
        self.assertIn("shell.hotkeyTriggered.connect(bridge.handleHotkey)", source)
        self.assertIn("_connect_preference_sync(bridge, settings)", source)
        self.assertIn("settings.configChanged.connect", source)
        self.assertIn("syncing_from_settings", source)
        self.assertIn("settings.persistMode", source)
        self.assertIn("settings.persistLanguage", source)
        self.assertIn("bridge.modeChanged.connect", source)
        self.assertIn("bridge.languageChanged.connect", source)
        self.assertIn("_show_translation_picker_if_needed", source)
        self.assertIn("tray_available=tray_available", source)
        self.assertIn("ShellStartResult.SECONDARY_INSTANCE", source)
        self.assertIn("QmlWorkflowBridge(", source)
        self.assertIn("dispatch_runner=scheduler.run_dispatch", source)
        self.assertIn("copy_runner=runtime.copy_result", source)
        self.assertIn("QtStatisticsGateway", source)
        self.assertIn(
            "on_usage=partial(_record_voice_translation_usage, usage_statistics)",
            source,
        )
        self.assertIn(
            "microphone_backend=runtime.recording_audio.recorder",
            source,
        )
        self.assertIn("hotkey_applier=apply_qml_hotkeys", source)
        self.assertIn("hotkeys.reconfigure(settings)", source)
        self.assertIn("app.aboutToQuit.connect(shell.stop)", source)
        self.assertIn("app.aboutToQuit.connect(runtime.shutdown)", source)
        self.assertIn("app.aboutToQuit.connect(settings.shutdown)", source)
        self.assertLess(
            source.index("app.aboutToQuit.connect(shell.stop)"),
            source.index("app.aboutToQuit.connect(runtime.shutdown)"),
        )
        self.assertLess(source.index("engine.rootObjects()"), source.index("QtShell("))
        self.assertIn("_start_shell_if_available", source)
        self.assertNotIn("FakeWorkflow", source)
        self.assertNotIn("--fake", source)

    @unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
    def test_escape_hotkey_sync_tracks_recording_surface(self):
        class Bridge:
            surface = "idle"

        class Hotkeys:
            def __init__(self):
                self.states = []

            def set_recording_active(self, active):
                self.states.append(active)

        bridge = Bridge()
        hotkeys = Hotkeys()

        _sync_recording_escape_hotkey(bridge, hotkeys)
        bridge.surface = "recording"
        _sync_recording_escape_hotkey(bridge, hotkeys)
        bridge.surface = "processing"
        _sync_recording_escape_hotkey(bridge, hotkeys)

        self.assertEqual(hotkeys.states, [False, True, False])

    @unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
    def test_branding_icon_loads_from_source_and_frozen_bundle_paths(self):
        self._qt_app = QApplication.instance() or QApplication([])
        source_icon = ROOT / "assets" / "branding" / "clarify.ico"
        self.assertEqual(_branding_icon_path(), source_icon)
        source_qicon = _load_branding_icon()
        self.assertIsInstance(source_qicon, QIcon)
        self.assertFalse(source_qicon.isNull())

        with tempfile.TemporaryDirectory() as temporary_directory:
            bundle_root = Path(temporary_directory)
            frozen_icon = bundle_root / "assets" / "branding" / "clarify.ico"
            frozen_icon.parent.mkdir(parents=True)
            shutil.copyfile(source_icon, frozen_icon)
            with (
                patch.object(qml_app.sys, "_MEIPASS", str(bundle_root), create=True),
                patch.object(qml_app.sys, "frozen", True, create=True),
            ):
                self.assertEqual(_branding_icon_path(), frozen_icon)
                frozen_qicon = _load_branding_icon()

            self.assertIsInstance(frozen_qicon, QIcon)
            self.assertFalse(frozen_qicon.isNull())

    @unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
    def test_qml_assets_load_from_source_and_frozen_bundle_paths(self):
        self.assertEqual(_qml_root(), QML_ROOT)

        with tempfile.TemporaryDirectory() as temporary_directory:
            bundle_root = Path(temporary_directory)
            frozen_qml = bundle_root / "qml"
            frozen_qml.mkdir()
            shutil.copyfile(QML_ROOT / "Main.qml", frozen_qml / "Main.qml")
            with (
                patch.object(qml_app.sys, "_MEIPASS", str(bundle_root), create=True),
                patch.object(qml_app.sys, "frozen", True, create=True),
            ):
                self.assertEqual(_qml_root(), frozen_qml)

    def test_qml_bridge_hydrates_persisted_preferences(self):
        bridge_source = (SPIKE / "qml_bridge.py").read_text(encoding="utf-8")
        self.assertIn("app_config: Any | None = None", bridge_source)
        self.assertIn("saved_config = current_config()", bridge_source)
        self.assertIn('getattr(ui_preferences, "mode", "prompt")', bridge_source)
        self.assertIn('getattr(ui_preferences, "language", "en")', bridge_source)
        self.assertIn("def mode(self) -> str:", bridge_source)
        self.assertIn("def language(self) -> str:", bridge_source)
        self.assertIn(
            "StartDictation(target, self._mode, self._language)", bridge_source
        )

        main_source = (QML_ROOT / "Main.qml").read_text(encoding="utf-8")
        self.assertIn(
            'property bool promptMode: workflow.mode === "prompt"', main_source
        )
        self.assertIn(
            "property string languageCode: workflow.language.toUpperCase()",
            main_source,
        )
        self.assertNotIn("languageCode = languageCode ===", main_source)
        self.assertNotIn("homePage.promptMode = !homePage.promptMode", main_source)

    def test_qml_runtime_uses_ui_free_adapters(self):
        for filename in ("qml_bridge.py", "qml_runtime.py"):
            source = (SPIKE / filename).read_text(encoding="utf-8")
            tree = ast.parse(source)
            top_level_imports = set()
            for node in tree.body:
                if isinstance(node, ast.Import):
                    top_level_imports.update(
                        alias.name.split(".")[0] for alias in node.names
                    )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top_level_imports.add(node.module.split(".")[0])
            self.assertNotIn("app", top_level_imports, filename)
            self.assertNotIn("customtkinter", top_level_imports, filename)
            self.assertNotIn("tkinter", top_level_imports, filename)

        runtime_source = (SPIKE / "qml_runtime.py").read_text(encoding="utf-8")
        for symbol in (
            "QtProviderGateway",
            "QtRecordingAudioGateway",
            "QtWorkflowRuntime",
            "QtClipboardGateway",
            "QtStatisticsGateway",
        ):
            self.assertIn(f"class {symbol}", runtime_source)
        self.assertIn("self.repositories = repositories", runtime_source)
        self.assertIn("repositories=active", runtime_source)
        self.assertIn("PROVIDER_REGISTRY", runtime_source)
        self.assertIn("QmlClipboardGateway", runtime_source)
        self.assertNotIn("import app", runtime_source)
        self.assertNotIn("to_legacy_mapping", runtime_source)

    def test_qml_bridge_routes_native_hotkeys_to_real_commands(self):
        bridge_source = (SPIKE / "qml_bridge.py").read_text(encoding="utf-8")
        self.assertIn("def handleHotkey(self, action: str) -> bool:", bridge_source)
        self.assertIn('normalized == "recording_hotkey"', bridge_source)
        self.assertIn('normalized == "rewrite_hotkey"', bridge_source)
        self.assertIn('normalized == "translation_hotkey"', bridge_source)
        self.assertIn("def _run_when_ready", bridge_source)
        self.assertIn("_pending_workflow_action", bridge_source)
        self.assertIn("StartRewrite(target)", bridge_source)
        self.assertIn("StartTranslation(target)", bridge_source)
        self.assertIn("CancelTranslation()", bridge_source)
        self.assertIn("ChooseTranslationLanguage", bridge_source)
        self.assertIn(
            "def chooseTranslation(self, language: str) -> bool:", bridge_source
        )
        self.assertIn("def cancelTranslation(self) -> bool:", bridge_source)
        self.assertIn(
            "def translationOptions(self) -> list[dict[str, str]]:", bridge_source
        )
        self.assertIn('return "translation_picker"', bridge_source)

    def test_real_entrypoint_has_no_fake_or_legacy_runtime(self):
        source = (SPIKE / "qml_app.py").read_text(encoding="utf-8")
        runtime_source = (SPIKE / "qml_runtime.py").read_text(encoding="utf-8")
        self.assertIn("QtRuntimeError", source)
        self.assertNotIn("FakeWorkflow", source)
        self.assertNotIn("legacy_adapters", runtime_source)
        self.assertNotIn("QmlRuntimeUnavailableError", runtime_source)
        self.assertIn("_hidden_start_requested", source)
        self.assertIn("presentationVisible", source)

    @unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
    def test_qml_entrypoint_accepts_only_the_supported_hidden_start_flag(self):
        self.assertFalse(_hidden_start_requested([]))
        self.assertTrue(_hidden_start_requested(["--hidden"]))
        with self.assertRaises(ValueError):
            _hidden_start_requested(["--compat"])

    @unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
    def test_voice_translation_usage_callback_records_both_legs(self):
        class UsageRepository:
            def __init__(self):
                self.events = []

            def append(self, event):
                self.events.append(event)

        usage_repository = UsageRepository()
        statistics = qml_app.QtStatisticsGateway(
            SimpleNamespace(usage_stats=usage_repository)
        )
        config = SimpleNamespace(
            route=SimpleNamespace(provider_id="openai", model_id="gpt-4o-mini"),
            target_language="en-US",
        )
        state = SimpleNamespace(
            transcription_provider="gemini",
            transcription_model="gemini-audio",
            raw_transcript="Olá",
            translated_text="Hello",
        )

        _record_voice_translation_usage(statistics, config, state, 12.5)

        self.assertEqual(len(usage_repository.events), 1)
        event = usage_repository.events[0]
        self.assertEqual(event["type"], "voice_translation")
        self.assertEqual(event["duration_seconds"], 12.5)
        self.assertEqual(event["target_language"], "en-US")
        self.assertEqual(
            [
                (entry["provider"], entry["model"], entry["purpose"])
                for entry in event["models"]
            ],
            [
                ("gemini", "gemini-audio", "transcription"),
                ("openai", "gpt-4o-mini", "translation"),
            ],
        )


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
class QmlWorkflowBridgeHotkeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    class WorkflowService:
        def __init__(self):
            from workflows import WorkflowState

            self.state = WorkflowState()
            self.commands = []
            self.listeners = []
            self.finish_calls = []

        def subscribe(self, listener):
            self.listeners.append(listener)

        def publish(self, state):
            self.state = state
            for listener in tuple(self.listeners):
                listener(state)

        def dispatch(self, command):
            self.commands.append(command)
            return True

        def finish(self, operation_id):
            from workflows import WorkflowState

            self.finish_calls.append(operation_id)
            self.publish(WorkflowState())
            return True

    class VoiceTranslationController(QObject):
        stateChanged = Signal(object)

        def __init__(self, active):
            super().__init__()
            self.active = active
            self.state = None

    class AudioBatchController(QObject):
        runningChanged = Signal()

        def __init__(self, running):
            super().__init__()
            self.running = running

    def _bridge(self, *, voice_active=False, audio_running=False, handler=None):
        service = self.WorkflowService()
        voice = self.VoiceTranslationController(voice_active)
        audio = self.AudioBatchController(audio_running)
        bridge = QmlWorkflowBridge(
            service,
            voice_translation_handler=handler,
            voice_translation_controller=voice,
            audio_batch_controller=audio,
        )
        return service, bridge

    def test_global_hotkeys_are_blocked_by_voice_or_audio_busy_state(self):
        for busy_kwargs in (
            {"voice_active": True},
            {"audio_running": True},
        ):
            with self.subTest(busy_kwargs=busy_kwargs):
                service, bridge = self._bridge(**busy_kwargs)

                self.assertTrue(bridge.busy)
                for action in (
                    "recording_hotkey",
                    "rewrite_hotkey",
                    "translation_hotkey",
                ):
                    with self.subTest(action=action):
                        self.assertFalse(bridge.handleHotkey(action))
                self.assertEqual(service.commands, [])

    def test_voice_translation_hotkey_stops_active_voice_workflow(self):
        calls = []
        service, bridge = self._bridge(
            voice_active=True,
            handler=lambda: calls.append("toggle"),
        )

        self.assertTrue(bridge.busy)
        self.assertTrue(bridge.handleHotkey("voice_translation_hotkey"))
        self.assertEqual(calls, ["toggle"])
        self.assertEqual(service.commands, [])

    def test_recording_hotkey_stops_active_workflow_even_when_busy(self):
        from workflows import StopDictation, WorkflowPhase, WorkflowState

        service, bridge = self._bridge(audio_running=True)
        service.publish(WorkflowState(phase=WorkflowPhase.RECORDING))

        self.assertTrue(bridge.busy)
        self.assertTrue(bridge.handleHotkey("recording_hotkey"))
        self.assertIsInstance(service.commands[-1], StopDictation)

    def test_terminal_result_is_released_before_next_global_workflow_hotkey(self):
        from workflows import (
            StartDictation,
            StartRewrite,
            StartTranslation,
            WorkflowPhase,
            WorkflowState,
        )

        cases = (
            ("recording_hotkey", StartDictation),
            ("rewrite_hotkey", StartRewrite),
            ("translation_hotkey", StartTranslation),
        )
        for action, command_type in cases:
            with self.subTest(action=action):
                service, bridge = self._bridge()
                service.publish(
                    WorkflowState(
                        phase=WorkflowPhase.COMPLETED,
                        operation_id=17,
                        result_text="previous result",
                    )
                )

                self.assertTrue(bridge.handleHotkey(action))
                self.assertEqual(service.finish_calls, [17])
                self.assertIsInstance(service.commands[-1], command_type)

    def test_completed_workflow_opens_result_surface_immediately(self):
        from workflows import WorkflowPhase, WorkflowState

        service, bridge = self._bridge()
        service.publish(
            WorkflowState(
                phase=WorkflowPhase.COMPLETED,
                operation_id=17,
                result_text="previous result",
            )
        )

        self.assertEqual(bridge.surface, "result")
        self.assertTrue(bridge.canShowResult)


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is an optional QML dependency")
class QmlEntrypointIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_uses_qapplication_and_registers_real_context_properties(self):
        self.assertIsInstance(self.app, QApplication)
        engine = QQmlApplicationEngine()
        workflow = QObject()
        settings = QObject()

        _register_qml_context(engine, workflow, settings)

        self.assertIs(engine.rootContext().contextProperty("workflow"), workflow)
        self.assertIs(engine.rootContext().contextProperty("settings"), settings)

    def test_registers_status_pill_context_when_available(self):
        engine = QQmlApplicationEngine()
        workflow = QObject()
        settings = QObject()
        status_pill = QObject()

        _register_qml_context(
            engine,
            workflow,
            settings,
            status_pill=status_pill,
        )

        self.assertIs(
            engine.rootContext().contextProperty("pillStatus"),
            status_pill,
        )

    def test_status_pill_samples_live_level_and_refreshes_target_icon(self):
        class Bridge(QObject):
            recordingChanged = Signal()
            targetExecutableChanged = Signal()

            def __init__(self):
                super().__init__()
                self.recording = False
                self.targetExecutable = ""

        bridge = Bridge()
        recorder = SimpleNamespace(mic_level=0.0)
        resolved = []
        controller = QmlStatusPillController(
            bridge,
            recorder,
            fallback_icon=QIcon(),
            icon_resolver=lambda executable: (
                resolved.append(executable) or f"icon:{executable}"
            ),
        )

        bridge.targetExecutable = "C:/Windows/notepad.exe"
        bridge.targetExecutableChanged.emit()
        self.assertEqual(controller.targetIcon, "icon:C:/Windows/notepad.exe")

        bridge.recording = True
        bridge.recordingChanged.emit()
        recorder.mic_level = 0.8
        controller._sample_level()
        self.assertGreater(controller.audioLevel, 0.0)

        bridge.recording = False
        bridge.recordingChanged.emit()
        self.assertEqual(controller.audioLevel, 0.0)

    def test_status_pill_prefers_packaged_high_resolution_icon_asset(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "Example.Package"
            executable = package / "bin" / "Example.exe"
            assets = package / "assets"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"MZ")
            assets.mkdir()
            source = assets / "Square44x44Logo.targetsize-64_altform-unplated.png"
            Image.new("RGBA", (128, 128), (24, 96, 220, 255)).save(source)

            icon = _packaged_app_icon(str(executable))

        self.assertIsNotNone(icon)
        assert icon is not None
        self.assertEqual(icon.size, (64, 64))
        self.assertEqual(icon.getchannel("A").getbbox(), (4, 4, 60, 60))
        self.assertTrue(_pillow_data_url(icon).startswith("data:image/png;base64,"))

    def test_transient_workflow_hides_and_restores_visible_main_window(self):
        class Bridge(QObject):
            surfaceChanged = Signal()

            def __init__(self):
                super().__init__()
                self.surface = "idle"

        class Window:
            def __init__(self):
                self.visible = True
                self.hide_calls = 0

            def isVisible(self):
                return self.visible

            def hide(self):
                self.visible = False
                self.hide_calls += 1

        class Shell:
            def __init__(self, window):
                self.window = window
                self.show_calls = 0

            def hide_window(self):
                self.window.hide()

            def show_window(self):
                self.window.visible = True
                self.show_calls += 1

        bridge = Bridge()
        window = Window()
        shell = Shell(window)
        coordinator = _WorkflowWindowVisibility(bridge, shell, window)

        bridge.surface = "recording"
        bridge.surfaceChanged.emit()
        self.assertEqual(window.hide_calls, 1)
        self.assertFalse(window.visible)

        bridge.surface = "processing"
        bridge.surfaceChanged.emit()
        self.assertEqual(shell.show_calls, 0)

        bridge.surface = "success"
        bridge.surfaceChanged.emit()
        self.assertEqual(shell.show_calls, 1)
        self.assertTrue(window.visible)
        self.assertIsNotNone(coordinator)

    def test_shutdown_connections_stop_shell_before_runtime(self):
        events = []

        class Shell(QObject):
            def stop(self):
                events.append("shell")

        class Runtime:
            def shutdown(self):
                events.append("runtime")

        shell = Shell()
        runtime = Runtime()
        _connect_shutdown(self.app, shell, runtime)
        QTimer.singleShot(0, self.app.quit)
        self.app.exec()

        self.assertEqual(events[-2:], ["shell", "runtime"])

    def test_terminal_feedback_does_not_activate_main_window(self):
        from workflows import WorkflowState, WorkflowPhase

        service = SimpleNamespace(state=WorkflowState(), subscribe=lambda fn: None)
        bridge = QmlWorkflowBridge(service)
        window = SimpleNamespace(isVisible=lambda: False)
        shell = SimpleNamespace(hide_window=lambda: None, show_window=Mock())
        coordinator = _WorkflowWindowVisibility(bridge, shell, window)
        for phase in (
            WorkflowPhase.RECORDING,
            WorkflowPhase.PROCESSING,
            WorkflowPhase.FAILED,
        ):
            bridge._on_workflow_state(
                WorkflowState(phase=phase, can_retry=phase is WorkflowPhase.FAILED)
            )
        self.assertTrue(bridge.feedbackVisible)
        self.assertTrue(bridge.canRetryTranscription)
        shell.show_window.assert_not_called()
        bridge._on_workflow_state(
            WorkflowState(phase=WorkflowPhase.COMPLETED, result_text="fixture")
        )
        self.assertFalse(bridge.feedbackVisible)
        shell.show_window.assert_not_called()
        requested = []
        bridge.resultRequested.connect(lambda: requested.append(True))
        bridge.showResult()
        self.assertEqual(requested, [True])
        self.assertFalse(bridge.feedbackVisible)
        self.assertIsNotNone(coordinator)

    def test_empty_selection_then_repeated_hotkeys_keep_editor_focus(self):
        from test_workflows import (
            FakeAudio,
            FakeClipboard,
            FakeClock,
            FakeConfig,
            FakeProvider,
            FakeStatistics,
            ImmediateScheduler,
        )
        from workflows import WorkflowPhase, WorkflowService

        clipboard = FakeClipboard()
        clipboard.selected = ""
        statistics = FakeStatistics()
        service = WorkflowService(
            FakeProvider(),
            FakeAudio(),
            clipboard,
            FakeConfig(),
            statistics,
            ImmediateScheduler(),
            FakeClock(),
        )
        bridge = QmlWorkflowBridge(service, target_provider=clipboard.capture_target)
        visible = [True]

        def show_main():
            visible[0] = True
            clipboard.selected = ""  # Activating Clarify loses the editor selection.

        shell = SimpleNamespace(
            hide_window=lambda: visible.__setitem__(0, False),
            show_window=Mock(side_effect=show_main),
        )
        coordinator = _WorkflowWindowVisibility(
            bridge, shell, SimpleNamespace(isVisible=lambda: visible[0])
        )
        self.assertTrue(bridge.handleHotkey("rewrite_hotkey"))
        self.assertEqual(service.state.status_key, "no_selection")
        failed_id = service.state.operation_id
        for selection in ("First new selection", "Second new selection"):
            clipboard.selected = selection
            self.assertTrue(bridge.handleHotkey("rewrite_hotkey"))
            self.assertEqual(service.state.phase, WorkflowPhase.COMPLETED)
            self.assertFalse(bridge.transitionPending)
            shell.show_window.assert_not_called()
        self.assertEqual(len(statistics.rewrites), 2)
        bridge.dismissFeedback(failed_id)
        self.assertEqual(service.state.phase, WorkflowPhase.COMPLETED)
        self.assertIsNotNone(coordinator)

    def test_feedback_expiry_releases_only_its_own_non_retryable_error(self):
        from workflows import WorkflowPhase, WorkflowState

        service = QmlWorkflowBridgeHotkeyTests.WorkflowService()
        bridge = QmlWorkflowBridge(service)
        service.publish(
            WorkflowState(
                phase=WorkflowPhase.FAILED, operation_id=9, status_key="no_selection"
            )
        )
        bridge.dismissFeedback(8)
        self.assertEqual(service.finish_calls, [])
        bridge.dismissFeedback(9)
        self.assertEqual(service.state.phase, WorkflowPhase.READY)
        service.publish(
            WorkflowState(
                phase=WorkflowPhase.FAILED,
                operation_id=10,
                status_key="transcription_network",
                can_retry=True,
            )
        )
        bridge.dismissFeedback(10)
        self.assertTrue(bridge.canRetryTranscription)
        self.assertEqual(service.finish_calls, [9])

    def test_preferences_sync_persists_home_changes_and_keeps_settings_as_draft(self):
        from repositories import AppConfig
        from workflows import StartDictation, WorkflowState

        class ConfigRepository:
            def __init__(self, config):
                self.config = config
                self.applied = []

            def load(self):
                return self.config

            def apply(self, config):
                self.config = config
                self.applied.append(config)
                return config

        class Repositories:
            def __init__(self, config):
                self.config = config

        class WorkflowService:
            def __init__(self):
                self.state = WorkflowState()
                self.listeners = []
                self.commands = []

            def subscribe(self, listener):
                self.listeners.append(listener)

            def dispatch(self, command):
                self.commands.append(command)
                return True

        initial = AppConfig.from_mapping(
            {
                "ui_mode": "prompt",
                "ui_language": "en",
                "autostart": False,
                "history_enabled": False,
                "workflows": {
                    "rewrite": {
                        "provider_id": "openai",
                        "model_id": "gpt-4o-mini",
                        "prompt": "Persisted prompt",
                        "enabled": True,
                    }
                },
            }
        )
        config_repository = ConfigRepository(initial)
        settings = QmlSettingsController(Repositories(config_repository))
        service = WorkflowService()
        bridge = QmlWorkflowBridge(service, app_config=initial)
        _connect_preference_sync(bridge, settings)

        settings.setMode("transcription")
        settings.setLanguage("pt")
        settings.selectWorkflow("rewrite")
        settings.setRoutePrompt("Draft prompt")
        settings.setHistoryEnabled(True)
        settings.setAutostart(True)
        self.assertEqual(config_repository.applied, [])
        bridge.startRecording()

        self.assertIsInstance(service.commands[-1], StartDictation)
        self.assertEqual(service.commands[-1].mode, "transcription")
        self.assertEqual(service.commands[-1].language, "pt")

        bridge.setMode("prompt")
        bridge.setLanguage("de")
        self.assertEqual(settings.mode, "prompt")
        self.assertEqual(settings.language, "de")
        self.assertEqual(len(config_repository.applied), 2)
        reloaded = QmlSettingsController(Repositories(config_repository))
        self.assertEqual(reloaded.mode, "prompt")
        self.assertEqual(reloaded.language, "de")
        self.assertFalse(reloaded.autostart)
        self.assertFalse(reloaded.historyEnabled)
        self.assertEqual(reloaded.routeFor("rewrite")["prompt"], "Persisted prompt")
        self.assertEqual(settings.routePrompt, "Draft prompt")
        self.assertTrue(settings.autostart)
        self.assertTrue(settings.historyEnabled)

        settings.setMode("transcription")
        settings.setLanguage("pt")
        self.assertEqual(bridge.mode, "transcription")
        self.assertEqual(bridge.language, "pt")
        self.assertTrue(settings.dirty)
        self.assertEqual(len(config_repository.applied), 2)

        self.assertTrue(settings.save())
        self.assertEqual(len(config_repository.applied), 3)
        persisted = config_repository.load()
        self.assertEqual(persisted.ui.mode, "transcription")
        self.assertEqual(persisted.ui.language, "pt")

    def test_translation_picker_reveals_a_window_hidden_by_the_tray(self):
        class Bridge(QObject):
            surfaceChanged = Signal()

            def __init__(self):
                super().__init__()
                self.surface = "idle"

        class Shell:
            def __init__(self):
                self.show_calls = 0

            def show_window(self):
                self.show_calls += 1

        bridge = Bridge()
        shell = Shell()
        bridge.surfaceChanged.connect(
            lambda: _show_translation_picker_if_needed(bridge, shell)
        )

        bridge.surface = "translation_picker"
        bridge.surfaceChanged.emit()

        self.assertEqual(shell.show_calls, 1)

    def test_shell_failure_is_distinguished_from_secondary_and_tray_absence(self):
        class Shell:
            def __init__(self):
                self.stop_calls = 0
                self.start_calls = []

            def start(self, *, tray_available):
                self.start_calls.append(tray_available)
                raise RuntimeError("event filter failed")

            def stop(self):
                self.stop_calls += 1

        shell = Shell()
        with patch(
            "spikes.pyside6.qml_app.QSystemTrayIcon.isSystemTrayAvailable",
            return_value=True,
        ):
            result = _start_shell_if_available(shell)
        self.assertIs(result, ShellStartResult.SETUP_FAILED)
        self.assertEqual(shell.stop_calls, 0)

        class NoTrayShell:
            def __init__(self):
                self.start_calls = []

            def start(self, *, tray_available):
                self.start_calls.append(tray_available)
                return True

        shell = NoTrayShell()
        with patch(
            "spikes.pyside6.qml_app.QSystemTrayIcon.isSystemTrayAvailable",
            return_value=False,
        ):
            result = _start_shell_if_available(shell)
        self.assertIs(result, ShellStartResult.STARTED_WITHOUT_TRAY)
        self.assertEqual(shell.start_calls, [False])

        class SecondaryShell:
            def start(self, *, tray_available):
                return False

        with patch(
            "spikes.pyside6.qml_app.QSystemTrayIcon.isSystemTrayAvailable",
            return_value=True,
        ):
            result = _start_shell_if_available(SecondaryShell())
        self.assertIs(result, ShellStartResult.SECONDARY_INSTANCE)


if __name__ == "__main__":
    unittest.main()
