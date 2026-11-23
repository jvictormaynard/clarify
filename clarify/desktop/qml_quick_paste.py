"""Focus-safe, explicitly requested paste from the compact quick menu."""

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot
from writing_styles import windows_executable_key


class QuickPasteController(QObject):
    _targetReady = Signal(int, object)

    def __init__(self, clipboard, dispatch, windows, hide, parent=None):
        super().__init__(parent)
        self.clipboard = clipboard
        self._macos = getattr(clipboard, "platform_name", "") == "Darwin"
        self.dispatch = dispatch
        self.windows = windows
        self.hide = hide
        self.excluded_executable = lambda: ""
        self.target = None
        self._poll_pending = False
        self._target_generation = 0
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        if self._macos:
            self.timer.timeout.connect(self._poll_target)
            self._targetReady.connect(
                self._accept_target, Qt.ConnectionType.QueuedConnection
            )
        else:
            self.timer.timeout.connect(self.remember_target)
            self.remember_target()
        self.timer.start()

    def capture_target(self):
        return self.remember_target()

    def _poll_target(self):
        if self._poll_pending or any(window.isActive() for window in self.windows()):
            return
        self._poll_pending = True
        generation = self._target_generation

        def capture():
            target = None
            try:
                import objc

                with objc.autorelease_pool():
                    target = self.clipboard.capture_target()
            except (ImportError, OSError, RuntimeError):
                pass
            finally:
                self._targetReady.emit(generation, target)

        self.dispatch(capture)

    @Slot(int, object)
    def _accept_target(self, generation, target):
        self._poll_pending = False
        if generation == self._target_generation:
            windows = self.windows()
            if not any(window.isActive() for window in windows):
                self._remember(target, windows)

    def remember_target(self):
        self._target_generation += 1
        # Never remember the menu, settings, or the overlay as a paste target.
        windows = self.windows()
        if any(window.isActive() for window in windows):
            return self.target
        return self._remember(self.clipboard.capture_target(), windows)

    def _remember(self, target, windows):
        if target is None:
            return None
        executable = self._executable_key(target.executable)
        if executable is None:
            return None
        if executable == self._executable_key(self.excluded_executable()):
            return self.target
        if self._macos or target.window not in {
            int(window.winId()) for window in windows
        }:
            self.target = target
            return target
        return None

    def _executable_key(self, executable):
        if not self._macos:
            return windows_executable_key(executable)
        if not executable or not Path(executable).is_absolute():
            return None
        try:
            return Path(executable).resolve()
        except (OSError, RuntimeError, ValueError):
            return None

    def paste(self, text, finished):
        self.remember_target()
        target = self.target
        self.hide()

        def publish():
            try:
                if target is not None:
                    self.clipboard.activate(target)
                # This gateway rechecks focus before writing and before paste.
                # A changed/closed target falls back to copy, never blind paste.
                result = self.clipboard.write_dictation_result(
                    target, text, allow_unconfirmed=False
                )
                finished(getattr(result, "value", str(result)))
            except Exception:
                finished("failed")

        self.dispatch(publish)
