import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import local_asr
from provider_http import CancellationToken
from provider_registry import ProviderRegistry, build_provider_registry
from provider_types import (
    ProviderCapability,
    ProviderConfigurationError,
    ProviderConnection,
    ProviderResponseError,
    TranscriptionRequest,
)


from tests.support.local_asr import (
    InstallerFixture,
)

ROOT = Path(__file__).resolve().parents[2]


class LocalASRManifestTests(unittest.TestCase):
    def test_published_manifest_pins_real_assets_and_licenses(self):
        manifest = local_asr.load_manifest(ROOT / "local_asr_manifest.json")

        self.assertEqual(manifest["engine"]["name"], "whisper.cpp")
        self.assertEqual(manifest["engine"]["version"], "v1.9.1")
        self.assertEqual(manifest["engine"]["license"], "MIT")
        self.assertEqual(manifest["recommended_model"]["id"], "ggml-small")
        self.assertEqual(manifest["recommended_model"]["license"], "MIT")
        self.assertEqual(
            manifest["assets"]["runtime"]["sha256"],
            "7d8be46ecd31828e1eb7a2ecdd0d6b314feafd82163038ab6092594b0a063539",
        )
        self.assertEqual(manifest["assets"]["runtime"]["size"], 7982101)
        self.assertEqual(
            manifest["assets"]["model"]["sha256"],
            "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
        )
        self.assertEqual(manifest["assets"]["model"]["size"], 487601967)
        self.assertIn(
            "80da2d8bfee42b0e836fc3a9890373e5defc00a6",
            manifest["assets"]["model"]["url"],
        )
        self.assertGreaterEqual(len(manifest["extracted_files"]), 10)
        for relative in manifest["license_files"]:
            self.assertTrue((ROOT / relative).is_file())

    def test_manifest_rejects_unsafe_destination(self):
        for destination in ("../escape.exe", r"..\\escape.exe"):
            with (
                self.subTest(destination=destination),
                tempfile.TemporaryDirectory() as directory,
            ):
                fixture = InstallerFixture(directory)
                fixture.manifest["extracted_files"][0]["path"] = destination
                fixture.manifest_path.write_text(
                    json.dumps(fixture.manifest), encoding="utf-8"
                )

                with self.assertRaises(local_asr.LocalASRIntegrityError):
                    local_asr.load_manifest(fixture.manifest_path)

    def test_manifest_rejects_unsafe_asset_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = InstallerFixture(directory)
            fixture.manifest["assets"]["model"]["filename"] = "../model.bin"
            fixture.manifest_path.write_text(
                json.dumps(fixture.manifest), encoding="utf-8"
            )

            with self.assertRaises(local_asr.LocalASRIntegrityError):
                local_asr.load_manifest(fixture.manifest_path)

    def test_manifest_rejects_unsafe_installation_components(self):
        cases = (
            ("engine", "name", "../victim"),
            ("engine", "version", "/absolute"),
            ("recommended_model", "id", "nested/model"),
            ("recommended_model", "id", r"C:\\victim"),
        )
        for section, field, value in cases:
            with (
                self.subTest(section=section, field=field, value=value),
                tempfile.TemporaryDirectory() as directory,
            ):
                fixture = InstallerFixture(directory)
                fixture.manifest[section][field] = value
                fixture.manifest_path.write_text(
                    json.dumps(fixture.manifest), encoding="utf-8"
                )

                with self.assertRaises(local_asr.LocalASRIntegrityError):
                    local_asr.load_manifest(fixture.manifest_path)

    def test_manifest_rejects_invalid_extracted_file_size(self):
        for size in (0, -1, "not-an-integer"):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as directory:
                fixture = InstallerFixture(directory)
                fixture.manifest["extracted_files"][0]["size"] = size
                fixture.manifest_path.write_text(
                    json.dumps(fixture.manifest), encoding="utf-8"
                )

                with self.assertRaises(local_asr.LocalASRIntegrityError):
                    local_asr.load_manifest(fixture.manifest_path)

    def test_repository_contains_no_sidecar_binary_or_model(self):
        # Check source inputs, not ignored package caches or local build output.
        # rglob + is_file traversed every npm/Cargo/venv file over UNC on Windows.
        generated = {
            ".git",
            ".venv",
            "venv",
            "node_modules",
            "__pycache__",
            "build",
            "dist",
            "target",
            "release",
            "test-results",
            "playwright-report",
        }
        names = []
        for _directory, directories, files in os.walk(ROOT):
            directories[:] = [name for name in directories if name not in generated]
            names.extend(name.casefold() for name in files)

        self.assertNotIn("whisper-server.exe", names)
        self.assertFalse(
            any(name.startswith("ggml-") and name.endswith(".bin") for name in names)
        )
        self.assertNotIn(
            "whisper.cpp",
            (ROOT / "requirements.txt").read_text(encoding="utf-8").casefold(),
        )


