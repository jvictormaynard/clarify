import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.check_settings_payload import verify_inventory, verify_payload


ROOT = Path(__file__).resolve().parents[1]


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

    def test_all_windows_workflows_validate_and_embed_settings(self):
        for name in ("ci.yml", "community-release.yml", "release.yml"):
            workflow = (ROOT / ".github" / "workflows" / name).read_text()
            with self.subTest(workflow=name):
                self.assertIn("uses: ./.github/actions/settings-build", workflow)
                self.assertIn(
                    "-SettingsExecutable dist\\clarify-settings.exe", workflow
                )
        action = (ROOT / ".github/actions/settings-build/action.yml").read_text()
        for command in (
            "npm ci",
            "npm audit",
            "npm run build",
            "npm test",
            "cargo build --locked",
        ):
            self.assertIn(command, action)

    def test_build_and_deploy_default_to_current_settings(self):
        for name in ("build.ps1", "deploy.ps1"):
            script = (ROOT / "scripts" / name).read_text()
            with self.subTest(script=name):
                self.assertIn("if (-not $SettingsExecutable)", script)
                self.assertIn("'build-settings.ps1'", script)
                normalized = script.index(
                    "$SettingsExecutable = (Resolve-Path -LiteralPath $SettingsExecutable).ProviderPath"
                )
                self.assertLess(normalized, script.index("'--add-binary'"))
        self.assertIn(
            "check_settings_payload.py", (ROOT / "scripts/build.ps1").read_text()
        )

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
