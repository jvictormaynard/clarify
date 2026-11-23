"""Isolated fake-provider bridge for the maintained Chromium transport test."""

import json
import os
from pathlib import Path
import signal
import threading
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tests.support.computer_host import ComputerHostFixture, audio
from .bridge import ComputerBridge
from .control import Control, Rejected
from .server import signaling_server


class Fixture(ComputerHostFixture, unittest.TestCase):
    pass


def root_manifest():
    return (
        Path(__file__).resolve().parents[2]
        / "local_asr_manifests/nemotron-3.5-streaming-linux-cpu.json"
    )


def main():
    output = Path(os.environ["CLARIFY_WEBRTC_EVIDENCE"])
    token = os.environ["CLARIFY_WEBRTC_TEST_TOKEN"]
    secret = os.environ["CLARIFY_WEBRTC_TURN_SECRET"].encode()
    turn_port = int(os.environ["CLARIFY_WEBRTC_TURN_PORT"])
    fixture = Fixture()
    fixture.setUp()
    _, session = fixture.pair()
    engine = None
    clip = None
    if os.environ.get("CLARIFY_WEBRTC_LIVE_WAV"):
        import base64
        import wave
        from local_asr_live import NativeEngine
        from local_asr_live_assets import NativeInstaller
        from local_asr import LocalASRProviderAdapter
        from provider_registry import PROVIDER_REGISTRY
        from computer_processing import ComputerProcessor
        from computer_live import ComputerLivePeer
        from repositories import AppConfig
        from dictionary_snippets import (
            DictionarySnippets,
            DictionarySnippetService,
            InMemoryDictionarySnippetsRepository,
        )

        installer = NativeInstaller(
            root=Path(os.environ["CLARIFY_WEBRTC_LIVE_ASSETS"]),
            manifest_path=root_manifest(),
        )
        engine = NativeEngine(installer)
        adapter = LocalASRProviderAdapter()
        adapter.select_backend = lambda *args: engine
        original_adapter = PROVIDER_REGISTRY.adapter
        # Only this isolated process substitutes the asset location; the engine,
        # processor and frozen workflow are production implementations.
        PROVIDER_REGISTRY.adapter = lambda provider: (
            adapter if provider == "local_asr" else original_adapter(provider)
        )
        config = AppConfig.from_mapping(
            {
                "transcription_provider": "local_asr",
                "local_asr_model": "nemotron-3.5-streaming",
                "dictation_cleanup_level": "preserve",
            }
        )

        class Processor(ComputerProcessor):
            def process_text(self, *args, **kwargs):
                return fixture.processor.process_text(*args, **kwargs)

            @property
            def action_readiness(self):
                return fixture.processor.action_readiness

        fixture.host.processor = Processor(
            SimpleNamespace(current=lambda: config),
            DictionarySnippetService(
                InMemoryDictionarySnippetsRepository(DictionarySnippets())
            ),
        )
        with wave.open(os.environ["CLARIFY_WEBRTC_LIVE_WAV"], "rb") as source:
            assert source.getparams()[:3] == (1, 2, 16000)
            clip = base64.b64encode(source.readframes(source.getnframes())).decode()
    bridge = ComputerBridge(
        fixture.host,
        recognition_handler=ComputerLivePeer(fixture.host) if engine else None,
    )

    def account(bearer):
        import hmac

        if not hmac.compare_digest(bearer, "Bearer " + token):
            raise Rejected("unauthorized")
        return "isolated-test-account"

    control = Control(
        account,
        turn_secret=secret,
        turn_urls=[f"turn:127.0.0.1:{turn_port}?transport=udp"],
    )
    from clarify.desktop.computer_webrtc import ComputerWebRTC, WebRTCHost

    signals = signaling_server(("127.0.0.1", 0), control)
    threading.Thread(target=signals.serve_forever, daemon=True).start()
    remote = ComputerWebRTC(
        SimpleNamespace(
            signed_in=True,
            context_stamp=lambda: (1,),
            secrets=SimpleNamespace(get=lambda _: token),
        )
    )
    if engine:
        remote.recognition_factory = lambda host, ticket: ComputerLivePeer(host)
    owner = WebRTCHost(fixture.host, remote)
    with patch(
        "clarify.desktop.computer_webrtc.configuration",
        return_value=f"http://127.0.0.1:{signals.server_port}/signal",
    ):
        owner.start()
    host_id = remote.config["host"]
    private_jwk = remote.config["privateJwk"]
    pipe_stopped = threading.Event()

    def read_pipe():
        for line in sys.stdin:
            value = json.loads(line)
            if value.get("event") == "computer-webrtc":
                remote.submit(value)

    def write_pipe():
        while not pipe_stopped.is_set():
            for message in remote.drain():
                print(json.dumps(message), flush=True)
            pipe_stopped.wait(0.01)

    threading.Thread(target=read_pipe, daemon=True).start()
    threading.Thread(target=write_pipe, daemon=True).start()
    root = Path(__file__).resolve().parents[2]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, value, status=200):
            raw = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            files = {
                f"/{name}": root / "desktop/electron" / name
                for name in ("webrtc-transport.mjs", "webrtc-signaling.mjs")
            }
            if self.path in files:
                raw = files[self.path].read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript")
                self.end_headers()
                self.wfile.write(raw)
            elif self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    (
                        b'<!doctype html><title>Clarify WebRTC transport acceptance</title><style>body{font:20px system-ui;background:#10151d;color:#def;padding:40px}pre{white-space:pre-wrap}</style><h1>Clarify WebRTC transport acceptance</h1><p>Isolated Linux browser peer. No microphone. DESCRIPTION</p><pre id="result">Test in progress.</pre>'
                    ).replace(
                        b"DESCRIPTION",
                        b"Public clip and native ASR; controlled text actions."
                        if engine
                        else b"Controlled processing.",
                    )
                )
            else:
                self.send_error(404)

        def do_POST(self):
            try:
                account(self.headers.get("Authorization", ""))
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 17 * 1024 * 1024:
                    raise ValueError()
                value = json.loads(self.rfile.read(size))
                if self.path == "/fixture":
                    self.reply(
                        dict(
                            host=host_id,
                            privateJwk=private_jwk,
                            authorization="Bearer " + session["session_token"],
                            text=fixture.text(),
                            audio=audio(frames=16000),
                            livePCM=clip,
                            operation=fixture.operation(),
                            device=session["device_id"],
                        )
                    )
                elif self.path == "/dispatch":
                    if value.get("recognition"):
                        self.reply(
                            (bridge.recognition_handler or bridge.recognition)(
                                value["authorization"],
                                value["recognition"],
                                value["operation_id"],
                                value.get("body"),
                            )
                        )
                    else:
                        self.reply(bridge.request(value))
                elif self.path == "/resources":
                    import resource

                    usage = resource.getrusage(resource.RUSAGE_SELF)
                    self.reply(
                        {
                            "cpuSeconds": usage.ru_utime + usage.ru_stime,
                            "maxRSSBytes": usage.ru_maxrss * 1024,
                        }
                    )
                elif self.path == "/block":
                    fixture.processor.entered.clear()
                    fixture.processor.release.clear()
                    fixture.processor.block = True
                    self.reply({"blocked": True})
                elif self.path == "/entered":
                    self.reply({"entered": fixture.processor.entered.is_set()})
                elif self.path == "/release":
                    fixture.processor.release.set()
                    fixture.processor.block = False
                    self.reply({"released": True})
                elif self.path == "/operation-state":
                    with fixture.host._lock:
                        row = fixture.host._db.execute(
                            "SELECT state FROM operations WHERE device_id=? AND operation_id=?",
                            (session["device_id"], value.get("operation_id")),
                        ).fetchone()
                    self.reply({"state": row[0] if row else None})
                elif self.path == "/revoke":
                    fixture.host.revoke_device(session["device_id"])
                    self.reply({"revoked": True})
                else:
                    self.send_error(404)
            except Exception:
                self.reply({"error": "rejected"}, 403)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    (output / "ready.json").write_text(
        json.dumps({"port": server.server_port, "signalPort": signals.server_port})
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        signals.shutdown()
        signals.server_close()
        owner.stop()
        pipe_stopped.set()
        remote.workers.shutdown(wait=True)
        remote.controls.shutdown(wait=True)
        bridge.close()
        fixture.tearDown()
        if engine:
            engine.shutdown()


if __name__ == "__main__":
    main()
