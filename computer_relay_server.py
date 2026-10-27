"""Explicitly started, bounded reverse TLS byte relay. Stores counters only."""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import ipaddress
import os
from pathlib import Path
import secrets
import signal
import sqlite3
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from computer_relay_protocol import (
    Limits,
    RelayError,
    Stream,
    bridge,
    certificate_key,
    challenge,
    dns_name,
    encode_frame,
    namespace,
    port_number,
    read_frame,
    token,
    untoken,
    verify,
)


class EgressBudget:
    """Durable, burned-ahead aggregate leases, shared by every relay write.

    Unused lease bytes are never refunded, including after a clean shutdown.
    SQLite serializes reservations across processes. One instance stays on its
    owning event-loop thread. Clock rollback cannot reopen a previous month.
    """

    APPLICATION_ID = 0x43524231
    SCHEMA = {
        "metadata": "CREATE TABLE metadata (id INTEGER PRIMARY KEY CHECK(id=1), month TEXT NOT NULL, cap INTEGER NOT NULL)",
        "months": "CREATE TABLE months (month TEXT PRIMARY KEY, reserved INTEGER NOT NULL CHECK(reserved>=0))",
    }

    def __init__(self, path, cap: int, lease_bytes: int, *, clock=None):
        if type(cap) is not int or not 1 <= cap <= 2**63 - 1:
            raise RelayError("invalid_budget")
        if type(lease_bytes) is not int or not 1 <= lease_bytes <= 1_000_000:
            raise RelayError("invalid_budget")
        self.cap, self.lease_bytes = cap, lease_bytes
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.remaining, self.month = 0, ""
        self.db = None
        path = Path(path).absolute()
        created = False
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            created = True
        except FileExistsError:
            if path.is_symlink() or not path.is_file():
                raise RelayError("invalid_budget_database") from None
        except OSError:
            raise RelayError("budget_unavailable") from None
        try:
            self.db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=1.0)
            if created:
                with self.db:
                    self.db.execute(f"PRAGMA application_id={self.APPLICATION_ID}")
                    self.db.execute("PRAGMA user_version=1")
                    for sql in self.SCHEMA.values():
                        self.db.execute(sql)
                    self.db.execute(
                        "INSERT INTO metadata VALUES (1, ?, ?)",
                        (self._utc_month(), cap),
                    )
            actual = dict(
                self.db.execute(
                    "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL"
                )
            )
            if (
                self.db.execute("PRAGMA application_id").fetchone()[0]
                != self.APPLICATION_ID
                or self.db.execute("PRAGMA user_version").fetchone()[0] != 1
                or actual != self.SCHEMA
                or self.db.execute("SELECT cap FROM metadata WHERE id=1").fetchone()
                != (cap,)
            ):
                raise ValueError
            self.db.execute("PRAGMA synchronous=FULL")
        except Exception:
            self.close()
            raise RelayError("invalid_budget_database") from None

    def _utc_month(self):
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise RelayError("invalid_budget_clock")
        return now.astimezone(timezone.utc).strftime("%Y-%m")

    def consume(self, size: int):
        if type(size) is not int or not 0 <= size <= 1_000_000 or self.db is None:
            raise RelayError("budget_unavailable")
        current = self._utc_month()
        if current != self.month:
            self.remaining = 0
        if self.remaining >= size:
            self.remaining -= size
            return
        try:
            self.db.execute("BEGIN IMMEDIATE")
            floor, cap = self.db.execute(
                "SELECT month, cap FROM metadata WHERE id=1"
            ).fetchone()
            if current < floor or cap != self.cap:
                raise RelayError("budget_clock_or_config")
            self.db.execute("UPDATE metadata SET month=? WHERE id=1", (current,))
            row = self.db.execute(
                "SELECT reserved FROM months WHERE month=?", (current,)
            ).fetchone()
            reserved = row[0] if row else 0
            if type(reserved) is not int or not 0 <= reserved <= self.cap:
                raise RelayError("budget_unavailable")
            # Existing lease credit stays burned. Reserve only the new bytes.
            needed = size - self.remaining
            grant = min(self.cap - reserved, max(needed, self.lease_bytes))
            if grant < needed:
                raise RelayError("budget_exhausted")
            self.db.execute(
                "INSERT INTO months VALUES (?, ?) ON CONFLICT(month) DO UPDATE SET reserved=excluded.reserved",
                (current, reserved + grant),
            )
            self.db.commit()
            self.month = current
            self.remaining += grant - size
        except Exception as exc:
            self.db.rollback()
            if isinstance(exc, RelayError):
                raise
            raise RelayError("budget_unavailable") from None

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        self.remaining = 0


