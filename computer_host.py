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
from urllib.parse import urlsplit
from uuid import UUID, uuid4
import wave

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from provider_http import CancellationToken, ProviderCancelledError
from secret_store import SecretStore, SecretStoreCorruptedError


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


def _supported_route(address: ipaddress.IPv4Address, *, loopback: bool) -> bool:
    return any(address in network for network in _LAN_NETWORKS) or (
        loopback and address.is_loopback
    )


class ComputerProcessing(Protocol):
    @property
    def ready(self) -> bool: ...

    def process_dictation(
        self, audio_wav: bytes, language: str, cancel_token: CancellationToken
    ) -> dict: ...

    def process_text(
        self, action: str, text: str, language: str, cancel_token: CancellationToken
    ) -> dict: ...


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

    def __init__(self, owner, context, workers, timeout):
        self.owner, self.context, self.read_timeout = owner, context, timeout
        self.slots = threading.BoundedSemaphore(workers)
        self.connections: dict[socket.socket, threading.Timer | None] = {}
        self.guard = threading.Lock()
        self.stopping = False
        super().__init__((owner.host, owner.port), _Handler)

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
                secured = self.context.wrap_socket(
                    request, server_side=True, do_handshake_on_connect=False
                )
                secured.settimeout(self.read_timeout)
                timer = threading.Timer(self.read_timeout, _close_socket, (secured,))
                timer.daemon = True
                self.connections[secured] = timer
                timer.start()
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
            path = self.path
            routes = {
                "pair": "POST",
                "status": "GET",
                "dictations": "POST",
                "text": "POST",
                "session": "DELETE",
            }
            route = path[len(_PREFIX) :] if path.startswith(_PREFIX) else ""
            if route.startswith("operations/"):
                operation_id = _uuid(route[len("operations/") :])
                expected = "DELETE"
            elif route in routes:
                expected = routes[route]
            else:
                raise _APIError(404, "not_found")
            if self.command != expected:
                raise _APIError(405, "method_not_allowed")
            if route == "pair":
                body = self._body(4096)
                result = owner._pair(body)
            else:
                auth = self.headers.get_all("Authorization", [])
                device = owner._authenticate(auth[0] if len(auth) == 1 else "")
                if route in {"dictations", "text"}:
                    body = self._body()
                    result = owner._process(device, route, body)
                else:
                    self.server.end_read(self.connection)
                    if route == "status":
                        result = owner._status()
                    elif route == "session":
                        owner.revoke_device(device)
                        result = {"revoked": True}
                    else:
                        owner._cancel(device, operation_id)
                        result = {"cancelled": True}
            # Claim publication under the same lock as cancellation/revocation.
            # A revocation that wins this lock prevents a queued success reply.
            with owner._lock:
                owner._require_started()
                if route not in {"pair", "session"}:
                    if (
                        owner._db.execute(
                            "SELECT 1 FROM devices WHERE device_id=?", (device,)
                        ).fetchone()
                        is None
                    ):
                        raise _APIError(401, "unauthorized")
                    if route in {"dictations", "text"}:
                        state = owner._db.execute(
                            "SELECT state FROM operations WHERE device_id=? AND operation_id=?",
                            (device, result["operation_id"]),
                        ).fetchone()
                        if state is None or state[0] != "succeeded":
                            raise _APIError(409, "operation_cancelled")
                self._reply(200, result)
        except _APIError as error:
            self._reply(error.status, {"error": error.code})
        except TimeoutError:
            self._reply(408, {"error": "request_timeout"})
        except Exception:
            self._reply(500, {"error": "internal_error"})

    do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = do_HEAD = do_OPTIONS = _handle


@dataclass
class _Running:
    device_id: str
    token: CancellationToken
    generation: object


class ComputerHost:
    """An explicit start enables TLS; stop revokes the current pairing code.

    port=0 is supported for loopback tests. Production should keep the default
    stable port. create_pairing accepts up to four RFC1918 IPv4 LAN URLs or
    route dicts; omitted routes use the bound address or discovered LAN IPv4s.
    A loopback-bound test host can also advertise loopback addresses.
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
        clock: Callable[[], float] = time.time,
        address_provider: Callable[[], list[str]] | None = None,
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
        self.address_provider = address_provider or _local_addresses
        self._max_handlers, self._read_timeout = max_handlers, read_timeout
        self._capacity = threading.BoundedSemaphore(max_concurrent_operations)
        self._lock = threading.RLock()
        self._lifecycle = threading.Lock()
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
                    server = _Server(
                        self, context, self._max_handlers, self._read_timeout
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

    def stop(self):
        with self._lifecycle:
            with self._lock:
                server, thread = self._server, self._thread
                if server is None:
                    return
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
            server.close_connections()
            server.shutdown()
            server.server_close()
            thread.join()

    def _require_started(self):
        if self._server is None:
            raise _APIError(503, "host_stopped")

    def create_pairing(self, routes=None) -> dict:
        with self._lock:
            self._require_started()
            loopback = ipaddress.IPv4Address(self.host).is_loopback
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
                        if len(routes) == 4:
                            break
            if not isinstance(routes, (list, tuple)) or not 1 <= len(routes) <= 4:
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
            token = secrets.token_urlsafe(32)
            expires = self.clock() + PAIRING_SECONDS
            expires_at = (
                datetime.fromtimestamp(expires, timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
            self._pairing = [_digest(token), expires, PAIRING_ATTEMPTS]
            payload = {
                "schema_version": 1,
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
            return {
                "schema_version": 1,
                "computer_id": self._identity["computer_id"],
                "computer_name": self.computer_name,
                "ready": self.ready,
            }

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
            return {
                "schema_version": 1,
                "computer_id": self._identity["computer_id"],
                "computer_name": self.computer_name,
                "device_id": device_id,
                "session_token": session,
            }

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
        if set(body) != fields:
            raise _APIError(400, "invalid_request")
        operation_id = _uuid(body["operation_id"])
        language = body["language"]
        if not isinstance(language, str) or not _LANGUAGE.fullmatch(language):
            raise _APIError(400, "invalid_request")
        if route == "dictations":
            value = _validate_wav(body["audio_wav"])
        else:
            if body["action"] not in ("rewrite", "translate"):
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
            if not self.ready:
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
                        value, language, work.token
                    )
                else:
                    result = self.processor.process_text(
                        body["action"], value, language, work.token
                    )
                if (
                    not isinstance(result, dict)
                    or set(result) != {"transcript", "text", "rewritten", "successful"}
                    or not isinstance(result["transcript"], str)
                    or not isinstance(result["text"], str)
                    or not result["text"].strip()
                    or len(result["text"].encode("utf-8")) > MAX_TEXT_BYTES
                    or len(result["transcript"].encode("utf-8")) > MAX_TEXT_BYTES
                    or type(result["rewritten"]) is not bool
                    or type(result["successful"]) is not bool
                ):
                    raise ValueError("Invalid computer processing result")
                result = {"operation_id": operation, **result}
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
