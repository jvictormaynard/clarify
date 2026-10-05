"""Cache cleanup and MSI boundaries use temporary paths and registry doubles."""

import os
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from portable_update_windows import (
    is_portable_installation,
    prune_portable_cache,
    run_portable_update_helper,
)
from portable_updates import MANIFEST_ASSET, SIGNATURE_ASSET
from test_portable_updates import ReleaseFixture


class PortableWindowsBoundaryTests(unittest.TestCase):
    def test_cleanup_removes_only_old_known_attempts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = root / "update-0.5.1-abcdefgh"
            recent = root / "update-0.5.1-recentab"
            unknown = root / "update-0.5.1-unknowna"
            unrelated = root / "profile"
            for directory in (old, recent, unknown, unrelated):
                directory.mkdir()
                (directory / "Clarify.exe").write_bytes(b"fixture")
            (unknown / "personal.txt").write_text("must stay")
            yesterday = time.time() - 90000
            for directory in (old, unknown, unrelated):
                for path in directory.iterdir():
                    os.utime(path, (yesterday, yesterday))
                os.utime(directory, (yesterday, yesterday))
            prune_portable_cache(root)
            self.assertFalse(old.exists())
            for directory in (recent, unknown, unrelated):
                self.assertTrue((directory / "Clarify.exe").exists())
            self.assertTrue((unknown / "personal.txt").exists())

    def test_msi_owned_path_is_excluded_but_another_portable_path_is_supported(self):
        registry = Mock(REG_SZ=1)
        registry.OpenKey.return_value.__enter__ = Mock(return_value=Mock())
        registry.OpenKey.return_value.__exit__ = Mock(return_value=False)
        target = str(Path(tempfile.gettempdir()) / "fixture-install" / "Clarify.exe")
        with (
            patch("portable_update_windows.sys.platform", "win32"),
            patch("portable_update_windows.sys.frozen", True, create=True),
            patch("portable_update_windows.sys.executable", target),
            patch.dict("sys.modules", winreg=registry),
        ):
            registry.QueryValueEx.return_value = (str(Path(target).parent), 1)
            self.assertFalse(is_portable_installation())
            registry.QueryValueEx.return_value = (str(Path(target).parent / "other"), 1)
            self.assertTrue(is_portable_installation())
            registry.QueryValueEx.side_effect = PermissionError()
            self.assertFalse(is_portable_installation())

    def test_source_execution_does_not_read_msi_registration(self):
        with patch("portable_update_windows.sys.frozen", False, create=True):
            self.assertFalse(is_portable_installation())


class PortableRecoveryLoggingTests(ReleaseFixture):
    def test_failed_log_write_cannot_prevent_restart_of_the_unchanged_installation(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "update-case"
            directory.mkdir()
            target = root / "installed.exe"
            target.write_bytes(b"MZ-old-version")
            (directory / "Clarify.exe").write_bytes(self.binary)
            data, signature = self.encoded()
            (directory / MANIFEST_ASSET).write_bytes(data)
            (directory / SIGNATURE_ASSET).write_bytes(signature)
            plan = {
                "schema_version": 1,
                "nonce": "a" * 32,
                "target": str(target),
                "parent_pid": 123,
                "parent_created": 1,
                "previous_version": "0.5.0",
                "original_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
            path = directory / "plan.json"
            path.write_text(json.dumps(plan))
            identity = Mock(path=target.resolve(), created=1)
            identity.exited.side_effect = (False, True)

            def write(destination, document):
                if destination.name == "armed.json":
                    return
                raise PermissionError("The diagnostic cache is not writable")

            with (
                patch("portable_update_windows.sys.platform", "win32"),
                patch("portable_update_windows.sys.frozen", True, create=True),
                patch("portable_update_windows.update_cache_root", return_value=root),
                patch("portable_update_windows.load_policy", return_value=self.policy),
                patch("portable_update_windows.WindowsProcess", return_value=identity),
                patch("portable_update_windows._write_document", side_effect=write),
                patch(
                    "portable_update_windows.replace_and_restart",
                    side_effect=PermissionError(),
                ),
                patch("portable_update_windows._launch") as launch,
            ):
                self.assertEqual(run_portable_update_helper(path, "0.5.0"), 2)
                launch.assert_called_once_with(target)
