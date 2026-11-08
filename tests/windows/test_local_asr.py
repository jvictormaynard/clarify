import ctypes
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import local_asr
from scripts import local_asr_harness


ROOT = Path(__file__).resolve().parents[2]


class LocalASRRecordedProcessTests(unittest.TestCase):
    def test_windows_working_set_reports_kernel_peak(self):
        def populate_counters(_process, pointer, _size):
            pointer._obj.PeakWorkingSetSize = 987654
            pointer._obj.WorkingSetSize = 123456
            return 1

        kernel32 = SimpleNamespace(
            OpenProcess=Mock(return_value=123),
            CloseHandle=Mock(return_value=1),
        )
        psapi = SimpleNamespace(
            GetProcessMemoryInfo=Mock(side_effect=populate_counters),
        )
        windll = SimpleNamespace(kernel32=kernel32, psapi=psapi)

        with (
            patch.object(local_asr_harness.platform, "system", return_value="Windows"),
            patch.object(ctypes, "windll", windll, create=True),
        ):
            peak = local_asr_harness._windows_working_set(4321)

        self.assertEqual(peak, 987654)
        kernel32.CloseHandle.assert_called_once_with(123)

    def test_windows_elevation_state_uses_admin_token_check(self):
        shell32 = SimpleNamespace(IsUserAnAdmin=Mock(return_value=1))
        windll = SimpleNamespace(shell32=shell32)

        with (
            patch.object(local_asr.platform, "system", return_value="Windows"),
            patch.object(ctypes, "windll", windll, create=True),
        ):
            self.assertTrue(local_asr._windows_elevation_state())

        shell32.IsUserAnAdmin.assert_called_once_with()
        shell32.IsUserAnAdmin.return_value = 0
        with (
            patch.object(local_asr.platform, "system", return_value="Windows"),
            patch.object(ctypes, "windll", windll, create=True),
        ):
            self.assertFalse(local_asr._windows_elevation_state())

    def test_pid_running_state_uses_synchronize_without_terminating(self):
        kernel32 = SimpleNamespace(
            OpenProcess=Mock(return_value=123),
            WaitForSingleObject=Mock(return_value=0x00000102),
            CloseHandle=Mock(return_value=1),
        )
        windll = SimpleNamespace(kernel32=kernel32)

        with (
            patch.object(local_asr.platform, "system", return_value="Windows"),
            patch.object(ctypes, "windll", windll, create=True),
        ):
            self.assertTrue(local_asr._pid_running_state(4321))

        kernel32.OpenProcess.assert_called_once_with(0x00100000, False, 4321)
        kernel32.WaitForSingleObject.assert_called_once_with(123, 0)
        kernel32.CloseHandle.assert_called_once_with(123)

        kernel32.WaitForSingleObject.return_value = 0
        with (
            patch.object(local_asr.platform, "system", return_value="Windows"),
            patch.object(ctypes, "windll", windll, create=True),
        ):
            self.assertFalse(local_asr._pid_running_state(4322))

    def test_pid_running_state_reports_nonexistent_pid_from_last_error(self):
        kernel32 = SimpleNamespace(OpenProcess=Mock(return_value=0))
        windll = SimpleNamespace(kernel32=kernel32)

        with (
            patch.object(local_asr.platform, "system", return_value="Windows"),
            patch.object(ctypes, "windll", windll, create=True),
            patch.object(ctypes, "get_last_error", return_value=87, create=True),
        ):
            self.assertFalse(local_asr._pid_running_state(4321))

        kernel32.OpenProcess.assert_called_once_with(0x00100000, False, 4321)

    def test_pid_running_state_preserves_access_denied_as_unknown(self):
        kernel32 = SimpleNamespace(OpenProcess=Mock(return_value=0))
        windll = SimpleNamespace(kernel32=kernel32)

        with (
            patch.object(local_asr.platform, "system", return_value="Windows"),
            patch.object(ctypes, "windll", windll, create=True),
            patch.object(ctypes, "get_last_error", return_value=5, create=True),
        ):
            self.assertIsNone(local_asr._pid_running_state(4321))

    def test_pid_running_state_uses_native_error_over_stale_ctypes_cache(self):
        for native_error, stale_error, expected in ((87, 5, False), (5, 87, None)):
            with self.subTest(native_error=native_error):
                kernel32 = SimpleNamespace(
                    OpenProcess=Mock(return_value=0),
                    GetLastError=Mock(return_value=native_error),
                )
                windll = SimpleNamespace(kernel32=kernel32)
                with (
                    patch.object(local_asr.platform, "system", return_value="Windows"),
                    patch.object(ctypes, "windll", windll, create=True),
                    patch.object(
                        ctypes,
                        "get_last_error",
                        return_value=stale_error,
                        create=True,
                    ),
                ):
                    self.assertIs(local_asr._pid_running_state(4321), expected)

    def test_kernel32_loader_requests_last_error_for_native_dll(self):
        calls = []

        class FakeWinDLL:
            def __init__(self, name, **kwargs):
                calls.append((name, kwargs))

        candidate = FakeWinDLL("windll-kernel32")
        calls.clear()
        module = SimpleNamespace(
            windll=SimpleNamespace(kernel32=candidate), WinDLL=FakeWinDLL
        )

        selected = local_asr._windows_kernel32_with_last_error(module)

        self.assertIsInstance(selected, FakeWinDLL)
        self.assertIsNot(selected, candidate)
        self.assertEqual(calls, [("kernel32", {"use_last_error": True})])

    def test_kernel32_loader_preserves_test_double(self):
        calls = []

        class FakeWinDLL:
            def __init__(self, name, **kwargs):
                calls.append((name, kwargs))

        candidate = SimpleNamespace(OpenProcess=Mock())
        module = SimpleNamespace(
            windll=SimpleNamespace(kernel32=candidate), WinDLL=FakeWinDLL
        )

        selected = local_asr._windows_kernel32_with_last_error(module)

        self.assertIs(selected, candidate)
        self.assertEqual(calls, [])

    def test_native_kernel32_reader_prefers_ctypes_last_error_copy(self):
        class FakeWinDLL:
            def __init__(self, _name):
                self.GetLastError = Mock(return_value=5)

        kernel32 = FakeWinDLL("kernel32")
        module = SimpleNamespace(
            WinDLL=FakeWinDLL, get_last_error=Mock(return_value=87)
        )

        self.assertEqual(local_asr._windows_last_error(module, kernel32), 87)
        module.get_last_error.assert_called_once_with()
        kernel32.GetLastError.assert_not_called()

    def test_terminate_pid_requests_synchronize_and_confirms_wait(self):
        kernel32 = SimpleNamespace(
            OpenProcess=Mock(return_value=123),
            TerminateProcess=Mock(return_value=1),
            WaitForSingleObject=Mock(return_value=0),
            CloseHandle=Mock(return_value=1),
        )
        windll = SimpleNamespace(kernel32=kernel32)

        with (
            patch.object(local_asr.platform, "system", return_value="Windows"),
            patch.object(ctypes, "windll", windll, create=True),
        ):
            self.assertTrue(local_asr._terminate_pid(4321))

        kernel32.OpenProcess.assert_called_once_with(0x00100001, False, 4321)
        kernel32.TerminateProcess.assert_called_once_with(123, 1)
        kernel32.WaitForSingleObject.assert_called_once_with(123, 2000)
        kernel32.CloseHandle.assert_called_once_with(123)

        kernel32.WaitForSingleObject.return_value = 0x00000102
        with (
            patch.object(local_asr.platform, "system", return_value="Windows"),
            patch.object(ctypes, "windll", windll, create=True),
        ):
            self.assertFalse(local_asr._terminate_pid(4322))

    def test_cleanup_keeps_record_when_termination_is_not_confirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record_path = root / "sidecar-process.json"
            executable = root / "installed" / "runtime" / "whisper-server.exe"
            executable.parent.mkdir(parents=True)
            record_path.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "executable": str(executable),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(local_asr, "_process_image_path", return_value=executable),
                patch.object(local_asr, "_terminate_pid", return_value=False),
            ):
                with self.assertRaises(local_asr.LocalASRSidecarError):
                    local_asr.cleanup_recorded_sidecar(record_path, executable, root)

            self.assertTrue(record_path.exists())

    def test_cleanup_keeps_record_when_image_lookup_is_inconclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record_path = root / "sidecar-process.json"
            executable = root / "installed" / "runtime" / "whisper-server.exe"
            executable.parent.mkdir(parents=True)
            record_path.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "executable": str(executable),
                    }
                ),
                encoding="utf-8",
            )

            for running in (True, None):
                with (
                    self.subTest(running=running),
                    patch.object(
                        local_asr,
                        "_process_image_path",
                        return_value=None,
                    ),
                    patch.object(
                        local_asr,
                        "_pid_running_state",
                        return_value=running,
                    ),
                    patch.object(local_asr, "_terminate_pid") as terminate,
                ):
                    with self.assertRaises(local_asr.LocalASRSidecarError):
                        local_asr.cleanup_recorded_sidecar(
                            record_path, executable, root
                        )

                self.assertTrue(record_path.exists())
                terminate.assert_not_called()

    def test_cleanup_preserves_record_when_access_denied_overrides_stale_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record_path = root / "sidecar-process.json"
            executable = root / "installed" / "runtime" / "whisper-server.exe"
            executable.parent.mkdir(parents=True)
            record_path.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "executable": str(executable),
                    }
                ),
                encoding="utf-8",
            )
            kernel32 = SimpleNamespace(
                OpenProcess=Mock(return_value=0),
                GetLastError=Mock(return_value=5),
            )
            windll = SimpleNamespace(kernel32=kernel32)

            with (
                patch.object(local_asr.platform, "system", return_value="Windows"),
                patch.object(ctypes, "windll", windll, create=True),
                patch.object(ctypes, "get_last_error", return_value=87, create=True),
                patch.object(local_asr, "_terminate_pid") as terminate,
            ):
                with self.assertRaises(local_asr.LocalASRSidecarError):
                    local_asr.cleanup_recorded_sidecar(record_path, executable, root)

            terminate.assert_not_called()
            self.assertTrue(record_path.exists())

    def test_cleanup_discards_record_after_proving_pid_exited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record_path = root / "sidecar-process.json"
            executable = root / "installed" / "runtime" / "whisper-server.exe"
            executable.parent.mkdir(parents=True)
            record_path.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "executable": str(executable),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(local_asr, "_process_image_path", return_value=None),
                patch.object(
                    local_asr,
                    "_pid_running_state",
                    return_value=False,
                ),
            ):
                local_asr.cleanup_recorded_sidecar(record_path, executable, root)

            self.assertFalse(record_path.exists())

    def test_cleanup_terminates_recorded_old_executable_during_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record_path = root / "sidecar-process.json"
            old_executable = root / "old-install" / "runtime" / "whisper-server.exe"
            current_executable = root / "new-install" / "runtime" / "whisper-server.exe"
            old_executable.parent.mkdir(parents=True)
            current_executable.parent.mkdir(parents=True)
            record_path.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "executable": str(old_executable),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(
                    local_asr, "_process_image_path", return_value=old_executable
                ),
                patch.object(
                    local_asr,
                    "_terminate_pid",
                    return_value=True,
                ) as terminate,
            ):
                local_asr.cleanup_recorded_sidecar(
                    record_path, current_executable, root
                )

            terminate.assert_called_once_with(4321)
            self.assertFalse(record_path.exists())

    def test_cleanup_preserves_record_for_executable_outside_asset_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record_path = root / "sidecar-process.json"
            current_executable = root / "current" / "runtime" / "whisper-server.exe"
            external_executable = (
                root.parent / "external" / "runtime" / "whisper-server.exe"
            )
            current_executable.parent.mkdir(parents=True)
            record_path.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "executable": str(external_executable),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(
                    local_asr,
                    "_pid_running_state",
                    return_value=True,
                ),
                patch.object(local_asr, "_terminate_pid") as terminate,
            ):
                with self.assertRaises(local_asr.LocalASRSidecarError):
                    local_asr.cleanup_recorded_sidecar(
                        record_path, current_executable, root
                    )

            terminate.assert_not_called()
            self.assertTrue(record_path.exists())


if __name__ == "__main__":
    unittest.main()
