"""Opt-in, bounded HTTPS host for paired personal devices.

Construction and import do not read a profile, create files, or bind a socket.
SQLite stores only identities, token/content hashes, and operation metadata.
Result text stays in a bounded volatile cache. An evicted or restarted operation
fails closed; its device must use a new operation ID for a deliberate new action.
"""

from __future__ import annotations

import base64
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
from socketserver import ThreadingMixIn
import sqlite3
import ssl
import struct
import tempfile
import threading
import time
from typing import Any, Callable, Protocol
from shared.output_preferences import output_language as parse_output_language
from shared.writing_style_policy import writing_style as parse_writing_style
from urllib.parse import urlsplit
from uuid import UUID, uuid4
import wave

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from computer_relay_client import ComputerRelayClient
from computer_processing import (
    ComputerActionChanged,
    ComputerActionNotReady,
    PreparedTextAction,
)
import computer_cloudflare as cloudflare
from computer_relay_protocol import RelayIdentity, dns_name, namespace, port_number
from provider_http import CancellationToken, ProviderCancelledError
from secret_store import SecretStore, SecretStoreCorruptedError
from text_actions import MAX_REVISION, TEXT_LANGUAGES, identity


MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_TEXT_BYTES = 32768
MAX_DEVICES = 32
MAX_OPERATIONS = 4096
OPERATION_SECONDS = 7200
OPERATION_FUTURE_SECONDS = 300
MAX_RESULTS = 64
MAX_RESULT_BYTES = 8 * 1024 * 1024
PAIRING_SECONDS = 300
PAIRING_ATTEMPTS = 5
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_LANGUAGE = re.compile(r"(?:auto|[A-Za-z]{2,8}(?:[-_][A-Za-z0-9]{1,8}){0,3})\Z")
_PREFIX = "/v1/computer/"
_LAN_NETWORKS = tuple(
    ipaddress.IPv4Network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_RELAY_STATUSES = frozenset(
    (
        "stopped",
        "connecting",
        "connected",
        "retrying",
        "stopping",
        "stop_failed",
        "relay_unavailable",
    )
)


def _supported_route(address: ipaddress.IPv4Address, *, loopback: bool) -> bool:
    return any(address in network for network in _LAN_NETWORKS) or (
        loopback and address.is_loopback
    )


class ComputerProcessing(Protocol):
    @property
    def ready(self) -> bool: ...

    @property
    def action_readiness(self) -> dict[str, bool]: ...

    @property
    def text_actions(self) -> list[dict[str, Any]]: ...

    def prepare_text_action(
        self,
        action_id: str,
        action_revision: int,
        text: str,
        language: str,
        *,
        writing_style: str | None = None,
    ) -> PreparedTextAction: ...

    def process_text_action(
        self, prepared: PreparedTextAction, cancel_token: CancellationToken
    ) -> dict: ...

    def process_dictation(
        self,
        audio_wav: bytes,
        language: str,
        cancel_token: CancellationToken,
        *,
        writing_style: str | None = None,
        output_language: str | None = None,
    ) -> dict: ...

    def process_text(
        self,
        action: str,
        text: str,
        language: str,
        cancel_token: CancellationToken,
        *,
        writing_style: str | None = None,
    ) -> dict: ...


class _RelayClient(Protocol):
    @property
    def connected(self) -> bool: ...

    @property
    def status(self) -> str: ...

    def start(self) -> None: ...

    def stop(self, timeout: float = 5.0) -> bool: ...


class _RelayClientFactory(Protocol):
    def __call__(
        self,
        relay_host: str,
        identity: RelayIdentity,
        target_port: int,
        *,
        relay_port: int,
    ) -> _RelayClient: ...


class _APIError(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code


def _digest(value: str | bytes) -> str:
    return hashlib.sha256(
        value.encode() if isinstance(value, str) else value
    ).hexdigest()


def _json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _uuid(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise _APIError(400, "invalid_request")
    try:
        return str(UUID(value))
    except ValueError:
        raise _APIError(400, "invalid_request") from None


def _operation_timestamp(operation: str) -> int:
    """Read RFC 9562 UUIDv7 epoch milliseconds, separately from identity UUIDs."""
    value = UUID(operation)
    if value.version != 7 or value.bytes[8] & 0xC0 != 0x80:
        raise _APIError(400, "invalid_operation_id")
    return int.from_bytes(value.bytes[:6], "big")


def _local_addresses() -> list[str]:
    return [
        item[4][0]
        for item in socket.getaddrinfo(
            socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM
        )
    ]


def _name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 100
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise _APIError(400, "invalid_request")
    return value.strip()


def _validate_wav(value: Any) -> bytes:
    if not isinstance(value, str) or len(value) > MAX_BODY_BYTES:
        raise _APIError(400, "invalid_audio")
    try:
        data = base64.b64decode(value, validate=True)
        # wave accepts truncated PCM and, in 3.12, extensible WAV. Require the
        # actual PCM tag, declared lengths, and complete frames on this wire.
        if (
            len(data) < 44
            or data[:4] != b"RIFF"
            or data[8:12] != b"WAVE"
            or struct.unpack_from("<I", data, 4)[0] != len(data) - 8
        ):
            raise ValueError
        offset, pcm, frames_bytes = 12, False, None
        while offset < len(data):
            if offset + 8 > len(data):
                raise ValueError
            kind, size = struct.unpack_from("<4sI", data, offset)
            offset += 8
            if offset + size > len(data):
                raise ValueError
            if kind == b"fmt ":
                if pcm or size < 16:
                    raise ValueError
                tag, channels, rate, byte_rate, align, bits = struct.unpack_from(
                    "<HHIIHH", data, offset
                )
                if (tag, channels, rate, byte_rate, align, bits) != (
                    1,
                    1,
                    16000,
                    32000,
                    2,
                    16,
                ):
                    raise ValueError
                pcm = True
            if kind == b"data":
                if not pcm or frames_bytes is not None:
                    raise ValueError
                frames_bytes = size
            offset += size + (size % 2)
        if (
            offset != len(data)
            or frames_bytes is None
            or not 0 < frames_bytes <= 16000 * 2 * 300
            or frames_bytes % 2
        ):
            raise ValueError
        with wave.open(io.BytesIO(data), "rb") as stream:
            if (
                stream.getnchannels(),
                stream.getsampwidth(),
                stream.getframerate(),
                stream.getcomptype(),
            ) != (1, 2, 16000, "NONE"):
                raise ValueError
            if len(stream.readframes(stream.getnframes())) != frames_bytes:
                raise ValueError
        return data
    except (ValueError, wave.Error, EOFError, struct.error):
        raise _APIError(400, "invalid_audio") from None


def _close_socket(connection):
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    connection.close()


class _Server(ThreadingMixIn, HTTPServer):
    # server_close joins request workers after their processor callbacks and
    # resource cleanup finish. The shared registry remains owned by the caller.
    daemon_threads = False
    block_on_close = True
    # POSIX can rebind closed TIME_WAIT connections without sharing a listener.
    # Windows SO_REUSEADDR can share an active port, so keep it disabled there.
    allow_reuse_address = os.name != "nt"
    request_queue_size = 8

    def __init__(self, owner, context, workers, timeout, *, address=None, handler=None):
        self.owner, self.context, self.read_timeout = owner, context, timeout
        self.slots = threading.BoundedSemaphore(workers)
        self.connections: dict[socket.socket, threading.Timer | None] = {}
        self.guard = threading.Lock()
        self.stopping = False
        super().__init__(address or (owner.host, owner.port), handler or _Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        secured = request
        timer = None
        try:
            with self.guard:
                if self.stopping:
                    return
                if self.context is not None:
                    secured = self.context.wrap_socket(
                        request, server_side=True, do_handshake_on_connect=False
                    )
                secured.settimeout(self.read_timeout)
                timer = threading.Timer(self.read_timeout, _close_socket, (secured,))
                timer.daemon = True
                self.connections[secured] = timer
                timer.start()
            if self.context is not None:
                secured.do_handshake()
            self.finish_request(secured, client_address)
        except Exception:
            # This is the outer connection boundary. Never let an unexpected
            # handler exception print a request or provider value to stderr.
            pass
        finally:
            if timer:
                timer.cancel()
            with self.guard:
                self.connections.pop(secured, None)
            self.shutdown_request(secured)
            self.slots.release()

    def end_read(self, connection):
        with self.guard:
            timer = self.connections.get(connection)
            if timer:
                timer.cancel()

    def close_connections(self):
        with self.guard:
            self.stopping = True
            for connection in tuple(self.connections):
                _close_socket(connection)

    def handle_error(self, request, client_address):
        # BaseServer prints exception tracebacks; provider bodies are private.
        return


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        return

    def send_error(self, code, message=None, explain=None):
        self._reply(code, {"error": "invalid_request"})

    def _reply(self, status, value):
        encoded = _json(value)
        self.close_connection = True
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)
        except OSError:
            pass

    def _body(self, limit=MAX_BODY_BYTES):
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
            raise _APIError(400, "invalid_request")
        length = lengths[0]
        if not re.fullmatch(r"[0-9]{1,10}", length):
            raise _APIError(400, "invalid_request")
        size = int(length)
        if size > limit:
            raise _APIError(413, "body_too_large")
        if self.headers.get_content_type() != "application/json":
            raise _APIError(415, "unsupported_media_type")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise _APIError(400, "invalid_request")
        self.server.end_read(self.connection)
        try:

            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError
                    result[key] = value
                return result

            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=unique,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
            if not isinstance(value, dict):
                raise ValueError
            _json(value)  # Reject escaped lone surrogates before validation/work.
            return value
        except (ValueError, UnicodeError, RecursionError):
            raise _APIError(400, "invalid_request") from None

    def handle_expect_100(self):
        # A caller must send one bounded body; do not invite an unchecked upload.
        self._reply(417, {"error": "invalid_request"})
        return False

    def _handle(self):
        owner = self.server.owner
        try:
            authorization = self.headers.get_all("Authorization", [])

            def read_body(limit):
                if limit is None:
                    self.server.end_read(self.connection)
                    return None
                return self._body(limit)

            owner._dispatch(
                self.command, self.path, authorization, read_body, self._reply
            )
        except _APIError as error:
            self._reply(error.status, {"error": error.code})
        except TimeoutError:
            self._reply(408, {"error": "request_timeout"})
        except Exception:
            self._reply(500, {"error": "internal_error"})

    do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = do_HEAD = do_OPTIONS = _handle


class _SealedHandler(_Handler):
    """Loopback-only origin. An HTTP reverse proxy never sees API plaintext."""

    def _handle(self):
        if self.command != "POST" or self.path != "/v1/computer/sealed":
            self._reply(404, {"error": "not_found"})
            return
        owner = self.server.owner
        try:
            if self.headers.get_all("Authorization", []):
                raise ValueError
            outer = self._body(cloudflare.MAX_WIRE)
            request = cloudflare.SealedRequest(
                cloudflare.packed(outer),
                cloudflare.decode(owner._identity["hpke_private_key"], 32),
                owner.clock(),
            )
        except Exception:
            self._reply(400, {"error": "invalid_request"})
            return

        def reply(status, body):
            try:
                encoded = request.response(status, body)
            except Exception:
                encoded = request.response(500, {"error": "internal_error"})
            self._reply(200, json.loads(encoded))

        def read_body(limit):
            body = request.value["body"]
            if limit is not None and (
                not isinstance(body, dict) or len(_json(body)) > limit
            ):
                raise _APIError(400, "invalid_request")
            return body

        try:
            owner._dispatch(
                request.value["method"],
                request.value["path"],
                [request.value["authorization"]]
                if request.value["authorization"]
                else [],
                read_body,
                reply,
                allow_remote=False,
            )
        except _APIError as error:
            reply(error.status, {"error": error.code})
        except Exception:
            reply(500, {"error": "internal_error"})

    do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = do_HEAD = do_OPTIONS = _handle


@dataclass
class _Running:
    device_id: str
    token: CancellationToken
    generation: object


class ComputerHost:
    """An explicit start enables TLS; stop revokes the current pairing code.

    port=0 is supported for loopback tests. Production should keep the default
    stable port. Explicit pairing routes accept up to four RFC1918 IPv4 LAN
    URLs or route dicts. Automatic routes reserve one of four slots for a
    configured relay, including during reconnect. Loopback tests can advertise
    loopback addresses. The relay client always targets IPv4 loopback.
    """

    def __init__(
        self,
        processor: ComputerProcessing,
        secret_store: SecretStore,
        state_path: str | Path,
        *,
        computer_name="Clarify Computer",
        host="0.0.0.0",
        port=47653,
        allow_port_fallback=False,
        clock: Callable[[], float] = time.time,
        address_provider: Callable[[], list[str]] | None = None,
        relay_host: str | None = None,
        relay_port: int = 443,
        relay_client_factory: _RelayClientFactory | None = None,
        cloudflare_config: dict | None = None,
        cloudflare_factory=None,
        cloudflare_claim=None,
        max_handlers=8,
        max_concurrent_operations=2,
        read_timeout=10.0,
    ):
        self.processor, self.secret_store, self.state_path = (
            processor,
            secret_store,
            Path(state_path),
        )
        self.computer_name = _name(computer_name)
        self.host = str(ipaddress.IPv4Address(host))
        if not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("Invalid computer host port")
        if (
            not 2 <= max_handlers <= 32
            or not 1 <= max_concurrent_operations < max_handlers
        ):
            raise ValueError("Invalid computer host concurrency")
        if not 0.1 <= read_timeout <= 60:
            raise ValueError("Invalid computer host timeout")
        self.port, self.clock = port, clock
        self._allow_port_fallback = allow_port_fallback
        self._relay_host = dns_name(relay_host) if relay_host is not None else None
        self._relay_port = port_number(relay_port)
        if self._relay_host is not None and self.host not in ("0.0.0.0", "127.0.0.1"):
            raise ValueError("Computer relay requires an IPv4 loopback listener")
        if relay_client_factory is not None and not callable(relay_client_factory):
            raise ValueError("Invalid computer relay factory")
        self._relay_factory = (
            relay_client_factory
            if relay_client_factory is not None
            else ComputerRelayClient
        )
        self._relay: _RelayClient | None = None
        self._relay_stop_failed = False
        self._cloudflare_config = cloudflare_config
        if cloudflare_config is not None:
            if set(cloudflare_config) != {"control_url", "tunnel_domain"}:
                raise ValueError("Invalid Cloudflare configuration")
            cloudflare.hostname(
                cloudflare.encode(bytes(32)), cloudflare_config["tunnel_domain"]
            )
            if (
                cloudflare_config["control_url"]
                != "https://clarify-connect." + cloudflare_config["tunnel_domain"]
            ):
                raise ValueError("Invalid Cloudflare configuration")
        self._cloudflare_factory = cloudflare_factory or cloudflare.CloudflareConnector
        self._cloudflare_claim = cloudflare_claim or cloudflare.claim
        self._tunnel_server = self._tunnel_thread = self._tunnel = None
        self._tunnel_settings = None
        self._tunnel_stop_failed = False
        self.address_provider = address_provider or _local_addresses
        self._max_handlers, self._read_timeout = max_handlers, read_timeout
        self._capacity = threading.BoundedSemaphore(max_concurrent_operations)
        self._lock = threading.RLock()
        self._lifecycle = threading.Lock()
        self._remote_admission = threading.Lock()
        self._server = self._thread = self._db = None
        self._identity = None
        self._pairing = None
        self._running: dict[tuple[str, str], _Running] = {}
        self._results: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._result_bytes = 0
        self._generation = object()

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._server is not None and bool(self.processor.ready)

    def _load_identity(self):
        encoded = self.secret_store.get("clarify_computer")
        if encoded is None:
            if self.state_path.exists() and self.state_path.stat().st_size:
                raise SecretStoreCorruptedError("Computer identity is missing")
            key = ec.generate_private_key(ec.SECP256R1())
            now = datetime.now(timezone.utc)
            name = x509.Name(
                [x509.NameAttribute(NameOID.COMMON_NAME, "Clarify Computer")]
            )
            certificate = (
                x509.CertificateBuilder()
                .subject_name(name)
                .issuer_name(name)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(days=1))
                .not_valid_after(now + timedelta(days=3650))
                .add_extension(
                    x509.BasicConstraints(ca=False, path_length=None), critical=True
                )
                .add_extension(
                    x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                    critical=False,
                )
                .sign(key, hashes.SHA256())
            )
            encoded = json.dumps(
                {
                    "schema_version": 1,
                    "computer_id": str(uuid4()),
                    "certificate": certificate.public_bytes(
                        serialization.Encoding.PEM
                    ).decode(),
                    "private_key": key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    ).decode(),
                }
            )
            self.secret_store.set("clarify_computer", encoded)
            if self.secret_store.get("clarify_computer") != encoded:
                raise SecretStoreCorruptedError("Computer identity could not be saved")
        try:
            identity = json.loads(encoded)
            if identity["schema_version"] != 1:
                raise ValueError
            _uuid(identity["computer_id"])
            certificate = x509.load_pem_x509_certificate(
                identity["certificate"].encode()
            )
            key = serialization.load_pem_private_key(
                identity["private_key"].encode(), password=None
            )
            public_format = (
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            if key.public_key().public_bytes(
                *public_format
            ) != certificate.public_key().public_bytes(*public_format):
                raise ValueError
            if certificate.not_valid_after_utc <= datetime.now(timezone.utc):
                raise ValueError
            identity["certificate_sha256"] = certificate.fingerprint(
                hashes.SHA256()
            ).hex()
            if self._cloudflare_config is not None:
                from cryptography.hazmat.primitives.asymmetric import x25519

                if "hpke_private_key" not in identity:
                    identity["hpke_private_key"] = cloudflare.encode(
                        x25519.X25519PrivateKey.generate().private_bytes_raw()
                    )
                    saved = dict(identity)
                    saved.pop("certificate_sha256", None)
                    value = json.dumps(saved)
                    self.secret_store.set("clarify_computer", value)
                    if self.secret_store.get("clarify_computer") != value:
                        raise ValueError
                key = x25519.X25519PrivateKey.from_private_bytes(
                    cloudflare.decode(identity["hpke_private_key"], 32)
                )
                identity["hpke_public_key"] = cloudflare.encode(
                    key.public_key().public_bytes_raw()
                )
            return identity
        except (ValueError, KeyError, TypeError, AttributeError, _APIError):
            raise SecretStoreCorruptedError("Computer identity is invalid") from None

    def _open_state(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.state_path, check_same_thread=False, timeout=5)
        try:
            if os.name != "nt":
                self.state_path.chmod(0o600)
            if db.execute("PRAGMA page_count").fetchone()[0] > 2048:
                raise ValueError("Computer state exceeds the storage limit")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError("Unsupported computer state version")
            if version == 2:
                highwater = db.execute(
                    "SELECT highwater_ms FROM replay_window WHERE id=1"
                ).fetchone()
                if (
                    highwater is None
                    or type(highwater[0]) is not int
                    or highwater[0] < 0
                ):
                    raise ValueError("Invalid computer replay window")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA max_page_count=2048")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS identity (computer_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (
                    device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
                    operation_id TEXT NOT NULL, content_hash TEXT NOT NULL,
                    state TEXT NOT NULL, created_at REAL NOT NULL,
                    PRIMARY KEY(device_id, operation_id));
                CREATE TABLE IF NOT EXISTS replay_window (
                    id INTEGER PRIMARY KEY CHECK (id=1),
                    highwater_ms INTEGER NOT NULL CHECK (highwater_ms>=0));
                INSERT OR IGNORE INTO replay_window VALUES (1, 0);
                PRAGMA user_version=2;
            """)
            row = db.execute("SELECT computer_id FROM identity").fetchone()
            if row is None:
                if db.execute("SELECT COUNT(*) FROM devices").fetchone()[0]:
                    raise ValueError("Computer state has no identity")
                db.execute(
                    "INSERT INTO identity VALUES (?)", (self._identity["computer_id"],)
                )
            elif row[0] != self._identity["computer_id"]:
                raise ValueError("Computer state identity does not match")
            db.execute("UPDATE operations SET state='uncertain' WHERE state='running'")
            db.commit()
            return db
        except BaseException:
            db.close()
            raise

    def start(self):
        with self._lifecycle:
            with self._lock:
                if self._tunnel_stop_failed:
                    raise RuntimeError("Cloudflare connector drain not confirmed")
                if self._relay is not None and (
                    self._relay_stop_failed or self._server is None
                ):
                    raise RuntimeError("Computer relay drain not confirmed")
                if self._server is not None:
                    return
                self._identity = self._load_identity()
                db = self._open_state()
                try:
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    context.minimum_version = ssl.TLSVersion.TLSv1_2
                    # SSLContext requires paths. Keep clear key material only
                    # inside this private, temporary directory during startup.
                    with tempfile.TemporaryDirectory(
                        prefix="clarify-computer-tls-"
                    ) as directory:
                        cert, key = (
                            Path(directory) / "certificate.pem",
                            Path(directory) / "private.pem",
                        )
                        cert.write_text(self._identity["certificate"], encoding="ascii")
                        key.write_text(self._identity["private_key"], encoding="ascii")
                        key.chmod(0o600)
                        context.load_cert_chain(cert, key)
                    try:
                        server = _Server(
                            self, context, self._max_handlers, self._read_timeout
                        )
                    except OSError as error:
                        if (
                            not self._allow_port_fallback
                            or self.port == 0
                            or error.errno not in (errno.EADDRINUSE, 10048)
                        ):
                            raise
                        server = _Server(
                            self,
                            context,
                            self._max_handlers,
                            self._read_timeout,
                            address=(self.host, 0),
                        )
                except BaseException:
                    db.close()
                    raise
                self._db, self._server = db, server
                self.port = server.server_address[1]
                self._generation = object()
                self._thread = threading.Thread(
                    target=server.serve_forever,
                    kwargs={"poll_interval": 0.05},
                    name="clarify-computer",
                    daemon=True,
                )
                try:
                    self._thread.start()
                except BaseException:
                    self._server = self._thread = self._db = None
                    server.server_close()
                    db.close()
                    raise
            if self._relay_host is not None:
                try:
                    self._start_relay()
                except Exception:
                    try:
                        self._stop()
                    except Exception:
                        pass
                    raise RuntimeError("Computer relay start failed") from None
            if self._cloudflare_config is not None:
                try:
                    self._start_cloudflare()
                except Exception:
                    # Keep an explicitly enabled LAN host available. No automatic
                    # claim, registration retry or alternate provider is selected.
                    self._tunnel_settings = None

    def _start_relay(self):
        certificate = x509.load_pem_x509_certificate(
            self._identity["certificate"].encode()
        )
        key = serialization.load_pem_private_key(
            self._identity["private_key"].encode(), password=None
        )
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError("Invalid computer relay identity")
        identity = RelayIdentity(
            certificate.public_bytes(serialization.Encoding.DER),
            lambda message: key.sign(message, ec.ECDSA(hashes.SHA256())),
        )
        # The factory has no target-host argument. The connector owns loopback.
        relay = self._relay_factory(
            self._relay_host, identity, self.port, relay_port=self._relay_port
        )
        with self._lock:
            self._relay = relay
        relay.start()

    def stop(self):
        with self._lifecycle:
            self._stop()

    def _stop(self):
        with self._lock:
            server, thread = self._server, self._thread
            if server is not None:
                self._server = self._thread = None
                self._generation = object()
                self._pairing = None
                for work in self._running.values():
                    work.token.cancel()
                try:
                    self._db.execute(
                        "UPDATE operations SET state='cancelled' WHERE state='running'"
                    )
                    self._db.commit()
                except sqlite3.Error:
                    # A failed shutdown write leaves running claims uncertain
                    # at the next start. It must not keep the listener open.
                    pass
                finally:
                    self._db.close()
                self._db = None
                self._results.clear()
                self._result_bytes = 0
        try:
            if server is not None:
                server.close_connections()
                server.shutdown()
                server.server_close()
                thread.join()
        finally:
            cloudflare_drained = self._stop_cloudflare()
            # Drain local workers even when the relay cannot confirm shutdown.
            # Keep an uncertain client so a later stop can retry without a server.
            relay = self._relay
            if relay is not None:
                try:
                    drained = relay.stop(timeout=5.0) is True
                except Exception:
                    drained = False
                with self._lock:
                    self._relay_stop_failed = not drained
                    if drained:
                        self._relay = None
                if not drained:
                    raise RuntimeError("Computer relay drain not confirmed") from None
            if not cloudflare_drained:
                raise RuntimeError("Cloudflare connector drain not confirmed") from None

    def _start_cloudflare(self):
        cached = self.secret_store.get("clarify_computer_tunnel")
        settings = cloudflare.document(cached.encode(), 16384) if cached else None
        public_key = self._identity["hpke_public_key"]
        expected_host = cloudflare.hostname(
            public_key, self._cloudflare_config["tunnel_domain"]
        )
        if settings is not None:
            if (
                set(settings) != {"schema_version", "hostname", "token", "origin_port"}
                or type(settings["schema_version"]) is not int
                or settings["schema_version"] != 1
                or settings["hostname"] != expected_host
                or type(settings["origin_port"]) is not int
                or not 1 <= settings["origin_port"] <= 65535
                or not isinstance(settings["token"], str)
                or not re.fullmatch(r"[A-Za-z0-9+/=_-]{32,8192}", settings["token"])
            ):
                raise ValueError("Invalid Cloudflare connector state")
        server = _Server(
            self,
            None,
            self._max_handlers,
            self._read_timeout,
            address=("127.0.0.1", settings["origin_port"] if settings else 0),
            handler=_SealedHandler,
        )
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="clarify-sealed-origin",
            daemon=True,
        )
        self._tunnel_server, self._tunnel_thread = server, thread
        try:
            thread.start()
        except BaseException:
            server.server_close()
            self._tunnel_server = self._tunnel_thread = None
            raise
        if settings is not None:
            self._tunnel_settings = settings
            connector = self._cloudflare_factory(
                settings["token"], self.state_path.parent / "connect-tools"
            )
            self._tunnel = connector
            connector.start()

    def _stop_cloudflare(self):
        # Close the only origin before draining an uncertain connector process.
        server, thread = self._tunnel_server, self._tunnel_thread
        if server is not None:
            server.close_connections()
            server.shutdown()
            server.server_close()
            thread.join()
            self._tunnel_server = self._tunnel_thread = None
        drained = True
        if self._tunnel is not None:
            try:
                drained = self._tunnel.stop(timeout=5.0) is True
            except Exception:
                drained = False
            if drained:
                self._tunnel = None
        self._tunnel_stop_failed = not drained
        return drained

    def _cloudflare_route(self):
        return {
            "url": "https://" + self._tunnel_settings["hostname"],
            "certificate_sha256": None,
            "hpke_public_key": self._identity["hpke_public_key"],
        }

    def _registration_info(self):
        if self._tunnel_server is None or self._tunnel_settings is not None:
            return None
        return {
            "control_url": self._cloudflare_config["control_url"],
            "origin_port": self._tunnel_server.server_address[1],
            "certificate_sha256": self._identity["certificate_sha256"],
            "hpke_public_key": self._identity["hpke_public_key"],
        }

    def _enable_remote(self, device, body):
        if not isinstance(body, dict) or set(body) != {"control_url", "grant"}:
            raise _APIError(400, "invalid_request")
        if not self._remote_admission.acquire(blocking=False):
            raise _APIError(409, "operation_conflict")
        try:
            with self._lock:
                self._require_started()
                if (
                    self._tunnel_server is None
                    or self._tunnel_stop_failed
                    or body["control_url"] != self._cloudflare_config["control_url"]
                ):
                    raise _APIError(409, "relay_unavailable")
                if self._tunnel_settings is not None:
                    raise _APIError(409, "operation_conflict")
                try:
                    cloudflare.decode(body["grant"], 32)
                except ValueError:
                    raise _APIError(400, "invalid_request") from None
            # Claim is one-use; an uncertain reply cannot cause a second claim.
            settings = self._cloudflare_claim(self._cloudflare_config, body["grant"])
            with self._lock:
                self._require_started()
                if (
                    self._db.execute(
                        "SELECT 1 FROM devices WHERE device_id=?", (device,)
                    ).fetchone()
                    is None
                ):
                    raise _APIError(401, "unauthorized")
                expected = cloudflare.hostname(
                    self._identity["hpke_public_key"],
                    self._cloudflare_config["tunnel_domain"],
                )
                if (
                    settings["hostname"] != expected
                    or settings["origin_port"] != self._tunnel_server.server_address[1]
                ):
                    raise _APIError(409, "relay_unavailable")
                encoded = cloudflare.packed(settings).decode()
                self.secret_store.set("clarify_computer_tunnel", encoded)
                if self.secret_store.get("clarify_computer_tunnel") != encoded:
                    raise _APIError(503, "relay_unavailable")
                self._tunnel_settings = settings
            connector = self._cloudflare_factory(
                settings["token"], self.state_path.parent / "connect-tools"
            )
            self._tunnel = connector
            connector.start()
            return {"schema_version": 1, "route": self._cloudflare_route()}
        finally:
            self._remote_admission.release()

    def _dispatch(
        self, method, path, authorization, read_body, reply, *, allow_remote=True
    ):
        routes = {
            "pair": "POST",
            "status": "GET",
            "dictations": "POST",
            "text": "POST",
            "session": "DELETE",
            "remote": "POST",
        }
        route = path[len(_PREFIX) :] if path.startswith(_PREFIX) else ""
        if route.startswith("operations/"):
            operation_id = _uuid(route[len("operations/") :])
            expected = "DELETE"
        elif route in routes:
            expected = routes[route]
        else:
            raise _APIError(404, "not_found")
        if method != expected:
            raise _APIError(405, "method_not_allowed")
        if route == "pair":
            body = read_body(4096)
            result = self._pair(body)
        else:
            auth = authorization
            device = self._authenticate(auth[0] if len(auth) == 1 else "")
            if route == "remote":
                if not allow_remote:
                    raise _APIError(404, "not_found")
                result = self._enable_remote(device, read_body(4096))
            elif route in {"dictations", "text"}:
                body = read_body(MAX_BODY_BYTES)
                result = self._process(device, route, body)
            else:
                read_body(None)
                if route == "status":
                    result = self._status()
                elif route == "session":
                    self.revoke_device(device)
                    result = {"revoked": True}
                else:
                    self._cancel(device, operation_id)
                    result = {"cancelled": True}
        # Claim publication under the same lock as cancellation/revocation.
        # A revocation that wins this lock prevents a queued success reply.
        with self._lock:
            self._require_started()
            if route not in {"pair", "session"}:
                if (
                    self._db.execute(
                        "SELECT 1 FROM devices WHERE device_id=?", (device,)
                    ).fetchone()
                    is None
                ):
                    raise _APIError(401, "unauthorized")
                if route in {"dictations", "text"}:
                    state = self._db.execute(
                        "SELECT state FROM operations WHERE device_id=? AND operation_id=?",
                        (device, result["operation_id"]),
                    ).fetchone()
                    if state is None or state[0] != "succeeded":
                        raise _APIError(409, "operation_cancelled")
            reply(200, result)

    def _require_started(self):
        if self._server is None:
            raise _APIError(503, "host_stopped")

    def create_pairing(self, routes=None) -> dict:
        with self._lock:
            self._require_started()
            loopback = ipaddress.IPv4Address(self.host).is_loopback
            automatic_cloudflare = routes is None and self._tunnel_settings is not None
            automatic_relay = routes is None and self._relay_host is not None
            reserved = int(automatic_relay) + int(automatic_cloudflare)
            if routes is None:
                addresses = (
                    [self.host] if self.host != "0.0.0.0" else self.address_provider()
                )
                routes = []
                for item in addresses:
                    try:
                        address = ipaddress.IPv4Address(item)
                    except (ValueError, TypeError):
                        continue
                    url = f"https://{address}:{self.port}"
                    if (
                        _supported_route(address, loopback=loopback)
                        and url not in routes
                    ):
                        routes.append(url)
                        if len(routes) == 4 - reserved:
                            break
            if (
                not isinstance(routes, (list, tuple))
                or not (0 if reserved else 1) <= len(routes) <= 4 - reserved
            ):
                raise ValueError("One to four computer LAN routes are required")
            canonical = []
            for route in routes:
                url = route.get("url") if isinstance(route, dict) else route
                if not isinstance(url, str) or len(url) > 256:
                    raise ValueError("Invalid computer route")
                parsed = urlsplit(url)
                try:
                    address = ipaddress.IPv4Address(parsed.hostname)
                    valid_port = parsed.port == self.port
                except ValueError:
                    raise ValueError("Invalid computer route") from None
                if (
                    parsed.scheme != "https"
                    or parsed.username
                    or parsed.password
                    or parsed.path
                    or parsed.query
                    or parsed.fragment
                    or not valid_port
                    or not _supported_route(address, loopback=loopback)
                ):
                    raise ValueError("Invalid computer route")
                canonical.append(
                    {
                        "url": f"https://{address}:{self.port}",
                        "certificate_sha256": self._identity["certificate_sha256"],
                    }
                )
            if automatic_relay:
                der = x509.load_pem_x509_certificate(
                    self._identity["certificate"].encode()
                ).public_bytes(serialization.Encoding.DER)
                canonical.append(
                    {
                        "url": f"https://{namespace(der)}.{self._relay_host}:{self._relay_port}",
                        "certificate_sha256": self._identity["certificate_sha256"],
                    }
                )
            token = secrets.token_urlsafe(32)
            if automatic_cloudflare:
                canonical.append(self._cloudflare_route())
            expires = self.clock() + PAIRING_SECONDS
            expires_at = (
                datetime.fromtimestamp(expires, timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
            self._pairing = [_digest(token), expires, PAIRING_ATTEMPTS]
            payload = {
                "schema_version": 2 if automatic_cloudflare else 1,
                "computer_id": self._identity["computer_id"],
                "computer_name": self.computer_name,
                "routes": canonical,
                "pairing_token": token,
                "expires_at": expires_at,
            }
            encoded = base64.urlsafe_b64encode(_json(payload)).decode().rstrip("=")
            return {
                "pairing_url": "clarify://computer?data=" + encoded,
                "expires_at": expires_at,
            }

    def _status(self):
        with self._lock:
            self._require_started()
            actions = self.processor.action_readiness
            result = {
                "schema_version": 1,
                "computer_id": self._identity["computer_id"],
                "computer_name": self.computer_name,
                "ready": actions["dictate"],
                "action_readiness": actions,
                "text_actions": getattr(self.processor, "text_actions", []),
                "output_preferences_supported": getattr(
                    self.processor, "output_preferences_supported", False
                )
                is True,
            }
            if self._tunnel_settings is not None:
                result["remote_route"] = self._cloudflare_route()
            else:
                registration = self._registration_info()
                if registration is not None:
                    result["remote_registration"] = registration
            return result

    def snapshot(self) -> dict:
        with self._lock:
            db, owned = self._db, False
            computer_id = self._identity["computer_id"] if self._identity else None
            devices = []
            try:
                if (
                    db is None
                    and self.state_path.is_file()
                    and self.state_path.stat().st_size
                ):
                    db = sqlite3.connect(
                        self.state_path.resolve().as_uri() + "?mode=ro",
                        uri=True,
                        timeout=1,
                    )
                    owned = True
                    if db.execute("PRAGMA user_version").fetchone()[0] not in (1, 2):
                        raise ValueError("Unsupported computer state version")
                    row = db.execute("SELECT computer_id FROM identity").fetchone()
                    if row is None or (
                        computer_id is not None and computer_id != row[0]
                    ):
                        raise ValueError("Computer state identity does not match")
                    computer_id = _uuid(row[0])
                if db is not None:
                    rows = db.execute(
                        "SELECT device_id,name,created_at FROM devices ORDER BY created_at,device_id LIMIT ?",
                        (MAX_DEVICES + 1,),
                    ).fetchall()
                    if len(rows) > MAX_DEVICES:
                        raise ValueError("Computer state exceeds the device limit")
                    devices = [
                        {
                            "device_id": row[0],
                            "device_name": row[1],
                            "created_at": row[2],
                        }
                        for row in rows
                    ]
            finally:
                if owned:
                    db.close()
            relay_status, relay_connected = "stopped", False
            if self._relay_host is None:
                relay_status = "disabled"
            elif self._relay_stop_failed:
                relay_status = "stop_failed"
            elif self._relay is not None:
                try:
                    status = self._relay.status
                    if isinstance(status, str) and status in _RELAY_STATUSES:
                        relay_status = status
                        relay_connected = (
                            self._server is not None and self._relay.connected is True
                        )
                    else:
                        relay_status = "relay_unavailable"
                except Exception:
                    relay_status = "relay_unavailable"
            return {
                "schema_version": 1,
                "enabled": self._server is not None,
                "ready": self.ready,
                "computer_id": computer_id,
                "computer_name": self.computer_name,
                "host": self.host,
                "port": self.port,
                "devices": devices,
                "active_operations": len(self._running),
                "relay_configured": self._relay_host is not None
                or self._cloudflare_config is not None,
                "relay_connected": relay_connected
                or bool(self._tunnel is not None and self._tunnel.connected),
                "relay_status": relay_status,
                "cloudflare_configured": self._cloudflare_config is not None,
                "cloudflare_registered": self._tunnel_settings is not None,
            }

    def _pair(self, body):
        if set(body) != {"pairing_token", "device_name"}:
            raise _APIError(400, "invalid_request")
        name = _name(body["device_name"])
        token = body["pairing_token"]
        with self._lock:
            self._require_started()
            pairing = self._pairing
            if pairing is None or self.clock() >= pairing[1] or pairing[2] <= 0:
                self._pairing = None
                raise _APIError(401, "invalid_pairing")
            pairing[2] -= 1
            if (
                not isinstance(token, str)
                or not _TOKEN.fullmatch(token)
                or not hmac.compare_digest(_digest(token), pairing[0])
            ):
                raise _APIError(401, "invalid_pairing")
            self._pairing = None
            if (
                self._db.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
                >= MAX_DEVICES
            ):
                raise _APIError(429, "device_limit")
            device_id, session = str(uuid4()), secrets.token_urlsafe(32)
            self._db.execute(
                "INSERT INTO devices VALUES (?,?,?,?)",
                (device_id, name, _digest(session), self.clock()),
            )
            self._db.commit()
            result = {
                "schema_version": 1,
                "computer_id": self._identity["computer_id"],
                "computer_name": self.computer_name,
                "device_id": device_id,
                "session_token": session,
            }
            registration = self._registration_info()
            if registration is not None:
                result["remote_registration"] = registration
            return result

    def _authenticate(self, header):
        token = header[7:] if header.startswith("Bearer ") else ""
        if not _TOKEN.fullmatch(token):
            raise _APIError(401, "unauthorized")
        with self._lock:
            self._require_started()
            row = self._db.execute(
                "SELECT device_id FROM devices WHERE token_hash=?", (_digest(token),)
            ).fetchone()
            if row is None:
                raise _APIError(401, "unauthorized")
            return row[0]

    def revoke_device(self, device_id):
        device_id = _uuid(device_id)
        with self._lock:
            db, owned = self._db, False
            if db is None:
                if not self.state_path.is_file() or not self.state_path.stat().st_size:
                    return
                self._identity = self._load_identity()
                db = self._open_state()
                owned = True
            for key, work in self._running.items():
                if key[0] == device_id:
                    work.token.cancel()
            try:
                db.execute("DELETE FROM devices WHERE device_id=?", (device_id,))
                db.commit()
            finally:
                if owned:
                    db.close()
            for key in list(self._results):
                if key[0] == device_id:
                    self._result_bytes -= len(self._results.pop(key))

    def _operation_window(self):
        """Persist the replay barrier before deleting any expired UUIDv7 claim.

        Call only under _lock. A restart or wall-clock rollback cannot lower
        this barrier. Legacy claims and keys with active workers remain stored.
        """
        now = int(self.clock() * 1000)
        self._db.execute(
            "UPDATE replay_window SET highwater_ms=MAX(highwater_ms, ?) WHERE id=1",
            (now,),
        )
        highwater = self._db.execute(
            "SELECT highwater_ms FROM replay_window WHERE id=1"
        ).fetchone()[0]
        self._db.commit()
        cutoff = highwater - OPERATION_SECONDS * 1000
        legacy_count = 0
        for device, operation in self._db.execute(
            "SELECT device_id,operation_id FROM operations"
        ).fetchall():
            try:
                timestamp = _operation_timestamp(operation)
            except (ValueError, _APIError):
                legacy_count += 1
                continue
            key = (device, operation)
            if timestamp < cutoff and key not in self._running:
                self._db.execute(
                    "DELETE FROM operations WHERE device_id=? AND operation_id=?", key
                )
                self._result_bytes -= len(self._results.pop(key, b""))
        # The actual metadata count owns admission. Retained legacy and active
        # claims use capacity even when their timestamps are outside the window.
        count = self._db.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
        self._db.commit()
        return now, cutoff, count, legacy_count

    def _require_operation_capacity(self, window):
        if window[2] >= MAX_OPERATIONS:
            if window[3] >= MAX_OPERATIONS:
                # Time cannot release legacy UUIDv4 claims. Explicit device
                # revocation removes that device's claims through FK cascade.
                raise _APIError(409, "operation_history_full")
            raise _APIError(429, "operation_limit")

    def _check_operation_time(self, operation, known, window):
        try:
            timestamp = _operation_timestamp(operation)
        except _APIError:
            # Older persisted UUIDv4 claims remain authoritative. An unknown
            # legacy ID can never reserve work or cancellation on this host.
            if known and UUID(operation).version == 4:
                return
            raise
        now, cutoff = window[:2]
        if timestamp < cutoff:
            raise _APIError(409, "operation_expired")
        if timestamp > now + OPERATION_FUTURE_SECONDS * 1000:
            raise _APIError(400, "operation_in_future")

    def _cancel(self, device, operation):
        operation = _uuid(operation)
        key = (device, operation)
        with self._lock:
            self._require_started()
            if (
                self._db.execute(
                    "SELECT 1 FROM devices WHERE device_id=?", (device,)
                ).fetchone()
                is None
            ):
                raise _APIError(401, "unauthorized")
            window = self._operation_window()
            known = self._db.execute(
                "SELECT 1 FROM operations WHERE device_id=? AND operation_id=?", key
            ).fetchone()
            # Cancelling an already running claim remains valid after expiry;
            # it cannot admit new work or revive a removed claim.
            if key not in self._running:
                self._check_operation_time(operation, known, window)
            if known is None:
                self._require_operation_capacity(window)
                # Cancellation may beat a slow upload to admission. This empty
                # content hash reserves the ID until its replay window expires.
                self._db.execute(
                    "INSERT INTO operations VALUES (?,?,?,?,?)",
                    (*key, "", "cancelled", self.clock()),
                )
            if key in self._running:
                self._running[key].token.cancel()
            self._db.execute(
                "UPDATE operations SET state='cancelled' WHERE device_id=? AND operation_id=?",
                key,
            )
            self._db.commit()
            self._result_bytes -= len(self._results.pop(key, b""))

    def _validated(self, route, body):
        fields = (
            {"operation_id", "language", "audio_wav"}
            if route == "dictations"
            else {"operation_id", "action", "text", "language"}
        )
        saved_action = route == "text" and body.get("action") == "text_action"
        if saved_action:
            fields |= {"action_id", "action_revision"}
        optional = (
            {"writing_style", "output_language"}
            if route == "dictations"
            else {"writing_style"}
        )
        if not fields <= set(body) or set(body) - fields - optional:
            raise _APIError(400, "invalid_request")
        try:
            if (
                "writing_style" in body
                and parse_writing_style(body["writing_style"]) is None
            ):
                raise ValueError()
            if (
                "output_language" in body
                and parse_output_language(body["output_language"]) is None
            ):
                raise ValueError()
        except (ValueError, TypeError):
            raise _APIError(400, "invalid_request") from None
        operation_id = _uuid(body["operation_id"])
        language = body["language"]
        if not isinstance(language, str) or not _LANGUAGE.fullmatch(language):
            raise _APIError(400, "invalid_request")
        if route == "dictations":
            value = _validate_wav(body["audio_wav"])
        else:
            if body["action"] not in ("rewrite", "translate", "text_action"):
                raise _APIError(400, "invalid_request")
            if saved_action:
                try:
                    identity(body["action_id"])
                except ValueError:
                    raise _APIError(400, "invalid_request") from None
                if (
                    type(body["action_revision"]) is not int
                    or not 1 <= body["action_revision"] <= MAX_REVISION
                    or language not in TEXT_LANGUAGES
                ):
                    raise _APIError(400, "invalid_request")
            value = body["text"]
            if not isinstance(value, str) or not value.strip() or "\0" in value:
                raise _APIError(400, "invalid_request")
            try:
                if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
                    raise _APIError(400, "invalid_request")
            except UnicodeEncodeError:
                raise _APIError(400, "invalid_request") from None
        return operation_id, language, value, _digest(_json({"route": route, **body}))

    def _cached(self, key, row, content_hash):
        if row == ("", "cancelled"):
            raise _APIError(409, "operation_cancelled")
        if not hmac.compare_digest(row[0], content_hash):
            raise _APIError(409, "operation_conflict")
        state = row[1]
        if state == "running":
            raise _APIError(409, "operation_in_progress")
        if state == "cancelled":
            raise _APIError(409, "operation_cancelled")
        if state == "failed":
            raise _APIError(502, "processing_failed")
        result = self._results.get(key)
        if result is None:
            raise _APIError(409, "result_unavailable")
        self._results.move_to_end(key)
        return json.loads(result)

    def _process(self, device, route, body):
        operation, language, value, content_hash = self._validated(route, body)
        preferences = {
            name: body[name]
            for name in ("writing_style", "output_language")
            if name in body
        }
        key = (device, operation)
        with self._lock:
            self._require_started()
            # Authentication can precede a slow body read. Recheck revocation
            # before claiming any expensive work.
            if (
                self._db.execute(
                    "SELECT 1 FROM devices WHERE device_id=?", (device,)
                ).fetchone()
                is None
            ):
                raise _APIError(401, "unauthorized")
            window = self._operation_window()
            row = self._db.execute(
                "SELECT content_hash,state FROM operations WHERE device_id=? AND operation_id=?",
                key,
            ).fetchone()
            self._check_operation_time(operation, row, window)
            if row:
                return self._cached(key, row, content_hash)
            action = "dictate" if route == "dictations" else body["action"]
            prepared = None
            if action == "text_action":
                try:
                    prepared = self.processor.prepare_text_action(
                        body["action_id"],
                        body["action_revision"],
                        value,
                        language,
                        **preferences,
                    )
                except ComputerActionChanged:
                    raise _APIError(409, "action_changed") from None
                except ComputerActionNotReady:
                    raise _APIError(503, "not_ready") from None
                except ValueError:
                    raise _APIError(400, "invalid_request") from None
            elif not self.processor.action_readiness.get(action, False):
                raise _APIError(503, "not_ready")
            self._require_operation_capacity(window)
            if not self._capacity.acquire(blocking=False):
                raise _APIError(429, "busy")
            work = _Running(device, CancellationToken(), self._generation)
            try:
                self._db.execute(
                    "INSERT INTO operations VALUES (?,?,?,?,?)",
                    (*key, content_hash, "running", self.clock()),
                )
                self._db.commit()
                self._running[key] = work
            except BaseException:
                self._capacity.release()
                raise
        try:
            try:
                if route == "dictations":
                    result = self.processor.process_dictation(
                        value, language, work.token, **preferences
                    )
                elif prepared is not None:
                    result = self.processor.process_text_action(prepared, work.token)
                else:
                    result = self.processor.process_text(
                        body["action"], value, language, work.token, **preferences
                    )
                if (
                    not isinstance(result, dict)
                    or set(result)
                    != {"transcript", "text", "rewritten", "successful"}
                    | {
                        prefix + suffix
                        for prefix in preferences
                        for suffix in ("_requested", "_applied", "_status")
                    }
                    or not isinstance(result["transcript"], str)
                    or not isinstance(result["text"], str)
                    or not result["text"].strip()
                    or len(result["text"].encode("utf-8")) > MAX_TEXT_BYTES
                    or len(result["transcript"].encode("utf-8")) > MAX_TEXT_BYTES
                    or type(result["rewritten"]) is not bool
                    or type(result["successful"]) is not bool
                ):
                    raise ValueError("Invalid computer processing result")
                for prefix, requested in preferences.items():
                    status = result[prefix + "_status"]
                    applied = result[prefix + "_applied"]
                    if (
                        result[prefix + "_requested"] != requested
                        or status
                        not in (
                            "applied",
                            "standalone",
                            "refinement_failed",
                            "refinement_not_allowed",
                            "unchanged",
                        )
                        or (status == "applied" and applied != requested)
                        or (
                            status == "unchanged"
                            and (
                                prefix != "output_language"
                                or requested != "auto"
                                or applied != "auto"
                            )
                        )
                        or (
                            status not in ("applied", "unchanged")
                            and applied is not None
                        )
                    ):
                        raise ValueError("Invalid output preference provenance")
                result = {"operation_id": operation, **result}
                if prepared is not None:
                    result.update(
                        action_id=body["action_id"],
                        action_revision=body["action_revision"],
                    )
                encoded = _json(result)
                if len(encoded) > MAX_RESULT_BYTES:
                    raise ValueError("Computer processing result is too large")
                failed = False
            except ProviderCancelledError:
                work.token.cancel()
                failed = True
            except Exception:
                failed = True
            with self._lock:
                if (
                    work.token.cancelled
                    or self._generation is not work.generation
                    or self._server is None
                ):
                    if self._server is not None and self._generation is work.generation:
                        self._db.execute(
                            "UPDATE operations SET state='cancelled' WHERE device_id=? AND operation_id=?",
                            key,
                        )
                        self._db.commit()
                    raise _APIError(409, "operation_cancelled")
                state = "failed" if failed else "succeeded"
                self._db.execute(
                    "UPDATE operations SET state=? WHERE device_id=? AND operation_id=?",
                    (state, *key),
                )
                self._db.commit()
                if failed:
                    raise _APIError(502, "processing_failed")
                while self._results and (
                    len(self._results) >= MAX_RESULTS
                    or self._result_bytes + len(encoded) > MAX_RESULT_BYTES
                ):
                    _, removed = self._results.popitem(last=False)
                    self._result_bytes -= len(removed)
                self._results[key] = encoded
                self._result_bytes += len(encoded)
                return result
        finally:
            with self._lock:
                if self._running.get(key) is work:
                    self._running.pop(key)
            self._capacity.release()
