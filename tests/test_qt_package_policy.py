import unittest
from pathlib import Path

from scripts.qt_package_policy import allowed_qml_destination, unexpected_qt_payload


class QtPackagePolicyTests(unittest.TestCase):
    def test_runtime_imports_and_control_styles_are_retained(self):
        for module in (
            "QtQml",
            "QtQml/Models",
            "QtQuick",
            "QtQuick/Controls/Basic",
            "QtQuick/Controls/Fusion/impl",
            "QtQuick/Layouts",
            "QtQuick/Dialogs",
        ):
            with self.subTest(module=module):
                self.assertTrue(allowed_qml_destination("PySide6/qml/" + module))
                self.assertTrue(allowed_qml_destination("PySide6/Qt/qml/" + module))

    def test_unused_modules_fail_closed(self):
        for module in (
            "QtQuick3D",
            "QtQuick/VirtualKeyboard",
            "QtGraphs",
            "QtCharts",
            "QtQuick/Timeline",
            "QtWebEngine",
            "QtFutureModule",
        ):
            self.assertFalse(allowed_qml_destination("PySide6/qml/" + module))
            self.assertTrue(
                unexpected_qt_payload(["PySide6/qml/" + module + "/qmldir"])
            )
        self.assertFalse(allowed_qml_destination("PySide6/QtQuick"))

    def test_archive_check_catches_dlls_independent_of_qml_plugins(self):
        names = [
            r"PySide6\Qt6Graphs.dll",
            r"PySide6\Qt6Quick3DRuntimeRender.dll",
            r"PySide6\Qt6VirtualKeyboard.dll",
            r"PySide6\Qt6Core.dll",
            r"PySide6\qml\QtQuick\qmldir",
            r"PySide6\qml\QtQml\Models\modelsplugin.dll",
        ]
        self.assertEqual(unexpected_qt_payload(names), sorted(names[:3]))

    def test_both_build_paths_use_the_policy_hook_and_payload_verification(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("build.ps1", "deploy.ps1"):
            script = (root / "scripts" / name).read_text()
            self.assertIn('"--additional-hooks-dir"', script)
            self.assertIn("check_settings_payload.py", script)


if __name__ == "__main__":
    unittest.main()
