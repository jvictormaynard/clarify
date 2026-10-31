"""Production settings RPC and draft capture, with private temporary profiles."""

import time
import os
import subprocess
import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace


from provider_types import RewriteResult
from text_actions import TextAction


from tests.support.qml_text_actions import (
    QmlTextActionFixture,
)


class QmlTextActionTests(QmlTextActionFixture, unittest.TestCase):
    def test_production_qml_menu_uses_saved_ids_and_keyboard_selection(self):
        root = Path(__file__).resolve().parents[2]
        temporary = TemporaryDirectory(prefix="clarify-qt-images-")
        self.addCleanup(temporary.cleanup)
        artifacts = Path(os.environ.get("CLARIFY_TEST_ARTIFACTS_DIR", temporary.name))
        result = subprocess.run(
            [
                sys.executable,
                str(root / "tests/support/qml_model_settings_smoke.py"),
                "--text-actions-only",
                str(artifacts / "text-actions"),
            ],
            cwd=root,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: saved text action menu", result.stdout)

    def test_full_snapshot_is_independent_of_workflow_selection_and_allowlist_is_typed(
        self,
    ):
        first = self.request("snapshot")["result"]
        self.assertEqual(
            [a["id"] for a in first["textActions"]], ["rewrite", "translation"]
        )
        self.assertEqual(len(first["textActionProfiles"]), 3)
        self.assertTrue(first["textActionsRevision"])
        self.request("selectWorkflow", "translation")
        second = self.request("snapshot")["result"]
        for key in (
            "textActions",
            "textActionProfiles",
            "textActionContext",
            "textActionsRevision",
        ):
            self.assertEqual(first[key], second[key])
        self.assertIn(
            "error", self.request("saveTextAction", {}, first["textActionContext"], 0)
        )
        self.assertIn(
            "error",
            self.request(
                "previewTextAction",
                "rewrite",
                "Sample",
                first["textActionContext"],
                True,
            ),
        )
        self.assertIn("error", self.request("invoke", "saveTextAction"))

    def test_capture_cancel_has_no_save_and_failed_restore_remains_retryable(self):
        before = self.request("snapshot")["result"]
        path = self.settings.repositories.config.path
        exists = path.exists()
        self.assertNotIn(
            "error",
            self.request("beginTextActionHotkeyCapture", before["textActionContext"]),
        )
        self.assertNotIn("error", self.request("cancelTextActionHotkeyCapture"))
        self.assertEqual(self.capture.call_args_list[0].args, (True,))
        self.assertEqual(self.capture.call_args_list[1].args, (False,))
        self.assertEqual(path.exists(), exists)
        self.assertEqual(
            self.request("snapshot")["result"]["textActions"], before["textActions"]
        )
        self.applier.assert_not_called()
        self.settings.beginTextActionHotkeyCapture(before["textActionContext"])
        self.capture.side_effect = RuntimeError("fixture restore")
        self.assertFalse(self.settings.endTextActionHotkeyCapture())
        self.assertTrue(self.settings._text_action_capture_context)
        self.capture.side_effect = None
        self.assertTrue(self.settings.endTextActionHotkeyCapture())

    def test_save_is_explicit_and_does_not_commit_unrelated_route_draft(self):
        self.settings.selectWorkflow("translation")
        self.settings.setRoutePrompt("Unrelated draft")
        state = self.request("snapshot")["result"]
        action = TextAction("summary", "Summary", "Summarize.").to_mapping()
        reply = self.request(
            "saveTextAction",
            action,
            state["textActionContext"],
            state["textActionsRevision"],
        )
        self.assertNotIn("error", reply)
        self.assertEqual(reply["result"]["routePrompt"], "Unrelated draft")
        self.assertTrue(reply["result"]["dirty"])
        saved = self.settings.repositories.config.load()
        self.assertNotEqual(saved.workflow("translation").prompt, "Unrelated draft")
        self.assertIsNotNone(saved.text_actions.action("summary"))
        self.assertEqual(self.settings.selectedScope, "translation")
        self.assertTrue(self.settings.save())
        self.assertEqual(
            self.settings.repositories.config.load()
            .text_actions.action("translation")
            .prompt,
            "Unrelated draft",
        )

    def test_profile_editor_by_id_preserves_selected_scope_and_unrelated_draft(self):
        self.settings.setRoutePrompt("Pending audio prompt")
        state = self.request("snapshot")["result"]
        profile = next(
            p for p in state["textActionProfiles"] if p["id"] == "legacy-translation"
        )
        self.assertEqual(
            set(profile),
            {
                "id",
                "name",
                "providerId",
                "modelId",
                "customEndpoint",
                "enabled",
                "managed",
                "available",
            },
        )
        profile.update(providerId="openai", modelId="gpt-4.1-mini")
        reply = self.request(
            "saveTextActionProfile",
            profile,
            state["textActionContext"],
            state["textActionsRevision"],
        )
        self.assertNotIn("error", reply)
        self.assertEqual(self.settings.selectedScope, "transcription")
        self.assertEqual(self.settings.routePrompt, "Pending audio prompt")
        saved = self.settings.repositories.config.load()
        self.assertEqual(saved.workflow("translation").model_id, "gpt-4.1-mini")
        self.assertNotEqual(
            saved.workflow("transcription").prompt, "Pending audio prompt"
        )
        self.assertTrue(self.settings.save())
        self.assertEqual(
            self.settings.repositories.config.load().workflow("translation").model_id,
            "gpt-4.1-mini",
        )

    def test_preview_uses_saved_revision_and_never_runs_selection_publication(self):
        state = self.request("snapshot")["result"]
        action = TextAction("rewrite", "Rewrite", "Edit.", "rewrite")
        self.provider.snapshot_text_action.return_value = SimpleNamespace(action=action)
        self.provider.transform_text_action.return_value = RewriteResult(
            "Preview result", "openai", "gpt-4o-mini"
        )
        self.assertIn(
            "error",
            self.request(
                "previewTextAction", "rewrite", "Sample", state["textActionContext"], 2
            ),
        )
        self.provider.transform_text_action.assert_not_called()
        self.assertNotIn(
            "error",
            self.request(
                "previewTextAction", "rewrite", "Sample", state["textActionContext"], 1
            ),
        )
        deadline = time.monotonic() + 2
        while self.settings.textActionPreview["busy"] and time.monotonic() < deadline:
            self.app.processEvents()
        self.assertEqual(self.settings.textActionPreview["text"], "Preview result")
        self.assertEqual(
            self.provider.transform_text_action.call_args.args[1], "Sample"
        )
        first_generation = self.settings.textActionPreview["generation"]
        self.assertNotIn(
            "error",
            self.request(
                "previewTextAction",
                "rewrite",
                "Another sample",
                state["textActionContext"],
                1,
            ),
        )
        self.assertGreater(
            self.settings.textActionPreview["generation"], first_generation
        )
        self.assertFalse(self.settings.dirty)
        self.applier.assert_not_called()

    def test_translation_preview_requires_its_own_language_and_hides_stale_result(self):
        state = self.request("snapshot")["result"]
        self.provider.snapshot_text_action.return_value = SimpleNamespace(
            action=TextAction(
                "translation", "Translation", "Translate to {lang}.", "translation"
            )
        )
        self.provider.transform_text_action.return_value = RewriteResult(
            "Translated preview", "openai", "gpt-4o-mini"
        )
        args = ("translation", "Sample", state["textActionContext"], 1)
        self.assertIn("error", self.request("previewTextAction", *args))
        self.assertIn("error", self.request("previewTextAction", *args, "auto"))
        self.provider.transform_text_action.assert_not_called()
        self.assertNotIn("error", self.request("previewTextAction", *args, "es"))
        deadline = time.monotonic() + 2
        while self.settings.textActionPreview["busy"] and time.monotonic() < deadline:
            self.app.processEvents()
        self.assertEqual(self.provider.transform_text_action.call_args.args[2], "es")
        self.assertEqual(self.settings.textActionPreview["text"], "Translated preview")
        self.settings._account._generation += 1
        self.assertEqual(self.settings.textActionPreview["text"], "")
