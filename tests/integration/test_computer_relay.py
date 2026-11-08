"""Synthetic loopback contracts. No desktop profile, provider or microphone."""

import asyncio
import base64
from contextlib import closing, suppress
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import secrets
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from computer_relay_client import ComputerRelayClient
from computer_relay_protocol import (
    Limits,
    RelayError,
    RelayIdentity,
    Stream,
    bridge,
    challenge,
    decode_frame,
    dns_name,
    encode_frame,
    namespace,
    read_frame,
    token,
    untoken,
)
from computer_relay_server import ComputerRelayServer, EgressBudget, _TLS


from tests.support.computer_relay import (
    make_certificate,
    server_context,
    client_context,
    identity,
    eventually,
)

HOST = "relay.test"


class WireTests(unittest.TestCase):
    def test_strict_wire_and_domain_challenges(self):
        for raw in (
            b'{"v":1,"v":1,"kind":"ping"}',
            b'{"v":true,"kind":"ping"}',
            b'{"v":1,"kind":"ping","extra":0}',
            b'{"v":1,"kind":"ping","x":"\\ud800"}',
            b'{"v":1,"kind":"unknown"}',
            b"[]",
            b"\xff",
            b'{"v":1,"kind":"challenge","nonce":"' + b"A" * 42 + b'B"}',
            b'{"v":1,"kind":"ping","nested":{"x":0,"x":1}}',
        ):
            with self.subTest(raw=raw), self.assertRaises(RelayError):
                decode_frame(raw)
        for invalid_limit in (0, 8193, True):
            with self.assertRaises(RelayError):
                encode_frame({"v": 1, "kind": "ping"}, invalid_limit)
        nonce = b"n" * 32
        self.assertNotEqual(
            challenge("register", "relay.test", nonce),
            challenge("attach", "relay.test", nonce, b"p" * 32),
        )
        with self.assertRaises(RelayError):
            challenge("arbitrary", "relay.test", nonce)

    def test_identity_is_der_bound_and_signer_is_domain_limited(self):
        key, cert = make_certificate("pc.test")
        calls = []
        pc = RelayIdentity(
            cert.public_bytes(serialization.Encoding.DER),
            lambda message: (
                calls.append(message) or key.sign(message, ec.ECDSA(hashes.SHA256()))
            ),
        )
        expected = (
            base64.b32encode(hashlib.sha256(pc.certificate_der).digest())
            .decode()
            .lower()
            .rstrip("=")
        )
        self.assertEqual(pc.namespace, expected)
        pc.proof("register", HOST, b"n" * 32)
        self.assertEqual(
            calls, [b"clarify-computer-relay\0v1\0register\0relay.test\0" + b"n" * 32]
        )
        with self.assertRaises(RelayError):
            pc.proof("sign arbitrary bytes", HOST, b"n" * 32)
        self.assertEqual(len(calls), 1)
        for host in (
            "RELAY.test",
            "127.0.0.1",
            "bad..test",
            "x.test/",
            "a." + "x" * 64,
        ):
            with self.subTest(host=host), self.assertRaises(RelayError):
                dns_name(host)
        _, other = make_certificate("bad.test", curve=ec.SECP384R1())
        with self.assertRaises(RelayError):
            namespace(other.public_bytes(serialization.Encoding.DER))
        with self.assertRaisesRegex(RelayError, "identity_proof_failed"):
            RelayIdentity(
                pc.certificate_der,
                lambda _: (_ for _ in ()).throw(ValueError("PRIVATE")),
            ).proof("register", HOST, b"n" * 32)

    def test_import_has_no_profile_database_network_or_thread_effects(self):
        root = str(Path(__file__).resolve().parents[2])
        code = """
import asyncio, ssl, socket, sqlite3, threading, pathlib, sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
with patch('builtins.open', side_effect=AssertionError('file')), \\
     patch.object(pathlib.Path, 'open', side_effect=AssertionError('path')), \\
     patch.object(sqlite3, 'connect', side_effect=AssertionError('db')), \\
     patch.object(socket, 'socket', side_effect=AssertionError('network')), \\
     patch.object(threading.Thread, 'start', side_effect=AssertionError('thread')):
    import computer_relay_protocol, computer_relay_client, computer_relay_server
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", code, root],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])


class BudgetTests(unittest.TestCase):
    def test_pessimistic_restart_exhaustion_and_utc_rollover(self):
        now = [datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.db"
            budget = EgressBudget(path, 100, 64, clock=lambda: now[0])
            budget.consume(1)  # 64 bytes are committed, not just the one written.
            self.assertEqual(
                budget.db.execute("SELECT reserved FROM months").fetchone(), (64,)
            )
            budget.close()
            budget = EgressBudget(path, 100, 64, clock=lambda: now[0])
            budget.consume(36)
            with self.assertRaisesRegex(RelayError, "budget_exhausted"):
                budget.consume(1)
            now[0] += timedelta(minutes=2)
            budget.consume(100)
            now[0] -= timedelta(minutes=2)
            with self.assertRaisesRegex(RelayError, "budget_clock"):
                budget.consume(1)
            budget.close()

    def test_shared_reservations_and_foreign_newer_database_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.db"
            first = EgressBudget(path, 100, 60)
            second = EgressBudget(path, 100, 60)
            first.consume(60)
            second.consume(40)
            with self.assertRaises(RelayError):
                first.consume(1)
            first.close()
            second.close()
            with closing(sqlite3.connect(path)) as db:
                db.execute("PRAGMA user_version=2")
            before = path.read_bytes()
            with self.assertRaises(RelayError):
                EgressBudget(path, 100, 60)
            self.assertEqual(path.read_bytes(), before)
            foreign = Path(directory) / "foreign.db"
            with closing(sqlite3.connect(foreign)) as db:
                db.execute("CREATE TABLE important (data TEXT)")
                db.execute("INSERT INTO important VALUES ('preserve')")
                db.commit()
            before = foreign.read_bytes()
            with self.assertRaises(RelayError):
                EgressBudget(foreign, 100, 60)
            self.assertEqual(foreign.read_bytes(), before)
            empty = Path(directory) / "empty.db"
            empty.touch()
            with self.assertRaises(RelayError):
                EgressBudget(empty, 100, 60)
            self.assertEqual(empty.read_bytes(), b"")


class ClientAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_overflow_is_bounded_and_replayed_overflow_id_is_rejected(self):
        key, cert = make_certificate("pc.test")
        pc = identity(key, cert)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        client = ComputerRelayClient(
            HOST,
            pc,
            1,
            ssl_context=context,
            limits=Limits(streams_per_host=2, max_pending=1),
        )
        reader = asyncio.StreamReader()
        control = mock.Mock(read=reader.read, write=mock.AsyncMock())
        started, barrier = asyncio.Queue(), asyncio.Event()
        releases = {}

        async def attach(pending, deadline):
            self.assertGreater(deadline, asyncio.get_running_loop().time())
            releases[pending] = asyncio.Event()
            started.put_nowait(pending)
            await releases[pending].wait()

        async def observed_read(stream, maximum):
            message = await read_frame(stream, maximum)
            if message["kind"] == "pong":
                barrier.set()
            return message

        def send(message):
            reader.feed_data(encode_frame({"v": 1, **message}))

        async def read_barrier():
            barrier.clear()
            send({"kind": "pong"})
            await asyncio.wait_for(barrier.wait(), 2)

        send({"kind": "challenge", "nonce": token(b"n" * 32)})
        send({"kind": "registered", "namespace": pc.namespace})
        ids = [token(bytes([index]) * 32) for index in range(8)]
        with (
            mock.patch.object(client, "_dial", mock.AsyncMock(return_value=control)),
            mock.patch.object(client, "_attach", attach),
            mock.patch("computer_relay_client.read_frame", observed_read),
        ):
            session = asyncio.create_task(client._session())
            try:
                for pending in ids[:2]:
                    send({"kind": "open", "pending": pending})
                    self.assertEqual(await asyncio.wait_for(started.get(), 2), pending)
                for pending in ids[2:]:
                    send({"kind": "open", "pending": pending})
                await read_barrier()
                self.assertTrue(client.connected)
                self.assertFalse(session.done())
                self.assertEqual(len(client._children), 2)
                releases[ids[0]].set()
                self.assertEqual(await asyncio.wait_for(started.get(), 2), ids[2])
                releases[ids[1]].set()
                await eventually(lambda: len(client._children) == 1)
                self.assertTrue(started.empty())
                # An ID rejected for capacity still belongs to replay memory.
                send({"kind": "open", "pending": ids[3]})
                with self.assertRaisesRegex(RelayError, "invalid_open"):
                    await asyncio.wait_for(session, 2)
                self.assertEqual(client._children, set())
                control.close.assert_called_once()
            finally:
                session.cancel()
                await asyncio.gather(session, return_exceptions=True)


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_silent_backend_covers_mobile_deadline_on_both_relay_ends(self):
        class MemoryStream:
            def __init__(self):
                self.reader = asyncio.StreamReader()

            async def read(self, size):
                return await self.reader.read(size)

            async def write(self, data):
                self.peer.reader.feed_data(data)

            async def finish(self):
                self.peer.reader.feed_eof()

        def pair():
            left, right = MemoryStream(), MemoryStream()
            left.peer, right.peer = right, left
            return left, right

        phone, server_phone = pair()
        server_data, desktop_data = pair()
        desktop_local, backend = pair()
        now, sleepers, checkpoints = [0.0], [], asyncio.Queue()

        async def clock_sleep(delay):
            future = asyncio.get_running_loop().create_future()
            sleepers.append(future)
            checkpoints.put_nowait((now[0], delay))
            await future

        controlled = mock.Mock(wraps=asyncio)
        controlled.FIRST_COMPLETED = asyncio.FIRST_COMPLETED
        controlled.get_running_loop.return_value = SimpleNamespace(time=lambda: now[0])
        controlled.sleep.side_effect = clock_sleep
        with mock.patch("computer_relay_protocol.asyncio", controlled):
            tasks = [
                asyncio.create_task(bridge(server_phone, server_data, Limits())),
                asyncio.create_task(bridge(desktop_data, desktop_local, Limits())),
            ]
            checked = None
            try:
                await phone.write(b"uploaded request")
                self.assertEqual(
                    await asyncio.wait_for(backend.read(16384), 2), b"uploaded request"
                )
                await asyncio.wait_for(checkpoints.get(), 2)
                await asyncio.wait_for(checkpoints.get(), 2)
                # The backend is silent for the mobile's full 100 seconds plus
                # five seconds of transit. Wake both watchdogs on that clock.
                now[0] = 105.0
                for future in sleepers:
                    future.set_result(None)
                sleepers.clear()

                async def both_checked():
                    for _ in tasks:
                        when, remaining = await checkpoints.get()
                        self.assertEqual(when, 105.0)
                        self.assertGreater(remaining, 0)

                checked = asyncio.create_task(both_checked())
                done, _ = await asyncio.wait(
                    [*tasks, checked], timeout=2, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    task.result()
                self.assertIn(checked, done)
                await backend.write(b"processed response")
                self.assertEqual(
                    await asyncio.wait_for(phone.read(16384), 2), b"processed response"
                )
                # Silence still has a finite bound on each relay end.
                now[0] = 226.0
                for future in sleepers:
                    future.set_result(None)
                done, waiting = await asyncio.wait(tasks, timeout=2)
                self.assertFalse(waiting)
                for task in tasks:
                    with self.assertRaises(TimeoutError):
                        task.result()
            finally:
                for task in [*tasks, *([checked] if checked else [])]:
                    task.cancel()
                await asyncio.gather(
                    *tasks, *([checked] if checked else []), return_exceptions=True
                )


class LoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        ca_key, self.ca = make_certificate("test CA", is_ca=True)
        key, cert = make_certificate(HOST, ca=self.ca, ca_key=ca_key)
        self.public_context = server_context(self.root, "relay", key, cert)
        self.control_context = client_context(self.ca)
        self.limits = Limits(
            handshake_timeout=1.0,
            setup_timeout=1.5,
            idle_timeout=3.0,
            heartbeat_interval=0.2,
        )
        self.server = None
        self.clients, self.streams, self.pc_servers, self.pc_tasks, self.pc_writers = (
            [],
            [],
            [],
            set(),
            set(),
        )
        self.pc_bytes = 0
        self.loop_errors = []
        self.old_exception_handler = asyncio.get_running_loop().get_exception_handler()
        asyncio.get_running_loop().set_exception_handler(
            lambda _loop, context: self.loop_errors.append(context)
        )
        await self.start_relay()

    async def start_relay(self, *, limits=None, cap=100_000_000):
        if self.server:
            await self.server.stop()
        self.server = ComputerRelayServer(
            "127.0.0.1",
            0,
            HOST,
            self.public_context,
            self.root / "budget.db",
            cap,
            limits=limits or self.limits,
        )
        await self.server.start()

    async def asyncTearDown(self):
        for client in self.clients:
            self.assertTrue(await asyncio.to_thread(client.stop, 3.0), client.status)
        for stream in self.streams:
            stream.close()
        await self.server.stop()
        for server in self.pc_servers:
            server.close()
            await server.wait_closed()
        for writer in tuple(self.pc_writers):
            writer.transport.abort()
        for task in tuple(self.pc_tasks):
            task.cancel()
        await asyncio.gather(*tuple(self.pc_tasks), return_exceptions=True)
        await asyncio.sleep(0)
        self.assertEqual(self.server.status["connections"], 0)
        self.assertEqual(self.server.status["tasks"], 0)
        asyncio.get_running_loop().set_exception_handler(self.old_exception_handler)
        self.assertEqual(self.loop_errors, [])

    async def pc(self, name="pc.test", *, tls12=False):
        key, cert = make_certificate(name)
        pc = identity(key, cert)

        async def respond(reader, writer):
            task = asyncio.current_task()
            self.pc_tasks.add(task)
            self.pc_writers.add(writer)
            try:
                request = await reader.readuntil(b"\r\n\r\n")
                if b"/flood " in request:
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 67108864\r\n\r\n")
                    for _ in range(4096):
                        if writer.is_closing():
                            break
                        writer.write(b"x" * 16384)
                        await writer.drain()
                        self.pc_bytes += 16384
                        # Process TLS close callbacks even if drain did not yield.
                        await asyncio.sleep(0)
                elif b"/hold " in request:
                    await reader.read()
                elif b"/echo " in request:
                    while data := await reader.read(16384):
                        writer.write(data)
                        await writer.drain()
                elif b"/pulse " in request:
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\n")
                    for value in b"01234567":
                        writer.write(bytes([value]))
                        await writer.drain()
                        await asyncio.sleep(0.2)
                else:
                    body = (
                        name.encode()
                        + b":"
                        + request.split(b"X-Private: ")[1].split(b"\r\n")[0]
                    )
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Length: "
                        + str(len(body)).encode()
                        + b"\r\n\r\n"
                        + body
                    )
                    await writer.drain()
            except (OSError, asyncio.IncompleteReadError):
                pass
            finally:
                writer.close()
                with suppress(OSError, TimeoutError):
                    await asyncio.wait_for(writer.wait_closed(), 0.5)
                self.pc_tasks.discard(task)
                self.pc_writers.discard(writer)

        context = server_context(self.root, name, key, cert)
        if tls12:
            context.maximum_version = ssl.TLSVersion.TLSv1_2
        server = await asyncio.start_server(
            respond,
            "127.0.0.1",
            0,
            ssl=context,
            ssl_handshake_timeout=1.0,
            limit=16384,
        )
        self.pc_servers.append(server)
        return pc, cert, server.sockets[0].getsockname()[1]

    def connector(self, pc, port, **kwargs):
        client = ComputerRelayClient(
            HOST,
            pc,
            port,
            relay_port=self.server.address[1],
            fixture_address="127.0.0.1",
            fixture_ssl_context=self.control_context,
            limits=self.limits,
            reconnect_initial=0.05,
            reconnect_max=0.1,
            **kwargs,
        )
        self.clients.append(client)
        client.start()
        return client

    async def control(self, pc=None, *, proof=None):
        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            self.server.address[1],
            ssl=self.control_context,
            server_hostname=HOST,
            ssl_handshake_timeout=1.0,
            limit=16384,
        )
        stream = Stream(reader, writer, self.limits)
        self.streams.append(stream)
        hello = await asyncio.wait_for(read_frame(stream), 2)
        if pc is not None:
            signature = proof or pc.proof("register", HOST, untoken(hello["nonce"]))
            message = {
                "v": 1,
                "kind": "register",
                "certificate": base64.b64encode(pc.certificate_der).decode(),
                "signature": signature,
            }
            await stream.write(encode_frame(message))
            return stream, message
        return stream, hello

    async def phone(self, pc, cert, *, sni=None):
        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            self.server.address[1],
            ssl=client_context(cert, check_hostname=False),
            server_hostname=sni or pc.namespace + "." + HOST,
            ssl_handshake_timeout=2,
            limit=16384,
        )
        stream = Stream(reader, writer, self.limits)
        self.streams.append(stream)
        self.assertEqual(
            writer.get_extra_info("ssl_object").getpeercert(binary_form=True),
            pc.certificate_der,
        )
        return stream

    async def test_two_desktops_real_leaf_passthrough_and_private_marker(self):
        pc1, cert1, port1 = await self.pc("one.test")
        pc2, cert2, port2 = await self.pc("two.test")
        clients = [self.connector(pc1, port1), self.connector(pc2, port2)]
        await eventually(lambda: all(client.connected for client in clients))
        marker = ("private-" + secrets.token_hex(32)).encode()
        observed = []
        original = _TLS.read

        async def observed_read(channel, size):
            data = await original(channel, size)
            observed.append(data)
            return data

        with mock.patch.object(_TLS, "read", observed_read):
            for pc, cert, name in (
                (pc1, cert1, b"one.test"),
                (pc2, cert2, b"two.test"),
            ):
                phone = await self.phone(pc, cert)
                await phone.write(
                    b"GET / HTTP/1.1\r\nX-Private: " + marker + b"\r\n\r\n"
                )
                response = bytearray()
                async with asyncio.timeout(3):
                    while chunk := await phone.read(16384):
                        response.extend(chunk)
                self.assertIn(name + b":" + marker, response)
        self.assertNotIn(marker, b"".join(observed))
        await eventually(lambda: self.server.status["tunnels"] == 0)

    async def test_registration_requires_fresh_proof_and_does_not_displace_owner(self):
        pc, _, _ = await self.pc()
        valid, message = await self.control(pc)
        self.assertEqual((await read_frame(valid))["kind"], "registered")
        replay, _ = await self.control(pc, proof=message["signature"])
        with self.assertRaises((RelayError, OSError)):
            await asyncio.wait_for(read_frame(replay), 2)
        self.assertEqual(self.server.status["hosts"], 1)
        other_key, other_cert = make_certificate("attacker.test")
        other = identity(other_key, other_cert)
        wrong, hello = await self.control()
        await wrong.write(
            encode_frame(
                {
                    **message,
                    "signature": other.proof("register", HOST, untoken(hello["nonce"])),
                }
            )
        )
        with self.assertRaises((RelayError, OSError)):
            await asyncio.wait_for(read_frame(wrong), 2)
        self.assertEqual(self.server.status["hosts"], 1)
        await valid.write(encode_frame({"v": 1, "kind": "ping"}))
        self.assertEqual((await read_frame(valid))["kind"], "pong")

    async def test_attach_proof_one_use_stale_generation_and_owner_replacement(self):
        pc, cert, _ = await self.pc()
        owner, _ = await self.control(pc)
        await read_frame(owner)
        phone_task = asyncio.create_task(self.phone(pc, cert))
        pending = (await asyncio.wait_for(read_frame(owner), 2))["pending"]
        wrong, hello = await self.control()
        # Valid signature, wrong purpose. The pending ID must remain usable.
        await wrong.write(
            encode_frame(
                {
                    "v": 1,
                    "kind": "attach",
                    "pending": pending,
                    "signature": pc.proof("register", HOST, untoken(hello["nonce"])),
                }
            )
        )
        with self.assertRaises((RelayError, OSError)):
            await asyncio.wait_for(read_frame(wrong), 2)
        abandoned, hello = await self.control()
        replayed_proof = pc.proof(
            "attach", HOST, untoken(hello["nonce"]), untoken(pending)
        )
        abandoned.close()
        replayed, _ = await self.control()
        await replayed.write(
            encode_frame(
                {
                    "v": 1,
                    "kind": "attach",
                    "pending": pending,
                    "signature": replayed_proof,
                }
            )
        )
        with self.assertRaises((RelayError, OSError)):
            await asyncio.wait_for(read_frame(replayed), 2)
        attached, hello = await self.control()
        proof = pc.proof("attach", HOST, untoken(hello["nonce"]), untoken(pending))
        await attached.write(
            encode_frame(
                {"v": 1, "kind": "attach", "pending": pending, "signature": proof}
            )
        )
        self.assertEqual((await read_frame(attached))["kind"], "attached")
        duplicate, hello = await self.control()
        await duplicate.write(
            encode_frame(
                {
                    "v": 1,
                    "kind": "attach",
                    "pending": pending,
                    "signature": pc.proof(
                        "attach", HOST, untoken(hello["nonce"]), untoken(pending)
                    ),
                }
            )
        )
        with self.assertRaises((RelayError, OSError)):
            await asyncio.wait_for(read_frame(duplicate), 2)
        # Replace owner while an attached phone has not completed its inner TLS.
        newer, _ = await self.control(pc)
        await read_frame(newer)
        with self.assertRaises((OSError, RelayError)):
            await phone_task
        await eventually(lambda: self.server.status["tunnels"] == 0)
        self.assertEqual(self.server.status["hosts"], 1)
        stale, hello = await self.control()
        await stale.write(
            encode_frame(
                {
                    "v": 1,
                    "kind": "attach",
                    "pending": pending,
                    "signature": pc.proof(
                        "attach", HOST, untoken(hello["nonce"]), untoken(pending)
                    ),
                }
            )
        )
        with self.assertRaises((RelayError, OSError)):
            await asyncio.wait_for(read_frame(stale), 2)
        await newer.write(encode_frame({"v": 1, "kind": "ping"}))
        self.assertEqual((await read_frame(newer))["kind"], "pong")

    async def test_unknown_sni_untrusted_control_and_oversized_frame_fail_closed(self):
        pc, cert, _ = await self.pc()
        for sni in (pc.namespace + "." + HOST, "wrong.test", "x." + HOST):
            with self.subTest(sni=sni), self.assertRaises(OSError):
                await self.phone(pc, cert, sni=sni)
        # Public control trust is never disabled, even with a known relay address.
        untrusted = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with self.assertRaises(ssl.SSLCertVerificationError):
            await asyncio.open_connection(
                "127.0.0.1", self.server.address[1], ssl=untrusted, server_hostname=HOST
            )
        control, _ = await self.control()
        await control.write((8193).to_bytes(4, "big"))
        with self.assertRaises((RelayError, OSError)):
            await asyncio.wait_for(read_frame(control), 2)
        insecure = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        insecure.check_hostname = False
        insecure.verify_mode = ssl.CERT_NONE
        with self.assertRaises(RelayError):
            ComputerRelayClient(HOST, pc, 1, ssl_context=insecure)
        with self.assertRaises(RelayError):
            ComputerRelayClient(HOST, pc, 1, fixture_address="192.0.2.1")

    async def test_handshake_host_and_stream_bounds_release_capacity(self):
        await self.start_relay(
            limits=replace(
                self.limits,
                max_handshakes=2,
                connections_per_ip=2,
                max_hosts=1,
                streams_per_host=1,
            )
        )
        raw = []
        for _ in range(3):
            reader, writer = await asyncio.open_connection(*self.server.address)
            raw.append((reader, writer))
        await eventually(lambda: self.server.handshakes == 2)
        self.assertLessEqual(self.server.status["connections"], 2)
        self.assertEqual(await asyncio.wait_for(raw[-1][0].read(1), 1), b"")
        for _, writer in raw:
            writer.transport.abort()
        await eventually(lambda: self.server.handshakes == 0)
        pc1, cert1, _ = await self.pc("one.test")
        pc2, _, _ = await self.pc("two.test")
        owner, _ = await self.control(pc1)
        await read_frame(owner)
        rejected, _ = await self.control(pc2)
        with self.assertRaises((RelayError, OSError)):
            await read_frame(rejected)
        first = asyncio.create_task(self.phone(pc1, cert1))
        await read_frame(
            owner
        )  # open; hold pending until setup timeout or control close
        with self.assertRaises(OSError):
            await self.phone(pc1, cert1)
        self.assertEqual(self.server.status["pending"], 1)
        owner.close()
        with self.assertRaises(OSError):
            await first
        await eventually(lambda: self.server.status["tunnels"] == 0)

    async def test_fragmented_clienthello_tls12_and_original_byte_replay(self):
        self.public_context.maximum_version = ssl.TLSVersion.TLSv1_2
        pc, cert, port = await self.pc(tls12=True)
        client = self.connector(pc, port)
        await eventually(lambda: client.connected)
        incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        context = client_context(cert, check_hostname=False)
        obj = context.wrap_bio(
            incoming,
            outgoing,
            server_side=False,
            server_hostname=pc.namespace + "." + HOST,
        )
        reader, writer = await asyncio.open_connection(*self.server.address)
        raw = Stream(reader, writer, self.limits)
        self.streams.append(raw)
        first = True
        async with asyncio.timeout(4):
            while True:
                try:
                    obj.do_handshake()
                    break
                except ssl.SSLWantReadError:
                    wire = outgoing.read()
                    if first:
                        # Split the TLS header/hello, without making scheduler
                        # latency across dozens of tiny writes the test oracle.
                        await raw.write(wire[:7])
                        await asyncio.sleep(0)
                        for offset in range(7, len(wire), 97):
                            await raw.write(wire[offset : offset + 97])
                            await asyncio.sleep(0)
                        first = False
                    else:
                        await raw.write(wire)
                    data = await raw.read(16384)
                    self.assertTrue(data)
                    incoming.write(data)
            if outgoing.pending:
                await raw.write(outgoing.read())
            self.assertEqual(obj.version(), "TLSv1.2")
            self.assertEqual(obj.getpeercert(binary_form=True), pc.certificate_der)
            obj.write(b"GET / HTTP/1.1\r\nX-Private: fragmented\r\n\r\n")
            await raw.write(outgoing.read())
            response = bytearray()
            while b"pc.test:fragmented" not in response:
                try:
                    response.extend(obj.read(16384))
                except ssl.SSLWantReadError:
                    data = await raw.read(16384)
                    self.assertTrue(data)
                    incoming.write(data)

    async def test_incomplete_tls_preface_expires(self):
        await self.start_relay(limits=replace(self.limits, handshake_timeout=0.2))
        reader, writer = await asyncio.open_connection(*self.server.address)
        self.streams.append(Stream(reader, writer, self.limits))
        writer.write(b"\x16\x03")
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.read(1), 1), b"")
        await eventually(lambda: self.server.status["connections"] == 0)

    async def test_pending_setup_expires_without_an_attachment(self):
        pc, cert, _ = await self.pc()
        owner, _ = await self.control(pc)
        await read_frame(owner)
        # Arm the attachment deadline after the control has registered.
        self.server.limits = replace(self.limits, setup_timeout=0.25)
        pending_phone = asyncio.create_task(self.phone(pc, cert))
        self.assertEqual((await read_frame(owner))["kind"], "open")
        with self.assertRaises(OSError) as closed:
            await asyncio.wait_for(pending_phone, 1)
        self.assertNotIsInstance(closed.exception, TimeoutError)
        await eventually(lambda: self.server.status["pending"] == 0, timeout=1)
        self.assertEqual(self.server.status["hosts"], 1)

    async def test_registered_control_expires_without_another_ping(self):
        pc, _, _ = await self.pc()
        owner, _ = await self.control(pc)
        await read_frame(owner)
        self.server.limits = replace(self.limits, idle_timeout=0.4)
        # The pong acknowledges a healthy control and starts its next idle wait.
        await owner.write(encode_frame({"v": 1, "kind": "ping"}))
        self.assertEqual((await read_frame(owner))["kind"], "pong")
        await eventually(lambda: self.server.status["hosts"] == 0, timeout=1)
        await eventually(lambda: self.server.status["connections"] == 0)

    async def test_oversized_tls_preface_is_rejected(self):
        await self.start_relay(limits=replace(self.limits, preface_bytes=1024))
        pc, cert, _ = await self.pc()
        padded = client_context(cert, check_hostname=False)
        padded.set_alpn_protocols([str(index) + "x" * 250 for index in range(8)])
        with self.assertRaises(OSError):
            await asyncio.open_connection(
                *self.server.address,
                ssl=padded,
                server_hostname=pc.namespace + "." + HOST,
                ssl_handshake_timeout=1,
            )
        self.assertEqual(self.server.last_error, "preface_limit")

    async def test_ip_admission_limit_rejects_the_next_connection(self):
        await self.start_relay(limits=replace(self.limits, admissions_per_ip_minute=2))
        for _ in range(2):
            reader, writer = await asyncio.open_connection(*self.server.address)
            writer.transport.abort()
            await eventually(lambda: self.server.status["connections"] == 0)
        reader, writer = await asyncio.open_connection(*self.server.address)
        self.streams.append(Stream(reader, writer, self.limits))
        self.assertEqual(await asyncio.wait_for(reader.read(1), 1), b"")
        self.assertEqual(self.server.status["connections"], 0)

    async def test_server_shutdown_cancels_active_and_pending_streams(self):
        pc, cert, port = await self.pc()
        client = self.connector(pc, port)
        await eventually(lambda: client.connected)
        phone = await self.phone(pc, cert)
        await phone.write(b"GET /hold HTTP/1.1\r\n\r\n")
        other, other_cert, _ = await self.pc("pending.test")
        control, _ = await self.control(other)
        await read_frame(control)
        pending = asyncio.create_task(self.phone(other, other_cert))
        await read_frame(control)
        self.assertEqual(self.server.status["tunnels"], 2)
        await self.server.stop()
        with self.assertRaises(OSError):
            await pending
        self.assertEqual(await asyncio.wait_for(phone.read(1), 1), b"")
        await eventually(lambda: not client.connected)
        self.assertEqual(self.server.status["hosts"], 0)
        self.assertEqual(self.server.status["pending"], 0)
        self.assertEqual(self.server.status["tunnels"], 0)

    async def test_one_way_activity_keeps_tunnel_alive_past_idle_period(self):
        self.limits = replace(
            self.limits, tunnel_idle_timeout=1.0, heartbeat_interval=0.1
        )
        await self.start_relay(limits=self.limits)
        pc, cert, port = await self.pc()
        client = self.connector(pc, port)
        await eventually(lambda: client.connected)
        phone = await self.phone(pc, cert)
        await phone.write(b"GET /pulse HTTP/1.1\r\n\r\n")
        response = bytearray()
        async with asyncio.timeout(3):
            while chunk := await phone.read(16384):
                response.extend(chunk)
        self.assertTrue(response.endswith(b"01234567"), response)

    async def _closing_child_capacity_case(self, *, release_before_deadline):
        # Observe reads from session start, including the read already waiting
        # when the server releases and reuses its slot.
        open_received = asyncio.Event()
        loop = asyncio.get_running_loop()

        async def observe_open(stream, maximum):
            message = await read_frame(stream, maximum)
            if message["kind"] == "open":
                loop.call_soon_threadsafe(open_received.set)
            return message

        patcher = mock.patch("computer_relay_client.read_frame", observe_open)
        patcher.start()
        self.addCleanup(patcher.stop)
        pc, cert, port = await self.pc()
        client = self.connector(pc, port)
        await eventually(lambda: client.connected)
        owner = self.server.owners[pc.namespace]
        phones = [await self.phone(pc, cert) for _ in range(4)]

        async def echo(phone):
            await phone.write(b"still-active")
            self.assertEqual(
                await asyncio.wait_for(phone.reader.readexactly(12), 2), b"still-active"
            )

        for phone in phones:
            await phone.write(b"GET /echo HTTP/1.1\r\n\r\n")
            await echo(phone)
        open_received.clear()
        entered = asyncio.Event()
        release = None
        held_loop = None
        finish = Stream.finish

        async def hold_one_finish(stream):
            nonlocal release, held_loop
            if asyncio.get_running_loop() is client._loop and release is None:
                held_loop = asyncio.get_running_loop()
                release = asyncio.Event()
                loop.call_soon_threadsafe(entered.set)
                await release.wait()
            await finish(stream)

        replacement = None
        with mock.patch.object(Stream, "finish", hold_one_finish):
            try:
                phones[0].close()
                await asyncio.wait_for(entered.wait(), 2)
                await eventually(lambda: owner.streams == 3)
                self.assertEqual(len(client._children), 4)
                replacement = asyncio.create_task(self.phone(pc, cert))
                await asyncio.wait_for(open_received.wait(), 2)
                if release_before_deadline:
                    held_loop.call_soon_threadsafe(release.set)
                    phone = await asyncio.wait_for(replacement, 3)
                    await phone.write(b"GET /echo HTTP/1.1\r\n\r\n")
                    await echo(phone)
                else:
                    with self.assertRaises(OSError):
                        await asyncio.wait_for(replacement, 3)
                self.assertIs(self.server.owners.get(pc.namespace), owner)
                self.assertTrue(client.connected)
                self.assertLessEqual(len(client._children), 4)
                for phone in phones[1:]:
                    await echo(phone)
                if not release_before_deadline:
                    open_received.clear()
                    replacement = asyncio.create_task(self.phone(pc, cert))
                    await asyncio.wait_for(open_received.wait(), 2)
                    # Shutdown must cancel the held close and a fresh queued ID.
                    self.assertTrue(await asyncio.to_thread(client.stop, 2))
                    with self.assertRaises(OSError):
                        await asyncio.wait_for(replacement, 2)
                    self.assertEqual(client._children, set())
                    self.assertEqual(client._streams, set())
            finally:
                if release is not None and held_loop.is_running():
                    held_loop.call_soon_threadsafe(release.set)
                if replacement:
                    replacement.cancel()
                    await asyncio.gather(replacement, return_exceptions=True)

    async def test_server_slot_reuse_waits_for_closing_child_without_dropping_others(
        self,
    ):
        await self._closing_child_capacity_case(release_before_deadline=True)

    async def test_persistent_local_capacity_lag_expires_only_new_request_and_can_stop(
        self,
    ):
        await self._closing_child_capacity_case(release_before_deadline=False)

    async def test_accept_cancelled_before_first_task_step_releases_admission(self):
        create_task = asyncio.create_task

        def cancel_at_creation(coroutine, *args, **kwargs):
            task = create_task(coroutine, *args, **kwargs)
            if coroutine.__qualname__ == "ComputerRelayServer._connection":
                task.cancel()
            return task

        with mock.patch(
            "computer_relay_server.asyncio.create_task", cancel_at_creation
        ):
            reader, writer = await asyncio.open_connection(*self.server.address)
            self.streams.append(Stream(reader, writer, self.limits))
            await asyncio.sleep(0.05)
        self.assertEqual(self.server.status["connections"], 0)
        self.assertEqual(self.server.status["handshakes"], 0)
        self.assertEqual(self.server.ip_counts, {})

    async def test_stop_waits_for_completed_connection_admission_release(self):
        async def complete(_stream):
            return

        writer = mock.Mock()
        writer.get_extra_info.return_value = ("127.0.0.1", 47100)
        with mock.patch.object(self.server, "_connection", complete):
            self.server._accept(mock.Mock(), writer)
            task = next(iter(self.server.tasks))
            # Finish the connection task, leaving its registered done callback
            # queued for the next loop turn. This is not a wall-clock delay.
            await asyncio.sleep(0)
            self.assertTrue(task.done())
            self.assertIn(task, self.server.tasks)
            await self.server.stop()
        self.assertEqual(self.server.status["connections"], 0)
        self.assertEqual(self.server.status["tasks"], 0)
        self.assertEqual(self.server.ip_counts, {})

    async def test_stop_during_listener_start_cannot_leave_unmetered_listener(self):
        await self.server.stop()
        entered, release = asyncio.Event(), asyncio.Event()
        start_server = asyncio.start_server

        async def delayed_start(*args, **kwargs):
            entered.set()
            await release.wait()
            return await start_server(*args, **kwargs)

        with mock.patch("computer_relay_server.asyncio.start_server", delayed_start):
            starting = asyncio.create_task(self.server.start())
            await entered.wait()
            stopping = asyncio.create_task(self.server.stop())
            try:
                await asyncio.sleep(0.02)
                self.assertFalse(stopping.done())
            finally:
                release.set()
                await starting
                await stopping
        self.assertIsNone(self.server.address)
        self.assertIsNone(self.server.budget)
        entered = asyncio.Event()
        start_serving = asyncio.Server.start_serving

        async def pause_after_bind(listener):
            await start_serving(listener)
            entered.set()
            await asyncio.Event().wait()

        with mock.patch.object(asyncio.Server, "start_serving", pause_after_bind):
            starting = asyncio.create_task(self.server.start())
            await entered.wait()
            self.assertIsNotNone(self.server.address)
            starting.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await starting
        self.assertIsNone(self.server.address)
        self.assertIsNone(self.server.budget)

    async def test_backpressure_control_disconnect_and_full_stop_drain(self):
        pc, cert, port = await self.pc()
        client = self.connector(pc, port)
        await eventually(lambda: client.connected)
        phone = await self.phone(pc, cert)
        await phone.write(b"GET /flood HTTP/1.1\r\n\r\n")
        await eventually(lambda: self.pc_bytes >= 32768)
        await asyncio.sleep(0.3)
        self.assertLess(self.pc_bytes, 64 * 1024 * 1024)
        self.assertTrue(self.server.status["tunnels"])
        for raw in self.server.sockets:
            self.assertLessEqual(
                raw.writer.transport.get_write_buffer_size(),
                self.limits.buffer_bytes * 3,
            )
            # asyncio may receive one transport chunk beyond its pause threshold.
            self.assertLessEqual(
                len(raw.reader._buffer), 2 * self.limits.buffer_bytes + 262144
            )
        self.assertTrue(await asyncio.to_thread(client.stop, 3))
        await eventually(
            lambda: (
                self.server.status["tunnels"] == 0 and self.server.status["hosts"] == 0
            )
        )
        await self.server.stop()
        self.assertEqual(self.server.status["connections"], 0)
        self.assertEqual(self.server.status["tasks"], 0)
        self.assertFalse(client.connected)
        self.assertEqual(client.status, "stopped")

    async def test_live_budget_exhaustion_and_restart_cannot_restore_allowance(self):
        # Replace the empty, task-owned DB to select a smaller immutable cap.
        await self.server.stop()
        (self.root / "budget.db").unlink()
        await self.start_relay(cap=20000)
        pc, cert, port = await self.pc()
        client = self.connector(pc, port)
        await eventually(lambda: client.connected)
        phone = await self.phone(pc, cert)
        await phone.write(b"GET /flood HTTP/1.1\r\n\r\n")
        async with asyncio.timeout(4):
            try:
                while await phone.read(16384):
                    pass
            except OSError:
                pass
        await eventually(lambda: self.server.status["tunnels"] == 0)
        self.assertTrue(await asyncio.to_thread(client.stop, 3))
        await self.server.stop()
        await self.start_relay(cap=20000)
        with self.assertRaises((OSError, RelayError)):
            await self.control()
        with closing(sqlite3.connect(self.root / "budget.db")) as db:
            self.assertEqual(
                db.execute("SELECT reserved FROM months").fetchone(), (20000,)
            )

    async def test_stop_reports_blocked_signer_and_interrupts_reconnect(self):
        pc, _, port = await self.pc()
        entered, release = threading.Event(), threading.Event()

        def blocked_signer(_message):
            entered.set()
            release.wait(5)
            raise ValueError("private callback failure")

        client = self.connector(RelayIdentity(pc.certificate_der, blocked_signer), port)
        try:
            await eventually(entered.is_set)
            self.assertFalse(client.stop(0.01))
            self.assertEqual(client.status, "stop_failed")
            with self.assertRaises(RelayError):
                client.start()
        finally:
            release.set()
        self.assertTrue(await asyncio.to_thread(client.stop, 3))
        stopped_relay_port = self.server.address[1]
        await self.server.stop()
        unavailable = ComputerRelayClient(
            HOST,
            pc,
            port,
            # Retry a stopped listener, not the PC's unrelated TLS endpoint.
            relay_port=stopped_relay_port,
            fixture_address="127.0.0.1",
            fixture_ssl_context=self.control_context,
            limits=self.limits,
            reconnect_initial=30,
            reconnect_max=30,
        )
        self.clients.append(unavailable)
        unavailable.start()
        await eventually(lambda: unavailable.status == "retrying")
        self.assertTrue(await asyncio.to_thread(unavailable.stop, 0.5))


if __name__ == "__main__":
    unittest.main()
