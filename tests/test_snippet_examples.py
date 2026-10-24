import json
from pathlib import Path
import unittest

from dictionary_snippets import (
    DictionarySnippets,
    DictionarySnippetService,
    InMemoryDictionarySnippetsRepository,
    Snippet,
)


class SharedSnippetExamplesTests(unittest.TestCase):
    def test_examples_shared_with_mobile(self):
        examples = json.loads(
            (
                Path(__file__).resolve().parents[1] / "shared/snippet_examples.json"
            ).read_text(encoding="utf-8")
        )
        for example in examples:
            with self.subTest(text=example["input"]):
                state = DictionarySnippets(
                    snippets=tuple(
                        Snippet.from_mapping(item) for item in example["snippets"]
                    )
                )
                service = DictionarySnippetService(
                    InMemoryDictionarySnippetsRepository(state)
                )
                self.assertEqual(service.expand(example["input"]), example["expected"])
