"""Data-channel adapter to the existing computer credential/operation contract."""

import base64
import threading
import time


class ComputerBridge:
    """One per peer. The trusted Electron pipe calls request on worker threads.

    Recognition hook: start(metadata), feed(sequence, WAV bytes), finish(),
    cancel(). The default buffers a complete 16-kHz PCM WAV, then invokes the
    existing once-only dictation route. It does not claim streaming inference.
    A streaming worker can replace this adapter, but must reserve operation IDs
    through ComputerHost before inference, share its CancellationToken and keep
    its replay barrier. No transport is allowed to mint a replacement ID.
    """

    def __init__(self, host, *, recognition_handler=None):
        self.host = host
        self.recognition_handler = recognition_handler
        self.lock = threading.RLock()
        self.uploads = {}
        self.retired = set()
        self.active = set()
        self.closed = False

    def request(self, value):
        if not isinstance(value, dict):
            return {"status": 400, "body": {"error": "invalid_request"}}
        with self.lock:
            if self.closed:
                return {"status": 410, "body": {"error": "peer_closed"}}
        if value.get("recognition"):
            handler = self.recognition_handler or self.recognition
            return handler(
                value.get("authorization", ""),
                value["recognition"],
                value.get("operation_id"),
                value.get("body"),
            )
        method, path = value.get("method"), value.get("path")
        token, body = value.get("authorization", ""), value.get("body")
        if not isinstance(token, str) or not isinstance(path, str):
            return {"status": 400, "body": {"error": "invalid_request"}}
        # Pairing stays explicit on the existing local pairing surface. WebRTC
        # tickets alone never create or grant a computer processing credential.
        if path == "/v1/computer/pair" or path == "/v1/computer/remote":
            return {"status": 403, "body": {"error": "local_pairing_required"}}
        key = None
        with self.lock:
            if self.closed:
                return {"status": 410, "body": {"error": "peer_closed"}}
            if method == "POST" and isinstance(body, dict) and body.get("operation_id"):
                import computer_host as protocol

                try:
                    key = (
                        self.host._authenticate(token),
                        protocol._uuid(body["operation_id"]),
                    )
                except protocol._APIError as error:
                    return {"status": error.status, "body": {"error": error.code}}
                self.active.add(key)
        try:
            return self.host.webrtc_request(method, path, token, body)
        finally:
            if key:
                with self.lock:
                    self.active.discard(key)

    def recognition(self, authorization, action, operation_id, body=None):
        import computer_host as protocol

        try:
            device = self.host._authenticate(authorization)
            operation_id = protocol._uuid(operation_id)
            key = (device, operation_id)
            with self.lock:
                if self.closed:
                    raise protocol._APIError(410, "peer_closed")
                now = time.monotonic()
                expired = [k for k, v in self.uploads.items() if now - v["time"] > 300]
                for old in expired:
                    self.uploads.pop(old)
                    self.host._cancel(*old)
                if action == "cancel":
                    self.uploads.pop(key, None)
                    self.host._cancel(*key)
                    return {"status": 200, "body": {"cancelled": True}}
                if action == "start":
                    if (
                        key in self.retired
                        or len(self.retired) >= 4096
                        or len(self.uploads) >= 2
                    ):
                        raise protocol._APIError(409, "session_unavailable")
                    if (
                        not isinstance(body, dict)
                        or len(protocol._json(body)) > 4096
                        or "audio_wav" in body
                    ):
                        raise protocol._APIError(400, "invalid_request")
                    with self.host._lock:
                        self.host._check_operation_time(
                            operation_id, None, self.host._operation_window()
                        )
                    self.retired.add(key)
                    self.uploads[key] = dict(
                        metadata={**body, "operation_id": operation_id},
                        parts=[],
                        size=0,
                        time=now,
                    )
                    return {"status": 200, "body": {"started": True}}
                upload = self.uploads.get(key)
                if upload is None:
                    raise protocol._APIError(409, "session_unavailable")
                if action == "feed":
                    if (
                        not isinstance(body, dict)
                        or body.get("sequence") != len(upload["parts"])
                        or not isinstance(body.get("data"), str)
                        or len(body["data"]) > 44000
                    ):
                        raise protocol._APIError(400, "invalid_frame")
                    try:
                        data = base64.b64decode(body["data"], validate=True)
                    except ValueError:
                        raise protocol._APIError(400, "invalid_frame") from None
                    if (
                        not data
                        or len(upload["parts"]) >= 4096
                        or upload["size"] + len(data) > 9600044
                    ):
                        raise protocol._APIError(413, "body_too_large")
                    upload["parts"].append(data)
                    upload["size"] += len(data)
                    return {"status": 200, "body": {"accepted": body["sequence"]}}
                if action != "finish":
                    raise protocol._APIError(400, "invalid_action")
                self.uploads.pop(key)
                metadata = upload["metadata"]
                metadata["audio_wav"] = base64.b64encode(
                    b"".join(upload["parts"])
                ).decode()
            return self.request(
                dict(
                    method="POST",
                    path="/v1/computer/dictations",
                    authorization=authorization,
                    body=metadata,
                )
            )
        except protocol._APIError as error:
            return {"status": error.status, "body": {"error": error.code}}

    def close(self):
        with self.lock:
            self.closed = True
            uploads, self.uploads = self.uploads, {}
            for key in set(uploads) | self.active:
                try:
                    self.host._cancel(*key)
                except Exception:
                    pass

        close = getattr(self.recognition_handler, "close", None)
        if close is not None:
            close()
