"""Reusable portable updates fixtures. This module defines no test cases."""

import hashlib

import json


from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from portable_updates import (
    PortableUpdatePolicy,
)


class ReleaseFixture:
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.policy = PortableUpdatePolicy(self.key.public_key().public_bytes_raw())
        self.binary = b"MZ-test-executable"
        self.payload = {
            "schema_version": 1,
            "repository": "jvictormaynard/clarify",
            "channel": "stable",
            "version": "0.5.1",
            "tag": "v0.5.1",
            "source_sha": "a" * 40,
            "asset": "Clarify.exe",
            "url": "https://github.com/jvictormaynard/clarify/releases/download/v0.5.1/Clarify.exe",
            "sha256": hashlib.sha256(self.binary).hexdigest(),
            "size": len(self.binary),
        }

    def encoded(self, payload=None):
        data = json.dumps(self.payload if payload is None else payload).encode()
        return data, self.key.sign(data)


def requests_error():
    import requests

    return requests.ConnectionError("Injected download interruption")
