import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.check_settings_payload import verify_inventory, verify_payload
from scripts.desktop_payload import MANIFEST, REQUIRED, manifest_bytes, payload_manifest


ROOT = Path(__file__).resolve().parents[2]


class SettingsPackagingTests(unittest.TestCase):
    def test_inventory_matches_archive_and_executable(self):
        from PyInstaller.archive.writers import CArchiveWriter

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "clarify-settings.exe"
            settings.write_bytes(b"synthetic-settings-payload")
            sbom = root / "Clarify-settings.sbom.json"
            sbom.write_text(
                json.dumps(
                    {
                        "metadata": {
                            "component": {
                                "hashes": [
                                    {
                                        "alg": "SHA-256",
                                        "content": hashlib.sha256(
                                            settings.read_bytes()
                                        ).hexdigest(),
                                    }
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            notice = root / "Clarify-settings-NOTICES.txt"
            notice.write_text("Synthetic license notice", encoding="utf-8")
            package = root / "test.pkg"
            CArchiveWriter(
                str(package),
                [
                    (file.name, str(file), True, "b")
                    for file in (settings, sbom, notice)
                ],
                pylib_name="python312.dll",
            )
            verify_inventory(package, settings)
            settings.write_bytes(b"different-build")
            with self.assertRaisesRegex(ValueError, "different executable"):
                verify_inventory(package, settings)
            notice.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inventory mismatch"):
                verify_inventory(package, settings)
            notice.unlink()
            with self.assertRaises(FileNotFoundError):
                verify_inventory(package, settings)

    def test_real_archive_payload_round_trip(self):
        from PyInstaller.archive.writers import CArchiveWriter

        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "clarify-settings.exe"
            package = Path(directory) / "test.pkg"
            settings.write_bytes(b"synthetic-settings-payload")
            CArchiveWriter(
                str(package),
                [(settings.name, str(settings), True, "b")],
                pylib_name="python312.dll",
            )
            verify_payload(package, settings)
            settings.write_bytes(b"different-build")
            with self.assertRaisesRegex(ValueError, "differs"):
                verify_payload(package, settings)

    def test_build_and_deploy_default_to_current_settings(self):
        for name in ("build.ps1", "deploy.ps1"):
            script = (ROOT / "scripts" / name).read_text()
            with self.subTest(script=name):
                self.assertIn(
                    "if (-not $SettingsExecutable -and -not $DesktopShellDirectory)",
                    script,
                )
                self.assertIn("'build-desktop.ps1'", script)
                self.assertIn('"${DesktopShellDirectory};desktop-shell"', script)
                normalized = script.index(
                    "$SettingsExecutable = (Resolve-Path -LiteralPath $SettingsExecutable).ProviderPath"
                )
                self.assertLess(normalized, script.index("'--add-binary'"))
        self.assertIn(
            "check_settings_payload.py", (ROOT / "scripts/build.ps1").read_text()
        )

    def test_electron_archive_binds_every_runtime_and_renderer_file(self):
        from PyInstaller.archive.writers import CArchiveWriter

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shell = root / "desktop-shell"
            for name in REQUIRED:
                file = shell / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b"isolated Electron fixture")
            manifest = root / MANIFEST
            manifest.write_bytes(manifest_bytes(payload_manifest(shell)))
            bom = root / "Clarify-settings.sbom.json"
            bom.write_text(
                json.dumps(
                    {
                        "metadata": {
                            "component": {
                                "hashes": [
                                    {
                                        "alg": "SHA-256",
                                        "content": hashlib.sha256(
                                            manifest.read_bytes()
                                        ).hexdigest(),
                                    }
                                ]
                            }
                        }
                    }
                )
            )
            notice = root / "Clarify-settings-NOTICES.txt"
            notice.write_text("fixture license")
            entries = [
                (
                    "desktop-shell/" + file.relative_to(shell).as_posix(),
                    str(file),
                    True,
                    "x",
                )
                for file in shell.rglob("*")
                if file.is_file()
            ]
            package = root / "desktop.pkg"
            CArchiveWriter(
                str(package),
                [
                    *entries,
                    *[
                        (file.name, str(file), True, "x")
                        for file in (manifest, bom, notice)
                    ],
                ],
                pylib_name="python312.dll",
            )
            verify_payload(package, shell)
            verify_inventory(package, shell)
            ambiguous = root / "ambiguous.pkg"
            CArchiveWriter(
                str(ambiguous),
                [
                    *entries,
                    (
                        "DESKTOP-SHELL/resources/app/dist/index.html",
                        str(shell / "resources/app/dist/index.html"),
                        True,
                        "x",
                    ),
                    (manifest.name, str(manifest), True, "x"),
                ],
                pylib_name="python312.dll",
            )
            with self.assertRaisesRegex(ValueError, "duplicate Windows paths"):
                verify_payload(ambiguous, shell)
            # A correct executable alone must not hide an old renderer or DLL.
            (shell / "resources/app/dist/index.html").write_text("new renderer")
            with self.assertRaisesRegex(ValueError, "manifest differs"):
                verify_payload(package, shell)
            (shell / "LICENSE").unlink()
            with self.assertRaisesRegex(ValueError, "missing runtime"):
                payload_manifest(shell)

    def test_payload_must_exist_and_match(self):
        # A fake archive avoids starting or modifying any installed executable.
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "clarify-settings.exe"
            settings.write_bytes(b"settings-build")
            with patch("PyInstaller.archive.readers.CArchiveReader") as reader:
                archive = Mock()
                reader.return_value = archive
                archive.extract.return_value = b"settings-build"
                verify_payload(Path("unused.exe"), settings)
                archive.extract.assert_called_with("clarify-settings.exe")
                archive.extract.return_value = b"old-settings"
                with self.assertRaisesRegex(ValueError, "differs"):
                    verify_payload(Path("unused.exe"), settings)
                archive.extract.side_effect = KeyError("missing")
                with self.assertRaisesRegex(ValueError, "no Settings"):
                    verify_payload(Path("unused.exe"), settings)

    def test_changelog_has_one_unreleased_section(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(changelog.count("## [Unreleased]"), 1)


if __name__ == "__main__":
    unittest.main()
