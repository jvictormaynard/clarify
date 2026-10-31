import json
import unittest
from pathlib import Path

from version import __version__


ROOT = Path(__file__).resolve().parents[2]


class RepositorySafetyTests(unittest.TestCase):
    def test_dependabot_uses_versioning_strategy_only_where_supported(self):
        config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        pip_section, actions_section = config.split(
            "  - package-ecosystem: github-actions", 1
        )
        self.assertIn("versioning-strategy: increase-if-necessary", pip_section)
        self.assertNotIn("versioning-strategy:", actions_section)

    def test_windows_builds_never_bundle_dotenv(self):
        scripts = [
            ROOT / "scripts" / "build.ps1",
            ROOT / "scripts" / "deploy.ps1",
            ROOT / "build.bat",
        ]
        for script in scripts:
            content = script.read_text(encoding="utf-8")
            self.assertNotIn('"--add-data", "${envFile};."', content)
            self.assertNotIn('--add-data ".env;."', content)

    def test_deploy_stages_all_python_modules(self):
        content = (ROOT / "scripts" / "deploy.ps1").read_text(encoding="utf-8")
        self.assertIn(
            '$sourceQmlPython = Join-Path $sourceDir "clarify\\desktop"', content
        )
        self.assertIn('Join-Path $repoQmlPython "qt_shell.py"', content)
        self.assertIn('"workflow_provider.py",', content)
        self.assertNotIn('Join-Path $repoRoot "*.py"', content)
        self.assertIn('$repoQml = Join-Path $repoQmlPython "qml"', content)
        self.assertIn("Copy-Item $repoQml $qml -Recurse -Force", content)
        self.assertIn("${distribution};distribution", content)
        self.assertIn('Join-Path $repoRoot "local_asr_manifest.json"', content)
        self.assertIn('Join-Path $repoRoot "licenses"', content)
        self.assertIn('"${localAsrManifest};."', content)
        self.assertIn('"${localAsrLicenses};licenses"', content)
        self.assertNotIn('Join-Path $soxDir "*.txt"', content)
        self.assertNotIn('Join-Path $soxDir "LICENSE.GPL.txt"', content)

    def test_deploy_uses_isolated_repository_requirements(self):
        content = (ROOT / "scripts" / "deploy.ps1").read_text(encoding="utf-8")
        self.assertIn('$venvDir = Join-Path $buildRoot "venv"', content)
        self.assertIn(
            '$requirementsFile = Join-Path $requirementsDir "requirements-dev.txt"',
            content,
        )
        self.assertIn('"-r", $requirementsFile, "-c", $lockFile', content)
        self.assertIn("Build dependencies: $dependencyVersions", content)
        self.assertNotIn(
            '"requests", "sounddevice", "customtkinter", "Pillow", "pyinstaller"',
            content,
        )
        self.assertIn("'PySide6-Essentials'", content)

    def test_windows_builds_isolate_host_dll_paths_and_smoke_test_imports(self):
        entrypoint = (ROOT / "clarify" / "desktop" / "qml_app.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('CLARIFY_IMPORT_SMOKE_TEST") == "1"', entrypoint)

        for name in ("build.ps1", "deploy.ps1"):
            content = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            with self.subTest(script=name):
                self.assertIn("function Get-IsolatedBuildPath", content)
                self.assertIn("codex-runtimes", content)
                self.assertIn("$env:PATH = Get-IsolatedBuildPath", content)
                self.assertIn('$env:CLARIFY_IMPORT_SMOKE_TEST = "1"', content)
                self.assertIn("Clarify import smoke test failed", content)

    def test_production_entrypoint_and_dependencies_are_qml_only(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        build = (ROOT / "scripts" / "build.ps1").read_text(encoding="utf-8")
        deploy = (ROOT / "scripts" / "deploy.ps1").read_text(encoding="utf-8")
        start_bat = (ROOT / "start.bat").read_text(encoding="utf-8")
        start_sh = (ROOT / "start.sh").read_text(encoding="utf-8")
        package = (ROOT / "package.json").read_text(encoding="utf-8")

        self.assertIn("PySide6-Essentials>=6.8,<7", requirements)
        self.assertNotIn("PySide6>=", requirements)
        self.assertNotIn("customtkinter", requirements.casefold())
        for content in (build, deploy):
            self.assertIn("qml_app.py", content)
            self.assertNotIn('Join-Path $repoRoot "app.py"', content)
        for content in (start_bat, start_sh):
            self.assertIn("qml_app.py", content)
            self.assertNotIn(" app.py", content)
        self.assertIn('"--add-data", "${qmlRoot};qml"', build)
        self.assertIn('"--add-data", "${qml};qml"', deploy)
        for module in ("qml_bridge", "qml_runtime", "qml_settings", "qt_shell"):
            self.assertIn(f'"--hidden-import", "{module}"', build)
            self.assertIn(f'"--hidden-import", "{module}"', deploy)
        self.assertIn('Get-ChildItem $qmlPythonRoot -Filter "qml_*.py" -File', build)
        self.assertIn('Get-ChildItem $repoQmlPython -Filter "qml_*.py" -File', deploy)
        for content in (build, deploy):
            self.assertIn('if ($qmlModule.BaseName -ne "qml_app")', content)
        self.assertEqual(
            json.loads(package)["scripts"]["check"],
            "python scripts/ci.py --task static",
        )
        self.assertNotIn("compileall -q app.py", package)

    def test_build_setup_bootstraps_the_locked_toolchain_inside_venv(self):
        content = (ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8")
        self.assertIn('"install_bootstrap_tools.py"', content)
        self.assertIn('"requirements-lock-windows.txt"', content)
        self.assertIn('"Could not install the pinned bootstrap tools."', content)

    def test_pre_commit_hook_formats_only_staged_python_files(self):
        hook = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
        formatter = (ROOT / "scripts" / "format_staged.py").read_text(encoding="utf-8")
        package = (ROOT / "package.json").read_text(encoding="utf-8")
        setup = (ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8")
        self.assertIn("scripts/format_staged.py", hook)
        self.assertIn('"--cached"', formatter)
        self.assertIn('"--diff-filter=ACMR"', formatter)
        self.assertIn('"format", "--force-exclude"', formatter)
        self.assertIn('"add", "--"', formatter)
        self.assertIn('"setup-hooks": "git config core.hooksPath .githooks"', package)
        self.assertIn('"config", "core.hooksPath", ".githooks"', setup)

    def test_signature_verification_requires_independent_rfc3161_check(self):
        content = (ROOT / "scripts" / "verify-signature.ps1").read_text(
            encoding="utf-8"
        )
        for required in (
            "Get-AuthenticodeSignature",
            "signtool.exe",
            "CryptQueryObject",
            "CryptMsgGetParam",
            "CmsgSignerUnauthAttrParam",
            "Marshal.SizeOf",
            "IntPtr.Add",
            "CertQueryContentPkcs7SignedEmbed",
            "CertQueryFormatBinary",
            "1.2.840.113549.1.9.16.2.14",
            "1.2.840.113549.1.9.6",
            "verify /pa /all /tw",
            "Timestamp status: $timestampStatus",
            "Timestamp protocol: $timestampProtocol",
            "Timestamp signer:",
            "Timestamp thumbprint:",
        ):
            self.assertIn(required, content)
        self.assertNotIn("Index  Algorithm  Timestamp", content)
        self.assertNotIn("$timestampProtocols", content)
        self.assertNotIn("/v", content)
        self.assertNotIn("Marshal.ReadIntPtr", content)

    def test_destructive_installer_smoke_is_hosted_runner_only(self):
        content = (ROOT / "scripts" / "test-installer.ps1").read_text(encoding="utf-8")
        guard_call = content.index("Assert-DisposableHostedRunner\n\n$baseline")
        first_write = content.index("New-Item $configDirectory")
        clean_target_call = content.index("Assert-CleanSmokeTarget\nNew-Item")

        self.assertLess(guard_call, first_write)
        self.assertLess(clean_target_call, first_write)
        for required in (
            'CI = "true"',
            'GITHUB_ACTIONS = "true"',
            'RUNNER_ENVIRONMENT = "github-hosted"',
            'RUNNER_OS = "Windows"',
            "GITHUB_WORKSPACE",
            "RUNNER_TEMP",
            "pre-existing Clarify state",
            "pre-existing Clarify autostart entry",
            "no longer the smoke-test sentinel",
        ):
            self.assertIn(required, content)

        for operation, expected_hash in (
            ("clean install", "$baselinePayloadHash"),
            ("upgrade", "$currentPayloadHash"),
            ("repair", "$currentPayloadHash"),
            ("manual rollback", "$baselinePayloadHash"),
        ):
            self.assertIn(f'Assert-Installed "{operation}" {expected_hash}', content)
        self.assertIn("Get-FileHash $installedExe -Algorithm SHA256", content)
        self.assertIn("Uninstall left the installed executable behind", content)

    def test_installer_and_update_contract_files_exist(self):
        required = [
            "distribution/update-policy.json",
            "installer/Clarify.wxs",
            "scripts/build-installer.ps1",
            "scripts/test-installer.ps1",
            "scripts/create_release_manifest.py",
            "scripts/build-manifest-container.ps1",
            "scripts/verify-signature.ps1",
            "update_security.py",
            "version.py",
        ]
        for relative_path in required:
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)

        build = (ROOT / "scripts" / "build.ps1").read_text(encoding="utf-8")
        self.assertIn("${distribution};distribution", build)

        installer = (ROOT / "installer" / "Clarify.wxs").read_text(encoding="utf-8")
        self.assertIn('Id="RemoveAutostartOnUninstall"', installer)
        self.assertIn(
            'Condition="REMOVE=&quot;ALL&quot; AND NOT UPGRADINGPRODUCTCODE"',
            installer,
        )
        self.assertNotIn("<RemoveRegistryValue", installer)

        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("if not _is_msi_installed_build():", app_source)
        self.assertNotIn(
            'if not IS_WIN or not getattr(sys, "frozen", False):\n'
            "                update_status.configure(",
            app_source,
        )

    def test_version_module_is_the_runtime_diagnostics_source(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

        self.assertIn("from version import __version__", app_source)
        self.assertNotIn('APP_VERSION = "', app_source)
        self.assertTrue(package["private"])
        self.assertEqual(package["version"], __version__)

    def test_open_source_community_files_exist(self):
        required = [
            "LICENSE",
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
            "SECURITY.md",
            "SUPPORT.md",
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/workflows/ci.yml",
            ".github/workflows/release.yml",
        ]
        for relative_path in required:
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)

    def test_dependency_contract_files_exist_and_have_review_policy(self):
        for lock_name in (
            "requirements-lock-linux.txt",
            "requirements-lock-windows.txt",
            "requirements-lock-runtime-windows.txt",
        ):
            lock = ROOT / lock_name
            self.assertTrue(lock.is_file(), lock_name)
            self.assertIn("pip-compile", lock.read_text(encoding="utf-8"))

        policy = json.loads(
            (ROOT / "dependency-audit.json").read_text(encoding="utf-8")
        )
        self.assertEqual(policy["policy_version"], 1)
        self.assertIsInstance(policy["ignored_vulnerabilities"], dict)

        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[tool.ruff]", pyproject)
        self.assertIn("[tool.mypy]", pyproject)
        checker = ROOT / "scripts" / "check_dependency_lock.py"
        self.assertTrue((ROOT / "scripts" / "sox-runtime-manifest.json").is_file())
        self.assertIn(
            "sox-runtime-manifest.json",
            (ROOT / "scripts" / "build.ps1").read_text(encoding="utf-8"),
        )
        checker_content = checker.read_text(encoding="utf-8")
        self.assertNotIn("--check", checker_content)
        self.assertIn('"--allow-unsafe"', checker_content)

        runtime_lock = (ROOT / "requirements-lock-runtime-windows.txt").read_text(
            encoding="utf-8"
        )
        for lock_name in (
            "requirements-lock-linux.txt",
            "requirements-lock-windows.txt",
        ):
            dev_lock = (ROOT / lock_name).read_text(encoding="utf-8")
            self.assertRegex(dev_lock, r"(?im)^pip==[^\n]+$")
            self.assertRegex(dev_lock, r"(?im)^setuptools==[^\n]+$")
        self.assertNotRegex(runtime_lock, r"(?im)^(pip|setuptools)==")
        windows_lock = (ROOT / "requirements-lock-windows.txt").read_text(
            encoding="utf-8"
        )
        for windows_only in ("colorama", "pefile", "pywin32-ctypes"):
            self.assertRegex(windows_lock, rf"(?im)^{windows_only}==")
        self.assertNotRegex(windows_lock, r"(?im)^keyboard==")
        for development_tool in (
            "cyclonedx-bom",
            "mypy",
            "pip-audit",
            "pip-tools",
            "pyinstaller",
            "ruff",
        ):
            self.assertNotRegex(runtime_lock, rf"(?im)^{development_tool}==")


if __name__ == "__main__":
    unittest.main()
