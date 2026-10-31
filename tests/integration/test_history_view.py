"""History reads and clipboard effects use only temporary, isolated stores."""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from account_history import AccountHistory
from history_store import HistoryRecord, HistoryStore
from clarify.desktop.history_view import HistoryView


class HistoryViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.account = SimpleNamespace(
            _lock=threading.RLock(),
            _generation=0,
            history_identity=lambda: None,
            directory=Path(self.temp.name),
        )
        self.store = HistoryStore(
            Path(self.temp.name) / "history.json", enabled=True, retention_days=None
        )
        self.view = HistoryView(AccountHistory(self.account, self.store))

    def seed(self, records):
        self.store.path.write_text(
            json.dumps(
                {"schema_version": 1, "records": [r.to_mapping() for r in records]}
            ),
            encoding="utf-8",
        )
        return self.view.snapshot()["context"]

    def test_search_reaches_older_original_and_result_without_sending_all_text(self):
        records = [HistoryRecord(raw_text="Other " + str(i)) for i in range(250)]
        records[0] = HistoryRecord(
            raw_text="Original Straße 😀", refined_text="Revised café"
        )
        context = self.seed(records)
        for query in ("STRASSE", "CAFÉ", "😀"):
            cursor, found = "", []
            for _ in range(20):
                page = self.view.page(context, cursor, query)
                found.extend(page["entries"])
                self.assertLess(len(json.dumps(page).encode()), 128 * 1024)
                cursor = page["cursor"]
                if not cursor:
                    break
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["text"], "Revised café")
        page = self.view.page(context, "", "missing")
        self.assertTrue(page["hasMore"])
        with self.assertRaises(ValueError):
            self.view.page(context, page["cursor"], "different query")

    def test_copy_preserves_both_texts_and_rejects_old_context_revision_and_deletion(
        self,
    ):
        context = self.seed(
            [HistoryRecord(raw_text="Original 😀", refined_text="Result é")]
        )
        page = self.view.page(context, "")
        token, revision = page["entries"][0]["id"], page["revision"]
        writer = Mock()
        for field, expected in (("text", "Result é"), ("transcript", "Original 😀")):
            self.view.copy_text(context, token, field, revision, writer)
            writer.assert_called_with(expected)
        self.assertEqual(self.store.list_records()[0].raw_text, "Original 😀")
        writer.reset_mock()
        with self.assertRaises(ValueError):
            self.view.copy_text(context, token, "text", "0" * 64, writer)
        self.account._generation += 1
        with self.assertRaises(ValueError):
            self.view.copy_text(context, token, "text", revision, writer)
        context = self.view.snapshot()["context"]
        page = self.view.page(context, "")
        self.view.delete(context, page["entries"][0]["id"])
        with self.assertRaises(ValueError):
            self.view.copy_text(
                context, page["entries"][0]["id"], "text", page["revision"], writer
            )
        writer.assert_not_called()

    def test_original_metadata_and_bounded_unicode_parts_and_clipboard_retry(self):
        context = self.seed(
            [
                HistoryRecord(raw_text=None, refined_text="Only result"),
                HistoryRecord(raw_text="Same", refined_text="Same"),
                HistoryRecord(raw_text="😀é" * 10000, refined_text="Different"),
            ]
        )
        page = self.view.page(context, "")
        rows = {row["text"]: row for row in page["entries"]}
        self.assertFalse(rows["Only result"]["hasOriginal"])
        self.assertFalse(rows["Same"]["originalDiffers"])
        self.assertTrue(rows["Different"]["originalDiffers"])
        token = rows["Different"]["id"]
        part = self.view.text_part(context, token, 0, "transcript")
        self.assertEqual(part["text"], "😀é" * 2000)
        self.assertEqual(part["revision"], page["revision"])
        writer = Mock(side_effect=[OSError("private failure details"), None])
        with self.assertRaises(OSError):
            self.view.copy_text(context, token, "text", page["revision"], writer)
        self.view.copy_text(context, token, "text", page["revision"], writer)
        self.assertEqual(writer.call_count, 2)

    def test_search_is_bounded_even_for_one_giant_legacy_record(self):
        context = self.seed([HistoryRecord(raw_text="x" * 1100000 + "Needle 😀")])
        page = self.view.page(context, "", "needle 😀")
        self.assertEqual(page["entries"], [])
        self.assertTrue(page["hasMore"])
        for _ in range(20):
            page = self.view.page(context, page["cursor"], "needle 😀")
            if page["entries"]:
                break
        self.assertEqual(len(page["entries"]), 1)

    def test_account_search_and_copy_do_not_cross_account_or_guest_scopes(self):
        from clarify_account import HistoryIdentity

        owner = HistoryIdentity("https://clarify.example", "account-a", 0)
        self.account.history_identity = lambda: owner
        self.seed([HistoryRecord(raw_text="Guest preserved")])
        self.view.history.append(
            HistoryRecord(raw_text="Account original", refined_text="Account result"),
            owner,
        )
        context = self.view.snapshot()["context"]
        page = self.view.page(context, "", "account original")
        self.assertEqual(len(page["entries"]), 1)
        self.assertEqual(page["entries"][0]["owner"], "account")
        original = self.view.text_part(
            context, page["entries"][0]["id"], 0, "transcript"
        )
        self.assertEqual(original["owner"], "account")
        self.assertEqual(original["text"], "Account original")
        writer = Mock()
        self.view.copy_text(
            context, page["entries"][0]["id"], "text", page["revision"], writer
        )
        writer.assert_called_once_with("Account result")
        self.account.history_identity = lambda: None
        self.account._generation += 1
        writer.reset_mock()
        with self.assertRaises(ValueError):
            self.view.copy_text(
                context, page["entries"][0]["id"], "text", page["revision"], writer
            )
        writer.assert_not_called()
        guest = self.view.page(self.view.snapshot()["context"], "", "account")
        self.assertEqual(guest["entries"], [])
        # Returning to the same user/endpoint is a new session, not the old scope.
        self.account.history_identity = lambda: HistoryIdentity(
            owner.endpoint, owner.user_id, 2
        )
        self.account._generation += 1
        with self.assertRaises(ValueError):
            self.view.copy_text(
                context, page["entries"][0]["id"], "text", page["revision"], writer
            )
        with self.assertRaises(ValueError):
            self.view.text_part(context, page["entries"][0]["id"], 0, "transcript")
        writer.assert_not_called()

    def test_search_keeps_matches_across_chunk_and_continuation_boundaries(self):
        for boundary in (4000, 128 * 4000):
            # Unicode casefold expands ß; the match starts before each boundary.
            context = self.seed(
                [HistoryRecord(raw_text="x" * (boundary - 4) + "Straße 😀 end")]
            )
            page = self.view.page(context, "", "STRASSE 😀")
            for _ in range(5):
                if page["entries"] or not page["cursor"]:
                    break
                page = self.view.page(context, page["cursor"], "STRASSE 😀")
            self.assertEqual(len(page["entries"]), 1)


if __name__ == "__main__":
    unittest.main()
