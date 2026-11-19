"""HTTP signaling adapter. TLS termination and account validation are operator-owned."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .control import Rejected


def signaling_server(address, control):
    import ipaddress

    if not ipaddress.ip_address(address[0]).is_loopback:
        raise ValueError("Signaling requires a loopback TLS-proxy origin")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            status = 200
            try:
                lengths = self.headers.get_all("Content-Length", [])
                if (
                    self.path != "/signal"
                    or self.headers.get("Transfer-Encoding")
                    or len(lengths) != 1
                ):
                    raise Rejected("invalid_request")
                size = int(lengths[0])
                if not 0 < size <= 131072:
                    raise Rejected("invalid_request")
                self.connection.settimeout(5)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise Rejected("invalid_request")
                value = control.call(
                    self.headers.get("Authorization", ""), json.loads(raw)
                )
            except Exception:
                status, value = 403, {"error": "signaling_rejected"}
            encoded = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)

    # Limit concurrent accepted sockets, including clients sending no headers.
    class Bounded(ThreadingHTTPServer):
        daemon_threads = True

        def __init__(self, *args):
            import threading

            self.slots = threading.BoundedSemaphore(32)
            super().__init__(*args)

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(5)
            return connection, address

        def process_request(self, request, address):
            if not self.slots.acquire(False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, address)
            except BaseException:
                self.slots.release()
                raise

        def process_request_thread(self, request, address):
            try:
                super().process_request_thread(request, address)
            finally:
                self.slots.release()

    return Bounded(address, Handler)
