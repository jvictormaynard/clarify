"""Unified model installation, reuse and CPU fallback checks."""
import hashlib
import os
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from local_asr import LocalASRInstaller, LocalASRCancelledError, LocalASRError
from local_asr_catalog import ModelInstaller


class UnifiedInstallTests(unittest.TestCase):
    def test_verified_model_is_shared_and_survives_source_removal(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "existing.bin"
            target = Path(directory) / "new.bin"
            source.write_bytes(b"model")
            installer = LocalASRInstaller.__new__(LocalASRInstaller)
            installer.model_sources = (source,)
            installer.asset = lambda name: SimpleNamespace(size=5, sha256=hashlib.sha256(b"model").hexdigest())
            self.assertTrue(installer._reuse_model(target))
            self.assertTrue(os.path.samefile(source, target))
            source.unlink()
            self.assertEqual(target.read_bytes(), b"model")

    def test_corrupt_model_is_not_reused(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "existing.bin"
            target = Path(directory) / "new.bin"
            source.write_bytes(b"wrong")
            installer = LocalASRInstaller.__new__(LocalASRInstaller)
            installer.model_sources = (source,)
            installer.asset = lambda name: SimpleNamespace(size=5, sha256=hashlib.sha256(b"model").hexdigest())
            self.assertFalse(installer._reuse_model(target))
            self.assertFalse(target.exists())

    def test_reuse_honors_cancellation(self):
        installer = LocalASRInstaller.__new__(LocalASRInstaller)
        installer.model_sources = (Path("unused"),)
        installer.asset = Mock()
        event = threading.Event()
        event.set()
        with self.assertRaises(LocalASRCancelledError):
            installer._reuse_model(Path("unused-target"), event)

    def run_install(self, gpu=False, failure=None):
        cpu, cuda = Mock(), Mock()
        cpu.status.return_value = {"state": "installed"}
        cpu.requirements.return_value = {"download_bytes": 5, "disk_bytes": 10}
        cpu.asset.return_value.size = 3
        cuda.requirements.return_value = {"download_bytes": 5, "disk_bytes": 10}
        if failure:
            cuda.install.side_effect = failure
        inventory = [{"id": "auto"}, {"id": "cpu"}]
        if gpu:
            inventory.append({"id": "cuda:0"})
        with patch("local_asr_catalog.installer_for", side_effect=lambda model, device: cuda if device.startswith("cuda") else cpu), patch("local_asr_catalog.devices", return_value=inventory), patch("local_asr_catalog.calibrate", return_value={"selected": "cpu"}) as measure:
            result = ModelInstaller("ggml-medium", Mock()).install()
        return result, cpu, cuda, measure

    def test_cpu_only_host_installs_and_measures(self):
        result, cpu, cuda, measure = self.run_install()
        cpu.install.assert_called_once()
        cuda.install.assert_not_called()
        measure.assert_called_once()
        self.assertEqual(result["state"], "installed")

    def test_gpu_host_prepares_both_and_measures(self):
        result, cpu, cuda, measure = self.run_install(gpu=True)
        cpu.install.assert_called_once()
        cuda.install.assert_called_once()
        measure.assert_called_once()
        self.assertEqual(result["state"], "installed")

    def test_gpu_failure_keeps_cpu_and_reports_partial_setup(self):
        result, cpu, cuda, measure = self.run_install(gpu=True, failure=LocalASRError("failure"))
        self.assertEqual(result["state"], "installed")
        self.assertIn("GPU setup failed", result["detail"])
        measure.assert_called_once()

    def test_gpu_cancellation_does_not_start_measurement(self):
        with self.assertRaises(LocalASRCancelledError):
            self.run_install(gpu=True, failure=LocalASRCancelledError("cancelled"))
