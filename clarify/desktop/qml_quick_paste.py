"""Focus-safe, explicitly requested paste from the compact quick menu."""

from PySide6.QtCore import QObject, QTimer


class QuickPasteController(QObject):
    def __init__(self, clipboard, dispatch, windows, hide, parent=None):
        super().__init__(parent)
        self.clipboard = clipboard
        self.dispatch = dispatch
        self.windows = windows
        self.hide = hide
        self.target = None
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.remember_target)
        self.remember_target()
        self.timer.start()

    def capture_target(self):
        self.remember_target()
        return self.target

    def remember_target(self):
        # Never remember the menu, settings, or the overlay as a paste target.
        windows = self.windows()
        if any(window.isActive() for window in windows):
            return
        target = self.clipboard.capture_target()
        if target is not None and target.window not in {
            int(window.winId()) for window in windows
        }:
            self.target = target

    def paste(self, text, finished):
        self.remember_target()
        target = self.target
        self.hide()

        def publish():
            try:
                if target is not None:
                    self.clipboard.activate(target)
                # This gateway rechecks focus before writing and before Ctrl+V.
                # A changed/closed target falls back to copy, never blind paste.
                result = self.clipboard.write_dictation_result(target, text)
                finished(getattr(result, "value", str(result)))
            except Exception:
                finished("failed")

        self.dispatch(publish)
