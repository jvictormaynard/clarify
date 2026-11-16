"""Personal-host WebRTC owner. Account sessions authorize signaling only."""

import base64
from concurrent.futures import ThreadPoolExecutor
import json
from queue import Empty, SimpleQueue
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from connect.webrtc.account import NoRedirect
from connect.webrtc.bridge import ComputerBridge


def configuration():
    # Source and packaged builds are disabled until the operator supplies this
    # exact HTTPS endpoint. Invitations cannot override this trust boundary.
    import os

    url = os.environ.get("CLARIFY_WEBRTC_SIGNAL_URL", "")
    if not url:
        return None
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != "/signal"
    ):
        raise ValueError("Invalid WebRTC configuration")
    return url


class ComputerWebRTC:
    def __init__(self, account):
        self.account = account
        self.lock = threading.RLock()
        self.events = SimpleQueue()
        self.workers = ThreadPoolExecutor(8, thread_name_prefix="ComputerRTC")
        self.controls = ThreadPoolExecutor(2, thread_name_prefix="ComputerRTCCancel")
        self.slots = threading.BoundedSemaphore(32)
        self.control_slots = threading.BoundedSemaphore(8)
        self.retired = set()
        self.last_signal = 0.0
        self.host = None
        self.bridges = {}
        self.config = None
        self.connected = False
        self.epoch = 0
        self.recognition_factory = None

    def start(self, host):
        url = configuration()
        if not url or self.account is None or not self.account.signed_in:
            return
        with self.lock:
            identity = json.loads(host.secret_store.get("clarify_computer"))
            jwk = identity.get("webrtc_private_jwk")
            if jwk is None:
                from cryptography.hazmat.primitives.asymmetric import ec

                key = ec.generate_private_key(ec.SECP256R1()).private_numbers()

                def encode(n):
                    return (
                        base64.urlsafe_b64encode(n.to_bytes(32, "big"))
                        .decode()
                        .rstrip("=")
                    )

                jwk = dict(
                    kty="EC",
                    crv="P-256",
                    x=encode(key.public_numbers.x),
                    y=encode(key.public_numbers.y),
                    d=encode(key.private_value),
                    ext=True,
                )
                identity["webrtc_private_jwk"] = jwk
                encoded = json.dumps(identity)
                host.secret_store.set("clarify_computer", encoded)
                if host.secret_store.get("clarify_computer") != encoded:
                    raise ValueError("Host key was not persisted")
            self.host = host
            self.config = dict(host=identity["computer_id"], privateJwk=jwk)
            self.url = url
            self.stamp = self.account.context_stamp()
            self.signal(
                "enroll", {"public_key": {k: jwk[k] for k in ("kty", "crv", "x", "y")}}
            )
            self.events.put({"event": "computer-webrtc-config", "config": self.config})

    def signal(self, action, fields):
        if action not in {"enroll", "pending", "poll", "turn", "answer", "close"}:
            raise ValueError("Invalid signaling action")
        if (
            not self.config
            or not self.account.signed_in
            or self.account.context_stamp() != self.stamp
        ):
            raise ValueError("Account changed")
        token = self.account.secrets.get("clarify_account")
        request = Request(
            self.url,
            data=json.dumps(
                {**fields, "action": action, "host": self.config["host"]}
            ).encode(),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        )
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            raw = response.read(131073)
            if response.status != 200 or len(raw) > 131072:
                raise ValueError("Signaling rejected")
            self.last_signal = time.monotonic()
            return json.loads(raw)

    def binding(self):
        with self.lock:
            if (
                not self.config
                or not self.connected
                or time.monotonic() - self.last_signal > 3
                or not self.account.signed_in
                or self.account.context_stamp() != self.stamp
            ):
                return None
            return {
                "signal_url": self.url,
                "public_key": {
                    k: self.config["privateJwk"][k] for k in ("kty", "crv", "x", "y")
                },
            }

    def submit(self, message):
        request_id = message.get("requestID")
        if type(request_id) is not int:
            return
        epoch = self.epoch
        kind, value = message.get("kind"), message.get("value")
        request = value.get("request") if isinstance(value, dict) else None
        if kind == "dispatch" and not isinstance(request, dict):
            self.events.put(
                {
                    "event": "computer-webrtc-reply",
                    "requestID": request_id,
                    "error": "Invalid request",
                }
            )
            return
        cancel = kind == "close-peer" or (
            kind == "dispatch"
            and isinstance(value, dict)
            and (
                request.get("method") == "DELETE"
                or request.get("recognition") == "cancel"
            )
        )

        slots = self.control_slots if cancel else self.slots
        if not slots.acquire(False):
            self.events.put(
                {
                    "event": "computer-webrtc-reply",
                    "requestID": request_id,
                    "error": "Computer connection capacity",
                }
            )
            return

        def run():
            try:
                with self.lock:
                    if epoch != self.epoch or self.host is None:
                        raise ValueError("Host stopped")
                    host = self.host
                if kind == "signal":
                    result = self.signal(value["action"], value.get("fields", {}))
                elif kind == "dispatch":
                    ticket = value["ticket"]
                    if not isinstance(ticket, str) or len(ticket) != 43:
                        raise ValueError("Invalid peer")
                    with self.lock:
                        if ticket in self.retired or len(self.retired) >= 4096:
                            raise ValueError("Peer closed")
                        if ticket not in self.bridges:
                            if len(self.bridges) >= 8:
                                raise ValueError("Peer capacity")
                            recognition = (
                                self.recognition_factory(host, ticket)
                                if self.recognition_factory
                                else None
                            )
                            self.bridges[ticket] = ComputerBridge(
                                host, recognition_handler=recognition
                            )
                        bridge = self.bridges[ticket]
                    result = bridge.request(value["request"])
                elif kind == "close-peer":
                    with self.lock:
                        self.retired.add(value)
                        bridge = self.bridges.pop(value, None)
                    if bridge:
                        bridge.close()
                    result = None
                else:
                    raise ValueError("Invalid private command")
                reply = {"result": result}
            except Exception:
                reply = {"error": "Computer connection unavailable"}
            finally:
                slots.release()
            if epoch == self.epoch:
                self.events.put(
                    {"event": "computer-webrtc-reply", "requestID": request_id, **reply}
                )

        (self.controls if cancel else self.workers).submit(run)

    def stop(self):
        with self.lock:
            self.epoch += 1
            self.retired.clear()
            bridges, self.bridges = self.bridges, {}
            self.host = self.config = None
            self.connected = False
            self.events.put({"event": "computer-webrtc-config", "config": None})
        for bridge in bridges.values():
            bridge.close()

    def shutdown(self):
        self.stop()
        self.workers.shutdown(wait=True)
        self.controls.shutdown(wait=True)

    def drain(self):
        while True:
            try:
                yield self.events.get_nowait()
            except Empty:
                return


class WebRTCHost:
    """Preserve LAN ownership; add a remote peer only after explicit opt-in."""

    def __init__(self, host, remote):
        self.host, self.remote = host, remote

    def __getattr__(self, name):
        return getattr(self.host, name)

    def start(self):
        self.host.start()
        try:
            self.remote.start(self.host)
        except Exception:
            # A remote setup failure cannot disable the existing LAN route.
            self.remote.stop()

    def stop(self):
        self.remote.stop()
        self.host.stop()

    def create_pairing(self):
        result = self.host.create_pairing()
        binding = self.remote.binding()
        if binding:
            prefix = "clarify://computer?data="
            encoded = result["pairing_url"][len(prefix) :]
            payload = json.loads(
                base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            )
            payload["webrtc"] = binding
            result["pairing_url"] = prefix + base64.urlsafe_b64encode(
                json.dumps(payload).encode()
            ).decode().rstrip("=")
        return result
