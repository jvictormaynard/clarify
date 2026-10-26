"""Application style selection uses only a captured executable identity."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from writing_styles import (
    MAX_APPLICATION_STYLE_RULES,
    ApplicationWritingStyleRule,
    ApplicationWritingStyles,
    WritingStyle,
    WritingStyleConfigurationError,
    WritingStyleDecisionReason,
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


class ApplicationWritingStyleTests(unittest.TestCase):
    def test_absent_unknown_and_unmatched_apps_use_default(self):
        rules = ApplicationWritingStyles().with_rule(EDITOR, WritingStyle.INFORMAL)
        for executable in (None, "editor.exe", r"C:\Other\Editor.exe"):
            with self.subTest(executable=executable):
                self.assertIsNone(rules.resolve(executable).requested_style)

    def test_rules_select_by_full_path_instead_of_executable_name(self):
        rules = (
            ApplicationWritingStyles()
            .with_rule(EDITOR, WritingStyle.INFORMAL)
            .with_rule(r"D:\Other\Editor.exe", WritingStyle.ORGANIZED)
        )
        first = rules.resolve("c:/program files/editor/EDITOR.EXE")
        self.assertEqual(first.executable, r"c:\program files\editor\editor.exe")
        self.assertIs(first.requested_style, WritingStyle.INFORMAL)
        self.assertIs(
            rules.resolve(r"d:\OTHER\editor.exe").requested_style,
            WritingStyle.ORGANIZED,
        )

    def test_editing_rules_only_changes_subsequent_selections(self):
        rules = ApplicationWritingStyles().with_rule(EDITOR, WritingStyle.NATURAL)
        captured = rules.resolve(EDITOR)
        updated = rules.with_rule(EDITOR.upper(), WritingStyle.ORGANIZED)
        self.assertIs(captured.requested_style, WritingStyle.NATURAL)
        self.assertIs(rules.resolve(EDITOR).requested_style, WritingStyle.NATURAL)
        self.assertIs(updated.resolve(EDITOR).requested_style, WritingStyle.ORGANIZED)
        self.assertEqual(len(updated.rules), 1)
        with self.assertRaises(FrozenInstanceError):
            captured.requested_style = WritingStyle.INFORMAL

    def test_removing_a_rule_restores_default_without_changing_other_apps(self):
        other = r"C:\Apps\Chat.exe"
        rules = (
            ApplicationWritingStyles()
            .with_rule(EDITOR, WritingStyle.NATURAL)
            .with_rule(other, WritingStyle.INFORMAL)
        )
        captured = rules.resolve(EDITOR)
        updated = rules.with_rule(EDITOR.upper(), None)
        self.assertIsNone(updated.resolve(EDITOR).requested_style)
        self.assertIs(updated.resolve(other).requested_style, WritingStyle.INFORMAL)
        self.assertIs(captured.requested_style, WritingStyle.NATURAL)
        self.assertEqual(updated.with_rule(EDITOR, None), updated)

    def test_mutating_the_input_list_cannot_change_rules_or_selection(self):
        entries = [ApplicationWritingStyleRule(EDITOR, WritingStyle.ORGANIZED)]
        rules = ApplicationWritingStyles(entries)
        captured = rules.resolve(EDITOR)
        entries.clear()
        self.assertEqual(len(rules.rules), 1)
        self.assertIsInstance(rules.rules, tuple)
        self.assertIs(captured.requested_style, WritingStyle.ORGANIZED)

    def test_rule_creation_rejects_invalid_targets_and_cleanup_ids(self):
        for executable in ("editor.exe", "", r"C:\Apps\*.exe"):
            with self.subTest(executable=executable):
                with self.assertRaises(WritingStyleConfigurationError):
                    ApplicationWritingStyleRule(executable, WritingStyle.NATURAL)
        for style in ("preserve", "light", "clarity", "default", "custom", None):
            with self.subTest(style=style):
                with self.assertRaises(WritingStyleConfigurationError):
                    ApplicationWritingStyleRule(EDITOR, style)

    def test_duplicate_normalized_app_rules_are_rejected(self):
        with self.assertRaises(WritingStyleConfigurationError) as raised:
            ApplicationWritingStyles(
                (
                    ApplicationWritingStyleRule(EDITOR, WritingStyle.NATURAL),
                    ApplicationWritingStyleRule(EDITOR.upper(), WritingStyle.INFORMAL),
                )
            )
        self.assertEqual(raised.exception.code, "duplicate_application_rule")

    def test_rule_limit_allows_replacement_and_removal_at_capacity(self):
        rules = ApplicationWritingStyles(
            tuple(
                ApplicationWritingStyleRule(
                    rf"C:\Apps\Editor{index}.exe", WritingStyle.NATURAL
                )
                for index in range(MAX_APPLICATION_STYLE_RULES)
            )
        )
        updated = rules.with_rule(r"C:\Apps\Editor0.exe", WritingStyle.INFORMAL)
        self.assertEqual(len(updated.rules), MAX_APPLICATION_STYLE_RULES)
        with self.assertRaises(WritingStyleConfigurationError) as raised:
            updated.with_rule(EDITOR, WritingStyle.NATURAL)
        self.assertEqual(raised.exception.code, "too_many_application_rules")
        self.assertEqual(
            len(updated.with_rule(r"C:\Apps\Editor0.exe", None).rules),
            MAX_APPLICATION_STYLE_RULES - 1,
        )


class WritingStyleEligibilityTests(unittest.TestCase):
    def test_default_is_explicit_and_requests_no_style(self):
        selection = ApplicationWritingStyles().resolve(EDITOR)
        for allowed in (False, True):
            with self.subTest(generative_allowed=allowed):
                decision = selection.for_refinement(generative_allowed=allowed)
                self.assertIsNone(decision.style)
                self.assertIs(decision.reason, WritingStyleDecisionReason.DEFAULT)

    def test_style_needs_existing_permission_for_generative_refinement(self):
        for style in WritingStyle:
            with self.subTest(style=style):
                selection = (
                    ApplicationWritingStyles().with_rule(EDITOR, style).resolve(EDITOR)
                )
                denied = selection.for_refinement(generative_allowed=False)
                self.assertIsNone(denied.style)
                self.assertIs(
                    denied.reason, WritingStyleDecisionReason.REFINEMENT_NOT_ALLOWED
                )
                self.assertIs(selection.requested_style, style)
                eligible = selection.for_refinement(generative_allowed=True)
                self.assertIs(eligible.style, style)
                self.assertIs(eligible.reason, WritingStyleDecisionReason.SELECTED)

    def test_non_boolean_permission_cannot_enable_a_style(self):
        selection = (
            ApplicationWritingStyles()
            .with_rule(EDITOR, WritingStyle.INFORMAL)
            .resolve(EDITOR)
        )
        for allowed in ("false", "clarity", 1, None):
            with self.subTest(generative_allowed=allowed):
                with self.assertRaises(TypeError):
                    selection.for_refinement(generative_allowed=allowed)


if __name__ == "__main__":
    unittest.main()
