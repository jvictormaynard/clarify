"""Protect focused test runs from profiles and swallowed application imports."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[2]


class TestEnvironmentTests(unittest.TestCase):
    def test_repository_collection_preserves_the_runner_profile(self):
        script = r"""
import importlib, os
from pathlib import Path
from scripts.run_tests import isolated_environment
with isolated_environment():
    before = {key: os.environ[key] for key in ("HOME", "APPDATA", "CLARIFY_DATA_DIR")}
    for module in ("tests.integration.test_repositories", "tests.compatibility.test_repositories"):
        importlib.import_module(module)
        assert {key: os.environ[key] for key in before} == before, module
    assert Path(before["HOME"]).is_dir()
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def run_tree(self, root, *arguments, environment=None):
        script = """
from pathlib import Path
import runpy, sys
runner = runpy.run_path(sys.argv[1])
runner["main"].__globals__["ROOT"] = Path(sys.argv[2])
raise SystemExit(runner["main"](sys.argv[3:]))
"""
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                script,
                str(ROOT / "scripts/run_tests.py"),
                str(root),
                *arguments,
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_suite_durations_report_only_the_selected_directory(self):
        from tests.support.suite_tree import suite_tree

        with TemporaryDirectory() as directory:
            root = suite_tree(directory)
            (root / "tests/contract/test_probe.py").write_text(
                "raise AssertionError('unselected suite imported')"
            )
            report = root / "nested" / "durations.json"
            result = self.run_tree(
                root,
                "--suite",
                "unit",
                environment={
                    **os.environ,
                    "CLARIFY_TEST_DURATIONS_JSON": str(report),
                    "CLARIFY_TEST_DURATIONS_UNIT": "file",
                },
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(report.read_text())
            self.assertTrue(data["successful"])
            self.assertEqual(data["tests_run"], 1)
            self.assertEqual(len(data["records"]), 1)
            self.assertEqual(
                Path(data["records"][0]["file"]), root / "tests/unit/test_probe.py"
            )

    def test_fixture_alias_keeps_selected_suite_ownership(self):
        from tests.support.suite_tree import suite_tree

        with TemporaryDirectory() as directory:
            alias = Path(directory) / "alias"
            alias.mkdir()
            root = suite_tree(alias / "..")
            result = self.run_tree(root, "--suite", "unit", "--list", "--json")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = json.loads(result.stdout)["tests"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["suite"], "unit")
            self.assertEqual(rows[0]["file"], "tests/unit/test_probe.py")

    def test_discovery_keeps_policy_named_modules_and_product_failures(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            case = "import unittest\nclass Case(unittest.TestCase):\n def test_case(self): {body}\n"
            for name in (
                "test_delivery_policy",
                "test_release_delivery",
                "test_ios_ipa",
                "test_product",
            ):
                (root / f"{name}.py").write_text(
                    case.format(body="self.fail('visible failure')")
                )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/run_tests.py"),
                    "discover",
                    "-s",
                    str(root),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("Ran 4 tests", result.stderr)
            self.assertEqual(result.stderr.count("AssertionError: visible failure"), 4)

    def test_suite_listing_sharding_and_repeated_selection_collect_once(self):
        from tests.support.suite_tree import suite_tree

        with TemporaryDirectory() as directory:
            root = suite_tree(directory)
            arguments = (
                "--suite",
                "unit",
                "--suite",
                "contract",
                "--suite",
                "unit",
                "--list",
                "--json",
            )
            result = self.run_tree(root, *arguments)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            complete = json.loads(result.stdout)
            self.assertEqual(complete["count"], 2)
            explicit = self.run_tree(
                root,
                "--suite",
                "unit",
                "--list",
                "--json",
                "discover",
                "-s",
                str(root / "tests"),
            )
            self.assertEqual(explicit.returncode, 0, explicit.stdout + explicit.stderr)
            self.assertEqual(json.loads(explicit.stdout)["count"], 1)
            collected = []
            for shard in ("1/2", "2/2"):
                result = self.run_tree(root, *arguments, "--shard", shard)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                collected.extend(
                    row["id"] for row in json.loads(result.stdout)["tests"]
                )
            self.assertEqual(
                sorted(collected), sorted(row["id"] for row in complete["tests"])
            )
            inventory = self.run_tree(root, "--list-suites", "--json")
            self.assertEqual(
                inventory.returncode, 0, inventory.stdout + inventory.stderr
            )
            self.assertEqual(len(json.loads(inventory.stdout)["suites"]), 7)

    def test_unknown_files_fail_before_selected_suite_imports(self):
        from tests.support.suite_tree import suite_tree

        with TemporaryDirectory() as directory:
            root = suite_tree(directory)
            marker = root / "imported"
            (root / "tests/unit/test_probe.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
            )
            (root / "tests/test_unclassified.py").touch()
            result = self.run_tree(root, "--suite", "unit", "--list", "--json")
            self.assertEqual(result.returncode, 2)
            self.assertIn("Unclassified", result.stderr)
            self.assertFalse(marker.exists())

    def test_import_errors_keep_unittest_failure_status(self):
        from tests.support.suite_tree import suite_tree

        with TemporaryDirectory() as directory:
            root = suite_tree(directory)
            (root / "tests/unit/test_probe.py").write_text(
                "raise ImportError('synthetic import error')"
            )
            result = self.run_tree(root, "--suite", "unit")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("synthetic import error", result.stderr)
            incomplete_shard = self.run_tree(
                root, "--suite", "unit", "--suite", "contract", "--shard", "1/2"
            )
            self.assertEqual(
                incomplete_shard.returncode,
                2,
                incomplete_shard.stdout + incomplete_shard.stderr,
            )
            (root / "tests/unit/test_probe.py").write_text(
                "import unittest\nclass Probe(unittest.TestCase):\n def test_ok(self): pass\n"
            )
            empty = self.run_tree(root, "--suite", "unit", "-k", "missing_case")
            self.assertEqual(empty.returncode, 5, empty.stdout + empty.stderr)

    def test_fast_suite_collection_never_imports_qt_or_legacy_runtime(self):
        script = """
import importlib.abc, runpy, sys
class NoRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app" or fullname.startswith(("PySide6", "tkinter", "customtkinter", "webbrowser")):
            raise ImportError("Fast lane attempted runtime import: " + fullname)
sys.meta_path.insert(0, NoRuntime())
sys.argv = [sys.argv[1], "--suite", "unit", "--suite", "contract", "--list", "--json"]
runpy.run_path(sys.argv[0], run_name="__main__")
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script, str(ROOT / "scripts/run_tests.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertGreater(json.loads(result.stdout)["count"], 0)

    def test_opt_in_durations_preserve_unittest_results_and_profile_cleanup(self):
        with TemporaryDirectory() as directory:
            fixture = Path(directory) / "test_timing_probe.py"
            profile = Path(directory) / "profile.json"
            fixture.write_text(
                "import json, os, pathlib, unittest\n"
                f"pathlib.Path({str(profile)!r}).write_text("
                "json.dumps(os.environ['CLARIFY_DATA_DIR']))\n"
                "class Probe(unittest.TestCase):\n"
                "    def test_pass(self): pass\n"
                "    @unittest.skip('synthetic skip')\n"
                "    def test_skip(self): pass\n"
                "    @unittest.expectedFailure\n"
                "    def test_expected(self): self.fail('expected')\n"
                "    def test_failure(self):\n"
                "        with self.subTest(case='failure'): self.fail('synthetic')\n"
                "        with self.subTest(case='skip'): self.skipTest('synthetic')\n"
                "    def test_error(self): raise RuntimeError('synthetic')\n",
                encoding="utf-8",
            )
            for unit in ("test", "file"):
                with self.subTest(unit=unit):
                    report = Path(directory) / f"{unit}.json"
                    environment = dict(os.environ)
                    environment["CLARIFY_TEST_DURATIONS_JSON"] = str(report)
                    environment["CLARIFY_TEST_DURATIONS_UNIT"] = unit
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(ROOT / "scripts/run_tests.py"),
                            "discover",
                            "-s",
                            directory,
                            "-p",
                            fixture.name,
                            "-v",
                        ],
                        cwd=ROOT,
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    self.assertEqual(
                        result.returncode, 1, result.stdout + result.stderr
                    )
                    self.assertTrue(report.is_file(), "No duration report was written")
                    data = json.loads(report.read_text(encoding="utf-8"))
                    self.assertEqual(data["unit"], unit)
                    self.assertFalse(data["successful"])
                    self.assertEqual(data["tests_run"], 5)
                    self.assertEqual(
                        data["summary"],
                        {
                            "failed": 1,
                            "error": 1,
                            "skipped": 2,
                            "expected_failure": 1,
                            "unexpected_success": 0,
                        },
                    )
                    self.assertFalse(
                        Path(json.loads(profile.read_text())).parent.exists()
                    )
                    if unit == "test":
                        self.assertEqual(
                            {record["status"] for record in data["records"]},
                            {
                                "passed",
                                "failed",
                                "error",
                                "skipped",
                                "expected_failure",
                            },
                        )
                        self.assertEqual(len(data["records"]), 5)
                    else:
                        self.assertEqual(len(data["records"]), 1)
                        self.assertEqual(data["records"][0]["tests"], 5)
                        self.assertEqual(data["records"][0]["statuses"]["skipped"], 1)
                    for record in data["records"]:
                        self.assertGreaterEqual(record["duration_seconds"], 0)

    def test_duration_opt_in_preserves_k_failfast_and_buffer_arguments(self):
        with TemporaryDirectory() as directory:
            fixture = Path(directory) / "test_timing_arguments.py"
            fixture.write_text(
                "import unittest\n"
                "class Probe(unittest.TestCase):\n"
                "    def test_1_selected(self): print('buffered'); self.fail('synthetic')\n"
                "    def test_2_selected(self): raise RuntimeError('must not run')\n"
                "    def test_3_other(self): raise RuntimeError('must not run')\n",
                encoding="utf-8",
            )
            report = Path(directory) / "durations.json"
            environment = dict(os.environ)
            environment["CLARIFY_TEST_DURATIONS_JSON"] = str(report)
            environment["CLARIFY_TEST_DURATIONS_UNIT"] = "test"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "scripts/run_tests.py"),
                    "discover",
                    "-s",
                    directory,
                    "-k",
                    "selected",
                    "-f",
                    "-b",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertTrue(report.is_file(), "No duration report was written")
            data = json.loads(report.read_text())
            self.assertEqual(data["tests_run"], 1)
            self.assertEqual(len(data["records"]), 1)
            self.assertEqual(data["records"][0]["status"], "failed")

    def test_runner_isolates_imports_before_discovery_and_ignores_dotenv(self):
        with TemporaryDirectory() as directory:
            personal = Path(directory) / "personal"
            personal.mkdir()
            config = personal / "Clarify/config.json"
            config.parent.mkdir()
            config.write_text('{"ui_mode": "prompt"}', encoding="utf-8")
            before = config.read_bytes()
            script = r"""
import json, logging, os, pathlib, runpy, sys, types, unittest
from unittest.mock import patch
root, personal = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
reads = {"dotenv": 0, "personal": 0}
exists, read_text = pathlib.Path.exists, pathlib.Path.read_text
def guarded_exists(path):
    return True if path == root / ".env" else exists(path)
def observed_read(path, *args, **kwargs):
    if path == root / ".env":
        reads["dotenv"] += 1
        return "GROQ_API_KEY=dotenv-test-only\n"
    if path.is_relative_to(personal):
        reads["personal"] += 1
    return read_text(path, *args, **kwargs)
pathlib.Path.exists, pathlib.Path.read_text = guarded_exists, observed_read
module = types.ModuleType("profile_probe")
class ProfileProbe(unittest.TestCase):
    def test_import(self):
        import app
        import local_asr
        with patch.object(local_asr.platform, "system", return_value="Linux"):
            asr_root = local_asr.default_install_root()
            asr_isolated = (
                asr_root.is_relative_to(app.DATA_DIR.parent)
                and not asr_root.is_relative_to(personal)
            )
        logging.getLogger("profile_probe").addHandler(
            logging.FileHandler(app.DATA_DIR / "probe.log")
        )
        print(json.dumps({
            "profile": str(app.DATA_DIR),
            "profile_isolated": not app.DATA_DIR.is_relative_to(personal),
            "asr_isolated": asr_isolated,
            "inherited_key_removed": not app.DEFAULT_CONFIG["gemini_api_key"],
            "dotenv_key_removed": not app.DEFAULT_CONFIG["groq_api_key"],
            "qml_style": os.environ.get("QT_QUICK_CONTROLS_STYLE"),
            "reads": reads,
        }))
module.ProfileProbe = ProfileProbe
sys.modules[module.__name__] = module
sys.argv = [str(root / "scripts/run_tests.py"), "profile_probe", "-v"]
runpy.run_path(sys.argv[0], run_name="__main__")
"""
            environment = dict(os.environ)
            for name in (
                "APPDATA",
                "LOCALAPPDATA",
                "USERPROFILE",
                "HOME",
                "XDG_DATA_HOME",
            ):
                environment[name] = str(personal)
            environment.pop("CLARIFY_SKIP_DOTENV", None)
            environment.pop("CLARIFY_DATA_DIR", None)
            environment["QT_QUICK_CONTROLS_STYLE"] = "Windows"
            environment["GEMINI_API_KEY"] = "inherited-test-only"
            environment.pop("GROQ_API_KEY", None)
            result = subprocess.run(
                [sys.executable, "-B", "-c", script, str(ROOT), str(personal)],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            observation = json.loads(result.stdout)
            self.assertFalse(Path(observation.pop("profile")).exists())
            self.assertEqual(config.read_bytes(), before)
            self.assertEqual(
                observation,
                {
                    "profile_isolated": True,
                    "asr_isolated": True,
                    "inherited_key_removed": True,
                    "dotenv_key_removed": True,
                    "qml_style": "Basic",
                    "reads": {"dotenv": 0, "personal": 0},
                },
            )


if __name__ == "__main__":
    unittest.main()
