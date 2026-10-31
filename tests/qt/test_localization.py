"""Device language and substitutions, without a device profile or services."""

import unittest


class LocalizationTests(unittest.TestCase):
    def test_qt_translator_is_installed_and_leaves_user_content_unchanged(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QCoreApplication
        from clarify.desktop.qml_localization import ClarifyTranslator

        app = QApplication.instance() or QApplication([])
        for locale, expected in [
            ("pt", "Iniciar gravação"),
            ("en", "Start recording"),
            ("es", "Iniciar grabación"),
        ]:
            translator = ClarifyTranslator(language=locale)
            self.assertTrue(app.installTranslator(translator))
            try:
                self.assertEqual(
                    QCoreApplication.translate("Main", "Start recording"), expected
                )
                self.assertEqual(
                    QCoreApplication.translate("Main", "user content 928"),
                    "user content 928",
                )
            finally:
                app.removeTranslator(translator)
