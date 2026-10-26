"""Isolated contract tests. No Qt, user profile, audio or network access."""

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from dictionary_snippets import (
    DictionaryEntry,
    DictionarySnippetService,
    DictionarySnippets,
    LocalDictionarySnippetsRepository,
    Snippet,
)
from history_corrections import (
    CorrectionError,
    CorrectionIdentity,
    CorrectionSource,
    HistoryDictionaryCorrectionService,
)


class ScopedRepository:
    def __init__(self, fixture):
        self.fixture = fixture

    @property
    def path(self):
        return self.fixture.root / (self.fixture.owner.context + ".json")

    @contextmanager
    def transaction(self, *, expected_context=None):
        with self.fixture.guard:
            if (
                expected_context is not None
                and expected_context != self.fixture.owner.context
            ):
                raise CorrectionError("context_changed")
            yield

    def load(self):
        return LocalDictionarySnippetsRepository(self.path).load()

    def save(self, state):
        return LocalDictionarySnippetsRepository(self.path).save(state)


class HistoryCorrectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.guard = threading.RLock()
        self.owner = CorrectionIdentity("local", 0, "local")
        self.source = CorrectionSource("history-context", "history-revision", "row")
        self.original = "We use clear if eye for this task."
        self.record_owner = "local"
        self.reads = []
        self.now = 0.0
        self.repository = ScopedRepository(self)
        self.dictionary = DictionarySnippetService(self.repository)
        self.dictionary.replace(
            DictionarySnippets(snippets=(Snippet("sig", "Exact\ntext"),))
        )
        self.service = HistoryDictionaryCorrectionService(
            self.dictionary,
            read_part=self.read_part,
            identity=lambda: self.owner,
            guard=lambda: self.guard,
            clock=lambda: self.now,
        )

    def read_part(self, context, token, offset, field):
        self.assertEqual(field, "transcript")
        self.reads.append(offset)
        text = self.original[offset : offset + 4000]
        return {
            "context": context,
            "revision": self.source.revision,
            "id": token,
            "owner": self.record_owner,
            "text": text,
            "nextOffset": offset + len(text),
            "hasMore": offset + len(text) < len(self.original),
        }

    def preview(self, heard="clear if eye", corrected="Clarify"):
        return self.service.preview(self.source, self.owner.context, heard, corrected)

    def test_preview_has_no_persistent_or_in_memory_effect(self):
        before = self.repository.path.read_bytes()
        state = self.dictionary.state
        proposal = self.preview()
        self.assertEqual(proposal.heard, "clear if eye")
        self.assertEqual(
            proposal.entry, DictionaryEntry("Clarify", aliases=("clear if eye",))
        )
        self.assertTrue(proposal.token)
        self.assertEqual(self.repository.path.read_bytes(), before)
        self.assertEqual(self.dictionary.state, state)
        self.assertEqual(self.original, "We use clear if eye for this task.")

    def test_confirm_and_undo_only_addition_preserve_snippets_and_original(self):
        original = self.original
        result = self.service.confirm(self.preview().token)
        self.assertEqual(result.status, "saved")
        self.assertTrue(self.service.can_undo(result.receipt))
        self.assertEqual(
            self.repository.load().dictionary,
            (DictionaryEntry("Clarify", aliases=("clear if eye",)),),
        )
        self.assertEqual(self.service.undo(result.receipt).status, "undone")
        self.assertEqual(self.repository.load().dictionary, ())
        self.assertEqual(
            self.repository.load().snippets, (Snippet("sig", "Exact\ntext"),)
        )
        self.assertEqual(self.original, original)
        self.assertEqual(self.service.undo(result.receipt).status, "undo_unavailable")

    def test_existing_term_never_changes_metadata_or_disabled_flag(self):
        existing = DictionaryEntry(
            "CLARIFY", "existing pronunciation", ("existing alias",), False
        )
        self.dictionary.replace(DictionarySnippets(dictionary=(existing,)))
        before = self.repository.path.read_bytes()
        proposal = self.preview()
        self.assertTrue(proposal.already_exists)
        self.assertFalse(proposal.token)
        self.assertEqual(self.repository.path.read_bytes(), before)
        self.assertEqual(self.dictionary.state.dictionary, (existing,))

    def test_multiple_words_unicode_and_chunk_boundary_are_supported(self):
        self.original = "x" * 3997 + "cafe\u0301 incorreto" + "y" * 8000
        proposal = self.preview("caf\u00e9 incorreto", "Caf\u00e9 correto")
        self.assertEqual(proposal.entry.aliases, ("caf\u00e9 incorreto",))
        self.assertEqual(self.reads, [0, 4000])
        self.assertEqual(self.service.confirm(proposal.token).status, "saved")

    def test_case_only_correction_does_not_create_redundant_alias(self):
        self.original = "clarify"
        proposal = self.preview("clarify", "Clarify")
        self.assertEqual(proposal.entry.aliases, ())

    def test_invalid_missing_or_unchanged_terms_do_not_write(self):
        before = self.repository.path.read_bytes()
        for heard, corrected, code in (
            ("", "Clarify", "invalid_term"),
            ("clear if eye", "\nwrong", "invalid_term"),
            ("clear if eye", "x" * 257, "invalid_term"),
            ("x" * 257, "Clarify", "invalid_term"),
            ("absent", "Clarify", "heard_not_found"),
            ("clear if eye", "clear if eye", "no_change"),
        ):
            with self.subTest(heard=heard, corrected=corrected):
                with self.assertRaisesRegex(CorrectionError, code):
                    self.preview(heard, corrected)
        self.assertEqual(self.repository.path.read_bytes(), before)

    def test_full_library_rejects_new_term(self):
        self.dictionary.replace(
            DictionarySnippets(
                dictionary=tuple(DictionaryEntry(str(i)) for i in range(512))
            )
        )
        with self.assertRaisesRegex(CorrectionError, "library_full"):
            self.preview()
        self.assertEqual(len(self.repository.load().dictionary), 512)

    def test_original_read_envelope_is_fully_validated(self):
        before = self.repository.path.read_bytes()
        read = self.read_part
        for field, value in (
            ("context", "other"),
            ("revision", "old"),
            ("id", "other"),
            ("owner", "unknown"),
            ("text", []),
            ("text", "x" * 4001),
            ("nextOffset", True),
            ("nextOffset", 0),
            ("hasMore", "false"),
        ):
            with self.subTest(field=field, value=str(value)[:20]):
                self.service._read_part = lambda *args, field=field, value=value: {
                    **read(*args),
                    field: value,
                }
                with self.assertRaisesRegex(CorrectionError, "history_changed"):
                    self.preview()
        self.assertEqual(self.repository.path.read_bytes(), before)

    def test_nonprogressing_chunk_and_source_work_limit_fail_closed(self):
        self.service._read_part = lambda context, token, offset, field: {
            "context": context,
            "revision": self.source.revision,
            "id": token,
            "owner": "local",
            "text": "",
            "nextOffset": offset,
            "hasMore": True,
        }
        with self.assertRaisesRegex(CorrectionError, "history_changed"):
            self.preview()
        self.service._read_part = self.read_part
        self.original = "x" * 20000
        with patch("history_corrections.MAX_SOURCE_CHARS", 8000):
            with self.assertRaisesRegex(CorrectionError, "source_too_large"):
                self.preview()
        self.assertEqual(self.reads, [0, 4000])

    def test_owner_mismatch_is_rejected_even_if_device_is_the_same(self):
        for owner, record_owner in (("account", "local"), ("local", "account")):
            self.owner = CorrectionIdentity(
                "account-a" if owner == "account" else "local", 1, owner
            )
            self.record_owner = record_owner
            with self.assertRaisesRegex(CorrectionError, "owner_mismatch"):
                self.preview()

    def test_session_change_during_read_cannot_publish_a_proposal(self):
        read = self.read_part

        def changed(*args):
            result = read(*args)
            self.owner = replace(self.owner, generation=1)
            return result

        self.service._read_part = changed
        with self.assertRaisesRegex(CorrectionError, "context_changed"):
            self.preview()

    def test_cancel_expiry_and_repeat_confirmation_do_not_add_twice(self):
        cancelled = self.preview()
        self.service.cancel(cancelled.token)
        with self.assertRaisesRegex(CorrectionError, "expired"):
            self.service.confirm(cancelled.token)
        expired = self.preview()
        self.now = 600
        with self.assertRaisesRegex(CorrectionError, "expired"):
            self.service.confirm(expired.token)
        result = self.service.confirm(self.preview().token)
        self.assertTrue(result.receipt)
        self.assertEqual(len(self.repository.load().dictionary), 1)

    def test_confirmation_revalidates_history_revision(self):
        proposal = self.preview()
        self.source = replace(self.source, revision="new-revision")
        with self.assertRaisesRegex(CorrectionError, "history_changed"):
            self.service.confirm(proposal.token)
        self.assertEqual(self.repository.load().dictionary, ())

    def test_confirmation_rejects_changed_library_and_keeps_external_entry(self):
        proposal = self.preview()
        self.repository.save(
            DictionarySnippets(dictionary=(DictionaryEntry("external"),))
        )
        with self.assertRaisesRegex(CorrectionError, "library_changed"):
            self.service.confirm(proposal.token)
        self.assertEqual(
            self.repository.load().dictionary, (DictionaryEntry("external"),)
        )

    def test_relogin_same_account_invalidates_proposal_and_receipt(self):
        self.owner = CorrectionIdentity("account-a", 1, "account")
        self.record_owner = "account"
        self.dictionary.reload()
        first = self.preview()
        receipt = self.service.confirm(self.preview().token).receipt
        before = self.repository.path.read_bytes()
        self.owner = replace(self.owner, generation=3)
        with self.assertRaisesRegex(CorrectionError, "context_changed"):
            self.service.confirm(first.token)
        self.assertFalse(self.service.can_undo(receipt))
        self.assertEqual(self.repository.path.read_bytes(), before)

    def test_change_account_never_writes_previous_terms_to_current_account(self):
        first = self.preview()
        self.owner = CorrectionIdentity("account-b", 2, "account")
        with self.assertRaisesRegex(CorrectionError, "context_changed"):
            self.service.confirm(first.token)
        self.assertFalse(self.repository.path.exists())
        self.assertEqual(
            LocalDictionarySnippetsRepository(self.root / "local.json")
            .load()
            .dictionary,
            (),
        )

    def test_failed_atomic_replace_leaves_state_unchanged_and_creates_no_receipt(self):
        proposal = self.preview()
        before, state = self.repository.path.read_bytes(), self.dictionary.state
        with patch(
            "dictionary_snippets.os.replace", side_effect=OSError("isolated failure")
        ):
            with self.assertRaisesRegex(CorrectionError, "persistence_failed"):
                self.service.confirm(proposal.token)
        self.assertEqual(self.repository.path.read_bytes(), before)
        self.assertEqual(self.dictionary.state, state)
        self.assertFalse(self.service._receipts)

    def test_equal_content_external_replacement_invalidates_undo(self):
        receipt = self.service.confirm(self.preview().token).receipt
        same = self.repository.load()
        self.repository.save(same)
        self.assertFalse(self.service.can_undo(receipt))
        self.assertEqual(self.service.undo(receipt).status, "undo_unavailable")
        self.assertEqual(self.repository.load(), same)

    def test_later_edit_or_delete_and_recreate_never_gets_undone(self):
        for recreate in (False, True):
            with self.subTest(recreate=recreate):
                self.dictionary.replace(DictionarySnippets.empty())
                receipt = self.service.confirm(self.preview().token).receipt
                if recreate:
                    saved = self.repository.load()
                    self.repository.save(DictionarySnippets.empty())
                    self.repository.save(saved)
                else:
                    self.dictionary.replace(
                        DictionarySnippets(
                            dictionary=(DictionaryEntry("Clarify", aliases=("new",)),)
                        )
                    )
                before = self.repository.path.read_bytes()
                self.assertEqual(self.service.undo(receipt).status, "undo_unavailable")
                self.assertEqual(self.repository.path.read_bytes(), before)

    def test_undo_failure_keeps_receipt_for_safe_retry(self):
        receipt = self.service.confirm(self.preview().token).receipt
        with patch(
            "dictionary_snippets.os.replace", side_effect=OSError("isolated failure")
        ):
            with self.assertRaisesRegex(CorrectionError, "persistence_failed"):
                self.service.undo(receipt)
        self.assertTrue(self.service.can_undo(receipt))
        self.assertEqual(self.service.undo(receipt).status, "undone")

    def test_write_proof_cannot_claim_equal_replacement_after_own_write(self):
        save = self.repository.save

        def competing(state):
            own_proof = save(state)
            save(state)
            return own_proof

        with patch.object(self.repository, "save", side_effect=competing):
            result = self.service.confirm(self.preview().token)
        self.assertEqual(result.status, "saved_without_undo")
        self.assertFalse(result.receipt)
        self.assertEqual(len(self.repository.load().dictionary), 1)

    def test_preview_does_not_create_missing_cache_or_overwrite_invalid_schema(self):
        self.repository.path.unlink()
        self.preview()
        self.assertFalse(self.repository.path.exists())
        self.repository.path.write_text('{"schema_version":99}', encoding="utf-8")
        with self.assertRaisesRegex(CorrectionError, "library_unavailable"):
            self.preview()
        self.assertEqual(self.repository.path.read_text(), '{"schema_version":99}')


if __name__ == "__main__":
    unittest.main()
