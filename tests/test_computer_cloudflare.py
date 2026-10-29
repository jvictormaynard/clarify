"""Synthetic wire tests. No provider, personal profile, Cloudflare or audio access."""

import hashlib
import http.client
import json
from pathlib import Path
import secrets
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

import computer_cloudflare as cf
from secret_store import MemorySecretStore
from tests import test_computer_host as host_tests


CONFIG = {
    "control_url": "https://clarify-connect.victormaynard.com",
    "tunnel_domain": "victormaynard.com",
}


def seal(key, now, *, method="GET", path="status", token=None, body=None, **changes):
    reply = secrets.token_bytes(32)
    value = {
        "schema_version": 1,
        "method": method,
        "path": "/v1/computer/" + path,
        "authorization": "Bearer " + token if token else None,
        "body": body,
        "reply_key": cf.encode(reply),
        "request_id": cf.encode(secrets.token_bytes(16)),
        "expires_at": int(now) + 120,
    }
    value.update(changes)
    encrypted = cf.SUITE.encrypt(
        cf.packed(value),
        x25519.X25519PublicKey.from_public_bytes(cf.decode(key, 32)),
        cf.INFO,
    )
    wire = cf.packed({"schema_version": 1, "ciphertext": cf.encode(encrypted)})

    def open_reply(raw):
        sealed = cf.decode(json.loads(raw)["ciphertext"])
        aad = cf.RESPONSE_INFO + hashlib.sha256(encrypted).digest()
        result = json.loads(
            ChaCha20Poly1305(reply).decrypt(sealed[:12], sealed[12:], aad)
        )
        if result["request_id"] != value["request_id"]:
            raise ValueError("Reply ownership changed")
        return result

    return wire, open_reply


