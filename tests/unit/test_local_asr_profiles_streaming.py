import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

from local_asr_catalog import MODELS, installer_for, normalize_device, measured_device
from local_asr import LocalASRSidecarManager
from local_asr_streaming import PauseStream, pcm_offset, wav_bytes
from provider_http import CancellationToken
from repositories import AppConfig


class ProfileTests(unittest.TestCase):
    def test_background_processing_stays_opt_in_until_quality_and_latency_pass(self):
        self.assertFalse(AppConfig().local_asr_streaming)
        self.assertFalse(AppConfig.from_mapping({}).local_asr_streaming)
        self.assertFalse(
            AppConfig.from_mapping({"local_asr_streaming": False}).local_asr_streaming
        )
        self.assertTrue(
            AppConfig.from_mapping({"local_asr_streaming": True}).local_asr_streaming
        )

    def test_all_profiles_have_verified_separate_manifests(self):
        roots = set()
        for model in MODELS:
            for device in ("cpu", "cuda:0"):
                installer = installer_for(model, device)
                self.assertEqual(installer.manifest["recommended_model"]["id"], model)
                self.assertNotIn(installer.root, roots)
                roots.add(installer.root)
                if device.startswith("cuda"):
                    self.assertIn("cublas", installer.manifest["assets"])
                    self.assertTrue(
                        any(
                            "cublas64_11.dll" in e["path"]
                            for e in installer.manifest["extracted_files"]
                        )
                    )
        for root in roots:
            self.assertFalse(
                any(other != root and root in other.parents for other in roots)
            )

    def test_config_roundtrip_and_invalid_inputs(self):
        config = AppConfig.from_mapping(
            {"local_asr_device": "cuda:1", "local_asr_streaming": True}
        )
        self.assertEqual(config.to_mapping()["local_asr_device"], "cuda:1")
        self.assertTrue(config.local_asr_streaming)
        self.assertEqual(normalize_device("cuda:1; bad"), "auto")
        self.assertFalse(
            AppConfig.from_mapping({"local_asr_streaming": "true"}).local_asr_streaming
        )

    def test_auto_without_measurement_is_cpu(self):
        with patch(
            "local_asr_catalog._benchmark_path",
            return_value=Path("missing-benchmark-test.json"),
        ):
            self.assertEqual(measured_device("ggml-small"), "cpu")

    def test_invalid_compute_is_rejected(self):
        with self.assertRaises(ValueError):
            LocalASRSidecarManager(compute_device="cuda:x")


class Backend:
    def __init__(self, fail=False):
        self.audio = []
        self.called = threading.Event()
        self.fail = fail

    def transcribe(self, path, language, *, audio_bytes, cancel_event):
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
            self.audio.append(wav.readframes(wav.getnframes()))
        self.called.set()
        if self.fail:
            raise RuntimeError("failed chunk")
        return "piece" + str(len(self.audio))


