"""Protect focused test runs from profiles and swallowed application imports."""

import json
from importlib.util import find_spec
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestEnvironmentTests(unittest.TestCase):
    def test_ci_product_scope_keeps_unknown_tests_and_product_failures(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            case = "import unittest\nclass Case(unittest.TestCase):\n def test_case(self): {body}\n"
            for name in (
                "test_delivery_policy",
                "test_release_delivery",
                "test_trusted_ci",
                "test_testflight_qa",
                "test_qa_device_archive",
            ):
                (root / f"{name}.py").write_text(
                    case.format(body="self.fail('repository duplicate')")
                )
            product = root / "test_product.py"
            product.write_text(case.format(body="pass"))
            command = [sys.executable, str(ROOT / "scripts/run_tests.py")]

            def run(*options, qa_policy="false"):
                return subprocess.run(
                    [*command, *options, "discover", "-s", str(root)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env={**os.environ, "CLARIFY_CI_QA_POLICY": qa_policy},
                )

            complete = run()
            self.assertNotEqual(complete.returncode, 0)
            self.assertIn("Ran 6 tests", complete.stderr)
            scoped = run("--ci-product-tests")
            self.assertEqual(scoped.returncode, 0, scoped.stdout + scoped.stderr)
            self.assertIn("Ran 1 test", scoped.stderr)
            for policy in ("true", "", "invalid"):
                with self.subTest(qa_policy=policy):
                    guarded = run("--ci-product-tests", qa_policy=policy)
                    count = 4 if sys.platform == "win32" else 1
                    self.assertIn(f"Ran {count} test", guarded.stderr)
                    self.assertEqual(guarded.returncode, int(sys.platform == "win32"))
            product.write_text(case.format(body="self.fail('product failure')"))
            failed = run("--ci-product-tests")
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("product failure", failed.stderr)
            product.write_text(case.format(body="pass"))
            (root / "test_new_policy.py").write_text(
                case.format(body="self.fail('unknown module')")
            )
            package = root / "extra"
            package.mkdir()
            (package / "__init__.py").touch()
            (package / "test_trusted_ci.py").write_text(
                case.format(body="self.fail('nested module')")
            )
            unknown = run("--ci-product-tests")
            self.assertNotEqual(unknown.returncode, 0)
            self.assertIn("unknown module", unknown.stderr)
            self.assertIn("nested module", unknown.stderr)

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

    @unittest.skipUnless(
        find_spec("PySide6"), "Qt is required for import fault injection"
    )
    def test_qt_application_import_failures_are_not_dependency_skips(self):
        cases = (
            ("test_pyside6_qml.py", "clarify.desktop.qml_app"),
            ("test_pyside6_qml_settings.py", "clarify.desktop.qml_settings"),
            ("test_pyside6_qml_audio_batch.py", "clarify.desktop.qml_audio_batch"),
            ("test_pyside6_qt_shell.py", "clarify.desktop.qt_shell"),
            ("test_refinement_recovery.py", "clarify.desktop.qml_runtime"),
        )
        script = r"""
import importlib.abc, pathlib, runpy, sys
sys.path[:0] = [sys.argv[1], str(pathlib.Path(sys.argv[1]) / "tests")]
from PySide6.QtWidgets import QApplication
class BrokenApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == sys.argv[3]:
            raise ImportError("synthetic application import failure")
sys.meta_path.insert(0, BrokenApplication())
try:
    runpy.run_path(str(pathlib.Path(sys.argv[1]) / "tests" / sys.argv[2]))
except ImportError as error:
    if str(error) != "synthetic application import failure":
        raise
else:
    raise SystemExit("Application error was converted to a dependency skip")
"""
        for filename, module in cases:
            with self.subTest(filename=filename):
                result = subprocess.run(
                    [sys.executable, "-B", "-c", script, str(ROOT), filename, module],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
