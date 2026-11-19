"""Batch native contracts, with fake compute and isolated assets/audio."""

import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from local_asr import (
    LocalASRCancelledError,
    LocalASRIntegrityError,
    LocalASRSidecarError,
)
from local_asr_batch import BatchEngine, create_engine
from local_asr_batch_assets import BatchInstaller
from local_asr_streaming import wav_bytes


class BatchTests(unittest.TestCase):
    def installer(self, root, model="parakeet-v3-int8"):
        if Path(root).is_dir():
            folder = Path(root) / "models"
            folder.mkdir(exist_ok=True)
            for name in (
                "encoder.int8.onnx",
                "decoder.int8.onnx",
                "joiner.int8.onnx",
                "tokens.txt",
            ):
                (folder / name).write_bytes(b"fake model")
        return SimpleNamespace(
            manifest={"recommended_model": {"id": model}},
            verify=lambda **kwargs: None,
            model_path=Path(root) / "models/encoder.int8.onnx",
            executable_path=Path(root) / "runtime/bin/sherpa-onnx-offline",
        )

    def test_final_sherpa_json_and_cpu_flags(self):
        with tempfile.TemporaryDirectory(prefix="João-") as root:
            installer = self.installer(root)
            commands = []

            class FakeProcess:
                returncode = 0

                def __init__(self, command, **kwargs):
                    commands.extend(command)
                    self_test = Path(kwargs["cwd"])
                    for argument in command[1:]:
                        assert argument.isascii()
                    assert (self_test / "input.wav").is_file()
                    assert (
                        self_test / "encoder.int8.onnx"
                    ).read_bytes() == b"fake model"
                    # This is the v1.12.14 CLI's stderr format, including suffix.
                    kwargs["stderr"].write(
                        b"config Jo\xe3o\n"
                        + f'{command[-1]}\r\n{{"text":"Olá {{mundo}}"}}\r\n'.encode(
                            "utf8"
                        )
                        + b"diagnostic Jo\xe3o\n"
                    )
                    kwargs["stderr"].flush()

                def poll(self):
                    return 0

                def wait(self, **kwargs):
                    return 0

            with (
                patch("local_asr_batch.subprocess.Popen", FakeProcess),
                patch(
                    "local_asr_batch.os.link",
                    side_effect=OSError("hard links unavailable"),
                ),
            ):
                engine = create_engine("parakeet-v3-int8", installer)
                self.assertEqual(
                    engine.transcribe(
                        None, "pt-BR", audio_bytes=wav_bytes(b"\0\0" * 1600)
                    ),
                    "Olá {mundo}",
                )
            self.assertIn("--num-threads=3", commands)
            self.assertIn("--provider=cpu", commands)
            self.assertIn("--model-type=nemo_transducer", commands)
            self.assertFalse(engine.native_streaming)

    def test_cancel_terminates_compute_before_audio_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            engine = BatchEngine("parakeet-v3-int8", self.installer(root))
            stopped = []

            class FakeProcess:
                returncode = None

                def __init__(self, command, **kwargs):
                    self.audio = Path(kwargs["cwd"]) / command[-1]
                    engine.cancel()

                def poll(self):
                    return self.returncode

                def terminate(self):
                    stopped.append(self.audio.exists())
                    self.returncode = -15

                def wait(self, **kwargs):
                    return self.returncode

            with patch("local_asr_batch.subprocess.Popen", FakeProcess):
                with self.assertRaises(LocalASRCancelledError):
                    engine.transcribe(None, audio_bytes=wav_bytes(b"\0\0" * 1600))
            self.assertEqual(stopped, [True])
            engine.shutdown()
            with self.assertRaises(LocalASRSidecarError):
                engine.transcribe(None)

    def test_rejects_wrong_model_language_audio_and_preserves_install_error(self):
        with tempfile.TemporaryDirectory() as root:
            installer = self.installer(root)
            with self.assertRaises(LocalASRIntegrityError):
                create_engine("granite-5-turboctc", installer)
            engine = create_engine("parakeet-v3-int8", installer)
            with self.assertRaises(LocalASRSidecarError):
                engine.transcribe(None, "ja", audio_bytes=wav_bytes(b"\0\0"))
            with self.assertRaises(LocalASRSidecarError):
                engine.transcribe(None, audio_bytes=b"not WAV")
            error = LocalASRIntegrityError("corrupt")
            installer.verify = lambda **kwargs: (_ for _ in ()).throw(error)
            with self.assertRaises(LocalASRIntegrityError) as caught:
                engine.transcribe(None, audio_bytes=wav_bytes(b"\0\0"))
            self.assertIs(caught.exception, error)

    def test_pre_cancel_never_verifies_or_launches(self):
        installer = self.installer("/unused")
        installer.verify = lambda: self.fail("Verification started after cancellation")
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(LocalASRCancelledError):
            create_engine("parakeet-v3-int8", installer).transcribe(
                None, cancel_event=cancel
            )

    def test_supplemental_assets_are_verified_and_staged_inside_guarded_hook(self):
        installer = BatchInstaller.__new__(BatchInstaller)
        payload = b"pinned decoder"
        value = dict(
            filename="decoder.int8.onnx",
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            url="https://example.test/decoder",
            source_url="https://example.test/source",
            license="CC-BY-4.0",
        )
        installer.manifest = {"batch_model_files": [value]}
        downloaded = []
        installer._download = lambda asset, destination, *args: downloaded.append(
            (asset.sha256, destination)
        )
        with (
            tempfile.TemporaryDirectory() as root,
            patch("local_asr.LocalASRInstaller._copy_license_notices"),
        ):
            installer._copy_license_notices(Path(root))
            self.assertEqual(
                downloaded, [(value["sha256"], Path(root) / "models/decoder.int8.onnx")]
            )

    def test_granite_spawn_failure_preserves_typed_error_and_releases_engine(self):
        installer = self.installer("/unused", "granite-5-turboctc")
        engine = create_engine("granite-5-turboctc", installer)

        class FailedProcess:
            def start(self):
                raise OSError("spawn failed")

            def is_alive(self):
                return False

            def join(self, *args):
                raise AssertionError("Cannot join an unstarted process")

        context = SimpleNamespace(Process=lambda **kwargs: FailedProcess())
        with patch("local_asr_batch.multiprocessing.get_context", return_value=context):
            with self.assertRaises(LocalASRSidecarError):
                engine.transcribe(None, audio_bytes=wav_bytes(b"\0\0" * 1600))
        self.assertTrue(engine._busy.acquire(blocking=False))
        engine._busy.release()

    def test_granite_worker_uses_cpu_and_frees_native_state_on_run_failure(self):
        from local_asr_batch import _granite_worker

        observed = {}

        class Function:
            def __init__(self, name):
                self.name = name

            def __call__(self, *args):
                if self.name == "version":
                    return b"0.4.2"
                if self.name == "open":
                    observed["backend"] = args[1]._obj.backend
                    observed["threads"] = args[2]._obj.threads
                    args[3]._obj.value = 42
                if self.name == "run":
                    observed["language"] = args[3]._obj.language
                    observed["samples"] = args[2]
                    return 10
                if self.name == "session_free":
                    observed["freed"] = args[0].value
                return 0

        class Library:
            def __getattr__(self, name):
                return Function(name.removeprefix("transcribe_"))

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "input.wav"
            result = Path(directory) / "result.json"
            audio.write_bytes(wav_bytes(b"\0\0" * 100))
            with patch("local_asr_batch.C.CDLL", return_value=Library()):
                _granite_worker(
                    str(Path(directory) / "fake.dll"),
                    "unused",
                    str(audio),
                    "pt",
                    str(result),
                )
            self.assertIn("error", json.loads(result.read_text()))
        self.assertEqual(
            observed,
            {
                "backend": 4,
                "threads": 3,
                "language": b"pt",
                "samples": 1120,
                "freed": 42,
            },
        )

    def test_corrupt_supplemental_model_is_rejected_before_native_use(self):
        installer = BatchInstaller.__new__(BatchInstaller)
        payload = b"pinned"
        asset = dict(
            filename="encoder.int8.onnx",
            url="https://example.test/model",
            source_url="https://example.test/source",
            license="CC-BY-4.0",
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        extra = dict(asset, filename="decoder.int8.onnx")
        installer.manifest = {
            "engine": {"name": "fixture", "version": "v1"},
            "recommended_model": {"id": "parakeet-v3-int8"},
            "assets": {"model": asset},
            "extracted_files": [],
            "license_files": [],
            "batch_model_files": [extra],
        }
        with tempfile.TemporaryDirectory() as root:
            installer.root = Path(root)
            installer.model_path.parent.mkdir(parents=True)
            installer.model_path.write_bytes(payload)
            decoder = installer.model_path.parent / "decoder.int8.onnx"
            decoder.write_bytes(payload)
            installer.verify()
            decoder.write_bytes(b"broken")
            with self.assertRaises(LocalASRIntegrityError):
                installer.verify()

    def test_all_manifests_pin_exact_models_and_existing_licenses(self):
        from local_asr import load_manifest

        root = Path(__file__).resolve().parents[2]
        for model in ("parakeet-v3-int8", "granite-5-turboctc"):
            for system in ("linux", "windows"):
                manifest = load_manifest(
                    root / "local_asr_manifests" / f"{model}-{system}-cpu.json"
                )
                self.assertEqual(manifest["recommended_model"]["id"], model)
                for license_file in manifest["license_files"]:
                    self.assertTrue((root / license_file).is_file())
                if model == "granite-5-turboctc":
                    self.assertEqual(
                        manifest["assets"]["model"]["sha256"],
                        "fc34cbe71f979a6aeb8bea08bfac88d5c62c1736c0bc845827e37c90f28e336c",
                    )


if __name__ == "__main__":
    unittest.main()
