"""Headless contracts for the user-facing workflow settings controller (#51)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repositories import LocalConfigRepository, WorkflowScope
from secret_store import MemorySecretStore
from workflow_settings import WorkflowSettingsController


class WorkflowSettingsControllerTests(unittest.TestCase):
    def repository(self) -> LocalConfigRepository:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return LocalConfigRepository(
            Path(directory.name) / "config.json",
            secret_store=MemorySecretStore(),
        )

    def test_routes_are_drafted_independently_and_apply_transactionally(self):
        controller = WorkflowSettingsController(self.repository())
        original_translation = controller.route(WorkflowScope.TRANSLATION)

        controller.set_route(
            WorkflowScope.REWRITE,
            provider_id="groq",
            model_id="llama-3.3-70b-versatile",
            prompt="Rewrite only the selected text.",
            custom_endpoint="https://proxy.example/v1",
        )
        controller.apply()

        self.assertEqual(controller.route(WorkflowScope.REWRITE).provider_id, "groq")
        self.assertEqual(
            controller.route(WorkflowScope.TRANSLATION), original_translation
        )
        restarted = WorkflowSettingsController(controller.repository)
        self.assertEqual(restarted.route(WorkflowScope.REWRITE).provider_id, "groq")
        self.assertEqual(
            restarted.route(WorkflowScope.TRANSLATION), original_translation
        )

    def test_effective_route_is_safe_and_marks_local_cloud_or_disabled(self):
        controller = WorkflowSettingsController(self.repository())
        controller.set_route(
            WorkflowScope.LOCAL_ASR_REFINEMENT,
            provider_id="openai",
            model_id="gpt-4o-mini",
            enabled=True,
        )
        effective = controller.effective_route(WorkflowScope.LOCAL_ASR_REFINEMENT)

        self.assertEqual(effective["execution"], "cloud")
        self.assertEqual(effective["provider_id"], "openai")
        self.assertNotIn("prompt", effective)
        controller.set_route(
            WorkflowScope.TRANSCRIPTION,
            provider_id="local_asr",
            model_id="ggml-small",
        )
        self.assertEqual(
            controller.effective_route(WorkflowScope.TRANSCRIPTION)["execution"],
            "local",
        )
        controller.set_route(WorkflowScope.LOCAL_ASR_REFINEMENT, enabled=False)
        self.assertEqual(
            controller.effective_route(WorkflowScope.LOCAL_ASR_REFINEMENT)["execution"],
            "disabled",
        )

    def test_test_validates_the_current_draft_before_apply(self):
        controller = WorkflowSettingsController(self.repository())
        persisted_translation = controller.route(WorkflowScope.TRANSLATION)
        controller.set_route(
            WorkflowScope.TRANSLATION,
            provider_id="local_asr",
            model_id="ggml-small",
        )
        with self.assertRaises(ValueError):
            controller.test(WorkflowScope.TRANSLATION)

        # The failed test must not mutate the persisted route or replace the
        # draft with the repository snapshot.
        self.assertEqual(
            controller.repository.load().workflow(WorkflowScope.TRANSLATION),
            persisted_translation,
        )
        self.assertEqual(
            controller.route(WorkflowScope.TRANSLATION).provider_id,
            "local_asr",
        )

    def test_reset_replaces_only_the_selected_draft_scope(self):
        controller = WorkflowSettingsController(self.repository())
        controller.set_route(
            WorkflowScope.REWRITE,
            provider_id="groq",
            model_id="llama-3.3-70b-versatile",
            prompt="unsaved rewrite policy",
        )
        controller.set_route(
            WorkflowScope.TRANSLATION,
            provider_id="groq",
            model_id="llama-3.3-70b-versatile",
            prompt="custom translation policy",
        )
        draft_rewrite = controller.route(WorkflowScope.REWRITE)
        persisted_rewrite = controller.repository.load().workflow(WorkflowScope.REWRITE)

        reset = controller.reset(WorkflowScope.TRANSLATION)
        self.assertEqual(
            reset.workflow(WorkflowScope.TRANSLATION).provider_id, "openai"
        )
        self.assertNotEqual(
            reset.workflow(WorkflowScope.TRANSLATION).prompt,
            "custom translation policy",
        )
        self.assertEqual(controller.route(WorkflowScope.REWRITE), draft_rewrite)
        self.assertEqual(
            controller.repository.load().workflow(WorkflowScope.REWRITE),
            persisted_rewrite,
        )


if __name__ == "__main__":
    unittest.main()
