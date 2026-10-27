"""Bounded wire contract for the optional computer byte relay. No startup effects."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import re
import ssl
import struct
from dataclasses import dataclass
from typing import Callable

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


class RelayError(Exception):
    """A fixed, public error code. Never include an underlying exception."""


def dns_name(value: str) -> str:
    if not isinstance(value, str) or not 3 <= len(value) <= 200:
        raise RelayError("invalid_hostname")
    if value != value.lower() or "." not in value:
        raise RelayError("invalid_hostname")
    if any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
        for part in value.split(".")
    ):
        raise RelayError("invalid_hostname")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise RelayError("invalid_hostname")


def port_number(value: int, *, ephemeral: bool = False) -> int:
    if type(value) is not int or not (0 if ephemeral else 1) <= value <= 65535:
        raise RelayError("invalid_port")
    return value


def token(value: bytes) -> str:
    if not isinstance(value, bytes) or len(value) != 32:
        raise RelayError("invalid_token")
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def untoken(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise RelayError("invalid_token")
    result = base64.urlsafe_b64decode(value + "=")
    if token(result) != value:
        raise RelayError("invalid_token")
    return result


def certificate_key(der: bytes) -> ec.EllipticCurvePublicKey:
    try:
        if not isinstance(der, bytes) or not 128 <= len(der) <= 4096:
            raise ValueError
        cert = x509.load_der_x509_certificate(der)
        if cert.public_bytes(serialization.Encoding.DER) != der:
            raise ValueError
        key = cert.public_key()
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError
        return key
    except Exception:
        raise RelayError("invalid_certificate") from None


def namespace(der: bytes) -> str:
    certificate_key(der)
    return (
        base64.b32encode(hashlib.sha256(der).digest())
        .decode("ascii")
        .lower()
        .rstrip("=")
    )


def challenge(
    purpose: str, host: str, nonce: bytes, pending: bytes | None = None
) -> bytes:
    dns_name(host)
    token(nonce)
    if purpose == "register" and pending is None:
        suffix = b""
    elif purpose == "attach" and pending is not None:
        token(pending)
        suffix = pending
    else:
        raise RelayError("invalid_purpose")
    return (
        b"clarify-computer-relay\x00v1\x00"
        + purpose.encode("ascii")
        + b"\x00"
        + host.encode("ascii")
        + b"\x00"
        + nonce
        + suffix
    )


def signature_text(signature: bytes) -> str:
    if not isinstance(signature, bytes) or not 8 <= len(signature) <= 72:
        raise RelayError("invalid_signature")
    return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def signature_bytes(value: str) -> bytes:
    try:
        if (
            not isinstance(value, str)
            or not 11 <= len(value) <= 96
            or not re.fullmatch(r"[A-Za-z0-9_-]+", value)
        ):
            raise ValueError
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        if signature_text(raw) != value:
            raise ValueError
        return raw
    except Exception:
        raise RelayError("invalid_signature") from None


def verify(key: ec.EllipticCurvePublicKey, signature: str, message: bytes) -> None:
    try:
        key.verify(signature_bytes(signature), message, ec.ECDSA(hashes.SHA256()))
    except Exception:
        raise RelayError("invalid_proof") from None


@dataclass(frozen=True)
class RelayIdentity:
    certificate_der: bytes
    sign_callback: Callable[[bytes], bytes]

    def __post_init__(self):
        certificate_key(self.certificate_der)
        if not callable(self.sign_callback):
            raise RelayError("invalid_signer")

    @property
    def namespace(self) -> str:
        return namespace(self.certificate_der)

    def proof(
        self, purpose: str, host: str, nonce: bytes, pending: bytes | None = None
    ) -> str:
        message = challenge(purpose, host, nonce, pending)
        try:
            result = signature_text(self.sign_callback(message))
            verify(certificate_key(self.certificate_der), result, message)
            return result
        except Exception:
            raise RelayError("identity_proof_failed") from None


@dataclass(frozen=True)
class Limits:
    max_hosts: int = 64
    max_connections: int = 256
    max_handshakes: int = 32
    max_pending: int = 64
    max_tunnels: int = 128
    streams_per_host: int = 4
    connections_per_ip: int = 32
    admissions_per_ip_minute: int = 60
    admissions_per_minute: int = 600
    ip_entries: int = 1024
    frame_bytes: int = 8192
    preface_bytes: int = 65536
    buffer_bytes: int = 16384
    lease_bytes: int = 65536
    handshake_timeout: float = 5.0
    setup_timeout: float = 10.0
    idle_timeout: float = 60.0
    heartbeat_interval: float = 15.0
    # Mobile processing permits 100 seconds with no response bytes.
    tunnel_idle_timeout: float = 120.0

    def __post_init__(self):
        for name, value in vars(self).items():
            if name.endswith("timeout") or name == "heartbeat_interval":
                if type(value) not in (int, float) or not 0.05 <= value <= 3600:
                    raise RelayError("invalid_limits")
            elif type(value) is not int or not 1 <= value <= 1_000_000:
                raise RelayError("invalid_limits")
        if (
            not 1024 <= self.frame_bytes <= 8192
            or not 1024 <= self.buffer_bytes <= 65536
        ):
            raise RelayError("invalid_limits")
        if (
            not 1024 <= self.preface_bytes <= 65536
            or self.heartbeat_interval >= self.idle_timeout
        ):
            raise RelayError("invalid_limits")


def validate_client_context(context: ssl.SSLContext) -> ssl.SSLContext:
    if (
        not isinstance(context, ssl.SSLContext)
        or context.protocol != ssl.PROTOCOL_TLS_CLIENT
        or context.verify_mode != ssl.CERT_REQUIRED
        or not context.check_hostname
        or context.minimum_version < ssl.TLSVersion.TLSv1_2
        or context.keylog_filename
    ):
        raise RelayError("invalid_tls_context")
    return context


def public_client_context() -> ssl.SSLContext:
    # Unlike create_default_context, this does not honor SSLKEYLOGFILE.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_default_certs()
    return context


def decode_frame(data: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    shapes = {
        "challenge": {"nonce"},
        "register": {"certificate", "signature"},
        "registered": {"namespace"},
        "open": {"pending"},
        "attach": {"pending", "signature"},
        "attached": set(),
        "ping": set(),
        "pong": set(),
    }
    try:
        if not isinstance(data, bytes) or not 1 <= len(data) <= 8192:
            raise ValueError
        message = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        if (
            not isinstance(message, dict)
            or type(message.get("v")) is not int
            or message["v"] != 1
        ):
            raise ValueError
        kind = message.get("kind")
        if (
            not isinstance(kind, str)
            or kind not in shapes
            or set(message) != shapes[kind] | {"v", "kind"}
        ):
            raise ValueError
        for key, value in message.items():
            if key != "v" and not isinstance(value, str):
                raise ValueError
        for name in ("nonce", "pending"):
            if name in message:
                untoken(message[name])
        if "signature" in message:
            signature_bytes(message["signature"])
        if "namespace" in message and not re.fullmatch(
            r"[a-z2-7]{51}[aq]", message["namespace"]
        ):
            raise ValueError
        if "certificate" in message:
            value = message["certificate"]
            if not 172 <= len(value) <= 5464:
                raise ValueError
            raw = base64.b64decode(value, validate=True)
            if (
                not 128 <= len(raw) <= 4096
                or base64.b64encode(raw).decode("ascii") != value
            ):
                raise ValueError
        return message
    except Exception:
        raise RelayError("invalid_frame") from None


def encode_frame(message: dict, maximum: int = 8192) -> bytes:
    if type(maximum) is not int or not 1 <= maximum <= 8192:
        raise RelayError("invalid_frame_limit")
    try:
        raw = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode(
            "ascii"
        )
        decode_frame(raw)
    except Exception:
        raise RelayError("invalid_frame") from None
    if not 1 <= len(raw) <= maximum:
        raise RelayError("frame_limit")
    return struct.pack("!I", len(raw)) + raw


async def read_frame(stream, maximum: int = 8192) -> dict:
    if type(maximum) is not int or not 1 <= maximum <= 8192:
        raise RelayError("invalid_frame_limit")
    header = await read_exact(stream, 4)
    size = struct.unpack("!I", header)[0]
    if not 1 <= size <= maximum:
        raise RelayError("frame_limit")
    return decode_frame(await read_exact(stream, size))


async def read_exact(stream, size: int) -> bytes:
    if type(size) is not int or not 1 <= size <= 8192:
        raise RelayError("invalid_frame_limit")
    data = bytearray()
    while len(data) < size:
        part = await stream.read(size - len(data))
        if not part:
            raise RelayError("connection_closed")
        data.extend(part)
    return bytes(data)


async def bridge(left, right, limits: Limits) -> None:
    loop = asyncio.get_running_loop()
    last_activity = loop.time()

    async def pump(source, destination):
        nonlocal last_activity
        while True:
            data = await source.read(limits.buffer_bytes)
            if not data:
                return
            last_activity = loop.time()
            await asyncio.wait_for(destination.write(data), limits.tunnel_idle_timeout)
            last_activity = loop.time()

    async def idle_watchdog():
        while True:
            remaining = limits.tunnel_idle_timeout - (loop.time() - last_activity)
            if remaining <= 0:
                raise TimeoutError
            await asyncio.sleep(remaining)

    tasks = [
        asyncio.create_task(pump(left, right)),
        asyncio.create_task(pump(right, left)),
        asyncio.create_task(idle_watchdog()),
    ]
    complete = False
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        complete = True
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if complete:
            await asyncio.gather(left.finish(), right.finish())


class Stream:
    """One bounded reader and a serialized, drained writer. Caller owns close."""

    def __init__(self, reader, writer, limits: Limits, budget=None):
        self.reader, self.writer, self.limits, self.budget = (
            reader,
            writer,
            limits,
            budget,
        )
        self.lock = asyncio.Lock()
        writer.transport.set_write_buffer_limits(
            high=limits.buffer_bytes, low=limits.buffer_bytes // 2
        )

    async def read(self, size: int) -> bytes:
        if type(size) is not int or size <= 0:
            raise RelayError("invalid_read_size")
        return await self.reader.read(min(size, self.limits.buffer_bytes))

    async def write(self, data: bytes) -> None:
        async with self.lock:
            for offset in range(0, len(data), self.limits.buffer_bytes):
                part = data[offset : offset + self.limits.buffer_bytes]
                if self.budget:
                    self.budget.consume(len(part))
                self.writer.write(part)
                await asyncio.wait_for(self.writer.drain(), self.limits.idle_timeout)

    def close(self):
        # Abort is deliberate: cancellation never waits on an uncooperative TLS peer.
        self.writer.transport.abort()

    async def finish(self):
        self.writer.close()
        try:
            await asyncio.wait_for(
                self.writer.wait_closed(), min(1.0, self.limits.setup_timeout)
            )
        except (OSError, TimeoutError):
            self.close()
