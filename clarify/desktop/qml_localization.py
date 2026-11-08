"""Apply the shared device-language catalog at the Qt presentation boundary."""

from PySide6.QtCore import QTranslator

from shared.localization import catalog, device_language


class ClarifyTranslator(QTranslator):
    def __init__(self, parent=None, *, language=None):
        super().__init__(parent)
        self.language = language or device_language()

    def translate(self, context, sourceText, disambiguation=None, n=-1):
        return catalog().get(sourceText, {}).get(self.language, sourceText)

    def isEmpty(self):
        return False


def install_translations(application):
    translator = ClarifyTranslator(application)
    application.installTranslator(translator)
    # Qt stores only a pointer. Keep the Python wrapper alive until shutdown.
    application.clarify_translator = translator
