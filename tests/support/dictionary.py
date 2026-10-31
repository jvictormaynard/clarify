"""Reusable dictionary fixtures. This module defines no test cases."""

from pathlib import Path

import tempfile


from dictionary_snippets import (
    LocalDictionarySnippetsRepository,
)


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _FakeHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    @staticmethod
    def json(response, **_kwargs):
        return response.json()


class DictionaryFixture:
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "dictionary.json"
        self.repository = LocalDictionarySnippetsRepository(self.path)

    def tearDown(self):
        self.directory.cleanup()
