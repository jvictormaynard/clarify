"""Reusable chatgpt provider fixtures. This module defines no test cases."""

import json


from types import SimpleNamespace


from provider_registry import build_provider_registry

from provider_types import (
    ProviderConnection,
    RewriteRequest,
)


class SessionChanged(RuntimeError):
    code = "stale_session"


class Session:
    def __init__(self):
        self.generation = 1

    def credential(self, *, cancel_token=None):
        if cancel_token:
            cancel_token.raise_if_cancelled()
        return SimpleNamespace(
            access_token="synthetic-oauth-token",
            generation=self.generation,
            account_id="synthetic-account",
        )

    def check_current(self, generation):
        if generation != self.generation:
            raise SessionChanged("The selected ChatGPT session changed.")


class Response:
    status_code = 200
    headers = {"Content-Type": "text/event-stream", "x-request-id": "synthetic-request"}

    def __init__(self, events=(), *, payload=None, before_event=None):
        self.events = list(events)
        self.payload = payload
        self.before_event = before_event
        self.closed = False

    def json(self):
        return self.payload

    def iter_lines(self, **kwargs):
        for event in self.events:
            if self.before_event:
                self.before_event(event)
            yield ("data: " + json.dumps(event)).encode()
            yield b""

    def close(self):
        self.closed = True

    def iter_content(self, chunk_size):
        for event in self.events:
            if self.before_event:
                self.before_event(event)
            content = ("data: " + json.dumps(event) + "\n\n").encode()
            for offset in range(0, len(content), chunk_size):
                yield content[offset : offset + chunk_size]


class Http:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def json(self, response, **kwargs):
        return response.json()


def completed(text):
    return {
        "type": "response.completed",
        "response": {
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": text}]}
            ],
        },
    }


def item_done(text, index=0):
    return {
        "type": "response.output_item.done",
        "output_index": index,
        "item": {
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": text}],
        },
    }


class ChatGPTProviderFixture:
    connection = ProviderConnection(
        "", "https://api.openai.com/v1", "synthetic-account"
    )

    rewrite = RewriteRequest(
        "source", "available-model", "pt", "Keep all facts.", "source"
    )

    def adapter(self, *responses, session=None):
        http = Http(*responses)
        session = session or Session()
        registry = build_provider_registry(http, chatgpt_session=session)
        return registry.adapter("chatgpt"), http

    @staticmethod
    def streaming_http_response(body, *, status=401, on_byte=None):
        import requests

        class StreamingResponse(requests.Response):
            def __init__(self):
                super().__init__()
                self.status_code = status
                self.headers["x-request-id"] = "synthetic-request"
                self.consumed = 0
                self.closed = False
                self.close_count = 0

            def iter_content(self, chunk_size=1, **kwargs):
                for byte in body:
                    self.consumed += 1
                    if on_byte:
                        on_byte()
                    yield bytes([byte])

            def close(self):
                self.closed = True
                self.close_count += 1

        return StreamingResponse()
