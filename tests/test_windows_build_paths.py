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
