"""Shared native hotkeys doubles. No runtime setup."""

from __future__ import annotations


class _Function:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class _User32:
    def __init__(self, fail_keys=()):
        self.fail_keys = set(fail_keys)
        self.registered = []
        self.unregistered = []
        self.RegisterHotKey = _Function(self._register)
        self.UnregisterHotKey = _Function(self._unregister)

    def _register(self, _hwnd, hotkey_id, _modifiers, key):
        if key in self.fail_keys:
            return False
        self.registered.append((hotkey_id, key))
        return True

    def _unregister(self, _hwnd, hotkey_id):
        self.unregistered.append(hotkey_id)
        self.registered = [item for item in self.registered if item[0] != hotkey_id]
        return True
