"""Selection and terminal CI results fail closed at their public boundaries."""

import json
import os
import tempfile
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from ci import impact
from ci.tasks import JOBS, STANDARD


class DeliveryPolicyTests(unittest.TestCase):
    def test_dependency_closure(self):
        cases = {
            "requirements-lock-linux.txt": {
                "python",
                "qt",
                "package",
                "audit",
                "server",
            },
            "desktop/src/app.tsx": {"settings_unit", "settings_browser"},
            "clarify_account.py": {
                "python",
                "qt",
                "settings_unit",
                "settings_browser",
                "server",
            },
            "shared/computer_connect.json": {
                "python",
                "qt",
                "package",
                "server",
                "mobile",
                "ios",
            },
            "server/cloud/service/api.py": {"server"},
            "mobile/src/history.ts": {"mobile"},
            "mobile/native/keyboard/Controller.swift": {"mobile", "ios"},
            "mobile/package-lock.json": {"mobile", "ios", "audit"},
            "installer/Clarify.wxs": {"package", "installer"},
            "assets/clarify.ico": {"python", "qt", "package"},
            "distribution/portable-update-policy.json": {"python", "qt", "package"},
            "desktop/src-tauri/src/main.rs": {
                "package",
                "python",
                "qt",
                "settings_unit",
                "settings_browser",
            },
            "workflow_provider.py": {
                "python",
                "qt",
                "settings_unit",
                "settings_browser",
                "package",
                "server",
                "mobile",
            },
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertLessEqual(expected, impact.select_jobs([path]))
        paths = list(cases)
        self.assertEqual(
            impact.select_jobs(paths), impact.select_jobs(paths[::-1] + paths)
        )

    def test_documentation_has_only_mandatory_policy(self):
        for path in ("README.md", "mobile/README.md", "docs/release.md", "AGENTS.md"):
            self.assertEqual(impact.select_jobs([path]), set())
        self.assertEqual(
            impact.select_jobs(["tests/policy/test_repository.py"]), {"static"}
        )

    def test_unknown_control_invalid_and_linked_inputs_select_every_job(self):
        for path in (
            "new-component/config.toml",
            ".github/workflows/new.yml",
            "ci/tasks.py",
            "scripts/run_tests.py",
            ".github/release-intent.json",
            "../README.md",
            "/README.md",
            "",
            None,
        ):
            with self.subTest(path=path):
                self.assertEqual(impact.select_jobs([path]), set(JOBS))
        with patch.object(Path, "is_symlink", return_value=True):
            self.assertEqual(
                impact.select_jobs(["README.md"], repo=Path(".")), set(JOBS)
            )

    def test_main_is_full_standard_and_extended_is_scheduled_or_manual(self):
        with patch.object(
            impact,
            "changed_paths",
            side_effect=AssertionError("Main must not use path selection"),
        ):
            self.assertEqual(
                impact.event_jobs(Path("."), "push", {}, "a" * 40), STANDARD
            )
        for name in ("schedule", "workflow_dispatch"):
            self.assertEqual(
                impact.event_jobs(Path("."), name, {}, "a" * 40), set(JOBS)
            )
        with self.assertRaises(ValueError):
            impact.event_jobs(Path("."), "untrusted-event", {}, "a" * 40)

    def test_pull_request_tests_the_complete_merge_against_base(self):
        event = {"pull_request": {"base": {"sha": "a" * 40}, "head": {"sha": "c" * 40}}}
        with (
            patch.object(
                impact, "changed_paths", return_value=["server/start.py"]
            ) as diff,
            patch.object(impact, "git_links", return_value=False),
        ):
            self.assertEqual(
                impact.event_jobs(Path("."), "pull_request", event, "b" * 40),
                {"server"},
            )
        diff.assert_called_once_with(Path("."), "a" * 40, "b" * 40)
        for error in (
            ValueError("missing ref"),
            subprocess.CalledProcessError(128, "git"),
            subprocess.TimeoutExpired("git", 30),
        ):
            with patch.object(impact, "changed_paths", side_effect=error):
                self.assertEqual(
                    impact.event_jobs(Path("."), "pull_request", event, "b" * 40),
                    set(JOBS),
                )
        self.assertEqual(
            impact.event_jobs(Path("."), "pull_request", {}, "b" * 40), set(JOBS)
        )

    def test_only_complete_shas_are_git_arguments(self):
        for revision in (None, "main", "-Sfixture", "a" * 39, "a" * 40 + "\n"):
            with self.assertRaises(ValueError):
                impact.changed_paths(Path("."), revision, "b" * 40)
        with patch.object(
            impact.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, b"old.py\0new name.py\0"),
        ) as run:
            self.assertEqual(
                impact.changed_paths(Path("."), "a" * 40, "b" * 40),
                ["old.py", "new name.py"],
            )
        self.assertIn("--no-renames", run.call_args.args[0])

    def test_uncertain_native_projection_retains_native_tests(self):
        with patch.object(impact.subprocess, "run", side_effect=OSError("unavailable")):
            self.assertFalse(
                impact.native_catalog_unchanged(Path("."), "a" * 40, "b" * 40)
            )

    def test_runner_choice_is_guarded_and_windows_stays_hosted(self):
        self.assertEqual(impact.runner_profile()["linux"], "ubuntu-24.04")
        self.assertEqual(
            impact.runner_profile("blacksmith", "Organization")["linux"],
            "blacksmith-4vcpu-ubuntu-2404",
        )
        self.assertEqual(
            impact.runner_profile("blacksmith", "Organization")["windows"],
            "windows-2025",
        )
        for provider, owner in (("typo", "Organization"), ("blacksmith", "User")):
            with self.assertRaises(ValueError):
                impact.runner_profile(provider, owner)

    def results(self):
        return {
            "plan": {"result": "success", "outputs": dict.fromkeys(JOBS, "true")},
            "policy": {"result": "success"},
            **{job: {"result": "success"} for job in JOBS},
        }

    def test_all_selected_jobs_and_matrices_must_succeed(self):
        impact.validate_ci_results(self.results())
        for job in ("plan", "policy", *JOBS):
            for state in (None, "skipped", "failure", "cancelled", "timed_out"):
                needs = self.results()
                needs[job]["result"] = state
                with self.subTest(job=job, state=state), self.assertRaises(ValueError):
                    impact.validate_ci_results(needs)
        for job in self.results():
            needs = self.results()
            del needs[job]
            with self.assertRaises(ValueError):
                impact.validate_ci_results(needs)
        needs = self.results()
        needs["unexpected"] = {"result": "success"}
        with self.assertRaises(ValueError):
            impact.validate_ci_results(needs)

    def test_unselected_jobs_allow_only_success_or_skip_and_flags_are_strict(self):
        needs = self.results()
        for job in JOBS:
            needs["plan"]["outputs"][job] = "false"
            needs[job]["result"] = "skipped"
        impact.validate_ci_results(needs)
        for value in (True, False, None, "TRUE", "", [], {}):
            invalid = self.results()
            invalid["plan"]["outputs"]["python"] = value
            with self.assertRaises(ValueError):
                impact.validate_ci_results(invalid)
        with self.assertRaises(ValueError):
            json.loads('{"job":1,"job":2}', object_pairs_hook=impact.json_object)


class NativeCatalogSelectionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        self.git("init", "--quiet")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        self.git("config", "core.hooksPath", os.devnull)
        self.intent_path = self.root / ".github/release-intent.json"
        self.intent_path.parent.mkdir()
        (self.root / "README.md").write_text("Fixture\n", encoding="utf-8")
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], env=self.env, text=True
        ).strip()

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def select(self, head):
        return impact.event_jobs(
            self.root,
            "pull_request",
            {"pull_request": {"base": {"sha": self.base}}},
            head,
        )

    def test_desktop_translation_selection_uses_tested_catalogs_not_working_files(self):
        shared = self.root / "shared"
        shared.mkdir()
        catalog = {
            "Shared": {"pt": "Comum", "en": "Shared", "es": "Común"},
            "Desktop": {"pt": "Desktop", "en": "Desktop", "es": "Desktop"},
        }
        path = shared / "ui_strings.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        scope = shared / "desktop_ui_keys.json"
        scope.write_text('["Desktop"]', encoding="utf-8")
        self.base = self.commit()
        catalog["Desktop"]["en"] = "Desktop settings"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        head = self.commit()
        path.write_text("not the tested catalog", encoding="utf-8")
        scope.write_text("not the tested scope", encoding="utf-8")
        self.assertEqual(
            self.select(head),
            {
                "static",
                "python",
                "qt",
                "settings_unit",
                "settings_browser",
                "package",
                "server",
                "mobile",
            },
        )

    def test_native_or_unclassified_catalog_changes_and_invalid_scope_keep_ios(self):
        shared = self.root / "shared"
        shared.mkdir()
        catalog = {
            "Shared": {"pt": "Comum", "en": "Shared", "es": "Común"},
            "Desktop": {"pt": "Desktop", "en": "Desktop", "es": "Desktop"},
        }
        path = shared / "ui_strings.json"
        scope = shared / "desktop_ui_keys.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        scope.write_text('["Desktop"]', encoding="utf-8")
        self.base = self.commit()
        for source in ("Shared", "New"):
            with self.subTest(source=source):
                catalog[source] = {"pt": "Novo", "en": "New", "es": "Nuevo"}
                path.write_text(json.dumps(catalog), encoding="utf-8")
                self.assertIn("ios", self.select(self.commit()))
        catalog["Shared"] = {"pt": "Comum", "en": "Shared", "es": "Común"}
        del catalog["New"]
        catalog["Desktop"]["en"] = "Desktop settings"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        for invalid in ('["Missing"]', '["Desktop", "Desktop"]', "null", "{"):
            with self.subTest(scope=invalid):
                scope.write_text(invalid, encoding="utf-8")
                self.assertIn("ios", self.select(self.commit()))


if __name__ == "__main__":
    unittest.main()
