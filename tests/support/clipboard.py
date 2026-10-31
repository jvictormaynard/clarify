"""Reusable clipboard fixtures. This module defines no test cases."""

from __future__ import annotations


from windows_clipboard import CF_UNICODETEXT, ClipboardFormat, ClipboardSnapshot


class FakeClipboardAdapter:
    """Clipboard adapter double with sequence ownership semantics."""

    is_windows = True

    def __init__(self, text="previous"):
        self.sequence_value = 10
        self.state = self._snapshot(text, self.sequence_value)
        self.writes = []
        self.restores = []

    @staticmethod
    def _snapshot(text, sequence):
        return ClipboardSnapshot(
            (
                ClipboardFormat(
                    CF_UNICODETEXT,
                    (str(text) + "\x00").encode("utf-16-le"),
                ),
            ),
            sequence,
        )

    def sequence(self):
        return self.sequence_value

    def snapshot(self):
        return self.state

    def text(self):
        return self.state.text

    def write_text(self, text):
        self.sequence_value += 1
        self.state = self._snapshot(text, self.sequence_value)
        self.writes.append(str(text))
        return True

    def restore(self, snapshot):
        self.sequence_value += 1
        self.state = ClipboardSnapshot(snapshot.formats, self.sequence_value)
        self.restores.append(snapshot)
        return True

    def restore_if_owned(self, snapshot, expected_sequence, expected_text):
        if (
            self.sequence() != expected_sequence
            or self.text() != expected_text
            or not snapshot.restorable
        ):
            return False
        return self.restore(snapshot)

    def external_write(self, text):
        self.write_text(text)
