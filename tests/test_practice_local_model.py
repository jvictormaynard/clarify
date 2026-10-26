"""Saved-model checks use fake installers and a deterministic worker scheduler."""

import unittest
from unittest.mock import Mock, patch

from test_workflows import ManualScheduler
from clarify.desktop.practice_local_model import LocalModelReadiness, _installed


class LocalPracticeModelTests(unittest.TestCase):
    def test_status_is_checked_off_thread_once_and_cached_for_the_saved_route(self):
        scheduler = ManualScheduler()
        status = Mock(return_value=True)
        readiness = LocalModelReadiness(scheduler, status)
        self.assertFalse(readiness.ready("ggml-small", "cpu"))
        self.assertFalse(readiness.ready("ggml-small", "cpu"))
        status.assert_not_called()
        self.assertEqual(len(scheduler.background), 1)
        scheduler.background.pop()()
        self.assertFalse(readiness.ready("ggml-small", "cpu"))
        scheduler.soon.pop()()
        self.assertTrue(readiness.ready("ggml-small", "cpu"))
        self.assertEqual(status.call_args.args[:2], ("ggml-small", "cpu"))
        self.assertEqual(scheduler.background, [])

    def test_new_route_or_opening_cancels_old_check_and_ignores_its_result(self):
        scheduler = ManualScheduler()
        readiness = LocalModelReadiness(scheduler, lambda *_: True)
        readiness.ready("ggml-small", "cpu")
        cancelled = readiness._cancel
        self.assertFalse(readiness.ready("ggml-medium", "cuda:1"))
        self.assertTrue(cancelled.is_set())
        self.assertEqual(len(scheduler.background), 1)
        scheduler.background.pop()()
        scheduler.soon.pop()()
        self.assertFalse(readiness.ready("ggml-medium", "cuda:1"))
        scheduler.background.pop()()
        scheduler.soon.pop()()
        self.assertTrue(readiness.ready("ggml-medium", "cuda:1"))
        readiness.invalidate()
        self.assertFalse(readiness.ready("ggml-medium", "cuda:1"))
        readiness.close()
        scheduler.background.pop()()
        scheduler.soon.pop()()
        self.assertFalse(readiness.ready("ggml-medium", "cuda:1"))

    def test_installer_uses_saved_model_and_resolved_device_with_existing_cpu_fallback(
        self,
    ):
        selected = []

        def installer(model, device):
            selected.append((model, device))
            return Mock(
                status=lambda **_: {
                    "state": "installed" if device == "cpu" else "not_installed"
                }
            )

        with (
            patch("local_asr_catalog.installer_for", side_effect=installer),
            patch("local_asr_catalog.measured_device", return_value="cuda:1"),
        ):
            self.assertTrue(_installed("ggml-small", "auto", lambda: False))
        self.assertEqual(selected, [("ggml-small", "cuda:1"), ("ggml-small", "cpu")])
