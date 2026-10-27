"""Contracts for the MAIN/source boundary without executing candidate code."""

import contextlib
import base64
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import trusted_ci as qa

ROOT = Path(__file__).resolve().parents[1]
CONTROL_ROOT = Path(os.environ.get("CLARIFY_TRUSTED_CI_TEST_ROOT", ROOT))
CORE = "mobile/modules/clarify-core/"


class GitFixture:
    def __init__(self, root):
        self.root = root
        self.git("init", "-q")

    def git(self, *args):
        return (
            subprocess.check_output(
                ["git", "-C", str(self.root), *args], stderr=subprocess.PIPE
            )
            .decode()
            .strip()
        )

    def commit(self, files):
        for name, value in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
        self.git("add", "--all")
        self.git(
            "-c",
            "user.name=QA fixture",
            "-c",
            "user.email=qa@example.invalid",
            "commit",
            "-qm",
            "Fixture",
        )
        return self.git("rev-parse", "HEAD")


class TrustedPlanTests(unittest.TestCase):
    def test_docs_plan_still_requires_both_native_executors(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = GitFixture(Path(temp))
            base = repo.commit({"docs/note.md": "Before"})
            source = repo.commit({"docs/note.md": "After"})
            result = qa.validation_plan(repo.root, base, source)
            self.assertEqual(
                result["selected_keys"],
                [
                    "selection",
                    "repository",
                    "mobile",
                    "ios_native",
                    "ios_build",
                    "ios_aggregate",
                    "ci_required",
                ],
            )
            self.assertTrue(result["components"]["mobile"])
            self.assertTrue(result["components"]["ios"])
            self.assertFalse(result["components"]["desktop"])

    def test_full_diff_and_unknown_input_require_the_full_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = GitFixture(Path(temp))
            base = repo.commit({"README.md": "Before"})
            repo.commit({"unknown.input": "New contract"})
            source = repo.commit({"README.md": "After"})
            result = qa.validation_plan(repo.root, base, source)
            self.assertTrue(all(result["components"].values()))
            self.assertEqual(len(result["selected_keys"]), 16)

    def test_digest_uses_the_agreed_canonical_json(self):
        self.assertEqual(qa.canonical_json({"b": 2, "a": 1}), '{"a":1,"b":2}')
        self.assertEqual(qa.digest({"a": 1, "b": 2}), qa.digest({"b": 2, "a": 1}))
        with self.assertRaises(ValueError):
            qa.canonical_json({"value": float("nan")})

    def test_only_the_main_caller_and_exact_tuple_can_authenticate(self):
        trusted, source = "a" * 40, "b" * 40
        env = {
            "QA_SOURCE_SHA": source,
            "QA_BASE_SHA": trusted,
            "QA_TRUSTED_SHA": trusted,
            "GITHUB_REPOSITORY": "jvictormaynard/clarify",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": trusted,
            "QA_WORKFLOW_SHA": trusted,
            "GITHUB_WORKFLOW_REF": "jvictormaynard/clarify/.github/workflows/ios-qa.yml@refs/heads/main",
        }
        with patch.object(
            qa, "git", side_effect=[trusted.encode(), source.encode(), b""]
        ):
            self.assertEqual(
                qa.authenticate_context(env, "trusted", "source"),
                (source, trusted, trusted),
            )
        for key, value in (
            ("GITHUB_EVENT_NAME", "pull_request"),
            ("GITHUB_REF", "refs/tags/untrusted"),
            ("QA_WORKFLOW_SHA", source),
            ("QA_BASE_SHA", source),
            ("QA_SOURCE_SHA", "short"),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                qa.authenticate_context({**env, key: value}, "trusted", "source")

    def test_the_required_gate_recomputes_flags_and_rejects_skipped_native(self):
        flags = {key: key in {"mobile", "ios"} for key in qa.delivery_policy.COMPONENTS}
        needs = {
            key: {
                "result": "success"
                if key in {"components", "repository", "mobile", "ios"}
                else "skipped"
            }
            for key in (
                "components",
                "repository",
                "test",
                "settings",
                "package",
                "installer",
                "server",
                "mobile",
                "ios",
                "audit",
            )
        }
        needs["components"]["outputs"] = {k: str(v).lower() for k, v in flags.items()}
        job = object.__new__(qa.Job)
        job.plan = {"components": flags}
        job.env = {"CI_NEEDS": qa.canonical_json(needs)}
        job.results()
        needs["components"]["outputs"]["ios"] = "false"
        job.env["CI_NEEDS"] = qa.canonical_json(needs)
        with self.assertRaises(ValueError):
            job.results()
        needs["components"]["outputs"]["ios"] = "true"
        needs["ios"]["result"] = "skipped"
        job.env["CI_NEEDS"] = qa.canonical_json(needs)
        with self.assertRaises(ValueError):
            job.results()


class InputBoundaryTests(unittest.TestCase):
    def test_paths_cannot_escape_or_alias_across_platforms(self):
        for value in (
            "../outside",
            "/absolute",
            "a/../b",
            "a\\b",
            "a//b",
            "C:drive",
            "a/CON.txt",
            "a/trailing.",
            "a/trailing ",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                qa.safe_path(value)
        self.assertEqual(qa.safe_path("mobile/src/feature.ts"), "mobile/src/feature.ts")

    def test_roots_cannot_overlap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                qa.validate_roots(
                    root / "trusted", root / "source", root / "source/run"
                )
            qa.validate_roots(root / "trusted", root / "source", root / "execution")

    def test_materialization_uses_main_controls_and_candidate_product(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            trusted = parent / "trusted"
            trusted.mkdir()
            repo = GitFixture(trusted)
            base = repo.commit(
                {
                    "product.py": "old product",
                    "scripts/controller.py": "MAIN control",
                    "tests/oracle.py": "MAIN assertions",
                }
            )
            source = parent / "source"
            subprocess.check_call(["git", "clone", "-q", str(trusted), str(source)])
            candidate = GitFixture(source)
            head = candidate.commit(
                {
                    "product.py": "new product",
                    "scripts/controller.py": "candidate control",
                    "tests/oracle.py": "candidate assertions",
                    "tests/new.py": "additional diagnostic",
                }
            )
            output = parent / "execution"
            inventory = qa.materialize_trees(trusted, source, output, base, head)
            self.assertEqual((output / "product.py").read_text(), "new product")
            self.assertEqual(
                (output / "scripts/controller.py").read_text(), "MAIN control"
            )
            self.assertEqual(
                (output / "tests/oracle.py").read_text(), "MAIN assertions"
            )
            self.assertFalse((output / "tests/new.py").exists())
            qa.verify_execution(output, inventory)
            (output / "product.py").write_text("changed during execution")
            with self.assertRaises(ValueError):
                qa.verify_execution(output, inventory)
            self.assertEqual(
                qa.control_inventory(trusted, base)["scripts/controller.py"],
                repo.git("rev-parse", base + ":scripts/controller.py"),
            )

    def test_unclassified_input_blocks_before_writing_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            trusted = parent / "trusted"
            trusted.mkdir()
            repo = GitFixture(trusted)
            base = repo.commit({"product.py": "baseline"})
            source = parent / "source"
            subprocess.check_call(["git", "clone", "-q", str(trusted), str(source)])
            head = GitFixture(source).commit({"unreviewed.blob": "unknown"})
            output = parent / "execution"
            with self.assertRaises(ValueError):
                qa.materialize_trees(trusted, source, output, base, head)
            self.assertFalse(output.exists())

    def test_a_new_native_type_requires_explicit_reconciliation(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            trusted = parent / "trusted"
            trusted.mkdir()
            base = GitFixture(trusted).commit({"product.py": "baseline"})
            source = parent / "source"
            subprocess.check_call(["git", "clone", "-q", str(trusted), str(source)])
            head = GitFixture(source).commit(
                {"mobile/native/keyboard/Unknown.swift": "new native type"}
            )
            with self.assertRaisesRegex(ValueError, "Unreconciled native"):
                qa.materialize_trees(trusted, source, parent / "execution", base, head)
            self.assertFalse((parent / "execution").exists())

    def test_product_output_is_inert_and_command_files_are_not_forwarded(self):
        with tempfile.TemporaryDirectory() as temp:
            job = object.__new__(qa.Job)
            job.env = {
                **os.environ,
                "GITHUB_OUTPUT": str(Path(temp) / "command-file"),
                "GH_TOKEN": "synthetic-token",
                "ACTIONS_RUNTIME_TOKEN": "synthetic-runtime",
            }
            job.metadata = Path(temp)
            job.execution = Path(temp)
            job.tools = {}
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                log = job.command(
                    [
                        os.sys.executable,
                        "-c",
                        "import os; print('::error::not a workflow command'); assert 'GITHUB_OUTPUT' not in os.environ; assert 'GH_TOKEN' not in os.environ; assert 'ACTIONS_RUNTIME_TOKEN' not in os.environ",
                    ]
                )
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("::error::not a workflow command", log.read_text())
            self.assertFalse((Path(temp) / "command-file").exists())


class NativeProjectionTests(unittest.TestCase):
    def inputs(self):
        return (
            (CONTROL_ROOT / CORE / "Package.swift").read_bytes(),
            {
                name: (CONTROL_ROOT / CORE / "tests" / name).read_bytes()
                for name in ("ContractsTests.swift", "RecordingTests.swift")
            },
        )

    def test_projection_includes_all_seven_products_and_preserves_oracles(self):
        manifest, oracles = self.inputs()
        result = qa.project_native_contracts(manifest, oracles)
        projected = result["manifest"].decode()
        for name in (
            "ComputerProtocol",
            "ComputerCredential",
            "ComputerTransport",
            "ComputerWAV",
            "ComputerAudio",
            "ComputerConnection",
            "ProcessingDestination",
        ):
            self.assertIn('"' + name + '.swift"', projected)
        self.assertIn('exclude: ["ComputerScanner.swift", ', projected)
        self.assertEqual(
            result["oracles"]["ContractsTests.swift"].count(b"context: nil"), 3
        )
        recording = result["oracles"]["RecordingTests.swift"]
        self.assertIn(
            b'operationID: "cancelled", context: state.processingContext)', recording
        )
        self.assertEqual(recording.count(b"context: nil"), 3)
        for name, before in oracles.items():
            after = result["oracles"][name]
            restored = after.replace(b", context: state.processingContext", b"")
            restored = restored.replace(b", context: nil", b"")
            self.assertEqual(restored, before)
            self.assertEqual(
                [line for line in before.splitlines() if b"XCT" in line],
                [line for line in after.splitlines() if b"XCT" in line],
            )

    def test_an_unexpected_oracle_shape_blocks_instead_of_best_effort(self):
        manifest, oracles = self.inputs()
        oracles["ContractsTests.swift"] = oracles["ContractsTests.swift"].replace(
            b'operationID: "second"', b'operationID: "changed"', 1
        )
        with self.assertRaises(ValueError):
            qa.project_native_contracts(manifest, oracles)


class ExportSetupTests(unittest.TestCase):
    def test_both_qa_packages_explicitly_skip_git_hook_configuration(self):
        job = object.__new__(qa.Job)
        job.plan = {"components": {"installer": True}}
        job.settings = lambda **kwargs: None
        job.runtime_python = lambda: "python.exe"
        job.command = lambda *args, **kwargs: None
        scripts = []
        job.powershell = scripts.append
        with patch.object(qa, "os", SimpleNamespace(name="nt")):
            job.package()
        builds = [script for script in scripts if "./scripts/build.ps1" in script]
        self.assertEqual(len(builds), 2)
        self.assertTrue(all("-SkipGitHooks" in script for script in builds))

    def test_setup_defaults_and_export_flag_at_the_process_boundary(self):
        shell = shutil.which("pwsh") or shutil.which("powershell.exe")
        if shell is None:
            self.skipTest("PowerShell is needed for the setup process boundary")
        # Execute the real setup entry point with only its external-process
        # boundary replaced. No interpreter, installer, pip or Git is started.
        probe = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$setup = $env:CLARIFY_SETUP_PROBE_SOURCE
$build = $env:CLARIFY_BUILD_PROBE_SOURCE
$buildAst = [System.Management.Automation.Language.Parser]::ParseFile($build, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Build parse error' }
$forward = @($buildAst.FindAll({ param($n)
    $n -is [System.Management.Automation.Language.CommandAst] -and
    $n.InvocationOperator -eq [System.Management.Automation.Language.TokenKind]::Ampersand -and
    $n.Extent.Text.Contains('"setup.ps1"')
}, $true))
if ($forward.Count -ne 1) { throw 'Missing setup invocation' }
$option = @($forward[0].CommandElements | Where-Object {
    $_ -is [System.Management.Automation.Language.CommandParameterAst] -and $_.ParameterName -ceq 'SkipGitHooks'
})
if ($option.Count -ne 1 -or $option[0].Argument.VariablePath.UserPath -cne 'SkipGitHooks') {
    throw 'Build does not forward the explicit hook option'
}
$source = [IO.File]::ReadAllText($setup, [Text.Encoding]::UTF8)
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Setup parse error' }
$boundary = @($ast.FindAll({ param($n)
    $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Invoke-CheckedProcess'
}, $true))
if ($boundary.Count -ne 1) { throw 'Missing process boundary' }
$stub = @'
function Invoke-CheckedProcess {
    param([string]$FilePath, [string[]]$Arguments, [string]$FailureMessage)
    $global:clarifySetupProbeCalls.Add(@{ file = $FilePath; arguments = @($Arguments) })
}
'@
$entry = $boundary[0].Extent
$source = $source.Substring(0, $entry.StartOffset) + $stub + $source.Substring($entry.EndOffset)
$target = Join-Path $env:CLARIFY_SETUP_PROBE_EXPORT 'scripts/setup-boundary.ps1'
[IO.File]::WriteAllText($target, $source, (New-Object Text.UTF8Encoding($false)))
$cases = New-Object 'System.Collections.Generic.List[object]'
foreach ($dev in @($false, $true)) {
    foreach ($mode in @('absent', 'false', 'true')) {
        $global:clarifySetupProbeCalls = New-Object 'System.Collections.Generic.List[object]'
        $options = @{}
        if ($dev) { $options.Dev = $true }
        if ($mode -ceq 'false') { $options.SkipGitHooks = $false }
        if ($mode -ceq 'true') { $options.SkipGitHooks = $true }
        & $target @options | Out-Null
        $cases.Add(@{ dev = $dev; mode = $mode; calls = @($global:clarifySetupProbeCalls.ToArray()) })
    }
}
ConvertTo-Json -Depth 8 -Compress -InputObject @($cases.ToArray())
"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in (
                ".venv/Scripts/python.exe",
                "requirements-lock-windows.txt",
                "requirements.txt",
                "requirements-dev.txt",
                "scripts/install_bootstrap_tools.py",
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic process-boundary fixture")
            result = subprocess.run(
                [
                    shell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-EncodedCommand",
                    base64.b64encode(probe.encode("utf-16-le")).decode("ascii"),
                ],
                env={
                    **os.environ,
                    "CLARIFY_SETUP_PROBE_SOURCE": str(ROOT / "scripts/setup.ps1"),
                    "CLARIFY_BUILD_PROBE_SOURCE": str(ROOT / "scripts/build.ps1"),
                    "CLARIFY_SETUP_PROBE_EXPORT": str(root),
                },
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            cases = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(len(cases), 6)
        for dev in (False, True):
            by_mode = {c["mode"]: c["calls"] for c in cases if c["dev"] == dev}
            self.assertEqual(by_mode["absent"], by_mode["false"])
            normal = by_mode["absent"]
            self.assertEqual(sum(c["file"] == "git.exe" for c in normal), 1)
            non_git = [c for c in normal if c["file"] != "git.exe"]
            self.assertEqual(len(non_git), 2 if dev else 1)
            self.assertEqual(by_mode["true"], non_git)


if __name__ == "__main__":
    unittest.main()
