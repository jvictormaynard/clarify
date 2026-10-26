"""Wire/security tests use loopback TLS and an isolated SQLite store."""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stderr
import hashlib
import http.client
import io
import json
from pathlib import Path
import socket
import sqlite3
import ssl
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
from uuid import UUID, uuid4
import wave

from computer_host import ComputerHost
from provider_http import ProviderCancelledError
from secret_store import MemorySecretStore


def audio(channels=1, rate=16000, frames=160):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setparams((channels, 2, rate, 0, "NONE", "none"))
        stream.writeframes(b"\0\0" * frames * channels)
    return base64.b64encode(output.getvalue()).decode()


class Processor:
    ready = True

    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.fail = False

    def process_text(self, action, text, language, cancel_token):
        self.calls.append((action, text, language, cancel_token))
        self.entered.set()
        if self.block:
            self.release.wait(5)
        if self.fail:
            raise RuntimeError("private text and token")
        return {
            "transcript": text,
            "text": "Processed.",
            "rewritten": True,
            "successful": True,
        }

    def process_dictation(self, audio_wav, language, cancel_token):
        self.calls.append((audio_wav, language, cancel_token))
        return {
            "transcript": "Spoken.",
            "text": "Spoken.",
            "rewritten": False,
            "successful": True,
        }


class ComputerHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "computer.sqlite3"
        self.secrets = MemorySecretStore()
        self.processor = Processor()
        self.now = 1800000000.0
        self.host = self.new_host()
        self.host.start()

    def new_host(self, **options):
        return ComputerHost(
            self.processor,
            self.secrets,
            self.path,
            computer_name="Test PC",
            host="127.0.0.1",
            port=0,
            clock=lambda: self.now,
            **options,
        )

    def tearDown(self):
        self.processor.release.set()
        self.host.stop()
        self.temp.cleanup()

    def request(
        self, method, path, payload=None, token=None, *, headers=None, raw=None
    ):
        connection = http.client.HTTPSConnection(
            "127.0.0.1",
            self.host.port,
            context=ssl._create_unverified_context(),
            timeout=4,
        )
        request_headers = {"Content-Type": "application/json"}
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        request_headers.update(headers or {})
        body = (
            raw
            if raw is not None
            else (json.dumps(payload).encode() if payload is not None else None)
        )
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def pairing(self, routes=None):
        pairing = self.host.create_pairing(routes)
        encoded = parse_qs(urlsplit(pairing["pairing_url"]).query)["data"][0]
        return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))

    def pair(self):
        qr = self.pairing()
        status, session = self.request(
            "POST",
            "/v1/computer/pair",
            {"pairing_token": qr["pairing_token"], "device_name": "Test iPhone"},
        )
        self.assertEqual(status, 200)
        return qr, session

    def operation(self, at=None):
        timestamp = int((self.now if at is None else at) * 1000)
        data = bytearray(timestamp.to_bytes(6, "big") + uuid4().bytes[6:])
        data[6] = 0x70 | (data[6] & 0x0F)
        data[8] = 0x80 | (data[8] & 0x3F)
        return str(UUID(bytes=bytes(data)))

    def text(self, operation=None, text="Original"):
        return {
            "operation_id": operation or self.operation(),
            "action": "rewrite",
            "text": text,
            "language": "pt",
        }

    def test_disabled_constructor_has_no_disk_or_secret_effects(self):
        self.host.stop()
        other_path = Path(self.temp.name) / "unused" / "state.sqlite3"
        store = MemorySecretStore()
        other = ComputerHost(self.processor, store, other_path)
        self.assertFalse(other.ready)
        self.assertFalse(other_path.parent.exists())
        self.assertEqual(store.values, {})
        other.stop()

    def test_not_ready_rejects_processing_before_provider_call(self):
        _, session = self.pair()
        self.processor.ready = False
        self.assertFalse(
            self.request("GET", "/v1/computer/status", token=session["session_token"])[
                1
            ]["ready"]
        )
        self.assertEqual(
            self.request(
                "POST", "/v1/computer/text", self.text(), session["session_token"]
            ),
            (503, {"error": "not_ready"}),
        )
        self.assertEqual(self.processor.calls, [])

    def test_qr_identity_and_live_certificate_fingerprint(self):
        qr = self.pairing()
        self.assertEqual(
            set(qr),
            {
                "schema_version",
                "computer_id",
                "computer_name",
                "routes",
                "pairing_token",
                "expires_at",
            },
        )
        self.assertEqual(qr["schema_version"], 1)
        self.assertEqual(len(base64.urlsafe_b64decode(qr["pairing_token"] + "=")), 32)
        context = ssl._create_unverified_context()
        with socket.create_connection(("127.0.0.1", self.host.port)) as raw:
            with context.wrap_socket(raw, server_hostname="localhost") as secured:
                fingerprint = hashlib.sha256(
                    secured.getpeercert(binary_form=True)
                ).hexdigest()
        self.assertEqual(
            qr["routes"],
            [
                {
                    "url": f"https://127.0.0.1:{self.host.port}",
                    "certificate_sha256": fingerprint,
                }
            ],
        )

    def test_pairing_consumed_rotated_expired_and_attempt_bounded(self):
        old = self.pairing()
        current = self.pairing()
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/pair",
                {"pairing_token": old["pairing_token"], "device_name": "Phone"},
            )[0],
            401,
        )
        self.now += 301
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/pair",
                {"pairing_token": current["pairing_token"], "device_name": "Phone"},
            )[0],
            401,
        )
        qr, _ = self.pair()
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/pair",
                {"pairing_token": qr["pairing_token"], "device_name": "Phone"},
            )[0],
            401,
        )
        qr = self.pairing()
        for _ in range(5):
            self.assertEqual(
                self.request(
                    "POST",
                    "/v1/computer/pair",
                    {"pairing_token": "x" * 43, "device_name": "Phone"},
                )[0],
                401,
            )
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/pair",
                {"pairing_token": qr["pairing_token"], "device_name": "Phone"},
            )[0],
            401,
        )

    def test_auth_status_snapshot_and_revocation(self):
        _, session = self.pair()
        path = "/v1/computer/status"
        self.assertEqual(self.request("GET", path)[0], 401)
        self.assertEqual(
            self.request("GET", path, token=session["session_token"]),
            (
                200,
                {
                    "schema_version": 1,
                    "computer_id": session["computer_id"],
                    "computer_name": "Test PC",
                    "ready": True,
                },
            ),
        )
        snapshot = self.host.snapshot()
        self.assertEqual(snapshot["devices"][0]["device_id"], session["device_id"])
        self.assertNotIn(session["session_token"], json.dumps(snapshot))
        self.host.revoke_device(session["device_id"])
        self.assertEqual(
            self.request("GET", path, token=session["session_token"])[0], 401
        )

    def test_identity_session_and_operation_survive_restart_without_secrets_or_text_in_db(
        self,
    ):
        qr, session = self.pair()
        request = self.text()
        token = session["session_token"]
        self.assertEqual(
            self.request("POST", "/v1/computer/text", request, token)[0], 200
        )
        self.host.stop()
        self.host = self.new_host()
        self.host.start()
        again = self.pairing()
        self.assertEqual(qr["computer_id"], again["computer_id"])
        self.assertEqual(
            qr["routes"][0]["certificate_sha256"],
            again["routes"][0]["certificate_sha256"],
        )
        self.assertEqual(
            self.request("GET", "/v1/computer/status", token=token)[0], 200
        )
        self.assertEqual(
            self.request("POST", "/v1/computer/text", request, token),
            (409, {"error": "result_unavailable"}),
        )
        raw = self.path.read_bytes()
        for secret in (qr["pairing_token"], token, "Original", "Processed."):
            self.assertNotIn(secret.encode(), raw)
        self.assertEqual(len(self.processor.calls), 1)

    def test_text_and_dictation_success_retry_and_collision(self):
        _, session = self.pair()
        token = session["session_token"]
        request = self.text()
        response = self.request("POST", "/v1/computer/text", request, token)
        self.assertEqual(
            response,
            (
                200,
                {
                    "operation_id": request["operation_id"],
                    "transcript": "Original",
                    "text": "Processed.",
                    "rewritten": True,
                    "successful": True,
                },
            ),
        )
        self.assertEqual(
            self.request("POST", "/v1/computer/text", request, token), response
        )
        self.assertEqual(len(self.processor.calls), 1)
        self.assertEqual(
            self.request(
                "POST", "/v1/computer/text", {**request, "text": "Changed"}, token
            ),
            (409, {"error": "operation_conflict"}),
        )
        response = self.request(
            "POST",
            "/v1/computer/dictations",
            {"operation_id": self.operation(), "language": "en", "audio_wav": audio()},
            token,
        )
        self.assertEqual(response[0], 200)
        self.assertEqual(response[1]["text"], "Spoken.")

    def test_text_input_uses_the_mobile_utf8_limit_before_provider_work(self):
        _, session = self.pair()
        token = session["session_token"]
        self.assertEqual(
            self.request(
                "POST", "/v1/computer/text", self.text(text="é" * 16384), token
            )[0],
            200,
        )
        self.assertEqual(
            self.request(
                "POST", "/v1/computer/text", self.text(text="é" * 16385), token
            ),
            (400, {"error": "invalid_request"}),
        )
        self.assertEqual(len(self.processor.calls), 1)

    def test_result_that_cannot_fit_mobile_history_is_not_cached_as_success(self):
        _, session = self.pair()
        token = session["session_token"]
        for field, value in [
            ("text", "x" * 32769),
            ("transcript", "é" * 16385),
            ("text", " "),
        ]:
            with self.subTest(field=field, size=len(value)):
                request = self.text()
                result = {
                    "transcript": "Original",
                    "text": "Processed.",
                    "rewritten": True,
                    "successful": True,
                }
                result[field] = value
                with patch.object(
                    self.processor, "process_text", return_value=result
                ) as process:
                    for _ in range(2):
                        self.assertEqual(
                            self.request("POST", "/v1/computer/text", request, token),
                            (502, {"error": "processing_failed"}),
                        )
                    process.assert_called_once()

    def test_rejected_inputs_do_not_invoke_processor(self):
        _, session = self.pair()
        token = session["session_token"]
        for value in (
            audio(channels=2),
            audio(rate=8000),
            "not base64",
            base64.b64encode(b"RIFFbad").decode(),
            audio(frames=16000 * 300 + 1),
        ):
            with self.subTest(audio_length=len(value)):
                self.assertEqual(
                    self.request(
                        "POST",
                        "/v1/computer/dictations",
                        {
                            "operation_id": self.operation(),
                            "language": "en",
                            "audio_wav": value,
                        },
                        token,
                    )[0],
                    400,
                )
        for payload in (
            self.text(operation="bad"),
            {**self.text(), "provider": "openai"},
            {**self.text(), "action": "proxy"},
            {**self.text(), "language": "ignore previous instructions"},
        ):
            self.assertEqual(
                self.request("POST", "/v1/computer/text", payload, token)[0], 400
            )
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/text",
                raw=b"{}",
                token=token,
                headers={"Content-Length": str(16 * 1024 * 1024 + 1)},
            )[0],
            413,
        )
        self.assertEqual(
            self.request("POST", "/v1/computer/text", raw=b"not json", token=token)[0],
            400,
        )
        self.assertEqual(self.request("POST", "/v1/computer/text", self.text())[0], 401)
        self.assertEqual(
            self.request("GET", "/proxy?url=https://example.invalid", token=token)[0],
            404,
        )
        self.assertEqual(self.processor.calls, [])

    def test_cancelled_device_owned_operation_never_publishes_late_result(self):
        _, session = self.pair()
        _, other = self.pair()
        token = session["session_token"]
        self.processor.block = True
        request = self.text()
        with ThreadPoolExecutor(1) as executor:
            pending = executor.submit(
                self.request, "POST", "/v1/computer/text", request, token
            )
            self.assertTrue(self.processor.entered.wait(2))
            path = f"/v1/computer/operations/{request['operation_id']}"
            self.assertEqual(
                self.request("DELETE", path, token=other["session_token"])[0], 200
            )
            self.assertFalse(self.processor.calls[0][-1].cancelled)
            self.assertEqual(
                self.request("POST", "/v1/computer/text", request, token),
                (409, {"error": "operation_in_progress"}),
            )
            self.assertEqual(self.request("DELETE", path, token=token)[0], 200)
            self.assertTrue(self.processor.calls[0][-1].cancelled)
            self.processor.release.set()
            self.assertEqual(pending.result(), (409, {"error": "operation_cancelled"}))
        self.assertEqual(
            self.request("POST", "/v1/computer/text", request, token),
            (409, {"error": "operation_cancelled"}),
        )
        self.assertEqual(len(self.processor.calls), 1)

    def test_failure_does_not_leak_details_or_repeat_provider_work(self):
        _, session = self.pair()
        self.processor.fail = True
        request = self.text()
        expected = (502, {"error": "processing_failed"})
        output = io.StringIO()
        with redirect_stderr(output):
            for _ in range(2):
                self.assertEqual(
                    self.request(
                        "POST", "/v1/computer/text", request, session["session_token"]
                    ),
                    expected,
                )
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(len(self.processor.calls), 1)

    def test_stop_closes_listener_even_if_state_write_fails(self):
        port = self.host.port
        db = self.host._db
        with patch.object(self.host, "_db", wraps=db) as failing:
            failing.execute.side_effect = sqlite3.OperationalError("disk failure")
            self.host.stop()
        self.host._db = None
        self.assertFalse(self.host.ready)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=0.2)

    def test_session_delete_revokes_only_current_device(self):
        _, first = self.pair()
        _, second = self.pair()
        self.assertEqual(
            self.request(
                "DELETE", "/v1/computer/session", token=first["session_token"]
            )[0],
            200,
        )
        self.assertEqual(
            self.request("GET", "/v1/computer/status", token=first["session_token"])[0],
            401,
        )
        self.assertEqual(
            self.request("GET", "/v1/computer/status", token=second["session_token"])[
                0
            ],
            200,
        )

    def test_revocation_survives_restart(self):
        _, session = self.pair()
        self.host.revoke_device(session["device_id"])
        self.host.stop()
        self.host = self.new_host()
        self.host.start()
        self.assertEqual(
            self.request("GET", "/v1/computer/status", token=session["session_token"])[
                0
            ],
            401,
        )

    def test_disabled_host_lists_and_revokes_persisted_devices_without_listener(self):
        _, session = self.pair()
        self.host.stop()
        self.host = self.new_host()
        self.assertEqual(
            self.host.snapshot()["devices"][0]["device_id"], session["device_id"]
        )
        self.assertFalse(self.host.snapshot()["enabled"])
        self.host.revoke_device(session["device_id"])
        self.assertEqual(self.host.snapshot()["devices"], [])
        self.assertFalse(self.host.ready)
        self.host.start()
        self.assertEqual(
            self.request("GET", "/v1/computer/status", token=session["session_token"])[
                0
            ],
            401,
        )

    def test_crash_left_running_record_is_uncertain_and_never_reexecuted(self):
        _, session = self.pair()
        request = self.text()
        self.assertEqual(
            self.request(
                "POST", "/v1/computer/text", request, session["session_token"]
            )[0],
            200,
        )
        self.host.stop()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE operations SET state='running'")
            db.commit()
        self.host = self.new_host()
        self.host.start()
        self.assertEqual(
            self.request(
                "POST", "/v1/computer/text", request, session["session_token"]
            ),
            (409, {"error": "result_unavailable"}),
        )
        self.assertEqual(len(self.processor.calls), 1)

    def test_result_eviction_and_operation_capacity_fail_closed(self):
        _, session = self.pair()
        token = session["session_token"]
        first = self.text()
        with (
            patch("computer_host.MAX_RESULTS", 1),
            patch("computer_host.MAX_OPERATIONS", 2),
        ):
            for request in (first, self.text()):
                self.assertEqual(
                    self.request("POST", "/v1/computer/text", request, token)[0], 200
                )
            self.assertEqual(
                self.request("POST", "/v1/computer/text", first, token),
                (409, {"error": "result_unavailable"}),
            )
            self.assertEqual(
                self.request("POST", "/v1/computer/text", self.text(), token),
                (429, {"error": "operation_limit"}),
            )
        self.assertEqual(len(self.processor.calls), 2)

    def test_operation_id_is_scoped_to_device(self):
        _, first = self.pair()
        _, second = self.pair()
        request = self.text()
        self.assertEqual(
            self.request("POST", "/v1/computer/text", request, first["session_token"])[
                0
            ],
            200,
        )
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/text",
                {**request, "text": "Other source"},
                second["session_token"],
            )[0],
            200,
        )
        self.assertEqual(len(self.processor.calls), 2)

    def test_uuid7_rfc_vector_and_time_admission_boundaries(self):
        _, session = self.pair()
        token = session["session_token"]
        self.now = 1645557742.0
        # RFC 9562 Appendix A.6, independent of the fixture generator.
        vector = "017f22e2-79b0-7cc3-98c4-dc0c0c07398f"
        for operation in (
            vector,
            self.operation(self.now - 7200),
            self.operation(self.now + 300),
        ):
            self.assertEqual(
                self.request("POST", "/v1/computer/text", self.text(operation), token)[
                    0
                ],
                200,
            )
        for operation, code, status in (
            (self.operation(self.now - 7200.001), "operation_expired", 409),
            (self.operation(self.now + 300.001), "operation_in_future", 400),
            (str(uuid4()), "invalid_operation_id", 400),
            (vector[:19] + "7" + vector[20:], "invalid_operation_id", 400),
        ):
            with self.subTest(code=code, operation=operation):
                self.assertEqual(
                    self.request(
                        "POST", "/v1/computer/text", self.text(operation), token
                    ),
                    (status, {"error": code}),
                )
        self.assertEqual(len(self.processor.calls), 3)

    def test_operation_window_recovers_capacity_and_does_not_revive_pruned_ids(self):
        _, session = self.pair()
        token = session["session_token"]
        first = self.text()
        with patch("computer_host.MAX_OPERATIONS", 2):
            for request in (first, self.text()):
                self.assertEqual(
                    self.request("POST", "/v1/computer/text", request, token)[0], 200
                )
            self.assertEqual(
                self.request("POST", "/v1/computer/text", self.text(), token),
                (429, {"error": "operation_limit"}),
            )
            self.now += 7501
            self.assertEqual(
                self.request("POST", "/v1/computer/text", self.text(), token)[0], 200
            )
            self.assertNotIn(
                (session["device_id"], first["operation_id"]), self.host._results
            )
            with closing(sqlite3.connect(self.path)) as db:
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                        (first["operation_id"],),
                    ).fetchone()[0],
                    0,
                )
            self.host.stop()
            self.now -= 7501
            self.host = self.new_host()
            self.host.start()
            for method, path, body in (
                ("POST", "/v1/computer/text", first),
                ("DELETE", "/v1/computer/operations/" + first["operation_id"], None),
            ):
                self.assertEqual(
                    self.request(method, path, body, token),
                    (409, {"error": "operation_expired"}),
                )
        self.assertEqual(len(self.processor.calls), 3)

    def test_v1_legacy_capacity_requires_explicit_revocation_and_pairing(self):
        _, session = self.pair()
        token = session["session_token"]
        legacy = str(uuid4())
        identity = session["computer_id"]
        self.host.stop()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("DROP TABLE IF EXISTS replay_window")
            db.execute("PRAGMA user_version=1")
            db.execute(
                "INSERT INTO operations VALUES (?,?,?,?,?)",
                (
                    session["device_id"],
                    legacy,
                    "legacy-hash",
                    "failed",
                    self.now - 9000,
                ),
            )
            db.commit()
        self.host = self.new_host()
        self.host.start()
        with patch("computer_host.MAX_OPERATIONS", 1):
            for _ in range(2):
                request = self.text()
                self.assertEqual(
                    self.request("POST", "/v1/computer/text", request, token),
                    (409, {"error": "operation_history_full"}),
                )
                self.assertEqual(
                    self.request(
                        "DELETE",
                        "/v1/computer/operations/" + request["operation_id"],
                        token=token,
                    ),
                    (409, {"error": "operation_history_full"}),
                )
                self.now += 7501
            self.assertEqual(
                self.request("POST", "/v1/computer/text", self.text(legacy), token),
                (409, {"error": "operation_conflict"}),
            )
            with closing(sqlite3.connect(self.path)) as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM operations").fetchone()[0], 1
                )
                self.assertEqual(
                    db.execute(
                        "SELECT content_hash,state FROM operations WHERE operation_id=?",
                        (legacy,),
                    ).fetchone(),
                    ("legacy-hash", "failed"),
                )
            self.assertEqual(self.processor.calls, [])
            self.host.revoke_device(session["device_id"])
            self.assertEqual(
                self.request("GET", "/v1/computer/status", token=token),
                (401, {"error": "unauthorized"}),
            )
            with closing(sqlite3.connect(self.path)) as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM operations").fetchone()[0], 0
                )
            _, replacement = self.pair()
            self.assertEqual(
                self.request(
                    "POST",
                    "/v1/computer/text",
                    self.text(legacy),
                    replacement["session_token"],
                ),
                (400, {"error": "invalid_operation_id"}),
            )
            self.assertEqual(
                self.request(
                    "POST",
                    "/v1/computer/text",
                    self.text(),
                    replacement["session_token"],
                )[0],
                200,
            )
            self.assertEqual(replacement["computer_id"], identity)
            self.assertNotEqual(replacement["device_id"], session["device_id"])
        self.assertEqual(len(self.processor.calls), 1)

    def test_mixed_legacy_and_uuid7_claims_share_the_total_metadata_bound(self):
        _, session = self.pair()
        token = session["session_token"]
        legacy = str(uuid4())
        with closing(sqlite3.connect(self.path)) as db:
            db.execute(
                "INSERT INTO operations VALUES (?,?,?,?,?)",
                (session["device_id"], legacy, "fixture", "uncertain", self.now - 9000),
            )
            db.commit()
        with patch("computer_host.MAX_OPERATIONS", 2):
            self.assertEqual(
                self.request("POST", "/v1/computer/text", self.text(), token)[0], 200
            )
            blocked = self.text()
            self.assertEqual(
                self.request("POST", "/v1/computer/text", blocked, token),
                (429, {"error": "operation_limit"}),
            )
            self.assertEqual(
                self.request(
                    "DELETE",
                    "/v1/computer/operations/" + blocked["operation_id"],
                    token=token,
                ),
                (429, {"error": "operation_limit"}),
            )
            self.now += 7201
            self.assertEqual(
                self.request("POST", "/v1/computer/text", self.text(), token)[0], 200
            )
            with closing(sqlite3.connect(self.path)) as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM operations").fetchone()[0], 2
                )
                self.assertEqual(
                    db.execute(
                        "SELECT state FROM operations WHERE operation_id=?", (legacy,)
                    ).fetchone()[0],
                    "uncertain",
                )
        self.assertEqual(len(self.processor.calls), 2)

    def test_unknown_legacy_and_future_ids_cannot_reserve_cancellation(self):
        _, session = self.pair()
        for operation, code in (
            (str(uuid4()), "invalid_operation_id"),
            (self.operation(self.now + 301), "operation_in_future"),
        ):
            self.assertEqual(
                self.request(
                    "DELETE",
                    "/v1/computer/operations/" + operation,
                    token=session["session_token"],
                ),
                (400, {"error": code}),
            )
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM operations").fetchone()[0], 0
            )

    def test_pruning_removes_expired_uncertain_but_preserves_active_and_legacy(self):
        _, session = self.pair()
        token = session["session_token"]
        claims = [
            (self.operation(), state)
            for state in ("succeeded", "failed", "cancelled", "uncertain")
        ] + [(str(uuid4()), "failed")]
        with closing(sqlite3.connect(self.path)) as db:
            db.executemany(
                "INSERT INTO operations VALUES (?,?,?,?,?)",
                [
                    (session["device_id"], operation, "fixture", state, self.now)
                    for operation, state in claims
                ],
            )
            db.commit()
        active = self.text()
        self.processor.block = True
        with ThreadPoolExecutor(1) as executor:
            pending = executor.submit(
                self.request, "POST", "/v1/computer/text", active, token
            )
            self.assertTrue(self.processor.entered.wait(2))
            self.now += 7501
            self.assertEqual(
                self.request(
                    "DELETE",
                    "/v1/computer/operations/" + active["operation_id"],
                    token=token,
                )[0],
                200,
            )
            # A second admission runs pruning while the cancelled callback is
            # still active; only its owning request may release its resources.
            self.processor.block = False
            self.assertEqual(
                self.request("POST", "/v1/computer/text", self.text(), token)[0], 200
            )
            with closing(sqlite3.connect(self.path)) as db:
                rows = dict(db.execute("SELECT operation_id,state FROM operations"))
            for operation, _ in claims[:4]:
                self.assertNotIn(operation, rows)
            self.assertEqual(rows[claims[4][0]], "failed")
            self.assertEqual(rows[active["operation_id"]], "cancelled")
            self.processor.release.set()
            self.assertEqual(pending.result(), (409, {"error": "operation_cancelled"}))
        self.assertEqual(
            self.request("POST", "/v1/computer/text", self.text(), token)[0], 200
        )
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(
                db.execute(
                    "SELECT 1 FROM operations WHERE operation_id=?",
                    (active["operation_id"],),
                ).fetchone()
            )

    def test_crash_restart_windows_keep_actual_metadata_bounded_without_reexecution(
        self,
    ):
        _, session = self.pair()
        token = session["session_token"]
        first = self.text()
        initial_time = self.now
        requests = [first, self.text()]
        with patch("computer_host.MAX_OPERATIONS", 2):
            for cycle in range(4):
                if cycle:
                    requests = [self.text(), self.text()]
                for request in requests:
                    self.assertEqual(
                        self.request("POST", "/v1/computer/text", request, token)[0],
                        200,
                    )
                    with closing(sqlite3.connect(self.path)) as db:
                        self.assertLessEqual(
                            db.execute("SELECT COUNT(*) FROM operations").fetchone()[0],
                            2,
                        )
                self.host.stop()
                # Simulate the durable claims left by a process crash, without
                # using real providers or leaving a live request worker behind.
                with closing(sqlite3.connect(self.path)) as db:
                    db.execute("UPDATE operations SET state='running'")
                    db.commit()
                self.host = self.new_host()
                self.host.start()
                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(
                        db.execute("SELECT state FROM operations").fetchall(),
                        [("uncertain",), ("uncertain",)],
                    )
                self.assertEqual(
                    self.request("POST", "/v1/computer/text", self.text(), token),
                    (429, {"error": "operation_limit"}),
                )
                self.assertEqual(
                    self.request("POST", "/v1/computer/text", requests[0], token),
                    (409, {"error": "result_unavailable"}),
                )
                self.now += 7201
            self.assertEqual(
                self.request("POST", "/v1/computer/text", self.text(), token)[0], 200
            )
            self.host.stop()
            self.now = initial_time
            self.host = self.new_host()
            self.host.start()
            self.assertEqual(
                self.request("POST", "/v1/computer/text", first, token),
                (409, {"error": "operation_expired"}),
            )
            with closing(sqlite3.connect(self.path)) as db:
                self.assertLessEqual(
                    db.execute("SELECT COUNT(*) FROM operations").fetchone()[0], 2
                )
        self.assertEqual(len(self.processor.calls), 9)

    def test_unknown_future_schema_is_not_modified(self):
        self.host.stop()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA user_version=3")
            db.commit()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Unsupported computer state version"):
            self.new_host().start()
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_persisted_window_cannot_reset_replay_barrier(self):
        self.host.stop()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("DELETE FROM replay_window")
            db.commit()
        with self.assertRaisesRegex(ValueError, "Invalid computer replay window"):
            self.new_host().start()

    def test_address_provider_preserves_priority_filters_and_deduplicates(self):
        self.host.stop()
        self.host = self.new_host(
            address_provider=lambda: [
                "garbage",
                "::1",
                "8.8.8.8",
                "192.168.1.255",
                "192.168.1.255",
                "10.0.0.0",
                "172.16.3.2",
                "10.0.1.1",
                "10.0.2.1",
            ]
        )
        self.host.start()
        with patch.object(self.host, "host", "0.0.0.0"):
            qr = self.pairing()
        self.assertEqual(
            [route["url"] for route in qr["routes"]],
            [
                f"https://{ip}:{self.host.port}"
                for ip in ("192.168.1.255", "10.0.0.0", "172.16.3.2", "10.0.1.1")
            ],
        )

    def test_concurrent_operation_limit_rejects_before_claim_then_allows_retry(self):
        self.host.stop()
        self.host = self.new_host(max_concurrent_operations=1)
        self.host.start()
        _, session = self.pair()
        token = session["session_token"]
        self.processor.block = True
        second = self.text()
        with ThreadPoolExecutor(1) as executor:
            pending = executor.submit(
                self.request, "POST", "/v1/computer/text", self.text(), token
            )
            self.assertTrue(self.processor.entered.wait(2))
            self.assertEqual(
                self.request("POST", "/v1/computer/text", second, token),
                (429, {"error": "busy"}),
            )
            self.processor.release.set()
            self.assertEqual(pending.result()[0], 200)
        self.assertEqual(
            self.request("POST", "/v1/computer/text", second, token)[0], 200
        )
        self.assertEqual(len(self.processor.calls), 2)

    def test_provider_cancellation_has_terminal_state(self):
        _, session = self.pair()
        request = self.text()
        with patch.object(
            self.processor, "process_text", side_effect=ProviderCancelledError()
        ) as processor:
            for _ in range(2):
                self.assertEqual(
                    self.request(
                        "POST", "/v1/computer/text", request, session["session_token"]
                    ),
                    (409, {"error": "operation_cancelled"}),
                )
            self.assertEqual(processor.call_count, 1)

    def test_cancellation_before_admission_prevents_late_upload_work(self):
        _, session = self.pair()
        request = self.text()
        path = f"/v1/computer/operations/{request['operation_id']}"
        self.assertEqual(
            self.request("DELETE", path, token=session["session_token"])[0], 200
        )
        self.assertEqual(
            self.request(
                "POST", "/v1/computer/text", request, session["session_token"]
            ),
            (409, {"error": "operation_cancelled"}),
        )
        self.assertEqual(self.processor.calls, [])

    def test_cancel_after_processing_before_response_blocks_success_publication(self):
        _, session = self.pair()
        request = self.text()
        processed, release_reply = threading.Event(), threading.Event()
        process = self.host._process

        def hold_response(*args):
            result = process(*args)
            processed.set()
            release_reply.wait(3)
            return result

        with (
            patch.object(self.host, "_process", side_effect=hold_response),
            ThreadPoolExecutor(1) as executor,
        ):
            pending = executor.submit(
                self.request,
                "POST",
                "/v1/computer/text",
                request,
                session["session_token"],
            )
            try:
                self.assertTrue(processed.wait(2))
                self.assertEqual(
                    self.request(
                        "DELETE",
                        f"/v1/computer/operations/{request['operation_id']}",
                        token=session["session_token"],
                    )[0],
                    200,
                )
            finally:
                release_reply.set()
            self.assertEqual(pending.result(), (409, {"error": "operation_cancelled"}))

    def test_revocation_cancels_running_device_work(self):
        _, session = self.pair()
        self.processor.block = True
        with ThreadPoolExecutor(1) as executor:
            pending = executor.submit(
                self.request,
                "POST",
                "/v1/computer/text",
                self.text(),
                session["session_token"],
            )
            self.assertTrue(self.processor.entered.wait(2))
            self.host.revoke_device(session["device_id"])
            self.assertTrue(self.processor.calls[0][-1].cancelled)
            self.processor.release.set()
            self.assertEqual(pending.result(), (409, {"error": "operation_cancelled"}))

    def test_bounded_handlers_and_read_deadline_free_slots_for_valid_request(self):
        self.host.stop()
        self.host = self.new_host(
            max_handlers=2, max_concurrent_operations=1, read_timeout=0.3
        )
        self.host.start()
        connections = []
        try:
            for _ in range(2):
                connections.append(
                    socket.create_connection(("127.0.0.1", self.host.port), timeout=1)
                )
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                with self.host._server.guard:
                    if len(self.host._server.connections) == 2:
                        break
                time.sleep(0.01)
            with socket.create_connection(
                ("127.0.0.1", self.host.port), timeout=1
            ) as third:
                self.assertEqual(third.recv(1), b"")
            for connection in connections:
                self.assertEqual(connection.recv(1), b"")
        finally:
            for connection in connections:
                connection.close()
        self.pair()

    def test_malformed_framing_duplicate_fields_and_surrogates_are_rejected(self):
        _, session = self.pair()
        token = session["session_token"]
        for raw in (b'{"x":1,"x":2}', b'{"text":"\\ud800"}', b'{"x":NaN}'):
            self.assertEqual(
                self.request("POST", "/v1/computer/text", token=token, raw=raw)[0], 400
            )
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/text",
                self.text(),
                token,
                headers={"Transfer-Encoding": "chunked"},
            )[0],
            400,
        )
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/text",
                self.text(),
                token,
                headers={"Content-Type": "text/plain"},
            )[0],
            415,
        )
        self.assertEqual(self.processor.calls, [])

    def test_state_identity_mismatch_fails_closed(self):
        self.host.stop()
        original = self.secrets.values.pop("clarify_computer")
        try:
            with self.assertRaisesRegex(OSError, "identity is missing"):
                self.new_host().start()
        finally:
            self.secrets.set("clarify_computer", original)

    def test_invalid_routes_do_not_replace_pairing(self):
        qr = self.pairing()
        for url in (
            "http://127.0.0.1:47653",
            "https://user:secret@127.0.0.1:47653",
            f"https://127.0.0.1:{self.host.port}/proxy",
        ):
            with self.assertRaises(ValueError):
                self.host.create_pairing([url])
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/pair",
                {"pairing_token": qr["pairing_token"], "device_name": "Phone"},
            )[0],
            200,
        )

    def test_stop_cancels_running_work_and_closes_listener(self):
        _, session = self.pair()
        port = self.host.port
        entered, cancelled, release, unwound, joining = (
            threading.Event() for _ in range(5)
        )
        registry_shutdown = threading.Event()
        processor_threads = []
        original_join = threading.Thread.join

        def controlled_processor(action, text, language, cancel_token):
            processor_threads.append(threading.current_thread())
            entered.set()
            try:
                if not cancel_token.wait(5):
                    raise AssertionError("Stop did not cancel the processor")
                cancelled.set()
                if not release.wait(5):
                    raise AssertionError("Test did not release the cancelled processor")
                return {
                    "transcript": text,
                    "text": "Late.",
                    "rewritten": True,
                    "successful": True,
                }
            finally:
                unwound.set()

        def observe_join(worker, *args, **kwargs):
            if processor_threads and worker is processor_threads[0]:
                joining.set()
            return original_join(worker, *args, **kwargs)

        def stop_then_shutdown_registry():
            self.host.stop()
            self.assertTrue(unwound.is_set())
            registry_shutdown.set()

        request = self.text()
        with (
            patch.object(
                self.processor, "process_text", side_effect=controlled_processor
            ) as process,
            patch.object(threading.Thread, "join", observe_join),
            ThreadPoolExecutor(2) as executor,
        ):
            pending = executor.submit(
                self.request,
                "POST",
                "/v1/computer/text",
                request,
                session["session_token"],
            )
            self.assertTrue(entered.wait(3))
            stopped = executor.submit(stop_then_shutdown_registry)
            try:
                self.assertTrue(cancelled.wait(3))
                # Observe the actual worker join rather than inferring a drain
                # from elapsed time. The processor still owns shared resources.
                self.assertTrue(joining.wait(3))
                self.assertFalse(stopped.done())
                self.assertFalse(registry_shutdown.is_set())
                self.assertFalse(unwound.is_set())
            finally:
                release.set()
            stopped.result(timeout=5)
            self.assertTrue(registry_shutdown.is_set())
            self.assertFalse(self.host.ready)
            with self.assertRaises(OSError):
                socket.create_connection(("127.0.0.1", port), timeout=0.2)
            try:
                result = pending.result(timeout=5)
            except (OSError, http.client.HTTPException):
                pass
            else:
                self.assertEqual(result, (409, {"error": "operation_cancelled"}))
            self.host.start()
            self.assertEqual(
                self.request(
                    "POST", "/v1/computer/text", request, session["session_token"]
                ),
                (409, {"error": "operation_cancelled"}),
            )
            process.assert_called_once()
        self.assertEqual(
            self.request(
                "POST", "/v1/computer/text", self.text(), session["session_token"]
            )[0],
            200,
        )

    def test_discovered_routes_filter_to_four_unique_rfc1918_addresses(self):
        addresses = [
            "203.0.113.10",
            "169.254.2.3",
            "127.0.0.1",
            "0.0.0.0",
            "224.0.0.1",
            "100.64.0.1",
            "192.0.0.1",
            "192.168.2.4",
            "10.0.0.255",
            "172.16.0.7",
            "10.0.0.0",
            "172.31.255.255",
            "10.0.0.0",
        ]
        info = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))
            for ip in addresses
        ]
        with (
            patch.object(self.host, "host", "0.0.0.0"),
            patch("computer_host.socket.getaddrinfo", return_value=info),
        ):
            qr = self.pairing()
        self.assertEqual(
            [route["url"] for route in qr["routes"]],
            [
                f"https://{ip}:{self.host.port}"
                for ip in ("192.168.2.4", "10.0.0.255", "172.16.0.7", "10.0.0.0")
            ],
        )
        self.assertTrue(
            all(len(route["certificate_sha256"]) == 64 for route in qr["routes"])
        )

    def test_explicit_lan_routes_accept_rfc1918_and_reject_unsupported_addresses(self):
        with patch.object(self.host, "host", "0.0.0.0"):
            routes = [
                f"https://{ip}:{self.host.port}"
                for ip in ("10.2.3.0", "172.16.1.255", "172.31.0.8", "192.168.4.9")
            ]
            self.assertEqual(
                [route["url"] for route in self.pairing(routes)["routes"]], routes
            )
            for ip in (
                "172.15.0.1",
                "172.32.0.1",
                "192.169.0.1",
                "8.8.8.8",
                "169.254.1.2",
                "127.0.0.1",
                "100.64.0.1",
            ):
                with self.subTest(ip=ip), self.assertRaises(ValueError):
                    self.host.create_pairing([f"https://{ip}:{self.host.port}"])
            with self.assertRaises(ValueError):
                self.host.create_pairing(
                    routes + [f"https://10.0.0.5:{self.host.port}"]
                )

    def test_no_supported_discovered_route_preserves_existing_pairing(self):
        qr = self.pairing()
        info = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))
            for ip in ("8.8.8.8", "169.254.1.2", "127.0.0.1")
        ]
        with (
            patch.object(self.host, "host", "0.0.0.0"),
            patch("computer_host.socket.getaddrinfo", return_value=info),
        ):
            with self.assertRaises(ValueError):
                self.host.create_pairing()
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/pair",
                {"pairing_token": qr["pairing_token"], "device_name": "Phone"},
            )[0],
            200,
        )
