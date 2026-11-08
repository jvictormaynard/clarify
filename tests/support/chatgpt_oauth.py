"""Reusable chatgpt oauth fixtures. This module defines no test cases."""

import base64

import copy


import json


import threading


from urllib.parse import parse_qs, urlencode, urlsplit

from cryptography.hazmat.primitives.asymmetric import rsa as rsa
from cryptography.hazmat.primitives import hashes

from cryptography.hazmat.primitives.asymmetric import padding


ISSUER = "https://auth.openai.com"

SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def number(value):
    return b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


class Response:
    def __init__(self, payload=None, status=200, raw=None):
        self.status_code = status
        self.raw = raw if raw is not None else json.dumps(payload).encode()

    def iter_content(self, chunk_size):
        yield self.raw

    def close(self):
        pass


class OAuthServer:
    def __init__(self, key):
        self.key = key
        self.now = 1000000.0
        self.query = None
        self.calls = []
        self.client = "oaiapp_first"
        self.subject = "user-one"
        self.email = "same@example.test"
        self.scopes = SCOPES
        self.claims_override = {}
        self.token_override = {}
        self.fail_refresh = False
        self.code_error = ""
        self.fail_revoke = False
        self.refresh_started = threading.Event()
        self.release_refresh = None
        self.before_token = None

    def id_token(self):
        claims = {
            "iss": ISSUER,
            "sub": self.subject,
            "aud": self.client,
            "exp": self.now + 3600,
            "iat": self.now,
            "nonce": self.query["nonce"][0],
            "email": self.email,
        }
        claims.update(self.claims_override)
        body = ".".join(
            b64(json.dumps(value).encode())
            for value in (
                {"alg": "RS256", "kid": "test-key"},
                claims,
            )
        )
        return (
            body
            + "."
            + b64(
                self.key.sign(
                    body.encode(),
                    padding.PKCS1v15(),
                    hashes.SHA256(),
                )
            )
        )

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, copy.deepcopy(kwargs)))
        if url == ISSUER + "/.well-known/openid-configuration":
            return Response(
                {
                    "issuer": ISSUER,
                    "authorization_endpoint": ISSUER + "/api/accounts/authorize",
                    "token_endpoint": ISSUER + "/api/accounts/oauth/token",
                    "jwks_uri": ISSUER + "/jwks",
                    "revocation_endpoint": ISSUER + "/revoke",
                    "id_token_signing_alg_values_supported": ["RS256"],
                }
            )
        if url.endswith("/jwks"):
            key = self.key.public_key().public_numbers()
            return Response(
                {
                    "keys": [
                        {
                            "kid": "test-key",
                            "alg": "RS256",
                            "kty": "RSA",
                            "use": "sig",
                            "n": number(key.n),
                            "e": number(key.e),
                        }
                    ]
                }
            )
        if url.endswith("/revoke"):
            if self.fail_revoke:
                raise OSError("SECRET remote response")
            return Response(raw=b"")
        data = kwargs["data"]
        if data["grant_type"] == "refresh_token":
            self.refresh_started.set()
            if self.release_refresh is not None:
                if not self.release_refresh.wait(3):
                    raise RuntimeError("test refresh timed out")
            if self.fail_refresh:
                raise OSError("SECRET uncertain refresh")
            return Response(
                {
                    "access_token": "rotated-access",
                    "refresh_token": "rotated-refresh",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
            )
        if self.before_token:
            self.before_token()
        if self.code_error:
            return Response(
                {"error": self.code_error, "error_description": "SECRET remote text"},
                status=400,
            )
        payload = {
            "id_token": self.id_token(),
            "access_token": "first-access",
            "refresh_token": "first-refresh",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": self.scopes,
        }
        payload.update(self.token_override)
        return Response(payload)

    def browser(self, url):
        self.query = parse_qs(urlsplit(url).query)
        return True

    def callback(self, *, state=None, client=None, **extra):
        query = {"code": "test-code", "state": state or self.query["state"][0]}
        if client is not False:
            query["client_id"] = client or self.client
        query.update(extra)
        return self.query["redirect_uri"][0] + "?" + urlencode(query)


class Listener:
    """Bound listener seam; no external or loopback network in protocol tests."""

    def __init__(self, callback):
        self.redirect_uri = "http://127.0.0.1:43123/auth/callback"
        self.callback = callback
        self.closed = False

    def wait(self, *, check):
        check()
        value = self.callback()
        check()
        return value

    def close(self):
        self.closed = True
