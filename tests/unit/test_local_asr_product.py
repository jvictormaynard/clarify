import time
import unittest

from local_asr import LocalASRError
from local_asr_product import (
    LocalASRProductController,
    format_requirements,
)


from tests.support.local_asr_product import FakeInstaller


class FakeBackend:
    def __init__(self):
        self.events = []
        self.stop_calls = 0
        self.cancel_calls = 0

    def cancel(self):
        self.cancel_calls += 1
        self.events.append("cancel")

    def stop(self):
        self.stop_calls += 1
        self.events.append("stop")


class LocalASRProductControllerTests(unittest.TestCase):
    def test_unsubscribe_releases_listener_and_stops_delivery(self):
        controller = LocalASRProductController(FakeInstaller())
        states = []
        controller.subscribe(states.append)
        controller.unsubscribe(states.append)
        controller.unsubscribe(states.append)
        controller._publish(controller.state)
        self.assertEqual(len(states), 1)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("condition did not complete")

    def test_constructor_is_read_only_and_install_is_explicit(self):
        installer = FakeInstaller()
        states = []
        controller = LocalASRProductController(installer, listener=states.append)

        self.assertEqual(installer.install_calls, 0)
        self.assertEqual(installer.status_calls, 0)
        self.assertEqual(controller.state.status, "checking")
        controller.refresh_async()
        self.wait_for(
            lambda: controller.state.status == "not_installed" and not controller.busy
        )
        self.assertEqual(installer.status_calls, 1)
        controller.install_async()
        self.wait_for(lambda: installer.install_calls == 1)
        self.assertEqual(controller.state.status, "installing")
        self.assertTrue(any(state.stage == "download:model" for state in states))
        installer.release.set()
        self.wait_for(lambda: controller.state.status == "installed")
        self.assertEqual(controller.state.fraction, 0.0)

    def test_cancel_propagates_to_installer_and_leaves_no_worker(self):
        installer = FakeInstaller()
        controller = LocalASRProductController(installer)
        controller.install_async()
        self.wait_for(lambda: installer.install_calls == 1)
        controller.cancel()
        self.wait_for(lambda: controller.state.status == "cancelled")
        self.assertTrue(installer.cancel_seen.is_set())
        self.assertFalse(controller.busy)

    def test_unsupported_platform_rejects_install_before_download(self):
        installer = FakeInstaller()
        installer.platform_supported = lambda: False
        controller = LocalASRProductController(installer)

        with self.assertRaises(LocalASRError):
            controller.install_async()

        self.assertEqual(installer.install_calls, 0)
        self.assertEqual(controller.state.status, "error")
        self.assertIn("Windows x64", controller.state.detail)
        self.assertFalse(controller.busy)

    def test_remove_is_explicit_and_reports_not_installed(self):
        installer = FakeInstaller()
        installer._status = "installed"
        backend = FakeBackend()
        controller = LocalASRProductController(installer, backend=backend)
        controller.remove_async()
        self.wait_for(lambda: controller.state.status == "not_installed")
        self.assertEqual(installer.remove_calls, 1)
        self.assertEqual(backend.stop_calls, 1)
        self.assertEqual(backend.events, ["cancel", "stop"])

    def test_remove_cancellation_reaches_installer(self):
        installer = FakeInstaller()
        installer._status = "installed"
        installer.block_remove = True
        controller = LocalASRProductController(installer, backend=FakeBackend())
        controller.remove_async()
        self.wait_for(lambda: installer.remove_started.is_set())
        controller.cancel()
        self.wait_for(lambda: controller.state.status == "cancelled")
        self.assertTrue(installer.remove_cancel_seen.is_set())
        self.assertFalse(controller.busy)

    def test_requirement_summary_is_human_readable(self):
        summary = format_requirements(
            {
                "platform": "Windows x64",
                "compute": "CPU-only; AVX support",
                "runtime": "Microsoft Visual C++ 2015-2022 Redistributable (x64)",
                "memory_bytes": 852_000_000,
                "disk_bytes": 510_000_000,
                "download_bytes": 495_584_068,
            }
        )
        self.assertIn("Windows x64", summary)
        self.assertIn("AVX support", summary)
        self.assertIn("Visual C++", summary)
        self.assertIn("MiB", summary)
        self.assertIn("download", summary)


if __name__ == "__main__":
    unittest.main()
