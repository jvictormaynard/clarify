import base64
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@unittest.skipUnless(POWERSHELL, "PowerShell is required for build path tests")
class WindowsBuildPathTests(unittest.TestCase):
    def stage_settings(self, repository, temporary_root, *, check=True):
        environment = os.environ.copy()
        environment["TEMP"] = str(temporary_root)
        result = subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(repository / "scripts" / "build-settings.ps1"),
                "-StageOnly",
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def make_settings_repository(self, root):
        repository = root / "work tree"
        scripts = repository / "scripts"
        scripts.mkdir(parents=True)
        for name in ("build-settings.ps1", "windows-build-paths.ps1"):
            shutil.copyfile(ROOT / "scripts" / name, scripts / name)
        files = {
            "desktop/src/keep.ts": "unchanged",
            "desktop/src/removed.ts": "removed",
            "desktop/src/rename.ts": "renamed",
            "desktop/src/update.ts": "before",
            "desktop/src/styles/tokens.css": "styles",
            "desktop/src/assets/inter/font.woff2": "font",
            "desktop/src-tauri/src/main.rs": "native",
            "shared/i18n.ts": "catalog",
            "shared/ui_strings.json": "{}",
            "shared/usage.ts": "usage",
        }
        for name, content in files.items():
            path = repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            os.utime(path, (946684800, 946684800))
        return repository, files

    @unittest.skipUnless(
        os.name == "nt" and shutil.which("robocopy"), "Windows robocopy is required"
    )
    def test_settings_staging_removes_stale_inputs_and_preserves_unchanged_inputs_and_caches(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, files = self.make_settings_repository(root)
            temporary_root = root / "isolated cache"
            temporary_root.mkdir()
            (paths,) = self.resolve_paths([repository], temporary_root)
            stage_root = Path(paths["SettingsStageRoot"])
            cache_files = [
                stage_root / "desktop" / name / "sentinel.bin"
                for name in (
                    "node_modules",
                    "target",
                    "dist",
                    "test-results",
                    "src-tauri/target",
                )
            ] + [Path(paths["SettingsTarget"]) / "sentinel.bin"]
            for path in cache_files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"retained-cache")
                os.utime(path, (946684800, 946684800))
            cache_times = {path: path.stat().st_mtime_ns for path in cache_files}
            (repository / "shared" / "unneeded.ts").write_text("not an input")
            # WSL checkouts can have a node_modules file instead of a directory.
            (repository / "desktop" / "node_modules").write_text("not an input")

            self.stage_settings(repository, temporary_root)
            with self.subTest("source files and assets"):
                for name, content in files.items():
                    self.assertEqual(
                        (stage_root / name).read_text(encoding="utf-8"), content
                    )
                self.assertFalse((stage_root / "shared" / "unneeded.ts").exists())
            tracked_times = {
                name: (stage_root / name).stat().st_mtime_ns for name in files
            }
            self.stage_settings(repository, temporary_root)
            with self.subTest("unchanged modification times"):
                self.assertEqual(
                    tracked_times,
                    {name: (stage_root / name).stat().st_mtime_ns for name in files},
                )

            (repository / "desktop/src/removed.ts").unlink()
            (repository / "desktop/src/rename.ts").rename(
                repository / "desktop/src/renamed.ts"
            )
            for name in ("desktop/src/update.ts", "shared/usage.ts"):
                (repository / name).write_text("after-update", encoding="utf-8")
                os.utime(repository / name, (978307200, 978307200))
            self.stage_settings(repository, temporary_root)
            with self.subTest("deleted and renamed files"):
                self.assertFalse((stage_root / "desktop/src/removed.ts").exists())
                self.assertFalse((stage_root / "desktop/src/rename.ts").exists())
                self.assertEqual(
                    (stage_root / "desktop/src/renamed.ts").read_text(), "renamed"
                )
            with self.subTest("changed inputs"):
                for name in ("desktop/src/update.ts", "shared/usage.ts"):
                    self.assertEqual((stage_root / name).read_text(), "after-update")
                self.assertEqual(
                    (stage_root / "desktop/src/keep.ts").stat().st_mtime_ns,
                    tracked_times["desktop/src/keep.ts"],
                )
            with self.subTest("excluded caches"):
                for path, modified in cache_times.items():
                    self.assertEqual(path.read_bytes(), b"retained-cache")
                    self.assertEqual(path.stat().st_mtime_ns, modified)

            # Old shared inputs must not survive a change in the required set.
            stale = stage_root / "shared" / "old input" / "obsolete.ts"
            stale.parent.mkdir()
            stale.write_text("obsolete")
            self.stage_settings(repository, temporary_root)
            self.assertFalse(stale.parent.exists())

    @unittest.skipUnless(
        os.name == "nt" and shutil.which("robocopy"), "Windows robocopy is required"
    )
    def test_settings_staging_rejects_a_link_outside_its_root_before_purging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, _ = self.make_settings_repository(root)
            temporary_root = root / "isolated cache"
            temporary_root.mkdir()
            (paths,) = self.resolve_paths([repository], temporary_root)
            stage_root = Path(paths["SettingsStageRoot"])
            self.stage_settings(repository, temporary_root)
            outside = root / "outside"
            outside.mkdir()
            sentinel = outside / "sentinel.bin"
            sentinel.write_bytes(b"must-not-change")
            modified = sentinel.stat().st_mtime_ns
            # Directory junctions do not need Windows symlink privileges.
            import _winapi

            for destination in (
                stage_root / "desktop" / "src" / "linked",
                stage_root / "shared" / "target",
            ):
                with self.subTest(destination=destination):
                    _winapi.CreateJunction(str(outside), str(destination))
                    try:
                        result = self.stage_settings(
                            repository, temporary_root, check=False
                        )
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("reparse point", result.stderr)
                        self.assertEqual(sentinel.read_bytes(), b"must-not-change")
                        self.assertEqual(sentinel.stat().st_mtime_ns, modified)
                    finally:
                        destination.rmdir()

    def resolve_paths(self, repositories, temporary_root, *, cwd=None):
        script = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