class LocalASRProviderAdapterTests(unittest.TestCase):
    def setUp(self):
        # Unit tests must not select the host GPU from its saved calibration.
        selection = patch("local_asr_catalog.measured_device", return_value="cpu")
        selection.start()
        self.addCleanup(selection.stop)

    def test_adapter_forwards_registry_cancellation_token(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "input.wav"
            audio.write_bytes(b"RIFF-audio")
            backend = Mock()
            backend.transcribe.return_value = "cancel-aware transcript"
            token = CancellationToken()
            adapter = local_asr.LocalASRProviderAdapter(backend)

            adapter.transcribe(
                TranscriptionRequest(
                    audio,
                    local_asr.MODEL_ID,
                    "en",
                    "",
                    "",
                    0.0,
                ),
                ProviderConnection("", ""),
                token,
            )

            backend.transcribe.assert_called_once_with(
                audio,
                "en",
                audio_bytes=None,
                cancel_event=token,
            )

    def test_adapter_registers_with_typed_audio_only_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "input.wav"
            audio.write_bytes(b"RIFF-audio")
            backend = Mock()
            backend.transcribe.return_value = "typed local transcript"
            registry = ProviderRegistry()
            registry.register(local_asr.LocalASRProviderAdapter(backend))

            result = registry.transcribe(
                local_asr.PROVIDER_ID,
                TranscriptionRequest(
                    audio,
                    local_asr.MODEL_ID,
                    "pt",
                    "unused",
                    "unused",
                    0.0,
                    audio_bytes=b"RIFF-owned-by-recording-session",
                ),
                ProviderConnection("", ""),
            )

            self.assertEqual(result.text, "typed local transcript")
            self.assertEqual(result.provider_id, local_asr.PROVIDER_ID)
            self.assertEqual(result.model, local_asr.MODEL_ID)
            self.assertTrue(
                registry.supports(
                    local_asr.PROVIDER_ID,
                    ProviderCapability.AUDIO_TRANSCRIPTION,
                )
            )
            self.assertFalse(
                registry.supports(
                    local_asr.PROVIDER_ID,
                    ProviderCapability.TEXT_GENERATION,
                )
            )
            backend.transcribe.assert_called_once_with(
                audio,
                "pt",
                audio_bytes=b"RIFF-owned-by-recording-session",
            )
            registry.adapter(local_asr.PROVIDER_ID).cancel()
            registry.adapter(local_asr.PROVIDER_ID).shutdown()
            backend.cancel.assert_called_once_with()
            backend.shutdown.assert_called_once_with()

    def test_adapter_maps_install_and_runtime_failures_to_provider_errors(self):
        request = TranscriptionRequest(
            Path("input.wav"), local_asr.MODEL_ID, "en", "", "", 0.0
        )
        connection = ProviderConnection("", "")
        cases = (
            (
                local_asr.LocalASRInstallRequiredError("Install Local ASR"),
                ProviderConfigurationError,
            ),
            (
                local_asr.LocalASRIntegrityError("Reinstall Local ASR"),
                ProviderConfigurationError,
            ),
            (
                local_asr.LocalASRSidecarError("Sidecar unavailable"),
                ProviderResponseError,
            ),
        )

        for local_error, provider_error in cases:
            with self.subTest(error=type(local_error).__name__):
                backend = Mock()
                backend.transcribe.side_effect = local_error
                adapter = local_asr.LocalASRProviderAdapter(backend)

                with self.assertRaises(provider_error) as raised:
                    adapter.transcribe(request, connection)

                self.assertEqual(raised.exception.provider_id, local_asr.PROVIDER_ID)
                self.assertEqual(
                    raised.exception.capability,
                    ProviderCapability.AUDIO_TRANSCRIPTION,
                )

    def test_adapter_rejects_unpinned_model_and_is_registered_without_starting(self):
        adapter = local_asr.LocalASRProviderAdapter(Mock())
        request = TranscriptionRequest(
            Path("input.wav"), "another-model", "en", "", "", 0.0
        )

        with self.assertRaises(ProviderConfigurationError):
            adapter.transcribe(request, ProviderConnection("", ""))

        registry = build_provider_registry()
        self.assertIn(local_asr.PROVIDER_ID, registry.provider_ids)
        self.assertTrue(
            registry.supports(
                local_asr.PROVIDER_ID, ProviderCapability.AUDIO_TRANSCRIPTION
            )
        )


if __name__ == "__main__":
    unittest.main()
