"""Reusable computer host fixtures. This module defines no test cases."""

import base64


from concurrent.futures import ThreadPoolExecutor

from contextlib import contextmanager


import http.client

import io

import json


from pathlib import Path


import ssl

import tempfile

import threading


from types import SimpleNamespace


from unittest.mock import Mock

from urllib.parse import urlsplit, parse_qs

from uuid import UUID, uuid4

import wave


from computer_host import ComputerHost


from computer_processing import ComputerProcessor

from dictionary_snippets import (
    DictionarySnippets,
    DictionarySnippetService,
    InMemoryDictionarySnippetsRepository,
)


from provider_registry import PROVIDER_REGISTRY, ProviderRegistry

from provider_types import RewriteResult, TranslationResult

from repositories import AppConfig, ProviderConfig

from secret_store import MemorySecretStore

from text_actions import TextAction, TextActionProfile, TextActionSettings

from workflow_config import WorkflowRoute


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


class ComputerHostFixture:
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

    @contextmanager
    def blocked_text(self, request, token):
        self.processor.block = True
        with ThreadPoolExecutor(1) as executor:
            pending = executor.submit(
                self.request, "POST", "/v1/computer/text", request, token
            )
            try:
                self.assertTrue(self.processor.entered.wait(2))
                yield pending
            finally:
                self.processor.release.set()

    def saved_text(self, **changes):
        return {
            **self.text(),
            "action": "text_action",
            "action_id": "summary",
            "action_revision": 3,
            **changes,
        }

    def relay_host(self, client=None, **options):
        self.host.stop()
        client = client or RelayClient()
        factory = Mock(return_value=client)
        self.host = self.new_host(
            relay_host="relay.test", relay_client_factory=factory, **options
        )
        self.host.start()
        return client, factory
