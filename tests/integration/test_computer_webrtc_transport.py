"""Transport regressions using the existing fake computer processor."""

import base64
import unittest
from tests.support.computer_host import ComputerHostFixture, audio
from connect.webrtc.bridge import ComputerBridge
from connect.webrtc.control import Control, Rejected


class BridgeTests(ComputerHostFixture, unittest.TestCase):
    def test_credentials_replay_audio_and_cancel(self):
        _, session = self.pair()
        bridge = ComputerBridge(self.host)
        auth = "Bearer " + session["session_token"]

        def request(body, token=auth):
            return bridge.request(
                dict(
                    method="POST",
                    path="/v1/computer/text",
                    authorization=token,
                    body=body,
                )
            )

        body = self.text()
        self.assertEqual(request(body, "Bearer invalid")["status"], 401)
        self.assertEqual(request(body)["status"], 200)
        self.assertEqual(request(body)["status"], 200)
        self.assertEqual(len(self.processor.calls), 1)
        op = self.operation()
        self.assertEqual(
            bridge.recognition(auth, "start", op, {"language": "auto"})["status"], 200
        )
        self.assertEqual(
            bridge.recognition(auth, "feed", op, {"sequence": 1, "data": audio()})[
                "status"
            ],
            400,
        )
        self.assertEqual(
            bridge.recognition(auth, "feed", op, {"sequence": 0, "data": audio()})[
                "status"
            ],
            200,
        )
        self.assertEqual(bridge.recognition(auth, "finish", op)["status"], 200)
        self.assertEqual(self.processor.calls[-1][0], base64.b64decode(audio()))
        op = self.operation()
        bridge.recognition(auth, "start", op, {"language": "auto"})
        bridge.recognition(auth, "cancel", op)
        self.assertEqual(bridge.recognition(auth, "finish", op)["status"], 409)
        self.host.revoke_device(session["device_id"])
        self.assertEqual(request(self.text())["status"], 401)
        bridge.close()


class ControlTests(unittest.TestCase):
    def test_account_host_binding_expiry_and_revocation(self):
        now = [1000]

        def account(token):
            if token not in ("a", "b"):
                raise Rejected("unauthorized")
            return token

        c = Control(
            account,
            turn_secret=b"x" * 32,
            turn_urls=["turn:127.0.0.1:3478"],
            clock=lambda: now[0],
        )

        def call(action, token="a", **fields):
            return c.call(token, dict(action=action, host="pc", **fields))

        from cryptography.hazmat.primitives.asymmetric import ec

        numbers = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
        key = {
            "kty": "EC",
            "crv": "P-256",
            **{
                name: base64.urlsafe_b64encode(
                    getattr(numbers, name).to_bytes(32, "big")
                )
                .decode()
                .rstrip("=")
                for name in ("x", "y")
            },
        }
        call("enroll", public_key=key)
        ticket = call("create")["ticket"]
        with self.assertRaises(Rejected):
            call("poll", token="b", ticket=ticket)
        with self.assertRaises(Rejected):
            call("poll", token="bad", ticket=ticket)
        self.assertEqual(call("turn", ticket=ticket)["expires"], 1900)
        call("offer", ticket=ticket, payload={"sdp": "offer"})
        with self.assertRaises(Rejected):
            call("offer", ticket=ticket, payload={})
        now[0] = 1121
        with self.assertRaises(Rejected):
            call("poll", ticket=ticket)
        ticket = call("create")["ticket"]
        call("offer", ticket=ticket, payload={"sdp": "offer"})
        call("answer", ticket=ticket, payload={"sdp": "answer"})
        # An authenticated session outlives the short setup ticket, including
        # a five-minute recording. Idle or revoked sessions still expire.
        for _ in range(11):
            now[0] += 60
            self.assertEqual(call("poll", ticket=ticket)["expires"], now[0] + 90)
        now[0] += 91
        with self.assertRaises(Rejected):
            call("poll", ticket=ticket)
        ticket = call("create")["ticket"]
        call("revoke")
        with self.assertRaises(Rejected):
            call("turn", ticket=ticket)


class InjectedAdapterTests(unittest.TestCase):
    def test_live_frames_cancel_and_final_are_not_reinferred(self):
        import threading
        from types import SimpleNamespace
        from unittest.mock import Mock
        from connect.webrtc.live import LiveRecognition

        engine = Mock()
        session = engine.open_live_session.return_value
        session.finish.return_value = SimpleNamespace(text="Final.", final=True)
        event = threading.Event()
        adapter = LiveRecognition(
            engine, "pt-BR", admitted=True, cancel_event=event, on_partial=Mock()
        )
        adapter.feed(0, b"\0\0" * 1280)
        with self.assertRaises(ValueError):
            adapter.feed(2, b"\0\0")
        first = adapter.finish()
        self.assertIs(first, adapter.finish())
        session.finish.assert_called_once_with(timeout=30, cancel_event=event)
        adapter.cancel()
        with self.assertRaises(ValueError):
            adapter.finish()
        session.cancel.assert_called_once()

    def test_account_validation_uses_existing_read_only_endpoint(self):
        import json
        from unittest.mock import patch, MagicMock
        from uuid import uuid4
        from connect.webrtc.account import AccountValidator

        identity = str(uuid4())
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = json.dumps({"id": identity}).encode()
        with patch("connect.webrtc.account.build_opener") as opener:
            opener.return_value.open.return_value = response
            validator = AccountValidator("https://account.example")
            self.assertEqual(
                validator("Bearer test-session"), "https://account.example/" + identity
            )
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://account.example/v1/account")
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("X-session-token"), "test-session")
            with self.assertRaises(Rejected):
                validator("Bearer invalid\nheader")
            response.status = 401
            with self.assertRaises(Rejected):
                validator("Bearer expired")
        with self.assertRaises(ValueError):
            AccountValidator("http://account.example")


if __name__ == "__main__":
    unittest.main()