class _TLS:
    """SSLObject adapter. One reader; writes and BIO flushes are serialized."""

    def __init__(self, raw, obj, incoming, outgoing):
        self.raw, self.obj, self.incoming, self.outgoing = raw, obj, incoming, outgoing
        self.flush_lock, self.write_lock = asyncio.Lock(), asyncio.Lock()

    async def flush(self):
        async with self.flush_lock:
            while self.outgoing.pending:
                await self.raw.write(self.outgoing.read(self.raw.limits.buffer_bytes))

    async def feed(self):
        await self.flush()
        data = await self.raw.read(self.raw.limits.buffer_bytes)
        if not data:
            self.incoming.write_eof()
            raise RelayError("connection_closed")
        self.incoming.write(data)

    async def read(self, size):
        while True:
            try:
                data = self.obj.read(min(size, self.raw.limits.buffer_bytes))
                await self.flush()
                return data
            except ssl.SSLWantReadError:
                await self.feed()
            except ssl.SSLWantWriteError:
                await self.flush()
            except ssl.SSLZeroReturnError:
                return b""

    async def write(self, data):
        async with self.write_lock:
            offset = 0
            while offset < len(data):
                try:
                    offset += self.obj.write(
                        data[offset : offset + self.raw.limits.buffer_bytes]
                    )
                except ssl.SSLWantWriteError:
                    pass
                # A TLS 1.2/1.3 application write does not need a peer read;
                # fail closed if a context attempts renegotiation instead.
                except ssl.SSLWantReadError:
                    raise RelayError("tls_renegotiation") from None
                await self.flush()

    def close(self):
        self.raw.close()

    async def finish(self):
        await self.flush()
        await self.raw.finish()


@dataclass(eq=False)
class _Owner:
    namespace: str
    key: object
    channel: _TLS
    generation: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    streams: int = 0
    tasks: set = field(default_factory=set)


@dataclass
class _Pending:
    owner: _Owner
    future: asyncio.Future
    phone_task: asyncio.Task
    generation: bytes
    consumed: bool = False


