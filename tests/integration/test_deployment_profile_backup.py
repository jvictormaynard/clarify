"""Offline deployment copies: data coverage, privacy and fail-closed behavior."""

import json
import os
import shutil
import subprocess
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from scripts import deployment_profile_backup as backup


class DeploymentProfileBackupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.profile = self.root / "profile"
        self.destination = self.root / "backups"
        self.profile.mkdir()
        self.destination.mkdir()

    def create(self):
        return backup.create_backup(
            self.profile, self.destination, exclusive_access=True
        )

    def test_complete_private_copy_includes_unknown_hidden_and_expired_audio(self):
        files = {
            "config.json": b'{"fake": true}',
            "secrets.dpapi.json": b"synthetic ciphertext",
            ".unknown": b"future artifact",
            "nested/history.sqlite-wal": b"uncheckpointed data",
            "clarify-recording-interrupted.wav": b"interrupted",
            "experimental-audio/clarify-benchmark-" + "a" * 32 + ".wav": b"old audio",
        }
        for name, content in files.items():
            path = self.profile / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            os.utime(path, (946684800, 946684800))
        (self.profile / "empty").mkdir()
        first = self.create()
        second = self.create()
        self.assertNotEqual(first, second)
        manifest = json.loads((first / "manifest.json").read_text())
        self.assertTrue(manifest["complete"])
        self.assertEqual(set(manifest["files"]), set(files))
        for name, content in files.items():
            self.assertEqual((first / "profile" / name).read_bytes(), content)
            self.assertEqual((self.profile / name).read_bytes(), content)
            self.assertEqual((first / "profile" / name).stat().st_mtime, 946684800)
        self.assertTrue((first / "profile/empty").is_dir())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o700)
            self.assertEqual(
                stat.S_IMODE((first / "profile/config.json").stat().st_mode), 0o600
            )

    def test_requires_exclusive_access_and_disjoint_explicit_existing_directories(self):
        with self.assertRaises(backup.BackupError):
            backup.create_backup(self.profile, self.destination, exclusive_access=False)
        for destination in (
            self.profile,
            self.profile / "nested",
            self.root,
            Path("relative"),
        ):
            with (
                self.subTest(destination=destination),
                self.assertRaises((OSError, backup.BackupError)),
            ):
                backup.create_backup(self.profile, destination, exclusive_access=True)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_refuses_links_in_profile_and_path_ancestors(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "data").write_bytes(b"outside")
        link = self.profile / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation is unavailable")
        with self.assertRaises(backup.BackupError):
            self.create()
        link.unlink()
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(backup.BackupError):
            backup.create_backup(
                alias / "profile", self.destination, exclusive_access=True
            )
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_no_completion_after_copy_omission_corruption_or_concurrent_change(self):
        (self.profile / "data").write_bytes(b"original")
        original = backup.shutil.copyfileobj
        for fault in ("omit", "corrupt", "modify", "add"):
            with self.subTest(fault=fault):
                (self.profile / "data").write_bytes(b"original")
                (self.profile / "new").unlink(missing_ok=True)

                def copy(source, output):
                    if fault == "corrupt":
                        output.write(b"corrupt")
                    elif fault != "omit":
                        original(source, output)
                    if fault == "modify":
                        (self.profile / "data").write_bytes(b"modified")
                    elif fault == "add":
                        (self.profile / "new").write_bytes(b"new")

                with patch.object(backup.shutil, "copyfileobj", side_effect=copy):
                    with self.assertRaises((backup.BackupError, OSError)):
                        self.create()
                self.assertEqual(list(self.destination.glob("*/manifest.json")), [])

    def test_concurrent_deletion_and_manifest_write_failure_never_publish_completion(
        self,
    ):
        (self.profile / "data").write_bytes(b"original")
        inventory = backup._inventory

        def remove_before_final_inventory(path):
            if path == self.profile and list(self.destination.glob("*/profile/data")):
                (self.profile / "data").unlink()
            return inventory(path)

        with patch.object(
            backup, "_inventory", side_effect=remove_before_final_inventory
        ):
            with self.assertRaises(backup.BackupError):
                self.create()
        (self.profile / "data").write_bytes(b"original")
        with patch.object(backup.json, "dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.create()
        self.assertEqual(list(self.destination.glob("*/manifest.json")), [])

    def test_deploy_gates_replacement_and_restart_on_verified_backup(self):
        source = (
            Path(__file__).resolve().parents[2] / "scripts/deploy.ps1"
        ).read_text()
        stop = source.index("$taskProcess.WaitForExit(10000)")
        path_safety = source.index("$taskBackupRoot =")
        self.assertLess(path_safety, source.index("'setup.ps1'"))
        self.assertLess(path_safety, source.index("Remove-Item"))
        termination = source.index("$taskProcess | Stop-Process")
        identity = source.index("$taskCurrent.CreationDate -ne")
        self.assertLess(source.index("$null = $taskProcess.Handle"), identity)
        self.assertLess(identity, termination)
        self.assertIn("$taskCurrent.ExecutablePath -ne", source[identity:termination])
        self.assertIn("$taskCurrent.ParentProcessId -ne", source[identity:termination])
        self.assertIn(
            "throw 'A process identity changed.", source[identity:termination]
        )
        copy = source.index("'deployment_profile_backup.py'")
        failure = source.index("if ($LASTEXITCODE -ne 0)", copy)
        replacement = source.index("Move-Item -LiteralPath $desktopShellTarget", copy)
        restart = source.index("'explorer.exe'", copy)
        self.assertLess(stop, copy)
        self.assertLess(copy, failure)
        self.assertLess(failure, replacement)
        self.assertLess(replacement, restart)
        self.assertIn("throw 'The profile backup failed.", source[failure:replacement])

    @unittest.skipUnless(
        os.name == "nt" and shutil.which("powershell.exe"),
        "Windows ACL acceptance requires Windows PowerShell",
    )
    def test_windows_backup_has_only_current_user_in_protected_acl(self):
        (self.profile / "data").write_bytes(b"synthetic")
        attempt = self.create()
        script = """
$acl = Get-Acl -LiteralPath $env:CLARIFY_BACKUP_ACL_TEST
[pscustomobject]@{
    Protected = $acl.AreAccessRulesProtected
    Rules = @($acl.Access | ForEach-Object {
        [pscustomobject]@{
            Sid = $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
            Rights = [int]$_.FileSystemRights
            Inherited = $_.IsInherited
        }
    })
    CurrentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
} | ConvertTo-Json -Depth 5 -Compress
"""
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env=dict(os.environ, CLARIFY_BACKUP_ACL_TEST=str(attempt)),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        acl = json.loads(result.stdout)
        self.assertTrue(acl["Protected"])
        self.assertEqual(
            acl["Rules"],
            [{"Sid": acl["CurrentSid"], "Rights": 2032127, "Inherited": False}],
        )

    def test_private_acl_failure_prevents_copy(self):
        with patch.object(backup, "_make_private", side_effect=OSError("denied")):
            with self.assertRaises(OSError):
                self.create()
        self.assertEqual(list(self.destination.glob("*/profile")), [])


if __name__ == "__main__":
    unittest.main()
