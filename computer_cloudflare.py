"""Opaque Cloudflare transport. Account credentials and provider data stay separate."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.hpke import AEAD, KDF, KEM, Suite


INFO = b"clarify-computer-http-v1"
RESPONSE_INFO = b"clarify-computer-response-v1"
MAX_WIRE = 24 * 1024 * 1024
MAX_PLAIN = 16 * 1024 * 1024 + 4096
MAX_RESPONSE = 512 * 1024
SUITE = Suite(KEM.X25519, KDF.HKDF_SHA256, AEAD.CHACHA20_POLY1305)
CONNECTOR_VERSION = "2026.10.4"
CONNECTOR_SIZE = 55344848
CONNECTOR_SHA256 = "411b16d40c8d872243efeb52c550053d00af0a8a97fbb32e730fb8aba429eaa8"
CONNECTOR_URL = (
    "https://github.com/cloudflare/cloudflared/releases/download/"
    + CONNECTOR_VERSION
    + "/cloudflared-windows-amd64.exe"
)


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode(value, length=None) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid sealed message")
    try:
        data = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception:
        raise ValueError("Invalid sealed message") from None
    if encode(data) != value or (length is not None and len(data) != length):
        raise ValueError("Invalid sealed message")
    return data


def document(raw: bytes, limit: int) -> dict:
    if not isinstance(raw, bytes) or len(raw) > limit:
        raise ValueError("Invalid sealed message")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Invalid sealed message")
            result[key] = value
        return result

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
        if not isinstance(result, dict):
            raise ValueError
        json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("Invalid sealed message") from None


def packed(value) -> bytes:
    return json.dumps(
        value, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def hostname(public_key: str, domain: str) -> str:
    key = decode(public_key, 32)
    label = (
        base64.b32encode(hashlib.sha256(key).digest())
        .decode("ascii")
        .lower()
        .rstrip("=")
    )
    if not isinstance(domain, str) or not re.fullmatch(
        r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", domain
    ):
        raise ValueError("Invalid Cloudflare configuration")
    labels = domain.split(".")
    if (
        len(labels) < 2
        or len(domain) > 190
        or any(
            not x or len(x) > 63 or x.startswith("-") or x.endswith("-") for x in labels
        )
    ):
        raise ValueError("Invalid Cloudflare configuration")
    if labels[-1] in {
        "local",
        "localhost",
        "internal",
        "test",
        "invalid",
    } or not re.search("[a-z]", labels[-1]):
        raise ValueError("Invalid Cloudflare configuration")
    return "c-" + label + "." + domain


def configuration(path: Path | None = None) -> dict | None:
    path = path or Path(__file__).parent / "shared" / "computer_cloudflare.json"
    config = document(path.read_bytes(), 4096)
    if (
        set(config) != {"schema_version", "control_url", "tunnel_domain"}
        or type(config["schema_version"]) is not int
        or config["schema_version"] != 1
    ):
        raise ValueError("Invalid Cloudflare configuration")
    if config["control_url"] is None and config["tunnel_domain"] is None:
        return None
    control = config["control_url"]
    domain = config["tunnel_domain"]
    hostname(encode(bytes(32)), domain)
    if not isinstance(control, str):
        raise ValueError("Invalid Cloudflare configuration")
    parts = urlsplit(control)
    if (
        parts.scheme != "https"
        or parts.hostname != "clarify-connect." + domain
        or parts.netloc != parts.hostname
        or parts.path
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Invalid Cloudflare configuration")
    return {"control_url": control, "tunnel_domain": domain}


class SealedRequest:
    """One HPKE request and one separately keyed, request-bound AEAD response."""

    def __init__(self, raw: bytes, private_key: bytes, now: float):
        outer = document(raw, MAX_WIRE)
        if (
            set(outer) != {"schema_version", "ciphertext"}
            or type(outer["schema_version"]) is not int
            or outer["schema_version"] != 1
        ):
            raise ValueError("Invalid sealed message")
        self.ciphertext = decode(outer["ciphertext"])
        if not 48 <= len(self.ciphertext) <= MAX_PLAIN + 48:
            raise ValueError("Invalid sealed message")
        key = x25519.X25519PrivateKey.from_private_bytes(private_key)
        value = document(SUITE.decrypt(self.ciphertext, key, INFO), MAX_PLAIN)
        if set(value) != {
            "schema_version",
            "method",
            "path",
            "authorization",
            "body",
            "reply_key",
            "request_id",
            "expires_at",
        }:
            raise ValueError("Invalid sealed message")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("Invalid sealed message")
        self.reply_key = decode(value["reply_key"], 32)
        decode(value["request_id"], 16)
        self.request_id = value["request_id"]
        if (
            type(value["expires_at"]) is not int
            or not now < value["expires_at"] <= now + 300
        ):
            raise ValueError("Invalid sealed message")
        if (
            value["method"] not in {"GET", "POST", "DELETE"}
            or not isinstance(value["path"], str)
            or not re.fullmatch(
                r"/v1/computer/(?:pair|status|dictations|text|session|operations/[0-9a-fA-F-]{36})",
                value["path"],
            )
        ):
            raise ValueError("Invalid sealed message")
        if value["authorization"] is not None and (
            not isinstance(value["authorization"], str)
            or not re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", value["authorization"])
        ):
            raise ValueError("Invalid sealed message")
        if value["body"] is not None and not isinstance(value["body"], dict):
            raise ValueError("Invalid sealed message")
        self.value = value

    def response(self, status: int, body: dict) -> bytes:
        clear = packed(
            {
                "schema_version": 1,
                "request_id": self.request_id,
                "status": status,
                "body": body,
            }
        )
        if len(clear) > MAX_RESPONSE:
            raise ValueError("Sealed response too large")
        nonce = secrets.token_bytes(12)
        aad = RESPONSE_INFO + hashlib.sha256(self.ciphertext).digest()
        result = nonce + ChaCha20Poly1305(self.reply_key).encrypt(nonce, clear, aad)
        return packed({"schema_version": 1, "ciphertext": encode(result)})


def read_response(response, limit: int) -> bytes:
    deadline = time.monotonic() + 15.0
    try:
        if response.status_code != 200:
            raise ValueError("Cloudflare connection unavailable")
        data = bytearray()
        for chunk in response.iter_content(1):
            if time.monotonic() > deadline:
                raise ValueError("Cloudflare response deadline exceeded")
            if len(data) + len(chunk) > limit:
                raise ValueError("Cloudflare response too large")
            data.extend(chunk)
        return bytes(data)
    finally:
        response.close()


def claim(config: dict, grant: str, *, request=requests.post) -> dict:
    decode(grant, 32)
    try:
        response = request(
            config["control_url"] + "/v1/connect/claim",
            json={"grant": grant},
            timeout=(5, 45),
            allow_redirects=False,
            stream=True,
        )
        value = document(read_response(response, 16384), 16384)
        if (
            set(value) != {"schema_version", "hostname", "token", "origin_port"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
        ):
            raise ValueError
        if not isinstance(value["token"], str) or not re.fullmatch(
            r"[A-Za-z0-9+/=_-]{32,8192}", value["token"]
        ):
            raise ValueError
        if (
            type(value["origin_port"]) is not int
            or not 1 <= value["origin_port"] <= 65535
        ):
            raise ValueError
        return value
    except Exception:
        # The one-use claim may already have provisioned a tunnel. Never retry.
        raise RuntimeError("Cloudflare registration is uncertain") from None


def connector_binary(directory: Path, *, request=requests.get) -> Path:
    if os.name != "nt" or os.environ.get("PROCESSOR_ARCHITECTURE", "").upper() not in {
        "AMD64",
        "X86",
    }:
        raise RuntimeError("Unsupported Cloudflare connector platform")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / ("cloudflared-" + CONNECTOR_VERSION + ".exe")
    if destination.is_file() and destination.stat().st_size == CONNECTOR_SIZE:
        with destination.open("rb") as existing:
            if hashlib.file_digest(existing, "sha256").hexdigest() == CONNECTOR_SHA256:
                return destination
    # Download to a new file. Never execute or overwrite a divergent cached file.
    if destination.exists():
        raise RuntimeError("Cloudflare connector integrity check failed")
    url = CONNECTOR_URL
    temporary = None
    deadline = time.monotonic() + 180.0
    try:
        for _ in range(3):
            response = request(url, timeout=(5, 60), allow_redirects=False, stream=True)
            if response.status_code in {301, 302, 307, 308}:
                location = response.headers.get("Location", "")
                response.close()
                parts = urlsplit(location)
                if (
                    parts.scheme != "https"
                    or parts.hostname
                    not in {
                        "release-assets.githubusercontent.com",
                        "objects.githubusercontent.com",
                    }
                    or parts.username
                    or parts.password
                    or parts.fragment
                ):
                    raise ValueError
                url = location
                continue
            try:
                if response.status_code != 200:
                    raise ValueError
                descriptor, name = tempfile.mkstemp(
                    prefix=".cloudflared-", dir=directory
                )
                temporary = Path(name)
                digest, size = hashlib.sha256(), 0
                with os.fdopen(descriptor, "wb") as target:
                    for chunk in response.iter_content(65536):
                        if time.monotonic() > deadline:
                            raise ValueError
                        size += len(chunk)
                        if size > CONNECTOR_SIZE:
                            raise ValueError
                        digest.update(chunk)
                        target.write(chunk)
                if size != CONNECTOR_SIZE or digest.hexdigest() != CONNECTOR_SHA256:
                    raise ValueError
                temporary.replace(destination)
                temporary = None
                return destination
            finally:
                response.close()
        raise ValueError
    except Exception:
        raise RuntimeError("Cloudflare connector download failed") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class CloudflareConnector:
    """Own one user-level connector; never install a system service or log tokens."""

    def __init__(
        self,
        token: str,
        directory: Path,
        *,
        binary=connector_binary,
        popen=subprocess.Popen,
    ):
        self._token, self.directory = token, directory
        self._binary, self._popen = binary, popen
        self._process = self._temporary = None
        self._metrics_port = None
        self._guard = threading.RLock()

    def start(self):
        with self._guard:
            if self._process is not None:
                raise RuntimeError("Cloudflare connector already owned")
            executable = self._binary(self.directory)
            self._temporary = tempfile.TemporaryDirectory(prefix="clarify-tunnel-")
            token_file = Path(self._temporary.name) / "token"
            try:
                token_file.write_text(self._token, encoding="ascii")
                token_file.chmod(0o600)
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", 0))
                    self._metrics_port = listener.getsockname()[1]
                arguments = [
                    str(executable),
                    "tunnel",
                    "--no-autoupdate",
                    "--metrics",
                    f"127.0.0.1:{self._metrics_port}",
                    "--loglevel",
                    "error",
                    "run",
                    "--token-file",
                    str(token_file),
                ]
                self._process = self._popen(
                    arguments,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except BaseException:
                self._temporary.cleanup()
                self._temporary = None
                raise RuntimeError("Cloudflare connector could not start") from None

    @property
    def connected(self):
        with self._guard:
            if self._process is None or self._process.poll() is not None:
                return False
            port = self._metrics_port
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.get(
                    f"http://127.0.0.1:{port}/ready",
                    timeout=(0.3, 0.3),
                    allow_redirects=False,
                    stream=True,
                )
                try:
                    return response.status_code == 200
                finally:
                    response.close()
        except requests.RequestException:
            return False

    def wait_ready(self, timeout=30.0):
        deadline = time.monotonic() + timeout
        stopped = threading.Event()
        while time.monotonic() < deadline:
            if self.connected:
                return True
            if self._process is None or self._process.poll() is not None:
                return False
            stopped.wait(0.2)
        return False

    def stop(self, timeout=5.0):
        with self._guard:
            process = self._process
            if process is not None:
                try:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        return False
                self._process = None
            if self._temporary is not None:
                self._temporary.cleanup()
                self._temporary = None
            return True