class ComputerRelayServer:
    """Owns its listener, admitted sockets, tasks and counter database.

    start/stop and inspection belong to one asyncio event loop. The supplied
    public server context must have the operator's certificate and private key.
    No context, database or listener is created until explicit construction/start.
    """

    def __init__(
        self,
        bind_host: str,
        port: int,
        relay_host: str,
        ssl_context: ssl.SSLContext,
        budget_path,
        monthly_egress_cap: int,
        *,
        limits: Limits | None = None,
        clock=None,
    ):
        try:
            if not isinstance(bind_host, str):
                raise ValueError
            ipaddress.ip_address(bind_host)
        except ValueError:
            raise RelayError("invalid_bind_address") from None
        self.bind_host, self.port = bind_host, port_number(port, ephemeral=True)
        self.relay_host, self.context = dns_name(relay_host), ssl_context
        if (
            not isinstance(ssl_context, ssl.SSLContext)
            or ssl_context.protocol != ssl.PROTOCOL_TLS_SERVER
            or ssl_context.minimum_version < ssl.TLSVersion.TLSv1_2
            or ssl_context.keylog_filename
        ):
            raise RelayError("invalid_tls_context")
        self.limits = limits if limits is not None else Limits()
        if not isinstance(self.limits, Limits):
            raise RelayError("invalid_limits")
        self.budget_path, self.cap, self.clock = budget_path, monthly_egress_cap, clock
        self.listener = self.budget = None
        self.owners, self.pending, self.tasks, self.sockets = {}, {}, set(), set()
        self._handshaking = set()
        self.tunnels = 0
        self.ip_counts, self.admissions = {}, {}
        self.global_admissions = []
        self.stopping = False
        self._lifecycle = asyncio.Lock()
        self.last_error = None
        self._sni = {}
        self.sniffer = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.sniffer.minimum_version = ssl.TLSVersion.TLSv1_2
        self.sniffer.options |= ssl.OP_NO_RENEGOTIATION
        self.sniffer.sni_callback = self._select_sni

    @property
    def handshakes(self):
        return len(self._handshaking)

    @property
    def address(self):
        if self.listener is None:
            return None
        return self.listener.sockets[0].getsockname()[:2]

    @property
    def status(self):
        return {
            "running": self.listener is not None,
            "hosts": len(self.owners),
            "pending": len(self.pending),
            "tunnels": self.tunnels,
            "connections": len(self.sockets),
            "tasks": len(self.tasks),
            "handshakes": self.handshakes,
            "error": self.last_error,
        }

    def _select_sni(self, obj, name, _context):
        self._sni[obj] = name
        if name == self.relay_host:
            obj.context = self.context
            return None
        return ssl.ALERT_DESCRIPTION_UNRECOGNIZED_NAME

    async def start(self):
        async with self._lifecycle:
            await self._start()

    async def _start(self):
        if self.listener is not None or self.tasks:
            raise RelayError("already_started")
        self.stopping = False
        self.budget = EgressBudget(
            self.budget_path, self.cap, self.limits.lease_bytes, clock=self.clock
        )
        try:
            self.listener = await asyncio.start_server(
                self._accept,
                self.bind_host,
                self.port,
                limit=self.limits.buffer_bytes,
                backlog=self.limits.max_handshakes,
                start_serving=False,
            )
            await self.listener.start_serving()
        except BaseException as exc:
            await self._stop()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise RelayError("listener_failed") from None

    async def stop(self):
        async with self._lifecycle:
            await self._stop()

    async def _stop(self):
        self.stopping = True
        listener = self.listener
        if self.listener:
            self.listener.close()
        for stream in tuple(self.sockets):
            stream.close()
        for task in tuple(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        # Python 3.12 can wait for active connections here. Abort and drain the
        # owned connections first, or a live tunnel can prevent shutdown.
        if listener:
            await listener.wait_closed()
        self.listener = None
        if self.budget:
            self.budget.close()
            self.budget = None
        self.admissions.clear()
        self.global_admissions.clear()
        if (
            self.tasks
            or self.sockets
            or self.pending
            or self.owners
            or self.handshakes
            or self.tunnels
        ):
            raise RelayError("drain_failed")

    def _admit(self, ip):
        now = time.monotonic()
        self.admissions = {
            key: [t for t in values if now - t < 60]
            for key, values in self.admissions.items()
            if values and now - values[-1] < 60
        }
        self.global_admissions = [t for t in self.global_admissions if now - t < 60]
        values = self.admissions.get(ip, [])
        if (
            self.stopping
            or len(self.sockets) >= self.limits.max_connections
            or self.handshakes >= self.limits.max_handshakes
            or self.ip_counts.get(ip, 0) >= self.limits.connections_per_ip
            or len(values) >= self.limits.admissions_per_ip_minute
            or len(self.global_admissions) >= self.limits.admissions_per_minute
            or (
                ip not in self.admissions
                and len(self.admissions) >= self.limits.ip_entries
            )
        ):
            return False
        self.admissions.setdefault(ip, []).append(now)
        self.global_admissions.append(now)
        return True

    def _accept(self, reader, writer):
        peer = writer.get_extra_info("peername")
        if not peer:
            writer.transport.abort()
            return
        ip = peer[0]
        if not self._admit(ip):
            writer.transport.abort()
            return
        stream = Stream(reader, writer, self.limits, self.budget)
        self.sockets.add(stream)
        self.ip_counts[ip] = self.ip_counts.get(ip, 0) + 1
        self._handshaking.add(stream)
        task = asyncio.create_task(self._connection(stream))
        self.tasks.add(task)
        task.add_done_callback(lambda completed: self._released(completed, stream, ip))

    def _released(self, task, stream, ip):
        # A task cancelled before its first step never executes its finally.
        # Admission ownership therefore belongs to this completion callback.
        self.tasks.discard(task)
        self._handshaking.discard(stream)
        stream.close()
        self.sockets.discard(stream)
        self.ip_counts[ip] -= 1
        if not self.ip_counts[ip]:
            del self.ip_counts[ip]

    async def _sniff(self, raw):
        incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        obj = self.sniffer.wrap_bio(incoming, outgoing, server_side=True)
        channel = _TLS(raw, obj, incoming, outgoing)
        original = bytearray()
        received = 0
        try:
            while True:
                try:
                    obj.do_handshake()
                    await channel.flush()
                    return self._sni.get(obj), channel, b""
                except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                    if self._sni.get(obj) == self.relay_host:
                        await channel.flush()
                        # After root SNI selection no original-byte replay is needed.
                        original.clear()
                    available = self.limits.preface_bytes - received
                    if available <= 0:
                        raise RelayError("preface_limit")
                    data = await raw.read(min(available, self.limits.buffer_bytes))
                    if not data:
                        raise RelayError("connection_closed")
                    original.extend(data)
                    received += len(data)
                    incoming.write(data)
                except ssl.SSLError:
                    name = self._sni.get(obj)
                    if name and name != self.relay_host:
                        # OpenSSL has parsed ClientHello. Its alert is discarded.
                        return name, None, bytes(original)
                    raise
        finally:
            self._sni.pop(obj, None)

    async def _connection(self, raw):
        try:
            async with asyncio.timeout(self.limits.handshake_timeout):
                name, channel, original = await self._sniff(raw)
            if name == self.relay_host:
                async with asyncio.timeout(self.limits.setup_timeout):
                    nonce = secrets.token_bytes(32)
                    await channel.write(
                        encode_frame(
                            {"v": 1, "kind": "challenge", "nonce": token(nonce)},
                            self.limits.frame_bytes,
                        )
                    )
                    message = await read_frame(channel, self.limits.frame_bytes)
                    if message["kind"] == "register":
                        owner = self._register(channel, message, nonce)
                        self._handshaking.discard(raw)
                        await channel.write(
                            encode_frame(
                                {
                                    "v": 1,
                                    "kind": "registered",
                                    "namespace": owner.namespace,
                                }
                            )
                        )
                    elif message["kind"] == "attach":
                        pending = self._attach(channel, message, nonce)
                        self._handshaking.discard(raw)
                        await channel.write(encode_frame({"v": 1, "kind": "attached"}))
                        pending.future.set_result(channel)
                        owner = None
                    else:
                        raise RelayError("invalid_preface")
                if owner is not None:
                    await self._control(owner)
                else:
                    # Phone task exclusively owns the data channel after ack.
                    await asyncio.shield(pending.phone_task)
            else:
                self._handshaking.discard(raw)
                await self._phone(raw, name, original)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = (
                str(exc) if isinstance(exc, RelayError) else "connection_failed"
            )
            if self.last_error in (
                "budget_exhausted",
                "budget_unavailable",
                "budget_clock_or_config",
            ):
                for stream in tuple(self.sockets):
                    stream.close()
        finally:
            # An ack write can fail after _register but before _control starts.
            for owner in tuple(self.owners.values()):
                if owner.channel.raw is raw:
                    self._drop_owner(owner)
            raw.close()

    def _register(self, channel, message, nonce):
        der = base64.b64decode(message["certificate"], validate=True)
        key = certificate_key(der)
        verify(key, message["signature"], challenge("register", self.relay_host, nonce))
        name = namespace(der)
        old = self.owners.get(name)
        if old is None and len(self.owners) >= self.limits.max_hosts:
            raise RelayError("host_limit")
        owner = _Owner(name, key, channel)
        self.owners[name] = owner
        if old:
            self._drop_owner(old)
        return owner

    def _drop_owner(self, owner):
        if self.owners.get(owner.namespace) is owner:
            del self.owners[owner.namespace]
        owner.channel.close()
        for task in tuple(owner.tasks):
            task.cancel()

    async def _control(self, owner):
        try:
            while True:
                message = await asyncio.wait_for(
                    read_frame(owner.channel, self.limits.frame_bytes),
                    self.limits.idle_timeout,
                )
                if (
                    message["kind"] != "ping"
                    or self.owners.get(owner.namespace) is not owner
                ):
                    raise RelayError("invalid_control")
                await owner.channel.write(encode_frame({"v": 1, "kind": "pong"}))
        finally:
            self._drop_owner(owner)

    def _attach(self, channel, message, nonce):
        pending = self.pending.get(message["pending"])
        if (
            pending is None
            or pending.consumed
            or pending.future.done()
            or self.owners.get(pending.owner.namespace) is not pending.owner
            or pending.generation != pending.owner.generation
        ):
            raise RelayError("invalid_attach")
        verify(
            pending.owner.key,
            message["signature"],
            challenge("attach", self.relay_host, nonce, untoken(message["pending"])),
        )
        pending.consumed = True
        return pending

    async def _phone(self, raw, name, original):
        import re

        suffix = "." + self.relay_host
        if (
            not isinstance(name, str)
            or not name.endswith(suffix)
            or not re.fullmatch(r"[a-z2-7]{52}", name[: -len(suffix)])
        ):
            raise RelayError("invalid_sni")
        owner = self.owners.get(name[: -len(suffix)])
        if owner is None:
            raise RelayError("host_offline")
        if (
            owner.streams >= self.limits.streams_per_host
            or len(self.pending) >= self.limits.max_pending
            or self.tunnels >= self.limits.max_tunnels
        ):
            raise RelayError("stream_limit")
        current = asyncio.current_task()
        pending_id = token(secrets.token_bytes(32))
        future = asyncio.get_running_loop().create_future()
        pending = _Pending(owner, future, current, owner.generation)
        self.pending[pending_id] = pending
        owner.tasks.add(current)
        owner.streams += 1
        self.tunnels += 1
        data = None
        try:
            async with asyncio.timeout(self.limits.setup_timeout):
                await owner.channel.write(
                    encode_frame({"v": 1, "kind": "open", "pending": pending_id})
                )
                data = await future
                if self.owners.get(owner.namespace) is not owner:
                    raise RelayError("stale_owner")
                self.pending.pop(pending_id, None)
                await data.write(original)
            await bridge(raw, data, self.limits)
        finally:
            self.pending.pop(pending_id, None)
            if data:
                data.close()
            elif future.done() and not future.cancelled():
                future.result().close()
            else:
                future.cancel()
            owner.tasks.discard(current)
            owner.streams -= 1
            self.tunnels -= 1


async def _serve(args):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.options |= ssl.OP_NO_RENEGOTIATION
    context.load_cert_chain(args.certificate, args.private_key)
    server = ComputerRelayServer(
        args.bind,
        args.port,
        args.relay_host,
        context,
        args.budget_db,
        args.monthly_egress_cap,
    )
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, stopped.set)
    await server.start()
    print("relay_started", flush=True)
    try:
        await stopped.wait()
    finally:
        await server.stop()
        print("relay_stopped", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Explicit computer TLS byte relay")
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--relay-host", required=True)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--budget-db", required=True)
    parser.add_argument("--monthly-egress-cap", type=int, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(_serve(args))
    except KeyboardInterrupt:
        pass
    except Exception:
        print("relay_failed", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
