"""One private ACP v1 text turn. No client file or terminal capabilities.

Wire contract: https://agentclientprotocol.com/protocol/v1/prompt-turn
OpenCode 2.3 selects models through session/set_config_option.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time

from provider_http import ProviderTimeoutError
from provider_types import ProviderResponseError


class TextSession:
    """The caller owns the child tree and must stop it before closing this client."""

    def __init__(self, process, stdout, stderr, timeout, cancel_token):
        self.process = process
        self.stdout = stdout
        self.stderr = stderr
        self.deadline = time.monotonic() + timeout
        self.cancel_token = cancel_token
        self.pending = b""
        self.total = 0
        self.sequence = 0
        self.session = None
        self.parts = []
        self.writes = queue.Queue(maxsize=8)
        self.stopping = threading.Event()
        self.failed = threading.Event()
        self.writer = threading.Thread(target=self._write, name="clarify-acp-writer")
        self.writer.start()

    def _write(self):
        try:
            while not self.stopping.is_set():
                try:
                    message, sent = self.writes.get(timeout=0.025)
                except queue.Empty:
                    continue
                self.process.stdin.write(message)
                self.process.stdin.flush()
                sent.set()
        except (OSError, ValueError):
            self.failed.set()

    def close(self):
        self.stopping.set()
        # The owner has killed and reaped the tree, so blocked writes now fail.
        self.writer.join(timeout=5)
        self.process.stdin.close()
        if self.writer.is_alive():
            raise ProviderResponseError("opencode", "OpenCode client did not stop.")

    def _error(
        self,
        message="OpenCode did not complete this free request. No fallback was used.",
    ):
        raise ProviderResponseError("opencode", message)

    def _check(self):
        if self.cancel_token is not None:
            self.cancel_token.raise_if_cancelled()
        if time.monotonic() >= self.deadline:
            raise ProviderTimeoutError(provider="opencode", operation="text_generation")
        if self.failed.is_set():
            self._error()
        if (
            os.fstat(self.stdout.fileno()).st_size > 4 * 1024 * 1024
            or os.fstat(self.stderr.fileno()).st_size > 1024 * 1024
        ):
            self._error("OpenCode output exceeded the limit.")
        if self.process.poll() is not None:
            self._error("OpenCode closed before confirmed completion.")

    def _send(self, message):
        self._check()
        data = (json.dumps({"jsonrpc": "2.0", **message}) + "\n").encode("utf-8")
        if len(data) > 4 * 1024 * 1024:
            self._error("OpenCode input exceeded the limit.")
        try:
            sent = threading.Event()
            self.writes.put_nowait((data, sent))
        except queue.Full:
            self._error()
        while not sent.wait(0.01):
            self._check()

    def _next(self):
        while True:
            self._check()
            if b"\n" in self.pending:
                line, self.pending = self.pending.split(b"\n", 1)
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError):
                    self._error()
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    self._error()
                return message
            block = self.stdout.read(65536)
            if block:
                self.total += len(block)
                if self.total > 4 * 1024 * 1024:
                    self._error("OpenCode output exceeded the limit.")
                self.pending += block
            else:
                time.sleep(0.01)

    def call(self, method, params):
        self.sequence += 1
        identity = self.sequence
        self._send({"id": identity, "method": method, "params": params})
        while True:
            message = self._next()
            if "method" in message and "id" in message:
                # Cancel EVERY permission request, including malformed or foreign
                # session requests. No client callback can touch files or terminals.
                if message["method"] == "session/request_permission":
                    reply = {"result": {"outcome": {"outcome": "cancelled"}}}
                else:
                    reply = {
                        "error": {
                            "code": -32601,
                            "message": "Client operation not supported",
                        }
                    }
                self._send({"id": message["id"], **reply})
            elif "method" in message:
                if message["method"] != "session/update":
                    continue
                params = message.get("params")
                if not isinstance(params, dict):
                    self._error()
                update = params.get("update")
                if not isinstance(update, dict):
                    self._error()
                if update.get("sessionUpdate") == "agent_message_chunk":
                    content = update.get("content")
                    if (
                        method != "session/prompt"
                        or params.get("sessionId") != self.session
                        or not isinstance(content, dict)
                        or content.get("type") != "text"
                        or not isinstance(content.get("text"), str)
                    ):
                        self._error()
                    self.parts.append(content["text"])
                if update.get("sessionUpdate") in {
                    "tool_call",
                    "tool_call_update",
                } and update.get("status") in {"in_progress", "completed"}:
                    self._error("OpenCode reported unexpected tool execution.")
            elif message.get("id") == identity:
                if "error" in message:
                    error = message["error"]
                    data = error.get("data", {}) if isinstance(error, dict) else {}
                    if (
                        isinstance(data, dict)
                        and data.get("errorName") == "provider.free-limit"
                    ):
                        self._error(
                            "OpenCode free usage limit reached. Retry later or explicitly select another service. No fallback was used."
                        )
                    self._error()
                result = message.get("result")
                if not isinstance(result, dict):
                    self._error()
                self._check()
                return result
            else:
                self._error()

    def generate(self, work, model, prompt):
        initialized = self.call(
            "initialize",
            {
                "protocolVersion": 1,
                "clientInfo": {"name": "clarify", "version": "1"},
                "clientCapabilities": {},
            },
        )
        if initialized.get("protocolVersion") != 1:
            self._error()
        self.session = self.call(
            "session/new", {"cwd": str(work), "mcpServers": []}
        ).get("sessionId")
        if not isinstance(self.session, str) or not self.session:
            self._error()
        self.call("session/set_mode", {"sessionId": self.session, "modeId": "clarify"})
        selected = self.call(
            "session/set_config_option",
            {"sessionId": self.session, "configId": "model", "value": model},
        )
        options = selected.get("configOptions", [])
        if not isinstance(options, list) or not any(
            isinstance(option, dict)
            and option.get("id") == "model"
            and option.get("currentValue") == model
            for option in options
        ):
            self._error("OpenCode did not confirm the selected free model.")
        result = self.call(
            "session/prompt",
            {"sessionId": self.session, "prompt": [{"type": "text", "text": prompt}]},
        )
        text = "".join(self.parts).strip()
        if result.get("stopReason") != "end_turn" or not text:
            self._error()
        return text
