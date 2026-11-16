"""Durable enrollment, host key ownership and private-pipe cancellation."""

import base64
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from clarify.desktop.computer_webrtc import ComputerWebRTC, WebRTCHost
from connect.webrtc.control import Control, Rejected
from tests.support.computer_host import ComputerHostFixture


class EnrollmentTests(unittest.TestCase):
    def test_restart_retains_enrollment_but_not_tickets_and_revoke_is_durable(self):
        from cryptography.hazmat.primitives.asymmetric import ec

        n = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()

        def encode(value):
            return (
                base64.urlsafe_b64encode(value.to_bytes(32, "big")).decode().rstrip("=")
            )

        public = dict(kty="EC", crv="P-256", x=encode(n.x), y=encode(n.y))
        with tempfile.TemporaryDirectory() as directory:

            def new():
                return Control(
                    lambda bearer: bearer,
                    turn_secret=b"x" * 32,
                    turn_urls=["turn:127.0.0.1:3478"],
                    database=Path(directory) / "hosts.sqlite3",
                )

            def call(control, action, **fields):
                return control.call(
                    "generated-account", dict(action=action, host="pc", **fields)
                )

            control = new()
            call(control, "enroll", public_key=public)
            ticket = call(control, "create")["ticket"]
            control = new()
            call(control, "enroll", public_key=public)
            with self.assertRaises(Rejected):
                call(control, "poll", ticket=ticket)
            self.assertEqual(call(control, "create")["public_key"], public)
            call(control, "revoke")
            with self.assertRaises(Rejected):
                call(new(), "create")


class LifecycleTests(ComputerHostFixture, unittest.TestCase):
    def test_key_pairing_and_shutdown_cancel_active_private_pipe_work(self):
        _, session = self.pair()
        account = SimpleNamespace(signed_in=True, context_stamp=lambda: (1,))
        remote = ComputerWebRTC(account)
        remote.signal = lambda *_: {"registered": True}
        owner = WebRTCHost(self.host, remote)
        try:
            with patch(
                "clarify.desktop.computer_webrtc.configuration",
                return_value="https://signal.example/signal",
            ):
                owner.start()
                first = json.loads(self.host.secret_store.get("clarify_computer"))[
                    "webrtc_private_jwk"
                ]
                remote.connected = True
                remote.last_signal = time.monotonic()
                qr = owner.create_pairing()["pairing_url"].split("data=")[1]
                payload = json.loads(
                    base64.urlsafe_b64decode(qr + "=" * (-len(qr) % 4))
                )
                self.assertEqual(payload["webrtc"]["public_key"]["x"], first["x"])
                self.assertNotIn("d", payload["webrtc"]["public_key"])
                remote.stop()
                remote.start(self.host)
                self.assertEqual(first, remote.config["privateJwk"])
            self.processor.block = True
            self.processor.release.clear()
            body = self.text()
            remote.submit(
                dict(
                    requestID=1,
                    kind="dispatch",
                    value=dict(
                        ticket="a" * 43,
                        request=dict(
                            method="POST",
                            path="/v1/computer/text",
                            authorization="Bearer " + session["session_token"],
                            body=body,
                        ),
                    ),
                )
            )
            self.assertTrue(self.processor.entered.wait(2))
            # Cancellation uses a separate worker and can pass blocked inference.
            remote.submit(
                dict(
                    requestID=2,
                    kind="dispatch",
                    value=dict(
                        ticket="a" * 43,
                        request=dict(
                            method="DELETE",
                            path="/v1/computer/operations/" + body["operation_id"],
                            authorization="Bearer " + session["session_token"],
                        ),
                    ),
                )
            )
            replies = {}
            deadline = time.monotonic() + 3
            while 2 not in replies and time.monotonic() < deadline:
                replies.update({x.get("requestID"): x for x in remote.drain()})
                threading.Event().wait(0.01)
            self.assertEqual(replies[2]["result"]["status"], 200)
            remote.stop()
            self.processor.release.set()
            self.assertIsNone(remote.binding())
        finally:
            self.processor.release.set()
            remote.stop()
            remote.workers.shutdown(wait=True)
            remote.controls.shutdown(wait=True)
