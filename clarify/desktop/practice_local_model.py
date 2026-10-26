"""Check the saved local route without hashing model assets on the Qt thread."""

import threading


def _installed(model, device, cancel_check):
    from local_asr_catalog import installer_for, measured_device, normalize_device

    selected = normalize_device(device)
    if selected == "auto":
        selected = measured_device(model)
    installed = installer_for(model, selected).status(cancel_check=cancel_check)
    if installed.get("state") == "installed":
        return True
    # Match the existing provider's explicit GPU-to-CPU recovery policy.
    return (
        selected.startswith("cuda:")
        and installer_for(model, "cpu").status(cancel_check=cancel_check).get("state")
        == "installed"
    )


class LocalModelReadiness:
    """Cache one read-only check per saved route and practice opening.

    Calls and publications use the Qt scheduler. A replaced check is cancelled;
    at most one asset-verification worker runs at a time. The real provider
    remains responsible for revalidating assets before transcription.
    """

    def __init__(self, scheduler, status=_installed):
        self._scheduler = scheduler
        self._status = status
        self._key = None
        self._value = None
        self._generation = 0
        self._checking = False
        self._closed = False
        self._cancel = threading.Event()

    def invalidate(self):
        self._generation += 1
        self._key = None
        self._value = None
        self._cancel.set()

    def close(self):
        self._closed = True
        self.invalidate()

    def ready(self, model: str, device: str) -> bool | None:
        if self._closed:
            return False
        key = (model, device)
        if key != self._key:
            self.invalidate()
            self._key = key
        if self._value is None and not self._checking:
            generation = self._generation
            cancel = threading.Event()
            self._cancel = cancel
            self._checking = True

            def check():
                try:
                    value = self._status(*key, cancel.is_set) is True
                except Exception:
                    value = False
                self._scheduler.call_soon(lambda: self._finish(generation, value))

            self._scheduler.run_in_background(check)
        return self._value

    def _finish(self, generation, value):
        self._checking = False
        if not self._closed and generation == self._generation:
            self._value = value