. $env:CLARIFY_TEST_BUILD_PATH_HELPER
$repositories = $env:CLARIFY_TEST_BUILD_REPOS | ConvertFrom-Json
$paths = @(foreach ($repository in $repositories) {
    Get-ClarifyWindowsBuildPaths -RepositoryPath $repository
})
ConvertTo-Json -InputObject $paths -Compress
"""
        environment = os.environ.copy()
        environment.update(
            CLARIFY_TEST_BUILD_PATH_HELPER=str(
                ROOT / "scripts" / "windows-build-paths.ps1"
            ),
            CLARIFY_TEST_BUILD_REPOS=json.dumps([str(path) for path in repositories]),
            TEMP=str(temporary_root),
        )
        result = subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                base64.b64encode(script.encode("utf-16-le")).decode("ascii"),
            ],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        paths = json.loads(result.stdout)
        self.assertEqual(len(paths), len(repositories))
        for result_paths in paths:
            self.assertEqual(
                set(result_paths), {"SettingsStageRoot", "SettingsTarget", "DeployRoot"}
            )
        return paths

    def test_same_worktree_reuses_distinct_build_roots_without_creating_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "work tree"
            repository.mkdir()
            temporary_root = root / "build cache"
            paths, repeated = self.resolve_paths(
                [repository, repository], temporary_root
            )

            self.assertEqual(paths, repeated)
            self.assertEqual(len(set(paths.values())), 3)
            for path in paths.values():
                self.assertEqual(Path(path).parent, temporary_root)
                self.assertFalse(Path(path).exists())

    def test_worktrees_with_equal_leaf_names_have_no_shared_build_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "one" / "clarify"
            second = root / "two" / "clarify"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            temporary_root = root / "build cache"

            first_paths, second_paths = self.resolve_paths(
                [first, second], temporary_root
            )

            for name in first_paths:
                with self.subTest(root=name):
                    self.assertNotEqual(first_paths[name], second_paths[name])
            self.assertTrue(set(first_paths.values()).isdisjoint(second_paths.values()))

    def test_equivalent_absolute_and_relative_paths_reuse_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "work tree"
            repository.mkdir()
            (repository / "desktop").mkdir()
            temporary_root = root / "build cache"
            equivalent = str(repository / "desktop") + os.sep + ".." + os.sep
            repositories = [repository, equivalent, "./work tree/"]
            if os.name == "nt":
                repositories.append(str(repository).swapcase())
            expected, *aliases = self.resolve_paths(
                repositories, temporary_root, cwd=root
            )

            for actual in aliases:
                self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
