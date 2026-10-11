"""Device language and substitutions, without a device profile or services."""

import re
import unittest

from shared.localization import catalog, language, translate


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

    def test_supported_device_languages_and_fallback(self):
        for value, expected in [
            ("pt-BR", "pt"),
            ("pt_PT", "pt"),
            ("en-US", "en"),
            ("es-MX", "es"),
            ("de-DE", "en"),
            (None, "en"),
        ]:
            self.assertEqual(language(value), expected)

    def test_shared_auth_labels_and_email_subjects(self):
        for locale, skip, subject in [
            ("pt", "Continuar sem conta", "Seu código de acesso"),
            ("en", "Continue without an account", "Your access code"),
            ("es", "Continuar sin cuenta", "Tu código de acceso"),
        ]:
            self.assertEqual(translate("Continuar sem conta", locale), skip)
            self.assertEqual(translate("email_subject", locale), subject)
            self.assertIn(
                "user@example.test",
                translate(
                    "Digite o código enviado para {v0}. O código vale por 10 minutos.",
                    locale,
                    v0="user@example.test",
                ),
            )

    def test_every_translation_preserves_substitutions(self):
        for source, entry in catalog().items():
            with self.subTest(source=source):
                self.assertEqual(set(entry), {"pt", "en", "es"})
                placeholders = {
                    frozenset(re.findall(r"\{\w+\}", text)) for text in entry.values()
                }
                self.assertEqual(len(placeholders), 1)
                self.assertTrue(all(entry.values()))
