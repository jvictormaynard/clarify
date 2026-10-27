"""Device language and substitutions, without a device profile or services."""

import re
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.localization import catalog, language, translate
from scripts import sync_locales


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


class NativeCatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "shared").mkdir()
        native = self.root / "mobile/native"
        native.mkdir(parents=True)
        (native / "Screen.swift").write_text(
            'let title = L("Shared")', encoding="utf-8"
        )
        self.catalog = {
            "Shared": {"pt": "Comum", "en": "Shared", "es": "Común"},
            "Desktop": {"pt": "Desktop", "en": "Desktop", "es": "Desktop"},
        }
        self.write_catalog()
        self.write_scope(["Desktop"])
        root = patch.object(sync_locales, "ROOT", self.root)
        root.start()
        self.addCleanup(root.stop)

    def write_catalog(self):
        (self.root / "shared/ui_strings.json").write_text(
            json.dumps(self.catalog, ensure_ascii=False), encoding="utf-8"
        )

    def write_scope(self, keys):
        (self.root / "shared/desktop_ui_keys.json").write_text(
            json.dumps(keys), encoding="utf-8"
        )

    def test_desktop_copy_does_not_change_native_output_but_unknown_copy_does(self):
        before = sync_locales.generated()
        self.catalog["Desktop"]["en"] = "Desktop settings"
        self.write_catalog()
        self.assertEqual(sync_locales.generated(), before)
        self.catalog["New"] = {"pt": "Novo", "en": "New", "es": "Nuevo"}
        self.write_catalog()
        self.assertNotEqual(sync_locales.generated(), before)

    def test_desktop_scope_cannot_hide_a_mobile_translation(self):
        self.write_scope(["Shared"])
        with self.assertRaisesRegex(ValueError, "mobile"):
            sync_locales.generated()

    def test_invalid_scope_and_incomplete_translations_fail_validation(self):
        for keys in (["Missing"], ["Desktop", "Desktop"], "Desktop"):
            with self.subTest(keys=keys):
                self.write_scope(keys)
                with self.assertRaises(ValueError):
                    sync_locales.generated()
        self.write_scope(["Desktop"])
        self.catalog["Desktop"].pop("es")
        self.write_catalog()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            sync_locales.generated()
