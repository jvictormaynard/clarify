"""Explicit history-to-dictionary corrections; never edits history or audio.

The reader must validate history tokens and session generation on every call.
The supplied guard must be the account guard used by the dictionary repository.
It serializes library writes, session changes and this service, in that order.
No transcript is retained: matching uses bounded chunks and a short overlap.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import threading
import time
import unicodedata
import uuid

from dictionary_snippets import (
    DictionaryEntry,
    DictionarySnippets,
    dictionary_file_revision,
)

MAX_SOURCE_CHARS = 1_048_576
MAX_PENDING = 64
TOKEN_LIFETIME = 600


@dataclass(frozen=True)
class CorrectionIdentity:
    context: str
    generation: int
    owner: str


@dataclass(frozen=True)
class CorrectionSource:
    context: str
    revision: str
    id: str


class CorrectionError(ValueError):
    """A content-free code; the Settings adapter owns localized messages."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CorrectionPreview:
    token: str
    heard: str
    entry: DictionaryEntry
    already_exists: bool = False


@dataclass(frozen=True)
class CorrectionResult:
    status: str
    receipt: str = ""


@dataclass(frozen=True)
class _Proposal:
    preview: CorrectionPreview
    source: CorrectionSource
    identity: CorrectionIdentity
    revision: tuple | None
    created: float


@dataclass(frozen=True)
class _Receipt:
    entry: DictionaryEntry
    identity: CorrectionIdentity
    revision: tuple
    created: float


