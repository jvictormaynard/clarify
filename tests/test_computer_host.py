"""Wire/security tests use loopback TLS and an isolated SQLite store."""

import asyncio
import base64
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stderr, suppress
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, parse_qs
from uuid import UUID, uuid4
import wave

from cryptography import x509

from computer_host import ComputerHost
from computer_relay_client import ComputerRelayClient
from computer_relay_protocol import RelayError, challenge, verify, certificate_key
from computer_relay_server import ComputerRelayServer
from computer_processing import ComputerProcessor
from dictionary_snippets import (
    DictionarySnippets,
    DictionarySnippetService,
    InMemoryDictionarySnippetsRepository,
)
from provider_http import ProviderCancelledError
from provider_registry import PROVIDER_REGISTRY, ProviderRegistry
from provider_types import RewriteResult, TranslationResult
from repositories import AppConfig, ProviderConfig
from secret_store import MemorySecretStore
from text_actions import TextAction, TextActionProfile, TextActionSettings
from workflow_config import WorkflowConfig, WorkflowRoute


def audio(channels=1, rate=16000, frames=160):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setparams((channels, 2, rate, 0, "NONE", "none"))
        stream.writeframes(b"\0\0" * frames * channels)
    return base64.b64encode(output.getvalue()).decode()


class Processor:
    ready = True

    @property
    def action_readiness(self):
        return dict.fromkeys(("dictate", "rewrite", "translate"), self.ready)

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


class RelayClient:
    """Controlled relay lifecycle; no resolver, socket or profile access."""

    connected = False
    status = "retrying"

    def __init__(self):
        self.start = Mock()
        self.stop = Mock(return_value=True)


class HostRelayLoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_relay_pins_host_and_preserves_once_only_cancel_and_revocation(
        self,
    ):
        try:
            from .test_computer_relay import (
                HOST,
                client_context,
                eventually,
                make_certificate,
                server_context,
            )
        except ImportError:
            from test_computer_relay import (
                HOST,
                client_context,
                eventually,
                make_certificate,
                server_context,
            )

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        ca_key, ca = make_certificate("test CA", is_ca=True)
        key, cert = make_certificate(HOST, ca=ca, ca_key=ca_key)
        server = ComputerRelayServer(
            "127.0.0.1",
            0,
            HOST,
            server_context(root, "relay", key, cert),
            root / "budget.db",
            1_000_000,
        )
        await server.start()
        self.addAsyncCleanup(server.stop)
        clients = []

        def factory(relay_host, identity, target_port, *, relay_port):
            client = ComputerRelayClient(
                relay_host,
                identity,
                target_port,
                relay_port=relay_port,
                fixture_address="127.0.0.1",
                fixture_ssl_context=client_context(ca),
                reconnect_initial=0.05,
                reconnect_max=0.1,
            )
            clients.append(client)
            return client

        processor = Processor()
        host = ComputerHost(
            processor,
            MemorySecretStore(),
            root / "computer.sqlite3",
            host="127.0.0.1",
            port=0,
            relay_host=HOST,
            relay_port=server.address[1],
            relay_client_factory=factory,
            address_provider=lambda: [],
        )

        async def stop_host():
            processor.release.set()
            await asyncio.to_thread(host.stop)

        self.addAsyncCleanup(stop_host)
        # Every dial uses a literal loopback fixture. No public DNS is allowed.
        with patch("socket.getaddrinfo", side_effect=AssertionError("DNS forbidden")):
            host.start()
            await eventually(lambda: host.snapshot()["relay_connected"])
            self.assertEqual(clients[0].target_port, host.port)
            with patch.object(host, "host", "0.0.0.0"):
                pairing = host.create_pairing()
            encoded = parse_qs(urlsplit(pairing["pairing_url"]).query)["data"][0]
            qr = json.loads(
                base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            )
            self.assertEqual(len(qr["routes"]), 1)
            route = qr["routes"][0]
            pc_cert = x509.load_der_x509_certificate(
                clients[0].identity.certificate_der
            )

            async def request(method, path, payload=None, token=None):
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1",
                    server.address[1],
                    ssl=client_context(pc_cert, check_hostname=False),
                    server_hostname=urlsplit(route["url"]).hostname,
                    ssl_handshake_timeout=3,
                )
                try:
                    der = writer.get_extra_info("ssl_object").getpeercert(
                        binary_form=True
                    )
                    self.assertEqual(
                        hashlib.sha256(der).hexdigest(), route["certificate_sha256"]
                    )
                    body = json.dumps(payload).encode() if payload is not None else b""
                    headers = f"{method} /v1/computer/{path} HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n"
                    if token:
                        headers += f"Authorization: Bearer {token}\r\n"
                    writer.write(headers.encode() + b"\r\n" + body)
                    await writer.drain()
                    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 4)
                    status = int(head.split(b" ", 2)[1])
                    size = next(
                        int(line.split(b":", 1)[1])
                        for line in head.split(b"\r\n")
                        if line.lower().startswith(b"content-length:")
                    )
                    return status, json.loads(
                        await asyncio.wait_for(reader.readexactly(size), 4)
                    )
                finally:
                    writer.close()
                    with suppress(OSError, TimeoutError):
                        await asyncio.wait_for(writer.wait_closed(), 1)

            status, session = await request(
                "POST",
                "pair",
                {
                    "pairing_token": qr["pairing_token"],
                    "device_name": "Fixture phone",
                },
            )
            self.assertEqual(status, 200)
            token = session["session_token"]

            def text():
                data = bytearray(
                    int(time.time() * 1000).to_bytes(6, "big") + uuid4().bytes[6:]
                )
                data[6], data[8] = 0x70 | data[6] & 0x0F, 0x80 | data[8] & 0x3F
                return {
                    "operation_id": str(UUID(bytes=bytes(data))),
                    "action": "rewrite",
                    "text": "Original",
                    "language": "pt",
                }

            first = text()
            result = await request("POST", "text", first, token)
            self.assertEqual(result[0], 200)
            self.assertEqual(result[1]["text"], "Processed.")
            self.assertEqual(await request("POST", "text", first, token), result)
            self.assertEqual(len(processor.calls), 1)
            processor.block = True
            processor.entered.clear()
            second = text()
            pending = asyncio.create_task(request("POST", "text", second, token))
            try:
                await eventually(processor.entered.is_set)
                self.assertEqual(
                    (
                        await request(
                            "DELETE",
                            "operations/" + second["operation_id"],
                            token=token,
                        )
                    )[0],
                    200,
                )
                self.assertTrue(processor.calls[-1][-1].cancelled)
            finally:
                processor.release.set()
            self.assertEqual(await pending, (409, {"error": "operation_cancelled"}))
            self.assertEqual(
                await request("POST", "text", second, token),
                (409, {"error": "operation_cancelled"}),
            )
            self.assertEqual(len(processor.calls), 2)
            host.revoke_device(session["device_id"])
            self.assertEqual((await request("GET", "status", token=token))[0], 401)
            await asyncio.to_thread(host.stop)
            self.assertFalse(clients[0]._thread.is_alive())
            await eventually(lambda: not server.status["tasks"])
            self.assertEqual(server.status["hosts"], 0)


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

    def saved_processor(self):
        registry = Mock(spec=ProviderRegistry)
        for name in (
            "describe",
            "supports",
            "connection_for_route",
            "canonical_audio_model",
        ):
            getattr(registry, name).side_effect = getattr(PROVIDER_REGISTRY, name)
        registry.rewrite.return_value = RewriteResult(
            "Saved summary.", "groq", "saved-model"
        )
        registry.translate.return_value = TranslationResult(
            "Translated.", "groq", "saved-model", "pt"
        )
        self.saved_config = SimpleNamespace(
            value=AppConfig(
                groq=ProviderConfig(api_key="fixture-secret"),
                text_actions=TextActionSettings(
                    actions=(
                        TextAction(
                            "summary", "Summary", "Use the PC saved prompt.", revision=3
                        ),
                    ),
                    profiles=(
                        TextActionProfile(
                            "default", WorkflowRoute("groq", "saved-model")
                        ),
                    ),
                ),
            )
        )
        self.host.processor = ComputerProcessor(
            SimpleNamespace(current=lambda: self.saved_config.value),
            DictionarySnippetService(
                InMemoryDictionarySnippetsRepository(DictionarySnippets())
            ),
            registry=registry,
        )
        return registry

    def saved_text(self, **changes):
        return {
            **self.text(),
            "action": "text_action",
            "action_id": "summary",
            "action_revision": 3,
            **changes,
        }

    def test_saved_action_style_is_bounded_reported_and_part_of_replay_identity(self):
        registry = self.saved_processor()
        _, session = self.pair()
        token = session["session_token"]
        self.assertTrue(
            self.request("GET", "/v1/computer/status", token=token)[1][
                "output_preferences_supported"
            ]
        )
        body = self.saved_text(writing_style="formal")
        code, result = self.request("POST", "/v1/computer/text", body, token)
        self.assertEqual(code, 200, result)
        self.assertEqual(result["writing_style_requested"], "formal")
        self.assertEqual(result["writing_style_applied"], "formal")
        self.assertIn(
            "Formal presentation", registry.rewrite.call_args.args[1].instruction
        )
        self.assertEqual(
            self.request("POST", "/v1/computer/text", body, token), (200, result)
        )
        self.assertEqual(
            self.request(
                "POST", "/v1/computer/text", {**body, "writing_style": "casual"}, token
            )[0],
            409,
        )
        for value in (None, True, "invented", {"prompt": "Do something"}):
            self.assertEqual(
                self.request(
                    "POST",
                    "/v1/computer/text",
                    self.saved_text(writing_style=value),
                    token,
                )[0],
                400,
            )
        registry.rewrite.assert_called_once()

    def test_saved_action_status_has_only_bounded_sanitized_definitions(self):
        registry = self.saved_processor()
        settings = self.saved_config.value.text_actions
        self.saved_config.value = replace(
            self.saved_config.value,
            text_actions=replace(
                settings,
                actions=tuple(
                    TextAction(
                        f"action-{i}",
                        "\u202e\n" + "x" * 78,
                        "Private prompt",
                        revision=i + 1,
                    )
                    for i in range(64)
                ),
            ),
        )
        _, session = self.pair()
        status, result = self.request(
            "GET", "/v1/computer/status", token=session["session_token"]
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(len(result["text_actions"]), 64)
        for i, item in enumerate(result["text_actions"]):
            self.assertEqual(
                item,
                {
                    "id": f"action-{i}",
                    "revision": i + 1,
                    "name": "x" * 78,
                    "kind": "custom",
                    "enabled": True,
                    "ready": True,
                },
            )
        self.assertLess(len(json.dumps(result).encode()), 32768)
        self.assertNotIn("fixture-secret", json.dumps(result))
        self.assertNotIn("Private prompt", json.dumps(result))
        registry.rewrite.assert_not_called()
        registry.discover_models.assert_not_called()
        registry.validate.assert_not_called()

    def test_saved_action_execution_and_accepted_replay_after_edit_and_delete(self):
        registry = self.saved_processor()
        _, session = self.pair()
        token = session["session_token"]
        request = self.saved_text()
        response = self.request("POST", "/v1/computer/text", request, token)
        self.assertEqual(
            response,
            (
                200,
                {
                    "operation_id": request["operation_id"],
                    "action_id": "summary",
                    "action_revision": 3,
                    "transcript": "Original",
                    "text": "Saved summary.",
                    "rewritten": True,
                    "successful": True,
                },
            ),
        )
        self.assertIn(
            "Use the PC saved prompt.", registry.rewrite.call_args.args[1].instruction
        )
        settings = self.saved_config.value.text_actions
        for actions in (
            (replace(settings.actions[0], prompt="Edited", revision=4),),
            (),
        ):
            self.saved_config.value = replace(
                self.saved_config.value, text_actions=replace(settings, actions=actions)
            )
            self.assertEqual(
                self.request("POST", "/v1/computer/text", request, token), response
            )
            self.assertEqual(
                self.request("POST", "/v1/computer/text", self.saved_text(), token),
                (409, {"error": "action_changed"}),
            )
        self.assertEqual(registry.rewrite.call_count, 1)
        self.assertEqual(
            self.request(
                "POST", "/v1/computer/text", {**request, "text": "Changed"}, token
            ),
            (409, {"error": "operation_conflict"}),
        )
        self.assertEqual(
            self.request(
                "POST", "/v1/computer/text", {**request, "action_revision": 4}, token
            ),
            (409, {"error": "operation_conflict"}),
        )

    def test_saved_action_stale_disabled_and_invalid_requests_do_not_claim_work(self):
        registry = self.saved_processor()
        _, session = self.pair()
        token = session["session_token"]
        for request in (
            self.saved_text(action_revision=2),
            self.saved_text(action_id="deleted"),
        ):
            self.assertEqual(
                self.request("POST", "/v1/computer/text", request, token),
                (409, {"error": "action_changed"}),
            )
        for changes in (
            {"action_revision": True},
            {"action_revision": "3"},
            {"action_revision": 3.0},
            {"action_revision": 0},
            {"action_revision": 1 << 63},
            {"action_id": "x" * 65},
            {"action_id": "bad/id"},
            {"prompt": "phone prompt"},
            {"provider": "groq"},
            {"profile": "default"},
            {"language": "fr"},
            {"text": "\0"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(
                    self.request(
                        "POST", "/v1/computer/text", self.saved_text(**changes), token
                    ),
                    (400, {"error": "invalid_request"}),
                )
        settings = self.saved_config.value.text_actions
        for disabled in (
            replace(settings, actions=(replace(settings.actions[0], enabled=False),)),
            replace(
                settings,
                profiles=(
                    TextActionProfile(
                        "default", WorkflowRoute("groq", "model", enabled=False)
                    ),
                ),
            ),
            replace(
                settings,
                profiles=(
                    TextActionProfile(
                        "default", WorkflowRoute("local_asr", "ggml-base")
                    ),
                ),
            ),
        ):
            self.saved_config.value = replace(
                self.saved_config.value, text_actions=disabled
            )
            self.assertEqual(
                self.request("POST", "/v1/computer/text", self.saved_text(), token),
                (503, {"error": "not_ready"}),
            )
        self.saved_config.value = replace(
            self.saved_config.value, text_actions=settings, groq=ProviderConfig()
        )
        self.assertEqual(
            self.request("POST", "/v1/computer/text", self.saved_text(), token),
            (503, {"error": "not_ready"}),
        )
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM operations").fetchone()[0], 0
            )
        registry.rewrite.assert_not_called()

    def test_saved_translation_rejects_auto_before_provider_work(self):
        registry = self.saved_processor()
        settings = self.saved_config.value.text_actions
        self.saved_config.value = replace(
            self.saved_config.value,
            text_actions=replace(
                settings, actions=(replace(settings.actions[0], kind="translation"),)
            ),
        )
        _, session = self.pair()
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/text",
                self.saved_text(language="auto"),
                session["session_token"],
            ),
            (400, {"error": "invalid_request"}),
        )
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/text",
                self.saved_text(language="pt"),
                session["session_token"],
            )[0],
            200,
        )
        self.assertEqual(registry.translate.call_count, 1)
        registry.rewrite.assert_not_called()

    def test_saved_action_freezes_definition_between_admission_and_provider(self):
        registry = self.saved_processor()
        process = self.host.processor.process_text_action

        def edit_then_process(*args):
            self.saved_config.value = replace(
                self.saved_config.value,
                text_actions=TextActionSettings(),
                groq=ProviderConfig(),
            )
            return process(*args)

        _, session = self.pair()
        with patch.object(
            self.host.processor, "process_text_action", side_effect=edit_then_process
        ):
            response = self.request(
                "POST", "/v1/computer/text", self.saved_text(), session["session_token"]
            )
        self.assertEqual(response[0], 200)
        self.assertEqual(response[1]["action_revision"], 3)
        self.assertEqual(registry.rewrite.call_args.args[2].api_key, "fixture-secret")

    def test_saved_action_failure_is_safe_and_never_repeats_provider_work(self):
        registry = self.saved_processor()
        registry.rewrite.side_effect = RuntimeError("private prompt and credentials")
        _, session = self.pair()
        request = self.saved_text()
        for _ in range(2):
            self.assertEqual(
                self.request(
                    "POST", "/v1/computer/text", request, session["session_token"]
                ),
                (502, {"error": "processing_failed"}),
            )
        registry.rewrite.assert_called_once()

    def test_saved_action_enforces_domain_input_and_mobile_result_bounds(self):
        registry = self.saved_processor()
        _, session = self.pair()
        token = session["session_token"]
        registry.rewrite.return_value = RewriteResult(
            "x" * 32768, "groq", "saved-model"
        )
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/text",
                self.saved_text(text="\u00e9" * 16384),
                token,
            )[0],
            200,
        )
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/text",
                self.saved_text(text="\u00e9" * 16385),
                token,
            ),
            (400, {"error": "invalid_request"}),
        )
        registry.rewrite.return_value = RewriteResult(
            "x" * 32769, "groq", "saved-model"
        )
        request = self.saved_text()
        for _ in range(2):
            self.assertEqual(
                self.request("POST", "/v1/computer/text", request, token),
                (502, {"error": "processing_failed"}),
            )
        self.assertEqual(registry.rewrite.call_count, 2)

    def test_saved_action_eviction_and_restart_never_reexecute_accepted_work(self):
        registry = self.saved_processor()
        _, session = self.pair()
        token = session["session_token"]
        first, second = self.saved_text(), self.saved_text()
        with patch("computer_host.MAX_RESULTS", 1):
            self.assertEqual(
                self.request("POST", "/v1/computer/text", first, token)[0], 200
            )
            self.assertEqual(
                self.request("POST", "/v1/computer/text", second, token)[0], 200
            )
        self.saved_config.value = replace(
            self.saved_config.value, text_actions=TextActionSettings()
        )
        self.assertEqual(
            self.request("POST", "/v1/computer/text", first, token),
            (409, {"error": "result_unavailable"}),
        )
        self.host.stop()
        self.host.start()
        self.assertEqual(
            self.request("POST", "/v1/computer/text", second, token),
            (409, {"error": "result_unavailable"}),
        )
        self.assertEqual(registry.rewrite.call_count, 2)

    def test_saved_action_keeps_uuid7_and_operation_capacity_admission(self):
        self.enterContext(patch("computer_host.MAX_OPERATIONS", 1))
        registry = self.saved_processor()
        _, session = self.pair()
        token = session["session_token"]
        for operation, code in (
            (str(uuid4()), "invalid_operation_id"),
            (self.operation(self.now - 7201), "operation_expired"),
            (self.operation(self.now + 301), "operation_in_future"),
        ):
            expected = 409 if code == "operation_expired" else 400
            self.assertEqual(
                self.request(
                    "POST",
                    "/v1/computer/text",
                    self.saved_text(operation_id=operation),
                    token,
                ),
                (expected, {"error": code}),
            )
        request = self.saved_text()
        response = self.request("POST", "/v1/computer/text", request, token)
        self.assertEqual(response[0], 200)
        self.assertEqual(
            self.request("POST", "/v1/computer/text", self.saved_text(), token),
            (429, {"error": "operation_limit"}),
        )
        self.assertEqual(
            self.request("POST", "/v1/computer/text", request, token), response
        )
        registry.rewrite.assert_called_once()

    def test_saved_action_cancellation_and_revocation_discard_provider_result(self):
        registry = self.saved_processor()
        for revoke in (False, True):
            _, session = self.pair()
            request = self.saved_text()
            self.processor.entered.clear()
            self.processor.release.clear()

            def blocked(*args):
                self.processor.entered.set()
                self.processor.release.wait(3)
                self.assertTrue(args[-1].cancelled)
                return RewriteResult("Late", "groq", "saved-model")

            registry.rewrite.side_effect = blocked
            with ThreadPoolExecutor(1) as executor:
                pending = executor.submit(
                    self.request,
                    "POST",
                    "/v1/computer/text",
                    request,
                    session["session_token"],
                )
                try:
                    self.assertTrue(self.processor.entered.wait(2))
                    if revoke:
                        self.host.revoke_device(session["device_id"])
                    else:
                        self.assertEqual(
                            self.request(
                                "DELETE",
                                f"/v1/computer/operations/{request['operation_id']}",
                                token=session["session_token"],
                            )[0],
                            200,
                        )
                finally:
                    self.processor.release.set()
                self.assertEqual(
                    pending.result(), (409, {"error": "operation_cancelled"})
                )
        self.assertEqual(registry.rewrite.call_count, 2)

    def test_disabled_constructor_has_no_disk_or_secret_effects(self):
        self.host.stop()
        other_path = Path(self.temp.name) / "unused" / "state.sqlite3"
        store = MemorySecretStore()
        other = ComputerHost(self.processor, store, other_path)
        self.assertFalse(other.ready)
        self.assertFalse(other_path.parent.exists())
        self.assertEqual(store.values, {})
        other.stop()

    def relay_host(self, client=None, **options):
        self.host.stop()
        client = client or RelayClient()
        factory = Mock(return_value=client)
        self.host = self.new_host(
            relay_host="relay.test", relay_client_factory=factory, **options
        )
        self.host.start()
        return client, factory

    def test_relay_configuration_is_validated_without_startup_effects(self):
        path = Path(self.temp.name) / "unused" / "state.sqlite3"
        store, factory = MemorySecretStore(), Mock()
        with patch("computer_host.socket.getaddrinfo") as resolver:
            host = ComputerHost(
                self.processor,
                store,
                path,
                relay_host="relay.test",
                relay_client_factory=factory,
            )
            self.assertFalse(host.ready)
            host.stop()
            resolver.assert_not_called()
        factory.assert_not_called()
        self.assertEqual(store.values, {})
        self.assertFalse(path.parent.exists())
        for bind in ("127.0.0.2", "192.168.1.2"):
            with (
                self.subTest(bind=bind),
                self.assertRaisesRegex(
                    ValueError, "^Computer relay requires an IPv4 loopback listener$"
                ),
            ):
                ComputerHost(
                    self.processor, store, path, host=bind, relay_host="relay.test"
                )
        for options in (
            {"relay_host": "https://user:secret@relay.test"},
            {"relay_host": "127.0.0.1"},
            {"relay_host": "Relay.test"},
            {"relay_host": ""},
            {"relay_port": True},
            {"relay_port": 0},
            {"relay_port": 65536},
        ):
            with self.subTest(options=options), self.assertRaises(RelayError):
                self.new_host(**options)

    def test_relay_automatic_routes_reserve_last_slot_and_pin_persisted_identity(self):
        client, factory = self.relay_host(
            address_provider=lambda: [
                "invalid",
                "8.8.8.8",
                "10.0.0.2",
                "10.0.0.2",
                "192.168.1.255",
                "172.16.0.0",
                "10.0.0.3",
            ]
        )
        relay_identity = factory.call_args.args[1]
        der = relay_identity.certificate_der
        namespace = (
            base64.b32encode(hashlib.sha256(der).digest()).decode().lower().rstrip("=")
        )
        self.assertEqual(len(namespace), 52)
        self.assertEqual(relay_identity.namespace, namespace)
        with patch.object(self.host, "host", "0.0.0.0"):
            qr = self.pairing()
            again = self.pairing()
        self.assertEqual(qr["routes"], again["routes"])
        self.assertEqual(
            [route["url"] for route in qr["routes"]],
            [
                f"https://{ip}:{self.host.port}"
                for ip in ("10.0.0.2", "192.168.1.255", "172.16.0.0")
            ]
            + [f"https://{namespace}.relay.test:443"],
        )
        self.assertEqual(
            {route["certificate_sha256"] for route in qr["routes"]},
            {hashlib.sha256(der).hexdigest()},
        )
        with socket.create_connection(("127.0.0.1", self.host.port), timeout=2) as raw:
            with ssl._create_unverified_context().wrap_socket(
                raw, server_hostname="localhost"
            ) as tls:
                self.assertEqual(tls.getpeercert(binary_form=True), der)
        message = challenge("register", "relay.test", b"n" * 32)
        verify(
            certificate_key(der),
            relay_identity.proof("register", "relay.test", b"n" * 32),
            message,
        )
        factory.assert_called_once_with(
            "relay.test", relay_identity, self.host.port, relay_port=443
        )
        client.start.assert_called_once()
        saved = self.secrets.get("clarify_computer")
        first_route = qr["routes"][-1]
        self.host.stop()
        self.host = self.new_host(relay_host="relay.test", relay_client_factory=factory)
        self.host.start()
        self.assertEqual(self.pairing()["routes"][-1], first_route)
        self.assertEqual(self.secrets.get("clarify_computer"), saved)

    def test_relay_remote_only_qr_and_explicit_lan_override(self):
        client, _ = self.relay_host(relay_port=8443, address_provider=lambda: [])
        with patch.object(self.host, "host", "0.0.0.0"):
            remote = self.pairing()
        self.assertEqual(len(remote["routes"]), 1)
        self.assertTrue(remote["routes"][0]["url"].endswith(".relay.test:8443"))
        self.assertFalse(client.connected)
        urls = [f"https://10.0.0.{index}:{self.host.port}" for index in range(1, 5)]
        self.assertEqual([route["url"] for route in self.pairing(urls)["routes"]], urls)
        for invalid in ([], ["https://other.test:443"], urls + urls[:1]):
            with self.assertRaises(ValueError):
                self.host.create_pairing(invalid)
        qr = self.pairing(urls)
        with (
            patch.object(self.host, "host", "0.0.0.0"),
            patch.object(
                self.host, "address_provider", side_effect=OSError("discovery failed")
            ),
        ):
            with self.assertRaises(OSError):
                self.host.create_pairing()
        self.assertEqual(
            self.request(
                "POST",
                "/v1/computer/pair",
                {
                    "pairing_token": qr["pairing_token"],
                    "device_name": "Phone",
                },
            )[0],
            200,
        )

    def test_relay_snapshot_reports_only_safe_states_and_unset_compatibility(self):
        state = self.host.snapshot()
        self.assertEqual(
            [
                state[key]
                for key in ("relay_configured", "relay_connected", "relay_status")
            ],
            [False, False, "disabled"],
        )
        with patch("computer_host.ComputerRelayClient") as factory:
            self.host.stop()
            self.host.start()
            factory.assert_not_called()
        client, _ = self.relay_host()
        for status, connected in (
            ("retrying", False),
            ("connected", True),
            ("private token URI", True),
        ):
            client.status, client.connected = status, connected
            state = self.host.snapshot()
            self.assertTrue(state["relay_configured"])
            self.assertEqual(
                state["relay_status"],
                "relay_unavailable" if status == "private token URI" else status,
            )
            self.assertEqual(
                state["relay_connected"], connected and status != "private token URI"
            )
            for private in (
                "relay.test",
                "private token URI",
                "private_key",
                "pairing_token",
            ):
                self.assertNotIn(private, json.dumps(state))
        self.host.stop()
        self.assertEqual(self.host.snapshot()["relay_status"], "stopped")

    def test_relay_start_failure_unwinds_listener_and_keeps_unknown_drain_for_retry(
        self,
    ):
        self.host.stop()
        client = RelayClient()
        local_threads = []

        def fail_after_local_https_starts():
            with socket.create_connection(
                ("127.0.0.1", self.host.port), timeout=2
            ) as raw:
                with ssl._create_unverified_context().wrap_socket(
                    raw, server_hostname="localhost"
                ):
                    local_threads.append(self.host._thread)
            raise RuntimeError("private token/key")

        client.start.side_effect = fail_after_local_https_starts
        client.stop.return_value = False
        self.host = self.new_host(
            relay_host="relay.test", relay_client_factory=Mock(return_value=client)
        )
        with self.assertRaisesRegex(RuntimeError, "^Computer relay start failed$"):
            self.host.start()
        port = self.host.port
        self.assertEqual(len(local_threads), 1)
        self.assertFalse(local_threads[0].is_alive())
        self.assertFalse(self.host.ready)
        self.assertIsNone(self.host._db)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=0.2)
        with self.assertRaisesRegex(
            RuntimeError, "^Computer relay drain not confirmed$"
        ):
            self.host.start()
        self.assertEqual(client.start.call_count, 1)
        client.stop.return_value = True
        self.host.stop()
        self.assertEqual(client.stop.call_count, 2)
        client.start.side_effect = None
        self.host.start()

    def test_relay_failed_stop_drains_local_workers_refuses_restart_and_retries(self):
        for failure in (False, RuntimeError("private credentials")):
            with self.subTest(failure=type(failure).__name__):
                client, factory = self.relay_host()
                _, session = self.pair()
                port, thread, server = (
                    self.host.port,
                    self.host._thread,
                    self.host._server,
                )
                entered, unwound, cancelled = (threading.Event() for _ in range(3))
                workers = []

                def process(action, text, language, cancel_token):
                    workers.append(threading.current_thread())
                    entered.set()
                    try:
                        self.assertTrue(cancel_token.wait(3))
                        cancelled.set()
                        raise ProviderCancelledError()
                    finally:
                        unwound.set()

                client.stop.side_effect = (
                    failure if isinstance(failure, Exception) else None
                )
                client.stop.return_value = failure
                request = self.text()
                with (
                    patch.object(
                        self.processor, "process_text", side_effect=process
                    ) as call,
                    ThreadPoolExecutor(1) as executor,
                ):
                    pending = executor.submit(
                        self.request,
                        "POST",
                        "/v1/computer/text",
                        request,
                        session["session_token"],
                    )
                    self.assertTrue(entered.wait(3))
                    with self.assertRaisesRegex(
                        RuntimeError, "^Computer relay drain not confirmed$"
                    ):
                        self.host.stop()
                    self.assertTrue(unwound.is_set())
                    self.assertTrue(cancelled.is_set())
                    self.assertFalse(thread.is_alive())
                    self.assertTrue(all(not worker.is_alive() for worker in workers))
                    self.assertEqual(server.connections, {})
                    self.assertIsNone(self.host._db)
                    try:
                        pending.result(timeout=3)
                    except (OSError, http.client.HTTPException):
                        pass
                    call.assert_called_once()
                with self.assertRaises(OSError):
                    socket.create_connection(("127.0.0.1", port), timeout=0.2)
                self.assertEqual(self.host.snapshot()["relay_status"], "stop_failed")
                self.assertFalse(self.host.snapshot()["relay_connected"])
                with self.assertRaisesRegex(
                    RuntimeError, "^Computer relay drain not confirmed$"
                ):
                    self.host.start()
                factory.assert_called_once()
                client.stop.side_effect, client.stop.return_value = None, True
                self.host.stop()
                self.assertEqual(client.stop.call_count, 2)
                self.host.start()
                self.assertEqual(
                    self.request(
                        "POST", "/v1/computer/text", request, session["session_token"]
                    ),
                    (409, {"error": "operation_cancelled"}),
                )

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

    def test_status_and_admission_use_each_requested_personal_workflow(self):
        registry = Mock(spec=ProviderRegistry)
        for name in (
            "describe",
            "supports",
            "connection_for_route",
            "canonical_audio_model",
        ):
            getattr(registry, name).side_effect = getattr(PROVIDER_REGISTRY, name)
        registry.rewrite.return_value = RewriteResult("Edited.", "groq", "editor")
        registry.translate.return_value = TranslationResult(
            "Traduzido.", "openai", "translator", "pt"
        )
        config = AppConfig(
            groq=ProviderConfig(api_key="fake-rewrite"),
            openai=ProviderConfig(api_key="fake-translation"),
            workflows=WorkflowConfig(
                transcription=WorkflowRoute("openai", "whisper-1", enabled=False),
                rewrite=WorkflowRoute("groq", "editor"),
                translation=WorkflowRoute("openai", "translator", enabled=False),
            ),
        )
        dictionary = DictionarySnippetService(
            InMemoryDictionarySnippetsRepository(DictionarySnippets())
        )
        _, session = self.pair()
        token = session["session_token"]
        for enabled, transcription_enabled, audio_key in (
            ("rewrite", False, "fake-translation"),
            ("translate", False, "fake-translation"),
            ("rewrite", True, ""),
        ):
            current = replace(
                config,
                openai=ProviderConfig(api_key=audio_key),
                workflows=replace(
                    config.workflows,
                    transcription=replace(
                        config.workflows.transcription, enabled=transcription_enabled
                    ),
                    rewrite=replace(
                        config.workflows.rewrite, enabled=enabled == "rewrite"
                    ),
                    translation=replace(
                        config.workflows.translation, enabled=enabled == "translate"
                    ),
                ),
            )
            self.host.processor = ComputerProcessor(
                current, dictionary, registry=registry
            )
            status, snapshot = self.request("GET", "/v1/computer/status", token=token)
            self.assertEqual(status, 200)
            self.assertFalse(snapshot["ready"])
            # Run the request before checking the new field: the old host
            # reproduces the bug here with 503 despite a valid text route.
            payload = self.text()
            payload["action"] = enabled
            self.assertEqual(
                self.request("POST", "/v1/computer/text", payload, token)[0], 200
            )
            self.assertEqual(
                snapshot["action_readiness"],
                {
                    "dictate": False,
                    "rewrite": enabled == "rewrite",
                    "translate": enabled == "translate",
                },
            )
            payload = self.text()
            payload["action"] = "translate" if enabled == "rewrite" else "rewrite"
            self.assertEqual(
                self.request("POST", "/v1/computer/text", payload, token),
                (503, {"error": "not_ready"}),
            )
            self.assertEqual(
                self.request(
                    "POST",
                    "/v1/computer/dictations",
                    {
                        "operation_id": self.operation(),
                        "language": "pt",
                        "audio_wav": audio(),
                    },
                    token,
                ),
                (503, {"error": "not_ready"}),
            )
        self.assertEqual(registry.rewrite.call_count, 2)
        self.assertEqual(registry.translate.call_count, 1)
        registry.transcribe.assert_not_called()
        # A later settings change cannot use the readiness from a prior GET.
        self.host.processor = ComputerProcessor(
            replace(config, groq=ProviderConfig()), dictionary, registry=registry
        )
        self.assertEqual(
            self.request("POST", "/v1/computer/text", self.text(), token),
            (503, {"error": "not_ready"}),
        )
        self.assertFalse(
            self.request("GET", "/v1/computer/status", token=token)[1][
                "action_readiness"
            ]["rewrite"]
        )
        self.assertEqual(registry.rewrite.call_count, 2)
        registry.validate.assert_not_called()
        registry.discover_models.assert_not_called()

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
                    "action_readiness": {
                        "dictate": True,
                        "rewrite": True,
                        "translate": True,
                    },
                    "text_actions": [],
                    "output_preferences_supported": False,
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

    def test_listener_restarts_after_server_closes_tls_without_sharing_live_port(self):
        _, session = self.pair()
        port = self.host.port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as competitor:
            if os.name != "nt":
                competitor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with self.assertRaises(OSError):
                competitor.bind(("127.0.0.1", port))
        context = ssl._create_unverified_context()
        with context.wrap_socket(
            socket.create_connection(("127.0.0.1", port), timeout=2),
            server_hostname="localhost",
        ) as client:
            client.sendall(
                (
                    "GET /v1/computer/status HTTP/1.1\r\nHost: localhost\r\n"
                    "Authorization: Bearer " + session["session_token"] + "\r\n\r\n"
                ).encode()
            )
            response = bytearray()
            while chunk := client.recv(4096):
                response.extend(chunk)
            self.assertTrue(response.startswith(b"HTTP/1.1 200 "))
        # The server initiated TCP close. Restart must not wait for TIME_WAIT.
        self.host.stop()
        self.host.start()
        self.assertEqual(self.host.port, port)
        self.assertEqual(
            self.request("GET", "/v1/computer/status", token=session["session_token"])[
                0
            ],
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