class SealedWireTests(unittest.TestCase):
    def setUp(self):
        self.key = x25519.X25519PrivateKey.generate()
        self.public = cf.encode(self.key.public_key().public_bytes_raw())

    def test_fixed_hpke_vector_used_by_native_crypto_kit(self):
        wire = "0JK4RtbDCOkK3Q8BjAjTFrX7cOgZtQ-BYD_lKHtdYmNOoCoaE20PzQZyydpwmg3RzQxSaDq6hU27flSwM38zjdN28BpPYFhMRBMJm0FdjFby3ay0LToVuJl32IuHlIHbzpq-PcbXwmZbKClk_MF2fQFeg2KeV8SA17WY7phgJ5Nr-t0gFhyTS1TJW-xWEqirhn88W9RGAw8aZa8MDDynxx9CHFr0QbAmGvel2nttfkFVBAZosySDmHK7_e843rDZmmsI9Ai4tUK2ktL93rIziYhqpNWm8PwiIIYfLYbsrNX7D3oiTgWUieQd3lUGdt43wnbqfzvUqmXjCAhWJR7OxlI5JA"
        value = cf.SealedRequest(
            cf.packed({"schema_version": 1, "ciphertext": wire}), bytes(range(32)), 1000
        )
        self.assertEqual(value.value["method"], "GET")
        self.assertEqual(value.value["path"], "/v1/computer/status")
        self.assertEqual(value.value["request_id"], cf.encode(bytes(range(16))))

    def test_hpke_round_trip_and_request_bound_response(self):
        wire, open_reply = seal(self.public, 1000, body=None)
        self.assertNotIn(b"reply_key", wire)
        message = cf.SealedRequest(wire, self.key.private_bytes_raw(), 1000)
        result = message.response(401, {"error": "unauthorized"})
        self.assertNotIn(b"unauthorized", result)
        self.assertEqual(open_reply(result)["status"], 401)
        _, unrelated = seal(self.public, 1000)
        with self.assertRaises(Exception):
            unrelated(result)

    def test_rejects_wrong_key_tamper_expiry_and_protocol_changes(self):
        for changed in (
            {"expires_at": 1000},
            {"expires_at": 1301},
            {"expires_at": True},
            {"method": "PUT"},
            {"path": "/v1/computer/status?next=evil"},
            {"reply_key": "bad"},
            {"request_id": "bad"},
            {"extra": True},
        ):
            with self.subTest(changed=changed), self.assertRaises(Exception):
                wire, _ = seal(self.public, 1000, **changed)
                cf.SealedRequest(wire, self.key.private_bytes_raw(), 1000)
        wire, _ = seal(self.public, 1000)
        with self.assertRaises(Exception):
            cf.SealedRequest(
                wire, x25519.X25519PrivateKey.generate().private_bytes_raw(), 1000
            )
        value = json.loads(wire)
        cipher = bytearray(cf.decode(value["ciphertext"]))
        cipher[-1] ^= 1
        value["ciphertext"] = cf.encode(cipher)
        with self.assertRaises(Exception):
            cf.SealedRequest(cf.packed(value), self.key.private_bytes_raw(), 1000)

    def test_strict_json_canonical_base64_and_scope(self):
        for raw in (
            b'{"schema_version":1,"schema_version":1}',
            b'{"x":NaN}',
            b'{"x":"\\ud800"}',
            b"[]",
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                cf.document(raw, 1024)
        for raw in ("Zg==", "Zh", "a+b", ""):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                cf.decode(raw)
        host = cf.hostname(self.public, "victormaynard.com")
        self.assertEqual(len(host.split(".")[0]), 54)
        self.assertTrue(host.endswith(".victormaynard.com"))
        for domain in (
            "localhost",
            "a.test",
            "a..com",
            "user@a.com",
            "a/com",
            "-a.com",
        ):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                cf.hostname(self.public, domain)


class Connector:
    def __init__(self, token, directory):
        self.start = Mock()
        self.stop = Mock(return_value=True)
        self.wait_ready = Mock(return_value=True)
        self.connected = True


class CloudflareHostTests(unittest.TestCase):
    new_host = host_tests.ComputerHostTests.new_host
    request = host_tests.ComputerHostTests.request
    pairing = host_tests.ComputerHostTests.pairing
    pair = host_tests.ComputerHostTests.pair
    operation = host_tests.ComputerHostTests.operation
    text = host_tests.ComputerHostTests.text

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "computer.sqlite3"
        self.secrets = MemorySecretStore()
        self.processor = host_tests.Processor()
        self.now = 1800000000.0
        self.claims = []

        def claim(config, grant):
            self.claims.append((config, grant))
            return {
                "schema_version": 1,
                "hostname": cf.hostname(
                    self.host._identity["hpke_public_key"], CONFIG["tunnel_domain"]
                ),
                "token": "synthetic-connector-token-" + "a" * 32,
                "origin_port": self.host._tunnel_server.server_address[1],
            }

        self.host = self.new_host(
            cloudflare_config=CONFIG,
            cloudflare_factory=Connector,
            cloudflare_claim=claim,
        )
        self.addCleanup(self.host.stop)
        self.host.start()

    def tunnel_request(self, method, path, body=None):
        port = self.host._tunnel_server.server_address[1]
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(method, path, body, {"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_lan_pair_exposes_registration_metadata_without_account_secret(self):
        _, session = self.pair()
        info = session.get("remote_registration")
        self.assertIsNotNone(info)
        self.assertEqual(info["control_url"], CONFIG["control_url"])
        self.assertEqual(
            info["hpke_public_key"], self.host._identity["hpke_public_key"]
        )
        self.assertEqual(
            info["origin_port"], self.host._tunnel_server.server_address[1]
        )
        self.assertEqual(self.claims, [])

    def test_loopback_origin_only_accepts_sealed_endpoint_and_stops(self):
        self.assertEqual(self.host._tunnel_server.server_address[0], "127.0.0.1")
        for path in ("status", "pair", "text", "remote"):
            self.assertEqual(
                self.tunnel_request("POST", "/v1/computer/" + path, b"{}")[0], 404
            )
        self.assertEqual(
            self.tunnel_request("POST", "/v1/computer/sealed", b"{}")[0], 400
        )
        server = self.host._tunnel_server
        self.host.stop()
        self.assertEqual(server.socket.fileno(), -1)

    def test_synthetic_sealed_processing_keeps_once_only_and_revocation(self):
        _, session = self.pair()
        key = self.host._identity["hpke_public_key"]
        body = self.text(text="Private synthetic text")
        wire, decrypt = seal(
            key,
            self.now,
            method="POST",
            path="text",
            token=session["session_token"],
            body=body,
        )
        self.assertNotIn(b"Private synthetic text", wire)
        self.assertNotIn(session["session_token"].encode(), wire)
        for _ in range(2):
            status, raw = self.tunnel_request("POST", "/v1/computer/sealed", wire)
            self.assertEqual(status, 200)
            self.assertEqual(decrypt(raw)["status"], 200)
        self.assertEqual(len(self.processor.calls), 1)
        self.host.revoke_device(session["device_id"])
        status, raw = self.tunnel_request("POST", "/v1/computer/sealed", wire)
        self.assertEqual(decrypt(raw)["status"], 401)
        self.assertEqual(len(self.processor.calls), 1)

    def test_registration_checks_origin_and_persists_connector_for_restart(self):
        _, session = self.pair()
        body = {"control_url": CONFIG["control_url"], "grant": cf.encode(bytes(32))}
        wrong = dict(body, control_url="https://evil.example.com")
        self.assertEqual(
            self.request(
                "POST", "/v1/computer/remote", wrong, session["session_token"]
            )[0],
            409,
        )
        self.assertEqual(len(self.claims), 0)
        status, result = self.request(
            "POST", "/v1/computer/remote", body, session["session_token"]
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            result["route"]["hpke_public_key"], self.host._identity["hpke_public_key"]
        )
        self.assertEqual(len(self.claims), 1)
        self.assertEqual(
            self.request("POST", "/v1/computer/remote", body, session["session_token"])[
                0
            ],
            409,
        )
        self.assertEqual(len(self.claims), 1)
        qr = self.pairing()
        self.assertEqual(qr["schema_version"], 2)
        self.assertEqual(qr["routes"][-1], result["route"])
        previous = self.host._identity.copy()
        self.host.stop()
        self.host.start()
        self.assertEqual(self.host._identity, previous)
        self.assertIsNotNone(self.host._tunnel)
        self.assertEqual(
            self.request("GET", "/v1/computer/status", token=session["session_token"])[
                0
            ],
            200,
        )

    def test_remote_worker_cannot_wait_for_the_shutdown_lifecycle_lock(self):
        _, session = self.pair()
        body = {"control_url": CONFIG["control_url"], "grant": cf.encode(bytes(32))}
        executor = ThreadPoolExecutor(max_workers=1)
        self.host._lifecycle.acquire()
        try:
            future = executor.submit(
                self.request,
                "POST",
                "/v1/computer/remote",
                body,
                session["session_token"],
            )
            self.assertEqual(future.result(timeout=0.5)[0], 200)
        finally:
            self.host._lifecycle.release()
            executor.shutdown(wait=True)

    def test_authenticated_status_recovers_route_without_repeating_a_lost_claim(self):
        _, session = self.pair()
        body = {"control_url": CONFIG["control_url"], "grant": cf.encode(bytes(32))}
        # The caller loses the successful registration reply. Its next action
        # is GET status with its existing paired credential, never another claim.
        self.assertEqual(
            self.request("POST", "/v1/computer/remote", body, session["session_token"])[
                0
            ],
            200,
        )
        for _ in range(2):
            status, recovered = self.request(
                "GET", "/v1/computer/status", token=session["session_token"]
            )
            self.assertEqual(status, 200)
            self.assertEqual(
                recovered.get("remote_route"), self.host._cloudflare_route()
            )
        self.assertEqual(len(self.claims), 1)


if __name__ == "__main__":
    unittest.main()
