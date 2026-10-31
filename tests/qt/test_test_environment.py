"""Protect focused test runs from profiles and swallowed application imports."""

from importlib.util import find_spec
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]


class TestEnvironmentTests(unittest.TestCase):
    @unittest.skipUnless(
        find_spec("PySide6"), "Qt is required for import fault injection"
    )
    def test_qt_application_import_failures_are_not_dependency_skips(self):
        cases = (
            ("test_pyside6_qml.py", "clarify.desktop.qml_app"),
            ("test_pyside6_qml_settings.py", "clarify.desktop.qml_settings"),
            ("test_pyside6_qml_audio_batch.py", "clarify.desktop.qml_audio_batch"),
            ("test_pyside6_qt_shell.py", "clarify.desktop.qt_shell"),
            ("test_refinement_recovery.py", "clarify.desktop.qml_runtime"),
        )
        script = r"""
import importlib.abc, pathlib, runpy, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtWidgets import QApplication
class BrokenApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == sys.argv[3]:
            raise ImportError("synthetic application import failure")
sys.meta_path.insert(0, BrokenApplication())
try:
    runpy.run_path(str(pathlib.Path(sys.argv[1]) / "tests" / "qt" / sys.argv[2]))
except ImportError as error:
    if str(error) != "synthetic application import failure":
        raise
else:
    raise SystemExit("Application error was converted to a dependency skip")
"""
        for filename, module in cases:
            with self.subTest(filename=filename):
                result = subprocess.run(
                    [sys.executable, "-B", "-c", script, str(ROOT), filename, module],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
