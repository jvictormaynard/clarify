"""Local validation uses the complete candidate and the shared delivery policy."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from ci import cli as validate, impact as delivery_policy
from ci.tasks import JOBS


ROOT = Path(__file__).resolve().parents[2]


class ValidationPlanTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="clarify-validation-git-")
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name)
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Validation fixture")
        self.write("README.md", "Base\n")
        self.write("windows_clipboard.py", "# base\n")
        self.write(".gitignore", ".env\n")
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("update-ref", "refs/remotes/origin/main", self.base)

    def git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self):
        self.git("add", "--all")
        self.git("-c", "core.hooksPath=", "commit", "-qm", "Fixture")

    def test_merge_base_includes_branch_changes_and_each_dirty_layer(self):
        self.write("mobile/src/committed.ts", "export {};\n")
        self.commit()
        head = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-qb", "advanced-main", self.base)
        self.write("docs/upstream.md", "Upstream only\n")
        self.commit()
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("checkout", "-q", "--detach", head)
        # A staged change remains an input even if the worktree reverses it.
        self.write("README.md", "Staged\n")
        self.git("add", "README.md")
        self.write("README.md", "Base\n")
        self.write("windows_clipboard.py", "# dirty\n")
        self.write("desktop/src/new view.tsx", "export {};\n")
        self.write(".env", "TEST_ONLY=value\n")
        plan = validate.build_plan(self.repo)
        self.assertEqual(plan["merge_base"], self.base)
        self.assertEqual(plan["head"], head)
        self.assertEqual(
            set(plan["paths"]),
            {
                "README.md",
                "windows_clipboard.py",
                "desktop/src/new view.tsx",
                "mobile/src/committed.ts",
            },
        )
        self.assertEqual(
            plan["components"],
            {job: job in delivery_policy.select_jobs(plan["paths"]) for job in JOBS},
        )

    def test_committed_and_staged_renames_keep_both_paths(self):
        (self.repo / "docs").mkdir()
        self.git("mv", "windows_clipboard.py", "docs/moved.md")
        self.commit()
        self.git("mv", "README.md", "docs/renamed.md")
        plan = validate.build_plan(self.repo)
        self.assertEqual(
            set(plan["paths"]),
            {"windows_clipboard.py", "docs/moved.md", "README.md", "docs/renamed.md"},
        )
        self.assertTrue(plan["components"]["python"])

    def test_staged_link_selects_all_even_when_the_worktree_is_regular(self):
        blob = self.git("hash-object", "README.md").strip()
        self.git("update-index", "--cacheinfo", "120000", blob, "README.md")
        self.assertFalse((self.repo / "README.md").is_symlink())
        plan = validate.build_plan(self.repo)
        self.assertTrue(all(plan["components"].values()))

    def test_policy_is_the_selection_owner_and_full_does_not_hide_invalid_refs(self):
        self.write("unknown.control", "input\n")
        with patch.object(
            delivery_policy,
            "select_jobs",
            wraps=delivery_policy.select_jobs,
        ) as select:
            plan = validate.build_plan(self.repo)
        select.assert_called_once_with(set(plan["paths"]), repo=self.repo)
        self.assertTrue(all(plan["components"].values()))
        full = validate.build_plan(self.repo, base=self.base, full=True)
        self.assertTrue(all(full["components"].values()))
        for reference in ("missing-ref", "--help", "HEAD:path"):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                validate.build_plan(self.repo, base=reference, full=True)

    def test_docs_plan_and_forced_full_include_honest_external_gates(self):
        self.write("docs/only.md", "Text\n")
        plan = validate.build_plan(self.repo)
        self.assertFalse(any(plan["components"].values()))
        self.assertIn("policy", {check["component"] for check in plan["checks"]})
        full = validate.build_plan(self.repo, full=True)
        gates = {check["id"] for check in full["checks"] if "reason" in check}
        self.assertTrue(
            {
                "windows-package",
                "installer",
                "server-database-container",
                "ios-native",
                "audits",
            }
            <= gates
        )
        python = next(
            check for check in full["checks"] if check["id"] == "python-tests"
        )
        self.assertIn("unit", python["argv"])
        self.assertNotIn("compatibility", python["argv"])
        native = next(check for check in full["checks"] if check["id"] == "qt-tests")
        self.assertIn("compatibility", native["argv"])

    def test_plan_only_json_does_not_execute_checks(self):
        with (
            patch.object(validate, "ROOT", self.repo),
            patch.object(
                validate, "run_plan", side_effect=AssertionError("Executed a plan")
            ),
            patch("sys.stdout") as output,
        ):
            self.assertEqual(validate.main(["--plan", "--full"]), 0)
        document = "".join(call.args[0] for call in output.write.call_args_list)
        self.assertTrue(json.loads(document)["full"])

    def test_settings_runs_build_then_built_and_source_contracts(self):
        self.write("desktop/src/changed.ts", "export {};\n")
        plan = validate.build_plan(self.repo)
        ids = [check["id"] for check in plan["checks"]]
        self.assertLess(ids.index("desktop-build"), ids.index("desktop-test:boot"))
        self.assertLess(
            ids.index("desktop-test:boot"), ids.index("desktop-test:browser")
        )


class ValidationExecutionTests(unittest.TestCase):
    def check(self, name, script):
        return {
            "id": name,
            "component": "repository",
            "cwd": str(ROOT),
            "argv": [sys.executable, "-c", script],
        }

    def test_failure_and_unexecuted_gates_cannot_report_success(self):
        plan = {
            "checks": [
                self.check("failure", "raise SystemExit(7)"),
                {"id": "ios", "component": "ios", "reason": "Needs macOS"},
            ]
        }
        report = validate.run_plan(plan, timeout=10, check_timeout=5)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["results"][0]["returncode"], 7)
        self.assertEqual(report["results"][1]["status"], "unexecuted")
        report = validate.run_plan({"checks": [plan["checks"][1]]})
        self.assertEqual(report["status"], "incomplete")

    def test_buffered_stderr_does_not_disable_subprocess_checks(self):
        with patch("sys.stderr", io.StringIO()):
            report = validate.run_plan({"checks": [self.check("buffered", "pass")]})
        self.assertEqual(report["status"], "passed")

    def test_missing_executable_and_exhausted_budget_are_unexecuted(self):
        missing = self.check("missing", "pass")
        missing["argv"] = [str(ROOT / "does-not-exist-executable")]
        report = validate.run_plan({"checks": [missing]})
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["results"][0]["status"], "unexecuted")
        with patch.object(validate.time, "monotonic", side_effect=[0, 20]):
            report = validate.run_plan(
                {"checks": [self.check("late", "pass")]}, timeout=10
            )
        self.assertEqual(report["results"][0]["status"], "unexecuted")

    def test_timeout_stops_the_check_and_remaining_budget_is_bounded(self):
        report = validate.run_plan(
            {"checks": [self.check("slow", "import time; time.sleep(30)")]},
            timeout=5,
            check_timeout=0.1,
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["results"][0]["status"], "timed_out")

    @unittest.skipUnless(os.name == "nt", "Windows process-tree cleanup")
    def test_timeout_also_stops_descendant_processes(self):
        import _winapi

        with TemporaryDirectory() as directory:
            marker = Path(directory) / "child-pid.txt"
            child_script = (
                "import os, time, pathlib; "
                f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); "
                "time.sleep(30)"
            )
            script = (
                "import subprocess, sys, time; "
                f"subprocess.Popen([sys.executable, '-c', {child_script!r}]); "
                "time.sleep(30)"
            )
            report = validate.run_plan(
                {"checks": [self.check("parent", script)]},
                timeout=5,
                check_timeout=2,
            )
            self.assertEqual(report["results"][0]["status"], "timed_out")
            self.assertTrue(marker.exists(), "The fixture did not start its child")
            try:
                handle = _winapi.OpenProcess(
                    0x1000 | 0x0001, False, int(marker.read_text())
                )
            except OSError as error:
                self.assertEqual(error.winerror, 87)  # The process no longer exists.
            else:
                try:
                    code = _winapi.GetExitCodeProcess(handle)
                    if code == 259:  # STILL_ACTIVE
                        _winapi.TerminateProcess(handle, 1)
                    self.assertNotEqual(code, 259, "A descendant outlived the timeout")
                finally:
                    _winapi.CloseHandle(handle)

    def test_cancelled_run_does_not_execute_later_checks(self):
        process = Mock()
        process.wait.side_effect = KeyboardInterrupt
        with patch.object(validate.subprocess, "Popen", return_value=process) as start:
            with patch.object(validate, "stop_process") as stop:
                report = validate.run_plan(
                    {
                        "checks": [
                            self.check("cancel", "pass"),
                            self.check("later", "pass"),
                        ]
                    }
                )
        stop.assert_called_once_with(process)
        self.assertEqual(start.call_count, 1)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            [result["status"] for result in report["results"]],
            ["cancelled", "unexecuted"],
        )

    def test_frontend_checks_do_not_load_local_dotenv(self):
        with TemporaryDirectory() as directory:
            Path(directory, ".env.local").write_text("TEST_ONLY=value\n")
            check = self.check("frontend", "raise RuntimeError('must not run')")
            check.update(component="settings_browser", cwd=directory)
            report = validate.run_plan({"checks": [check]})
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["results"][0]["status"], "unexecuted")

    def test_child_environment_has_no_credentials_and_uses_a_temporary_profile(self):
        with TemporaryDirectory() as directory:
            observation = Path(directory) / "observation.json"
            script = (
                "import json, os, pathlib; "
                f"pathlib.Path({str(observation)!r}).write_text(json.dumps("
                "{name: os.environ.get(name) for name in "
                "('HOME', 'CLARIFY_SKIP_DOTENV', 'EXPO_NO_DOTENV', 'GROQ_API_KEY')}))"
            )
            with patch.dict(os.environ, {"GROQ_API_KEY": "synthetic-only"}):
                report = validate.run_plan({"checks": [self.check("env", script)]})
            self.assertEqual(report["status"], "passed")
            environment = json.loads(observation.read_text())
            self.assertIsNone(environment["GROQ_API_KEY"])
            self.assertEqual(environment["CLARIFY_SKIP_DOTENV"], "1")
            self.assertEqual(environment["EXPO_NO_DOTENV"], "1")
            self.assertFalse(Path(environment["HOME"]).exists())

    def test_browser_download_cache_survives_profile_isolation(self):
        with TemporaryDirectory() as directory:
            observation = Path(directory) / "browser.json"
            script = (
                "import json, os, pathlib; "
                f"pathlib.Path({str(observation)!r}).write_text(json.dumps("
                "{key: os.environ[key] for key in ('PLAYWRIGHT_BROWSERS_PATH', 'LOCALAPPDATA')}))"
            )
            for configured in (None, str(Path(directory) / "explicit-cache")):
                with self.subTest(configured=configured), patch.dict(os.environ):
                    os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
                    os.environ["LOCALAPPDATA"] = directory
                    if configured is not None:
                        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = configured
                    with patch.object(validate.sys, "platform", "win32"):
                        report = validate.run_plan(
                            {"checks": [self.check("cache", script)]}
                        )
                    self.assertEqual(report["status"], "passed")
                    environment = json.loads(observation.read_text())
                    self.assertEqual(
                        environment["PLAYWRIGHT_BROWSERS_PATH"],
                        configured or str(Path(directory) / "ms-playwright"),
                    )
                    self.assertNotEqual(environment["LOCALAPPDATA"], directory)


if __name__ == "__main__":
    unittest.main()
