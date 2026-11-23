"""Shared controlled local-asset installation fixture; no model download."""

import threading
from local_asr import LocalASRCancelledError


class FakeInstaller:
    def __init__(self):
        self.requirements_value = {
            "platform": "Windows x64",
            "memory_bytes": 852_000_000,
            "disk_bytes": 510_000_000,
            "download_bytes": 495_584_068,
        }
        self.install_calls = 0
        self.remove_calls = 0
        self.cancel_seen = threading.Event()
        self.remove_started = threading.Event()
        self.remove_cancel_seen = threading.Event()
        self.block_remove = False
        self.release = threading.Event()
        self._status = "not_installed"
        self.status_calls = 0

    def requirements(self):
        return dict(self.requirements_value)

    def status(self):
        self.status_calls += 1
        return {
            "state": self._status,
            "detail": "not installed" if self._status == "not_installed" else "ready",
            "requirements": self.requirements(),
        }

    def install(self, callback=None, cancel_event=None):
        self.install_calls += 1
        if callback:
            callback("download:model", 10, 100)
        while not self.release.wait(0.01):
            if cancel_event is not None and cancel_event.is_set():
                self.cancel_seen.set()
                raise LocalASRCancelledError("cancelled")
        self._status = "installed"
        return self.status()

    def remove(self, cancel_event=None):
        self.remove_calls += 1
        if self.block_remove:
            self.remove_started.set()
            while not self.release.wait(0.01):
                if cancel_event is not None and cancel_event.is_set():
                    self.remove_cancel_seen.set()
                    raise LocalASRCancelledError("cancelled")
        self._status = "not_installed"
        return True
