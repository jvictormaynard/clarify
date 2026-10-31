"""Application style selection uses only a captured executable identity."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from writing_styles import (
    ApplicationWritingStyles,
    WritingStyle,
    WritingStyleConfigurationError,
    windows_executable_key,
)


EDITOR = r"C:\Program Files\Editor\Editor.exe"


class WindowsExecutableIdentityTests(unittest.TestCase):
    def test_full_path_matching_normalizes_case_and_separators(self):
        self.assertEqual(
            windows_executable_key("C:/Program Files/EDITOR/Editor.EXE"),
            r"c:\program files\editor\editor.exe",
        )
        self.assertEqual(
            windows_executable_key(r"\\Server\Share\Editor.exe"),
            r"\\server\share\editor.exe",
        )

    def test_unicode_names_are_retained_without_collapsing_distinct_paths(self):
        self.assertEqual(
            windows_executable_key(r"C:\Aplicações\AÇÃO\编辑器.exe"),
            r"c:\aplicações\ação\编辑器.exe",
        )
        self.assertNotEqual(
            windows_executable_key(r"C:\Apps\Maße.exe"),
            windows_executable_key(r"C:\Apps\Masse.exe"),
        )
        self.assertNotEqual(
            windows_executable_key("C:\\Apps\\Caf\u00e9.exe"),
            windows_executable_key("C:\\Apps\\Cafe\u0301.exe"),
        )

    def test_unknown_and_untrusted_targets_have_no_executable_identity(self):
        invalid = (
            None,
            "",
            "editor.exe",
            r"C:Editor.exe",
            r"\Apps\Editor.exe",
            "https://example.test/editor.exe",
            r"C:\Apps\*.exe",
            r"C:\Apps\Editor.exe:stream",
            r"C:\Apps\Editor.bat",
            "C:\\Apps\\Editor.exe\x00",
            "C:\\Apps\\Ed\nitor.exe",
            r"\\?\C:\Apps\Editor.exe",
            r"\\.\C:\Apps\Editor.exe",
            r"C:\Apps\..\Editor.exe",
            r"C:\Apps\.\Editor.exe",
        )
        for executable in invalid:
            with self.subTest(executable=executable):
                self.assertIsNone(windows_executable_key(executable))

    def test_selection_does_not_inspect_or_execute_a_path(self):
        with (
            patch("pathlib.Path.resolve", side_effect=AssertionError("resolve")),
            patch("os.stat", side_effect=AssertionError("stat")),
            patch("builtins.open", side_effect=AssertionError("open")),
            patch("subprocess.Popen", side_effect=AssertionError("execute")),
        ):
            rules = ApplicationWritingStyles().with_rule(EDITOR, WritingStyle.NATURAL)
            self.assertIs(rules.resolve(EDITOR).requested_style, WritingStyle.NATURAL)

    def test_reserved_dos_names_are_rejected_in_files_and_directories(self):
        rules = ApplicationWritingStyles().with_rule(EDITOR, WritingStyle.NATURAL)
        for name in ("NUL", "con", "PRN", "AUX", "COM1", "LPT9", "COM¹", "LPT²"):
            for executable in (rf"C:\Apps\{name}.exe", rf"C:\{name}.data\Editor.exe"):
                with self.subTest(executable=executable):
                    self.assertIsNone(windows_executable_key(executable))
                    self.assertIsNone(rules.resolve(executable).requested_style)
                    with self.assertRaises(WritingStyleConfigurationError):
                        rules.with_rule(executable, WritingStyle.INFORMAL)


if __name__ == "__main__":
    unittest.main()
