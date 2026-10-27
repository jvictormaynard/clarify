"""Desktop connector primitive. The only backend destination is IPv4 loopback."""

from __future__ import annotations

import asyncio
import base64
from collections import deque
import ipaddress
import random
import socket
import ssl
import threading
import time

from computer_relay_protocol import (
    Limits,
    RelayError,
    RelayIdentity,
    Stream,
    bridge,
    dns_name,
    encode_frame,
    port_number,
    public_client_context,
    read_frame,
    untoken,
    validate_client_context,
)


class ComputerRelayClient:
    """Nonblocking activation with one owned event loop and worker thread.

    stop() returns False if the worker cannot be joined within the deadline.
    A blocked platform DNS lookup or application signer can cause that result.
    The caller must keep the object and retry stop; a new worker is refused.
    No profile, file, secret store or installed backend is accessed here.
    """

    def __init__(
        self,
        relay_host: str,
        identity: RelayIdentity,
        target_port: int,
        *,
        relay_port: int = 443,
        ssl_context: ssl.SSLContext | None = None,
        limits: Limits | None = None,
        reconnect_initial: float = 0.5,
        reconnect_max: float = 30.0,
        fixture_address: str | None = None,
        fixture_ssl_context: ssl.SSLContext | None = None,
    ):
        self.relay_host, self.relay_port = dns_name(relay_host), port_number(relay_port)
        self.target_port = port_number(target_port)
        if not isinstance(identity, RelayIdentity):
            raise RelayError("invalid_identity")
        self.identity, self.limits = (
            identity,
            limits if limits is not None else Limits(),
        )
        if not isinstance(self.limits, Limits):
            raise RelayError("invalid_limits")
        if (
            type(reconnect_initial) not in (int, float)
            or type(reconnect_max) not in (int, float)
            or not 0.05 <= reconnect_initial <= reconnect_max <= 300
        ):
            raise RelayError("invalid_reconnect")
        self.reconnect_initial, self.reconnect_max = reconnect_initial, reconnect_max
        if fixture_address is not None:
            try:
                if (
                    not isinstance(fixture_address, str)
                    or not ipaddress.ip_address(fixture_address).is_loopback
                ):
                    raise ValueError
            except ValueError:
                raise RelayError("invalid_fixture_address") from None
        if fixture_ssl_context is not None and (
            fixture_address is None or ssl_context is not None
        ):
            raise RelayError("invalid_fixture_context")
        self.fixture_address = fixture_address
        selected_context = (
            fixture_ssl_context if fixture_ssl_context is not None else ssl_context
        )
        self.context = validate_client_context(
            selected_context
            if selected_context is not None
            else public_client_context()
        )
        self._lock, self._stop_requested = threading.Lock(), threading.Event()
        self._lifecycle = threading.Lock()
        self._thread = self._loop = self._main_task = None
        self._drained = True
        self._connected, self._status = False, "stopped"
        self._streams, self._children = set(), set()

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def _state(self, status, connected=False):
        with self._lock:
            if connected and self._stop_requested.is_set():
                status, connected = "stopping", False
            self._status, self._connected = status, connected

    def start(self):
        if not self._lifecycle.acquire(blocking=False):
            raise RelayError("lifecycle_busy")
        try:
            self._start()
        finally:
            self._lifecycle.release()

    def _start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop_requested.is_set():
                    raise RelayError("drain_not_confirmed")
                return
            if not self._drained:
                raise RelayError("drain_not_confirmed")
            self._stop_requested.clear()
            self._drained = False
            self._status, self._connected = "connecting", False
            self._thread = threading.Thread(
                target=self._worker, name="computer-relay", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> bool:
        if type(timeout) not in (float, int) or not 0 <= timeout <= 60:
            raise RelayError("invalid_stop_timeout")
        began = time.monotonic()
        if not self._lifecycle.acquire(timeout=timeout):
            self._stop_requested.set()
            self._state("stop_failed")
            return False
        try:
            return self._stop(max(0.0, timeout - (time.monotonic() - began)))
        finally:
            self._lifecycle.release()

    def _stop(self, timeout: float) -> bool:
        if type(timeout) not in (float, int) or not 0 <= timeout <= 60:
            raise RelayError("invalid_stop_timeout")
        self._stop_requested.set()
        with self._lock:
            thread, loop, task = self._thread, self._loop, self._main_task
            self._connected, self._status = False, "stopping"
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass
        if thread is threading.current_thread():
            self._state("stop_failed")
            return False
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                self._state("stop_failed")
                return False
        if not self._drained:
            self._state("stop_failed")
            return False
        self._state("stopped")
        return True

    def _worker(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        task = loop.create_task(self._run())
        with self._lock:
            self._loop, self._main_task = loop, task
        try:
            if self._stop_requested.is_set():
                task.cancel()
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        except Exception:
            self._state("relay_unavailable")
        finally:
            try:
                for stream in tuple(self._streams):
                    stream.close()
                pending = asyncio.all_tasks(loop)
                for item in pending:
                    item.cancel()
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
                loop.run_until_complete(loop.shutdown_asyncgens())
                self._streams.clear()
                self._drained = not asyncio.all_tasks(loop)
            except Exception:
                self._drained = False
            finally:
                loop.close()
            with self._lock:
                self._loop = self._main_task = None
                self._connected = False
                if self._stop_requested.is_set() and self._drained:
                    self._status = "stopped"

    async def _dial(self):
        validate_client_context(self.context)
        # Keep system DNS in the owned worker, rather than creating executor
        # threads whose cancellation could falsely appear to have drained.
        addresses = (
            [(self.fixture_address, self.relay_port)]
            if self.fixture_address
            else [
                entry[4][:2]
                for entry in socket.getaddrinfo(
                    self.relay_host, self.relay_port, type=socket.SOCK_STREAM
                )[:16]
            ]
        )
        for address, port in addresses:
            if self._stop_requested.is_set():
                raise asyncio.CancelledError
            try:
                async with asyncio.timeout(self.limits.setup_timeout):
                    reader, writer = await asyncio.open_connection(
                        address,
                        port,
                        ssl=self.context,
                        server_hostname=self.relay_host,
                        ssl_handshake_timeout=self.limits.handshake_timeout,
                        ssl_shutdown_timeout=0.1,
                        limit=self.limits.buffer_bytes,
                    )
                stream = Stream(reader, writer, self.limits)
                self._streams.add(stream)
                return stream
            except (OSError, TimeoutError):
                continue
        raise RelayError("relay_unavailable")

    async def _hello(self, stream):
        message = await read_frame(stream, self.limits.frame_bytes)
        if message["kind"] != "challenge":
            raise RelayError("invalid_challenge")
        return untoken(message["nonce"])

    async def _heartbeat(self, control):
        while True:
            await asyncio.sleep(self.limits.heartbeat_interval)
            await control.write(encode_frame({"v": 1, "kind": "ping"}))

    async def _attach(self, pending, deadline):
        data = local = None
        try:
            async with asyncio.timeout_at(deadline):
                data = await self._dial()
                nonce = await self._hello(data)
                proof = self.identity.proof(
                    "attach", self.relay_host, nonce, untoken(pending)
                )
                await data.write(
                    encode_frame(
                        {
                            "v": 1,
                            "kind": "attach",
                            "pending": pending,
                            "signature": proof,
                        }
                    )
                )
                ack = await read_frame(data, self.limits.frame_bytes)
                if ack["kind"] != "attached":
                    raise RelayError("invalid_attach_ack")
                reader, writer = await asyncio.open_connection(
                    "127.0.0.1", self.target_port, limit=self.limits.buffer_bytes
                )
                local = Stream(reader, writer, self.limits)
                self._streams.add(local)
            await bridge(data, local, self.limits)
        except asyncio.CancelledError:
            raise
        except Exception:
            # No payload, signer exception, nonce or connection identity is logged.
            pass
        finally:
            for stream in (data, local):
                if stream:
                    stream.close()
                    self._streams.discard(stream)

    async def _session(self):
        control = None
        heartbeat = None
        admission = None
        pending = deque()
        changed = asyncio.Event()
        loop = asyncio.get_running_loop()

        def child_done(child):
            self._children.discard(child)
            changed.set()

        async def admit():
            while True:
                changed.clear()
                while pending:
                    pending_id, deadline = pending[0]
                    if deadline <= loop.time():
                        pending.popleft()
                        continue
                    if len(self._children) >= self.limits.streams_per_host:
                        break
                    pending.popleft()
                    child = asyncio.create_task(self._attach(pending_id, deadline))
                    self._children.add(child)
                    child.add_done_callback(child_done)
                # Expire waiting IDs even if every old child remains in close.
                # No socket or attachment task is allocated for a waiting ID.
                try:
                    async with asyncio.timeout_at(pending[0][1] if pending else None):
                        await changed.wait()
                except TimeoutError:
                    continue

        try:
            async with asyncio.timeout(self.limits.setup_timeout):
                control = await self._dial()
                nonce = await self._hello(control)
                proof = self.identity.proof("register", self.relay_host, nonce)
                await control.write(
                    encode_frame(
                        {
                            "v": 1,
                            "kind": "register",
                            "certificate": base64.b64encode(
                                self.identity.certificate_der
                            ).decode("ascii"),
                            "signature": proof,
                        },
                        self.limits.frame_bytes,
                    )
                )
                ack = await read_frame(control, self.limits.frame_bytes)
                if (
                    ack["kind"] != "registered"
                    or ack["namespace"] != self.identity.namespace
                ):
                    raise RelayError("invalid_registration_ack")
            self._state("connected", True)
            heartbeat = asyncio.create_task(self._heartbeat(control))
            admission = asyncio.create_task(admit())
            seen = set()
            while True:
                message = await asyncio.wait_for(
                    read_frame(control, self.limits.frame_bytes),
                    self.limits.idle_timeout,
                )
                if heartbeat.done():
                    heartbeat.result()
                if admission.done():
                    admission.result()
                if message["kind"] == "pong":
                    continue
                if message["kind"] != "open":
                    raise RelayError("invalid_control")
                if message["pending"] in seen:
                    raise RelayError("invalid_open")
                # Replay memory is bounded by a control-session lifetime. Rotate
                # the session after 4096 streams rather than forgetting old IDs.
                if len(seen) >= 4096:
                    raise RelayError("session_rotation")
                seen.add(message["pending"])
                # The server can release its slot before the old desktop child
                # finishes close. Bound that lag without resetting other streams.
                # Overflow and expiry leave only the new server request to time out.
                if len(pending) < min(
                    self.limits.streams_per_host, self.limits.max_pending
                ):
                    pending.append(
                        (message["pending"], loop.time() + self.limits.setup_timeout)
                    )
                    changed.set()
        finally:
            self._state("retrying")
            if heartbeat:
                heartbeat.cancel()
            if admission:
                admission.cancel()
            children = tuple(self._children)
            for child in children:
                child.cancel()
            await asyncio.gather(
                *children,
                *([heartbeat] if heartbeat else []),
                *([admission] if admission else []),
                return_exceptions=True,
            )
            pending.clear()
            self._children.clear()
            if control:
                control.close()
                self._streams.discard(control)

    async def _run(self):
        delay = self.reconnect_initial
        while not self._stop_requested.is_set():
            began = asyncio.get_running_loop().time()
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._state("retrying")
            if asyncio.get_running_loop().time() - began >= self.limits.idle_timeout:
                delay = self.reconnect_initial
            await asyncio.sleep(random.uniform(delay / 2, delay))
            delay = min(self.reconnect_max, delay * 2)