class StreamTests(unittest.TestCase):
    def run_stream(self, pcm, fail=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "audio.wav"
        audio = wav_bytes(pcm)
        path.write_bytes(audio)
        backend = Backend(fail)
        token = CancellationToken()
        stream = PauseStream(path, backend, "ggml-small", "pt", token)
        stream.start()
        self.addCleanup(stream.cancel)
        return stream, backend, token, audio, path

    def test_voiced_tail_keeps_the_complete_recording_for_normal_recognition(self):
        pcm = b"\xe8\x03" * 40000 + b"\x00\x00" * 24000 + b"\xe8\x03" * 16000
        stream, backend, _, audio, path = self.run_stream(pcm)
        self.assertTrue(backend.called.wait(3))
        result = stream.finish(audio)
        self.assertIsNone(result)
        self.assertEqual(path.read_bytes(), audio)
        self.assertEqual(backend.audio[0], pcm[: stream.committed])

    def test_no_pause_leaves_full_audio_for_normal_path(self):
        stream, backend, _, audio, _ = self.run_stream(b"\xe8\x03" * 64000)
        self.assertIsNone(stream.finish(audio))
        self.assertEqual(backend.audio, [])

    def test_chunk_failure_discards_partial_results(self):
        stream, backend, _, audio, _ = self.run_stream(
            b"\xe8\x03" * 40000 + b"\x00\x00" * 24000, True
        )
        self.assertTrue(backend.called.wait(3))
        self.assertIsNone(stream.finish(audio))

    def test_final_audio_mismatch_discards_segments(self):
        stream, backend, _, audio, _ = self.run_stream(
            b"\xe8\x03" * 40000 + b"\x00\x00" * 24000
        )
        self.assertTrue(backend.called.wait(3))
        self.assertIsNone(stream.finish(wav_bytes(b"\x00\x00" * 64000)))

    def test_cancel_never_returns_text(self):
        stream, backend, token, audio, _ = self.run_stream(
            b"\xe8\x03" * 40000 + b"\x00\x00" * 24000
        )
        self.assertTrue(backend.called.wait(3))
        token.cancel()
        self.assertIsNone(stream.finish(audio))

    def test_backlog_is_bounded(self):
        stream, backend, _, audio, _ = self.run_stream(b"\xe8\x03" * (16000 * 61))
        stream.worker.join(3)
        self.assertTrue(stream.failed)
        self.assertIsNone(stream.finish(audio))
        self.assertFalse(backend.audio)

    def test_busy_decoder_has_bounded_finish_and_keeps_caller_token(self):
        class SlowBackend(Backend):
            def transcribe(self, path, language, *, audio_bytes, cancel_event):
                self.called.set()
                while not cancel_event.is_set():
                    time.sleep(0.005)
                raise RuntimeError("cancelled speculative decode")

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "audio.wav"
            audio = wav_bytes(b"\xe8\x03" * 40000 + b"\x00\x00" * 24000)
            path.write_bytes(audio)
            backend = SlowBackend()
            token = CancellationToken()
            stream = PauseStream(
                path, backend, "ggml-medium", "pt", token, worker_wait_seconds=0.03
            )
            self.addCleanup(stream.cancel)
            stream.start()
            self.assertTrue(backend.called.wait(2))
            started = time.monotonic()
            self.assertIsNone(stream.finish(audio))
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertFalse(token.cancelled)
            stream.worker.join(1)
            self.assertFalse(stream.worker.is_alive())

    def test_cancellation_interrupts_finish_wait(self):
        class SlowBackend(Backend):
            def transcribe(self, path, language, *, audio_bytes, cancel_event):
                self.called.set()
                while not cancel_event.is_set():
                    time.sleep(0.005)
                raise RuntimeError("cancelled")

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "audio.wav"
            audio = wav_bytes(b"\xe8\x03" * 40000 + b"\x00\x00" * 24000)
            path.write_bytes(audio)
            backend = SlowBackend()
            token = CancellationToken()
            stream = PauseStream(
                path, backend, "ggml-medium", "pt", token, worker_wait_seconds=10
            )
            stream.start()
            self.addCleanup(stream.cancel)
            self.assertTrue(backend.called.wait(2))
            timer = threading.Timer(0.03, token.cancel)
            timer.start()
            self.addCleanup(timer.cancel)
            started = time.monotonic()
            self.assertIsNone(stream.finish(audio))
            self.assertLess(time.monotonic() - started, 0.5)
            stream.worker.join(1)
            self.assertFalse(stream.worker.is_alive())

    def test_pending_complete_snapshot_can_finish_without_restarting_the_model(self):
        class SlowBackend(Backend):
            def transcribe(self, *args, **kwargs):
                value = super().transcribe(*args, **kwargs)
                time.sleep(0.06)
                return value

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "audio.wav"
            audio = wav_bytes(b"\xe8\x03" * 40000 + b"\x00\x00" * 32000)
            path.write_bytes(audio)
            backend = SlowBackend()
            stream = PauseStream(
                path,
                backend,
                "ggml-medium",
                "en",
                CancellationToken(),
                worker_wait_seconds=0.5,
            )
            stream.start()
            self.addCleanup(stream.cancel)
            self.assertTrue(backend.called.wait(2))
            self.assertEqual(stream.finish(audio).text, "piece1")
            self.assertFalse(stream.abort.is_set())

    def test_header_must_be_supported(self):
        with self.assertRaises(ValueError):
            pcm_offset(b"not a wave")

    def test_later_snapshots_keep_earlier_audio_and_replace_earlier_text(self):
        pcm = (b"\xe8\x03" * 40000 + b"\x00\x00" * 24000) * 2
        stream, backend, _, audio, _ = self.run_stream(pcm)
        limit = time.monotonic() + 3
        while stream.completed_snapshots < 2 and time.monotonic() < limit:
            time.sleep(0.005)
        self.assertEqual(stream.completed_snapshots, 2)
        result = stream.finish(audio)
        self.assertIsNotNone(result)
        self.assertEqual(result.text, "piece2")
        self.assertTrue(backend.audio[1].startswith(backend.audio[0]))
        self.assertEqual(backend.audio[1], pcm[: stream.committed])

    def test_short_quiet_speech_is_not_discarded_as_a_silent_tail(self):
        # Low average energy with a voiced peak must take the full-audio path.
        pcm = b"\xe8\x03" * 40000 + b"\x00\x00" * 24000
        stream, backend, _, audio, path = self.run_stream(pcm)
        self.assertTrue(backend.called.wait(2))
        final = wav_bytes(pcm + b"\x00\x00" * 15999 + b"\x78\x00")
        path.write_bytes(final)
        self.assertIsNone(stream.finish(final))

    def test_quiet_tail_reuses_completed_speech_without_an_empty_decode(self):
        pcm = b"\xe8\x03" * 40000 + b"\x08\x00" * 32000
        stream, backend, _, audio, _ = self.run_stream(pcm)
        self.assertTrue(backend.called.wait(2))
        result = stream.finish(audio)
        self.assertIsNotNone(result)
        self.assertEqual(result.text, "piece1")
        self.assertEqual(len(backend.audio), 1)


class RecoveryTests(unittest.TestCase):
    def test_gpu_failure_uses_only_local_cpu(self):
        from unittest.mock import Mock
        from local_asr import LocalASRProviderAdapter, LocalASRSidecarError
        from provider_types import TranscriptionRequest, ProviderConnection

        gpu = Mock(spec=LocalASRSidecarManager)
        gpu.compute_device = "cuda:0"
        gpu.transcribe.side_effect = LocalASRSidecarError("GPU unavailable")
        cpu = Mock(spec=LocalASRSidecarManager)
        cpu.transcribe.return_value = "local recovery"
        adapter = LocalASRProviderAdapter(backend=cpu)
        request = TranscriptionRequest(
            Path("audio.wav"),
            "ggml-small",
            "pt",
            "",
            "",
            0,
            audio_bytes=b"wave",
            execution_device="cuda:0",
        )
        with patch.object(adapter, "select_backend", side_effect=[gpu, cpu]) as select:
            result = adapter.transcribe(request, ProviderConnection("", ""))
        self.assertEqual(result.text, "local recovery")
        self.assertEqual(select.call_args_list[-1].args, ("ggml-small", "cpu"))
        gpu.stop.assert_called_once()

    def test_cancelled_gpu_does_not_retry_on_cpu(self):
        from unittest.mock import Mock
        from local_asr import LocalASRProviderAdapter, LocalASRCancelledError
        from provider_types import TranscriptionRequest, ProviderConnection

        gpu = Mock(spec=LocalASRSidecarManager)
        gpu.compute_device = "cuda:0"
        gpu.transcribe.side_effect = LocalASRCancelledError("cancelled")
        adapter = LocalASRProviderAdapter(backend=gpu)
        request = TranscriptionRequest(
            Path("audio.wav"), "ggml-small", "pt", "", "", 0, execution_device="cuda:0"
        )
        with patch.object(adapter, "select_backend", return_value=gpu) as select:
            with self.assertRaises(LocalASRCancelledError):
                adapter.transcribe(request, ProviderConnection("", ""))
        self.assertEqual(select.call_count, 1)

    def test_stale_measurement_never_selects_gpu(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bench.json"
            path.write_text(
                json.dumps(
                    {
                        "ggml-small": {
                            "fingerprint": {"driver": "old"},
                            "selected": "cuda:0",
                        }
                    }
                )
            )
            with (
                patch("local_asr_catalog._benchmark_path", return_value=path),
                patch("local_asr_catalog._fingerprint", return_value={"driver": "new"}),
                patch("local_asr_catalog.devices", return_value=[]),
            ):
                self.assertEqual(measured_device("ggml-small"), "cpu")
