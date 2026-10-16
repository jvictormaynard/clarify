"""Small Settings snapshots and explicit, bounded history reads."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid

_HEX = re.compile(r"[a-f0-9]{32,64}\Z")
_CHANGED = "O histórico mudou. Atualize e tente novamente."


class HistoryView:
    def __init__(self, history):
        self.history = history
        self._salt = uuid.uuid4().hex
        self._lock = threading.RLock()
        self._key = None
        self._rows = []
        self._items = {}
        self._cursors = {}

    def snapshot(self):
        """Only stat files; regular Settings polling never parses transcripts."""
        account = self.history.account
        with account._lock:
            owner = account.history_identity()
            identity = [self._salt, account._generation, repr(owner)]
            context = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
            paths = [self.history.local.path]
            if owner:
                paths.append(self.history._path(owner))
            stamps = []
            for path in paths:
                try:
                    stat = path.stat()
                    stamps.append(
                        [
                            stat.st_mtime_ns,
                            stat.st_ctime_ns,
                            stat.st_size,
                            stat.st_dev,
                            stat.st_ino,
                        ]
                    )
                except FileNotFoundError:
                    stamps.append(None)
                except OSError:
                    stamps.append("unavailable")
            revision = hashlib.sha256(
                (context + json.dumps(stamps)).encode()
            ).hexdigest()
            return {"context": context, "revision": revision}

    def _check(self, context):
        if not isinstance(context, str) or not _HEX.fullmatch(context):
            raise ValueError("Invalid history context")
        current = self.snapshot()
        if context != current["context"]:
            raise ValueError(_CHANGED)
        return current

    def page(self, context, cursor):
        if not isinstance(cursor, str) or (cursor and not _HEX.fullmatch(cursor)):
            raise ValueError("Invalid history cursor")
        with (
            self.history.account._lock,
            self._lock,
            self.history._lock,
            self.history.local._lock,
        ):
            current = self._check(context)
            key = (current["context"], current["revision"])
            if key != self._key:
                self._rows = [
                    (uuid.uuid4().hex, prefix + record.id, record)
                    for prefix, record in self.history.list_items(display=True)
                ]
                # Legacy migration can replace the local document once.
                current = self.snapshot()
                self._key = (current["context"], current["revision"])
                self._items = {
                    token: (item_id, record) for token, item_id, record in self._rows
                }
                self._cursors = {}
            if cursor:
                if cursor not in self._cursors:
                    raise ValueError(_CHANGED)
                offset = self._cursors[cursor]
            else:
                offset = 0
            rows = self._rows[offset : offset + 20]
            entries = []
            for token, _, record in rows:
                text = (
                    record.refined_text
                    if record.refined_text is not None
                    else record.raw_text or ""
                )
                entries.append(
                    {
                        "id": token,
                        "timestamp": record.timestamp.timestamp(),
                        "text": text[:500],
                        "truncated": len(text) > 500,
                        "sourceDevice": record.source_device or "desktop",
                    }
                )
            next_offset = offset + len(rows)
            next_cursor = ""
            if next_offset < len(self._rows):
                next_cursor = uuid.uuid4().hex
                # A bounded cursor registry also makes arbitrary offsets opaque.
                if len(self._cursors) >= 2048:
                    self._cursors.pop(next(iter(self._cursors)))
                self._cursors[next_cursor] = next_offset
            return {
                **current,
                "entries": entries,
                "cursor": next_cursor,
                "hasMore": bool(next_cursor),
            }

    def _resolve(self, context, token):
        current = self._check(context)
        if not isinstance(token, str) or not _HEX.fullmatch(token):
            raise ValueError("Invalid history item")
        if (
            self._key != (current["context"], current["revision"])
            or token not in self._items
        ):
            raise ValueError(_CHANGED)
        return self._items[token]

    def text_part(self, context, token, offset, field):
        if type(offset) is not int or offset < 0 or field not in ("text", "transcript"):
            raise ValueError("Invalid history text request")
        with self.history.account._lock, self._lock:
            _, record = self._resolve(context, token)
            text = (
                record.raw_text or ""
                if field == "transcript"
                else (
                    record.refined_text
                    if record.refined_text is not None
                    else record.raw_text or ""
                )
            )
            if offset > len(text):
                raise ValueError("Invalid history text offset")
            # An astral code point can use 12 bytes after JSON ASCII escaping.
            # This stays below 48 KiB plus the small response envelope.
            chunk = text[offset : offset + 4000]
            next_offset = offset + len(chunk)
            return {
                "context": context,
                "id": token,
                "text": chunk,
                "nextOffset": next_offset,
                "hasMore": next_offset < len(text),
            }

    def delete(self, context, token):
        with self.history.account._lock, self._lock:
            item_id, _ = self._resolve(context, token)
            self.history.delete(item_id)

    def clear(self, context):
        with self.history.account._lock, self._lock:
            self._check(context)
            self.history.clear()