class HistoryDictionaryCorrectionService:
    def __init__(self, dictionary, *, read_part, identity, guard, clock=None):
        self.dictionary = dictionary
        self._read_part = read_part
        self._identity = identity
        self._guard = guard
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._proposals = {}
        self._receipts = {}

    def _current(self, expected=None):
        current = self._identity()
        if (
            not isinstance(current, CorrectionIdentity)
            or not isinstance(current.context, str)
            or not 0 < len(current.context) <= 128
            or type(current.generation) is not int
            or current.generation < 0
            or current.owner not in ("local", "account")
            or (expected is not None and current != expected)
        ):
            raise CorrectionError("context_changed")
        return current

    def _library(self):
        path = Path(self.dictionary.repository.path)
        revision = dictionary_file_revision(path)
        try:
            # Read without reload: account repository reload can seed a cache.
            # Preview must not create a cache or change the service snapshot.
            document = (
                DictionarySnippets.from_mapping(json.loads(path.read_text("utf-8")))
                if revision is not None
                else DictionarySnippets.empty()
            )
        except (OSError, ValueError, TypeError):
            raise CorrectionError("library_unavailable") from None
        if revision != dictionary_file_revision(path):
            raise CorrectionError("library_changed")
        return document, revision

    def _part(self, source, offset, identity):
        if not isinstance(source, CorrectionSource) or any(
            not isinstance(value, str) or not 0 < len(value) <= 128
            for value in (source.context, source.revision, source.id)
        ):
            raise CorrectionError("history_changed")
        try:
            part = self._read_part(source.context, source.id, offset, "transcript")
        except Exception:
            raise CorrectionError("history_changed") from None
        self._current(identity)
        if (
            not isinstance(part, dict)
            or part.get("context") != source.context
            or part.get("revision") != source.revision
            or part.get("id") != source.id
            or part.get("owner") not in ("local", "account")
            or not isinstance(part.get("text"), str)
            or len(part["text"]) > 4000
            or type(part.get("nextOffset")) is not int
            or part["nextOffset"] != offset + len(part["text"])
            or type(part.get("hasMore")) is not bool
            or (part["hasMore"] and not part["text"])
        ):
            raise CorrectionError("history_changed")
        if part["owner"] != identity.owner:
            raise CorrectionError("owner_mismatch")
        return part

    def _contains(self, source, heard, identity):
        offset, overlap = 0, ""
        while offset < MAX_SOURCE_CHARS:
            part = self._part(source, offset, identity)
            if part["nextOffset"] > MAX_SOURCE_CHARS:
                raise CorrectionError("source_too_large")
            text = unicodedata.normalize("NFC", overlap + part["text"])
            # A following chunk can still compose the final Unicode cluster.
            end = len(text)
            if part["hasMore"]:
                while end and unicodedata.combining(text[end - 1]):
                    end -= 1
                end = max(0, end - 1)
                if len(text) - end > 1024:
                    raise CorrectionError("source_too_large")
            if heard in text[:end]:
                return
            if not part["hasMore"]:
                raise CorrectionError("heard_not_found")
            overlap = text[-(len(heard) + 1024) :]
            offset = part["nextOffset"]
        raise CorrectionError("source_too_large")

    def _remember(self, registry, value):
        now = self._clock()
        for token, old in list(registry.items()):
            if now - old.created >= TOKEN_LIFETIME:
                registry.pop(token)
        if len(registry) >= MAX_PENDING:
            registry.pop(next(iter(registry)))
        token = uuid.uuid4().hex
        registry[token] = value
        return token

    def _get(self, registry, token):
        value = registry.get(token) if isinstance(token, str) else None
        if value is None or self._clock() - value.created >= TOKEN_LIFETIME:
            if isinstance(token, str):
                registry.pop(token, None)
            raise CorrectionError("expired")
        return value

    def preview(self, source, context, heard, corrected):
        try:
            if not isinstance(heard, str) or not isinstance(corrected, str):
                raise ValueError()
            if any(char in value for value in (heard, corrected) for char in "\r\n"):
                raise ValueError()
            alias = DictionaryEntry(heard.strip()).term
            correct = DictionaryEntry(corrected.strip()).term
            entry = DictionaryEntry(
                correct,
                aliases=() if alias.casefold() == correct.casefold() else (alias,),
            )
        except (ValueError, TypeError):
            raise CorrectionError("invalid_term") from None
        if alias == entry.term:
            raise CorrectionError("no_change")
        with (
            self._guard(),
            self.dictionary.transaction(expected_context=context),
            self._lock,
        ):
            identity = self._current()
            if identity.context != context:
                raise CorrectionError("context_changed")
            self._contains(source, alias, identity)
            document, revision = self._library()
            if any(
                item.term.casefold() == entry.term.casefold()
                for item in document.dictionary
            ):
                return CorrectionPreview("", alias, entry, already_exists=True)
            try:
                replace(document, dictionary=(*document.dictionary, entry))
            except ValueError:
                raise CorrectionError("library_full") from None
            preview = CorrectionPreview("", alias, entry)
            proposal = _Proposal(preview, source, identity, revision, self._clock())
            token = self._remember(self._proposals, proposal)
            return replace(preview, token=token)

    def confirm(self, token, *, validate=None):
        with self._guard(), self._lock:
            proposal = self._get(self._proposals, token)
            self._proposals.pop(token)
            self._current(proposal.identity)
            self._part(proposal.source, 0, proposal.identity)
            document, revision = self._library()
            if revision != proposal.revision:
                raise CorrectionError("library_changed")
            with self.dictionary.transaction(
                expected_context=proposal.identity.context
            ):
                current = self.dictionary.reload()
                if (
                    current.dictionary != document.dictionary
                    or dictionary_file_revision(Path(self.dictionary.repository.path))
                    != revision
                ):
                    raise CorrectionError("library_changed")
                candidate = replace(
                    current, dictionary=(*current.dictionary, proposal.preview.entry)
                )
                if validate is not None:
                    validate(candidate)
                try:
                    _, published = self.dictionary.replace_with_revision(
                        candidate,
                        expected_context=proposal.identity.context,
                    )
                except Exception:
                    raise CorrectionError("persistence_failed") from None
            # Missing/unverifiable proof never grants a destructive undo.
            if not published or published != dictionary_file_revision(
                Path(self.dictionary.repository.path)
            ):
                return CorrectionResult("saved_without_undo")
            receipt = self._remember(
                self._receipts,
                _Receipt(
                    proposal.preview.entry, proposal.identity, published, self._clock()
                ),
            )
            return CorrectionResult("saved", receipt)

    def can_undo(self, token):
        with self._guard(), self._lock:
            try:
                receipt = self._get(self._receipts, token)
                self._current(receipt.identity)
                _, revision = self._library()
                if revision == receipt.revision:
                    return True
            except (CorrectionError, OSError):
                pass
            if isinstance(token, str):
                self._receipts.pop(token, None)
            return False

    def undo(self, token, *, validate=None):
        with self._guard(), self._lock:
            if not self.can_undo(token):
                return CorrectionResult("undo_unavailable")
            receipt = self._receipts[token]
            with self.dictionary.transaction(expected_context=receipt.identity.context):
                current = self.dictionary.reload()
                if (
                    dictionary_file_revision(Path(self.dictionary.repository.path))
                    != receipt.revision
                ):
                    self._receipts.pop(token)
                    return CorrectionResult("undo_unavailable")
                entries = tuple(
                    item for item in current.dictionary if item != receipt.entry
                )
                if len(entries) != len(current.dictionary) - 1:
                    self._receipts.pop(token)
                    return CorrectionResult("undo_unavailable")
                candidate = replace(current, dictionary=entries)
                if validate is not None:
                    validate(candidate)
                try:
                    self.dictionary.replace(
                        candidate,
                        expected_context=receipt.identity.context,
                    )
                except Exception:
                    raise CorrectionError("persistence_failed") from None
            self._receipts.pop(token)
            return CorrectionResult("undone")

    def cancel(self, token):
        with self._lock:
            self._proposals.pop(token, None)

    def clear(self):
        with self._lock:
            self._proposals.clear()
            self._receipts.clear()
