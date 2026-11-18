"""Isolated ACP v1 text turns. No client file or terminal capabilities.

Wire contract: https://agentclientprotocol.com/protocol/v1/prompt-turn
OpenCode 2.3 selects models through session/set_config_option.
"""

from __future__ import annotations

from contextlib import nullcontext
import json
import os
import queue
import threading
import time

from provider_http import ProviderCancelledError, ProviderTimeoutError
from provider_types import ProviderResponseError

_OUTPUT_LIMIT = 4 * 1024 * 1024
_DIAGNOSTIC_LIMIT = 1024 * 1024


def _offers_model(choices, model):
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        if choice.get("value") == model:
            return True
        group = choice.get("options")
        if isinstance(group, list) and any(
            isinstance(item, dict) and item.get("value") == model for item in group
        ):
            return True
    return False


class TextSession:
    """The caller owns the child tree and must stop it before closing this client."""

    def __init__(self, process, stopping):
        self.process = process
        self.owner_stopping = stopping
        self.deadline = 0
        self.cancel_token = None
        self.sequence = 0
        self.session = None
        self.parts = []
        self.initialized = False
        self.can_delete = False
        self.reusable = False
        self.writes = queue.Queue(maxsize=8)
        self.reads = queue.Queue(maxsize=64)
        self.stopping = threading.Event()
        self.failure = ""
        self._budget_lock = threading.Lock()
        self._stdout_left = _OUTPUT_LIMIT
        self._stderr_left = _DIAGNOSTIC_LIMIT
        self.workers = (
            threading.Thread(target=self._read, name="clarify-acp-reader", daemon=True),
            threading.Thread(
                target=self._drain_stderr, name="clarify-acp-stderr", daemon=True
            ),
            threading.Thread(
                target=self._write, name="clarify-acp-writer", daemon=False
            ),
        )
        try:
            for worker in self.workers:
                worker.start()
        except RuntimeError:
            self.stopping.set()
            raise

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
            self.failure = "OpenCode stopped receiving requests."

    def _read(self):
        try:
            while not self.stopping.is_set():
                line = self.process.stdout.readline(_OUTPUT_LIMIT + 1)
                if not line:
                    return
                with self._budget_lock:
                    self._stdout_left -= len(line)
                    if self._stdout_left < 0:
                        self.failure = "OpenCode output exceeded the limit."
                        return
                while not self.stopping.is_set():
                    try:
                        self.reads.put(line, timeout=0.025)
                        break
                    except queue.Full:
                        continue
        except (OSError, ValueError):
            self.failure = "OpenCode output could not be read."

    def _drain_stderr(self):
        try:
            with self.process.stderr as stream:
                while not self.stopping.is_set():
                    block = os.read(stream.fileno(), 65536)
                    if not block:
                        return
                    with self._budget_lock:
                        self._stderr_left -= len(block)
                        if self._stderr_left < 0:
                            self.failure = "OpenCode output exceeded the limit."
                            return
        except (OSError, ValueError):
            self.failure = "OpenCode diagnostics could not be read."

    def close(self):
        self.stopping.set()
        # The owner has killed and reaped the tree, so blocked writes now fail.
        for worker in self.workers:
            worker.join(timeout=1)
        if any(worker.is_alive() for worker in self.workers):
            raise ProviderResponseError("opencode", "OpenCode client did not stop.")
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()

    def _error(
        self,
        message="OpenCode did not complete this free request. No fallback was used.",
    ):
        raise ProviderResponseError("opencode", message)

    def _check(self):
        if self.cancel_token is not None:
            self.cancel_token.raise_if_cancelled()
        if self.owner_stopping.is_set():
            raise ProviderCancelledError(provider="opencode")
        if time.monotonic() >= self.deadline:
            raise ProviderTimeoutError(provider="opencode", operation="text_generation")
        if self.failure:
            self._error(self.failure)
        if self.process.poll() is not None:
            self._error("OpenCode closed before confirmed completion.")

    def _send(self, message, authorization=None):
        self._check()
        data = (json.dumps({"jsonrpc": "2.0", **message}) + "\n").encode("utf-8")
        if len(data) > 4 * 1024 * 1024:
            self._error("OpenCode input exceeded the limit.")
        try:
            sent = threading.Event()
            with authorization() if authorization is not None else nullcontext():
                self.writes.put_nowait((data, sent))
        except queue.Full:
            self._error()
        while not sent.wait(0.01):
            self._check()

    def _next(self):
        while True:
            self._check()
            try:
                line = self.reads.get(timeout=0.01)
            except queue.Empty:
                continue
            try:
                message = json.loads(line)
            except (ValueError, UnicodeError):
                self._error()
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                self._error()
            return message

    def call(self, method, params, authorization=None):
        self.sequence += 1
        identity = self.sequence
        self._send({"id": identity, "method": method, "params": params}, authorization)
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

    def _initialize(self):
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
        agent = initialized.get("agentCapabilities")
        capabilities = (
            agent.get("sessionCapabilities") if isinstance(agent, dict) else None
        )
        self.can_delete = isinstance(capabilities, dict) and isinstance(
            capabilities.get("delete"), dict
        )
        self.initialized = True

    def generate(
        self, work, model, prompt, authorization=None, *, timeout, cancel_token, reuse
    ):
        self.deadline = time.monotonic() + timeout
        self.cancel_token = cancel_token
        self.reusable = False
        with self._budget_lock:
            self._stdout_left = _OUTPUT_LIMIT
            self._stderr_left = _DIAGNOSTIC_LIMIT
        try:
            if not self.initialized:
                self._initialize()
            text = self._turn(work, model, prompt, authorization)
            if reuse and self.can_delete:
                # Cleanup may retire a worker, but cannot delay an already complete turn.
                self.deadline = min(self.deadline, time.monotonic() + 0.35)
                try:
                    self.call("session/delete", {"sessionId": self.session})
                except (ProviderResponseError, ProviderTimeoutError):
                    pass
                else:
                    self.reusable = True
            return text
        finally:
            self.parts.clear()
            self.session = None
            self.cancel_token = None

    def _turn(self, work, model, prompt, authorization):
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
            and _offers_model(option.get("options"), model)
            for option in options
        ):
            self._error("OpenCode did not confirm the selected free model.")
        result = self.call(
            "session/prompt",
            {"sessionId": self.session, "prompt": [{"type": "text", "text": prompt}]},
            authorization,
        )
        text = "".join(self.parts).strip()
        if result.get("stopReason") != "end_turn" or not text:
            self._error()
        return text
