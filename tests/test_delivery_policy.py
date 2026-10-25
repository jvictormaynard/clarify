import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import scripts.delivery_policy as policy
from scripts.delivery_policy import affected_components, changed_paths, event_components
from unittest.mock import patch


COMPONENTS = (
    "desktop",
    "settings",
    "package",
    "installer",
    "server",
    "mobile",
    "ios",
    "audit",
)


def selection(*components):
    return {component: component in components for component in COMPONENTS}


def release_intent(component):
    intent = {
        "schema": 1,
        "component": component,
        "version": "1.2.3",
        "base_sha": "a" * 40,
        "notes": "Fixture release.",
        "evidence": {
            "report_url": "https://github.com/jvictormaynard/clarify/issues/1"
        },
    }
    if component == "desktop":
        intent["evidence"].update(tested_sha="a" * 40, windows_accepted=True)
    else:
        intent["evidence"].update(
            build="2",
            highest_build="1",
            pending_builds_checked=True,
            checked_at="2026-10-25T20:00:00Z",
        )
    return intent


class DeliveryPolicyTests(unittest.TestCase):
    def test_design_changes_select_only_the_web_or_mobile_checks(self):
        for path, component in (
            ("desktop/src/app.tsx", "settings"),
            ("desktop/src/styles/tokens.css", "settings"),
            ("desktop/tests/settings.spec.ts", "settings"),
            ("mobile/src/app/sign-in.tsx", "mobile"),
            ("mobile/src/history.ts", "mobile"),
            ("mobile/modules/clarify-core/index.ts", "mobile"),
        ):
            with self.subTest(path=path):
                self.assertEqual(affected_components([path]), selection(component))

    def test_python_and_qml_do_not_build_a_native_package(self):
        for path in ("windows_clipboard.py", "clarify/desktop/qml/Main.qml"):
            with self.subTest(path=path):
                self.assertEqual(affected_components([path]), selection("desktop"))

    def test_settings_bridge_inputs_select_python_and_web_checks(self):
        for path in (
            "clarify/desktop/qml_web_settings.py",
            "clarify/desktop/qml_settings.py",
            "repositories.py",
            "workflow_config.py",
            "tests/web_settings_fixture.py",
            "tests/test_web_settings.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    affected_components([path]), selection("desktop", "settings")
                )

    def test_native_mobile_inputs_select_ios_without_desktop_jobs(self):
        for path in (
            "mobile/native/keyboard/KeyboardViewController.swift",
            "mobile/native/keyboard/KeyboardHeightSync.m",
            "mobile/plugins/with-clarify-keyboard.cjs",
            "mobile/app.json",
            "mobile/locales/pt.json",
            "mobile/app.config.ts",
            "mobile/eas.json",
            "mobile/assets/icon.png",
            "mobile/modules/clarify-core/expo-module.config.json",
            "mobile/scripts/test-keyboard-ui.cjs",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    affected_components([path]), selection("mobile", "ios")
                )

    def test_dependencies_select_their_consumers_and_existing_desktop_audits(self):
        for path, expected in (
            ("requirements.txt", selection("desktop", "settings", "package", "audit")),
            (
                "requirements-lock-linux.txt",
                selection("desktop", "settings", "package", "audit"),
            ),
            (
                "requirements-lock-runtime-windows.txt",
                selection("desktop", "settings", "package", "audit"),
            ),
            (
                "desktop/package-lock.json",
                selection("desktop", "settings", "package", "audit"),
            ),
            (
                "desktop/src-tauri/Cargo.lock",
                selection("desktop", "settings", "package", "audit"),
            ),
            ("server/requirements.txt", selection("server")),
            ("mobile/package.json", selection("mobile", "ios")),
            ("mobile/package-lock.json", selection("mobile", "ios")),
            (
                "mobile/modules/clarify-core/Package.swift",
                selection("mobile", "ios"),
            ),
        ):
            with self.subTest(path=path):
                self.assertEqual(affected_components([path]), expected)

    def test_build_inputs_select_portable_packaging_without_msi_checks(self):
        for path in (
            "scripts/build.ps1",
            "scripts/build-settings.ps1",
            "scripts/windows-build-paths.ps1",
            "build.bat",
            "scripts/pyinstaller-hooks/hook-PySide6.QtQml.py",
            "desktop/src-tauri/tauri.conf.json",
            "desktop/src-tauri/src/main.rs",
            "desktop/vite.config.ts",
            "desktop/scripts/build.mjs",
            "Clarify.spec",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    affected_components([path]),
                    selection("desktop", "settings", "package"),
                )

    def test_bundled_assets_licenses_and_asr_manifests_select_packaging(self):
        for path in (
            "assets/branding/clarify.ico",
            "licenses/whisper.cpp-MIT.txt",
            "LICENSE",
            "local_asr_manifest.json",
            "local_asr_manifests/ggml-base-cpu.json",
            "extra/sox-14.4.2/sox.exe",
            "distribution/portable-update-policy.json",
        ):
            with self.subTest(path=path):
                selected = affected_components([path])
                self.assertTrue(selected["desktop"])
                self.assertTrue(selected["package"])
                self.assertFalse(selected["installer"])
                self.assertFalse(selected["ios"])

    def test_only_installer_inputs_add_msi_checks_to_desktop_builds(self):
        for path in (
            "installer/Clarify.wxs",
            "scripts/build-installer.ps1",
            "scripts/test-installer.ps1",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    affected_components([path]),
                    selection("desktop", "settings", "package", "installer"),
                )

    def test_unknown_paths_fail_closed_and_selection_is_order_independent(self):
        for path in (
            "new-component/runtime.toml",
            "future.config",
            ".github/workflows/new-validation.yml",
        ):
            with self.subTest(path=path):
                self.assertEqual(affected_components([path]), selection(*COMPONENTS))
        paths = ["desktop/src/app.tsx", "mobile/src/history.ts", "server/start.py"]
        expected = selection("settings", "mobile", "server")
        self.assertEqual(affected_components(paths), expected)
        self.assertEqual(affected_components(list(reversed(paths)) + paths), expected)
        self.assertEqual(affected_components([]), selection())

    def test_client_contract_dependencies_also_select_server_tests(self):
        for path in (
            "clarify_account.py",
            "social_login.py",
            "account_history.py",
            "history_store.py",
            "secret_store.py",
            "provider_types.py",
        ):
            with self.subTest(path=path):
                self.assertTrue(affected_components([path])["server"])

    def test_manual_runs_and_new_branches_validate_all_components(self):
        for event_name, event in (
            ("workflow_dispatch", {}),
            ("push", {"before": "0" * 40}),
        ):
            with self.subTest(event=event_name):
                self.assertEqual(
                    event_components(Path("."), event_name, event, "a" * 40),
                    selection(*COMPONENTS),
                )

    def test_push_uses_the_whole_push_range(self):
        with patch(
            "scripts.delivery_policy.changed_paths", return_value=["server/start.py"]
        ) as diff:
            selected = event_components(
                Path("."), "push", {"before": "a" * 40}, "b" * 40
            )
        diff.assert_called_once_with(Path("."), "a" * 40, "b" * 40)
        self.assertTrue(selected["server"])

    def test_pull_request_validates_the_tested_merge_against_base(self):
        event = {"pull_request": {"base": {"sha": "a" * 40}, "head": {"sha": "c" * 40}}}
        with patch(
            "scripts.delivery_policy.changed_paths", return_value=["mobile/app.json"]
        ) as diff:
            selected = event_components(Path("."), "pull_request", event, "b" * 40)
        diff.assert_called_once_with(Path("."), "a" * 40, "b" * 40)
        self.assertTrue(selected["ios"])

    def test_missing_or_unsafe_change_boundaries_fail_validation(self):
        with self.assertRaises(KeyError):
            event_components(Path("."), "push", {}, "a" * 40)
        for revision in (None, "main", "-Sfixture", "a" * 39, "a" * 40 + "\n"):
            for base, head in ((revision, "a" * 40), ("a" * 40, revision)):
                with self.subTest(base=base, head=head), self.assertRaises(ValueError):
                    changed_paths(Path("."), base, head)

    def test_git_failures_cannot_look_like_an_empty_diff(self):
        for error in (
            subprocess.CalledProcessError(128, "git"),
            subprocess.TimeoutExpired("git", 30),
        ):
            with self.subTest(error=error):
                with patch("scripts.delivery_policy.subprocess.run", side_effect=error):
                    with self.assertRaises(type(error)):
                        changed_paths(Path("."), "a" * 40, "b" * 40)

    def test_documentation_does_not_select_product_validation(self):
        paths = [
            "docs/development.md",
            "server/README.md",
            "mobile/README.md",
            "AGENTS.md",
            ".agents/skills/tdd/SKILL.md",
        ]
        self.assertEqual(
            affected_components(paths),
            selection(),
        )

    def test_server_runtime_and_docker_inputs_select_server(self):
        for path in (
            "server/cloud/service/api.py",
            "server/requirements.txt",
            ".dockerignore",
            "dictionary_snippets.py",
        ):
            with self.subTest(path=path):
                self.assertTrue(affected_components([path])["server"])

    def test_shared_contracts_and_canonical_prompts_select_all_consumers(self):
        for path in (
            "shared/usage.ts",
            "shared/ui_strings.json",
            "shared/text_prompts.json",
            "workflow_provider.py",
            "mobile/modules/clarify-core/ios/RewritePrompt.swift",
            "scripts/sync_locales.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    affected_components([path]),
                    selection(
                        "desktop", "settings", "package", "server", "mobile", "ios"
                    ),
                )

    def test_platform_changes_select_only_their_component(self):
        for path, component in (
            ("clarify/desktop/qml/Main.qml", "desktop"),
            ("desktop/src/App.tsx", "settings"),
            ("server/start.py", "server"),
            ("mobile/src/app/index.tsx", "mobile"),
        ):
            with self.subTest(path=path):
                selected = affected_components([path])
                self.assertEqual(
                    [name for name, value in selected.items() if value], [component]
                )

    def test_ci_changes_revalidate_all_components(self):
        for path in (
            ".github/workflows/ci.yml",
            "scripts/delivery_policy.py",
            "tests/test_delivery_policy.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(affected_components([path]), selection(*COMPONENTS))

    def test_reusable_validation_changes_select_their_consumers(self):
        for path, expected in (
            (".github/workflows/server-validation.yml", selection("server")),
            (".github/workflows/ios-validation.yml", selection("mobile", "ios")),
            (
                ".github/workflows/shared-account.yml",
                selection("server", "mobile", "ios"),
            ),
            (".github/workflows/settings-validation.yml", selection("settings")),
            (
                ".github/actions/settings-build/action.yml",
                selection("desktop", "settings", "package"),
            ),
        ):
            with self.subTest(path=path):
                self.assertEqual(affected_components([path]), expected)

    def test_server_mail_templates_are_runtime_inputs(self):
        self.assertTrue(
            affected_components(
                ["server/cloud/service/templates/account/email/login_code_message.txt"]
            )["server"]
        )

    def test_change_range_includes_deleted_rename_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {
                **os.environ,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            }

            def git(*args):
                return subprocess.check_output(
                    ["git", "-C", str(root), *args], env=env, text=True
                ).strip()

            git("init", "--quiet")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "user.name", "Fixture")
            git("config", "core.hooksPath", os.devnull)
            (root / "server").mkdir()
            (root / "server/input.py").write_text("# fixture\n", encoding="utf-8")
            git("add", "server/input.py")
            git("commit", "--quiet", "-m", "fixture source")
            base = git("rev-parse", "HEAD")
            (root / "docs").mkdir()
            git("mv", "server/input.py", "docs/input.md")
            git("commit", "--quiet", "-m", "fixture rename")
            paths = changed_paths(root, base, git("rev-parse", "HEAD"))
            self.assertCountEqual(paths, ["server/input.py", "docs/input.md"])
            self.assertTrue(affected_components(paths)["server"])


class ReleaseIntentSelectionTests(unittest.TestCase):
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
        return event_components(self.root, "push", {"before": self.base}, head)

    def test_release_intent_selects_only_its_platform_from_the_tested_commit(self):
        for component, expected in (
            ("desktop", selection("desktop", "settings", "package", "audit")),
            ("mobile", selection("mobile", "ios")),
        ):
            with self.subTest(component=component):
                self.intent_path.write_text(
                    json.dumps(release_intent(component)), encoding="utf-8"
                )
                head = self.commit()
                # The checked-out file is deliberately not the tested source.
                self.intent_path.write_text(
                    '{"schema":1,"component":"unknown"}', encoding="utf-8"
                )
                self.assertEqual(self.select(head), expected)

    def test_invalid_unknown_or_deleted_intent_selects_full_validation(self):
        for data in (
            "{",
            "null",
            "[]",
            "{}",
            '{"component":"mobile"}',
            '{"schema":1,"component":"server"}',
            '{"schema":true,"component":"mobile"}',
            '{"schema":2,"component":"mobile"}',
            '{"schema":1,"component":[]}',
            '{"schema":1,"component":"desktop","component":"mobile"}',
        ):
            with self.subTest(data=data):
                with (
                    patch(
                        "scripts.delivery_policy.changed_paths",
                        return_value=[".github/release-intent.json"],
                    ),
                    patch(
                        "scripts.delivery_policy.subprocess.run",
                        side_effect=[
                            subprocess.CompletedProcess(
                                [], 0, stdout=b"100644 blob fixture"
                            ),
                            subprocess.CompletedProcess([], 0, stdout=data.encode()),
                        ],
                    ),
                ):
                    self.assertEqual(self.select("a" * 40), selection(*COMPONENTS))
        self.intent_path.write_text(
            json.dumps(release_intent("mobile")), encoding="utf-8"
        )
        self.base = self.commit()
        self.intent_path.unlink()
        self.assertEqual(self.select(self.commit()), selection(*COMPONENTS))

    def test_invalid_release_version_or_evidence_cannot_reduce_validation(self):
        for component, field, value in (
            ("desktop", "version", "invalid"),
            ("desktop", "windows_accepted", False),
            ("desktop", "tested_sha", "b" * 40),
            ("mobile", "pending_builds_checked", False),
            ("mobile", "build", "1"),
        ):
            with self.subTest(component=component, field=field):
                intent = release_intent(component)
                if field == "version":
                    intent[field] = value
                else:
                    intent["evidence"][field] = value
                with (
                    patch(
                        "scripts.delivery_policy.changed_paths",
                        return_value=[".github/release-intent.json"],
                    ),
                    patch(
                        "scripts.delivery_policy.subprocess.run",
                        side_effect=[
                            subprocess.CompletedProcess(
                                [], 0, stdout=b"100644 blob fixture"
                            ),
                            subprocess.CompletedProcess(
                                [], 0, stdout=json.dumps(intent).encode()
                            ),
                        ],
                    ),
                ):
                    self.assertEqual(self.select("a" * 40), selection(*COMPONENTS))

    def test_release_intent_does_not_hide_other_changed_components(self):
        self.intent_path.write_text(
            json.dumps(release_intent("mobile")), encoding="utf-8"
        )
        (self.root / "server").mkdir()
        (self.root / "server/start.py").write_text("# fixture\n", encoding="utf-8")
        self.assertEqual(
            self.select(self.commit()), selection("server", "mobile", "ios")
        )

    def test_pull_request_reads_intent_from_the_tested_merge(self):
        self.intent_path.write_text(
            json.dumps(release_intent("desktop")), encoding="utf-8"
        )
        head = self.commit()
        event = {
            "pull_request": {"base": {"sha": self.base}, "head": {"sha": self.base}}
        }
        self.assertEqual(
            event_components(self.root, "pull_request", event, head),
            selection("desktop", "settings", "package", "audit"),
        )

    def test_unreadable_intent_falls_back_to_full_validation(self):
        with patch(
            "scripts.delivery_policy.changed_paths",
            return_value=[".github/release-intent.json"],
        ):
            for error in (OSError("unavailable"), subprocess.TimeoutExpired("git", 30)):
                with self.subTest(error=error):
                    with patch(
                        "scripts.delivery_policy.subprocess.run", side_effect=error
                    ):
                        self.assertEqual(self.select("a" * 40), selection(*COMPONENTS))

    def test_release_metadata_cannot_be_a_symlink(self):
        self.intent_path.write_text(
            json.dumps(release_intent("mobile")), encoding="utf-8"
        )
        self.git("add", ".github/release-intent.json")
        blob = self.git("hash-object", ".github/release-intent.json")
        self.git(
            "update-index", "--cacheinfo", f"120000,{blob},.github/release-intent.json"
        )
        self.git("commit", "--quiet", "-m", "fixture link")
        self.assertEqual(
            self.select(self.git("rev-parse", "HEAD")), selection(*COMPONENTS)
        )

    def test_complete_tested_merge_excludes_changes_already_in_base(self):
        self.git("checkout", "--quiet", "-b", "feature")
        (self.root / "server").mkdir()
        (self.root / "server/start.py").write_text(
            "# earlier change\n", encoding="utf-8"
        )
        self.commit()
        (self.root / "desktop/src").mkdir(parents=True)
        (self.root / "desktop/src/app.tsx").write_text(
            "// later design change\n", encoding="utf-8"
        )
        feature_head = self.commit()
        self.git("checkout", "--quiet", "-b", "target", self.base)
        (self.root / "mobile/src").mkdir(parents=True)
        (self.root / "mobile/src/history.ts").write_text(
            "// already in base\n", encoding="utf-8"
        )
        base = self.commit()
        self.git("merge", "--quiet", "--no-edit", "feature")
        tested_merge = self.git("rev-parse", "HEAD")
        event = {"pull_request": {"base": {"sha": base}, "head": {"sha": feature_head}}}
        self.assertEqual(
            event_components(self.root, "pull_request", event, tested_merge),
            selection("server", "settings"),
        )

    def test_selector_cli_writes_all_eight_output_flags(self):
        (self.root / "desktop/src").mkdir(parents=True)
        (self.root / "desktop/src/app.tsx").write_text("// fixture\n", encoding="utf-8")
        head = self.commit()
        event_path = self.root / "event.json"
        event_path.write_text(json.dumps({"before": self.base}), encoding="utf-8")
        output_path = self.root / "output.txt"
        output_path.write_text("existing=kept\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(Path(policy.__file__)), "--repo", str(self.root)],
            env={
                **self.env,
                "GITHUB_EVENT_PATH": str(event_path),
                "GITHUB_OUTPUT": str(output_path),
                "GITHUB_EVENT_NAME": "push",
                "GITHUB_SHA": head,
            },
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), selection("settings"))
        self.assertEqual(
            output_path.read_text(encoding="utf-8").splitlines(),
            [
                "existing=kept",
                *[
                    f"{key}={str(value).lower()}"
                    for key, value in selection("settings").items()
                ],
            ],
        )


def ci_needs(*selected):
    flags = selection(*selected)
    needs = {
        "components": {
            "result": "success",
            "outputs": {key: str(value).lower() for key, value in flags.items()},
        },
        "repository": {"result": "success"},
    }
    for component, required in flags.items():
        needs["test" if component == "desktop" else component] = {
            "result": "success" if required else "skipped"
        }
    return needs


class CiResultTests(unittest.TestCase):
    def test_successful_selected_jobs_and_skipped_unselected_jobs_pass(self):
        for selected in ((), ("settings",), ("mobile", "ios"), COMPONENTS):
            with self.subTest(selected=selected):
                policy.validate_ci_results(ci_needs(*selected))
        needs = ci_needs()
        needs["test"]["result"] = "success"
        policy.validate_ci_results(needs)

    def test_repository_and_selector_must_succeed(self):
        for job in ("components", "repository"):
            for result in ("skipped", "failure", "cancelled", "timed_out", None):
                with self.subTest(job=job, result=result):
                    needs = ci_needs()
                    needs[job]["result"] = result
                    with self.assertRaises(ValueError):
                        policy.validate_ci_results(needs)

    def test_every_selected_job_must_succeed(self):
        for component in COMPONENTS:
            job = "test" if component == "desktop" else component
            for result in ("skipped", "failure", "cancelled", "timed_out", "", None):
                with self.subTest(component=component, result=result):
                    needs = ci_needs(component)
                    needs[job]["result"] = result
                    with self.assertRaises(ValueError):
                        policy.validate_ci_results(needs)

    def test_unselected_failed_cancelled_or_missing_jobs_cannot_pass(self):
        for job in ci_needs():
            with self.subTest(missing=job):
                needs = ci_needs()
                del needs[job]
                with self.assertRaises(ValueError):
                    policy.validate_ci_results(needs)
        for job in (
            "test",
            "settings",
            "package",
            "installer",
            "server",
            "mobile",
            "ios",
            "audit",
        ):
            for result in ("failure", "cancelled", "timed_out", None):
                with self.subTest(job=job, result=result):
                    needs = ci_needs()
                    needs[job]["result"] = result
                    with self.assertRaises(ValueError):
                        policy.validate_ci_results(needs)

    def test_flags_must_all_be_present_and_use_exact_boolean_strings(self):
        for component in COMPONENTS:
            with self.subTest(missing=component):
                needs = ci_needs()
                del needs["components"]["outputs"][component]
                with self.assertRaises(ValueError):
                    policy.validate_ci_results(needs)
            for value in (
                True,
                False,
                0,
                1,
                None,
                "True",
                "FALSE",
                "",
                " true",
                [],
                {},
            ):
                with self.subTest(component=component, value=value):
                    needs = ci_needs()
                    needs["components"]["outputs"][component] = value
                    with self.assertRaises(ValueError):
                        policy.validate_ci_results(needs)

    def test_malformed_payloads_and_job_records_fail(self):
        for payload in (None, [], "success", True, {}, {"components": None}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                policy.validate_ci_results(payload)
        for job in ci_needs():
            for record in (None, [], "success", {}):
                with self.subTest(job=job, record=record):
                    needs = ci_needs()
                    needs[job] = record
                    with self.assertRaises(ValueError):
                        policy.validate_ci_results(needs)
        for outputs in (None, [], "false"):
            with self.subTest(outputs=outputs):
                needs = ci_needs()
                needs["components"]["outputs"] = outputs
                with self.assertRaises(ValueError):
                    policy.validate_ci_results(needs)

    def test_additional_failed_needs_cannot_be_hidden(self):
        needs = ci_needs()
        needs["extra"] = {"result": "failure"}
        with self.assertRaises(ValueError):
            policy.validate_ci_results(needs)

    def test_check_results_cli_does_not_require_event_environment(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GITHUB_") and key != "CI_NEEDS"
        }
        cancelled = ci_needs("settings")
        cancelled["settings"]["result"] = "cancelled"
        for payload, status in (
            (json.dumps(ci_needs("settings")), 0),
            (json.dumps(cancelled), 1),
            ("{", 1),
            ("null", 1),
            (json.dumps({}), 1),
            ('{"components":{},"components":{}}', 1),
            (None, 1),
        ):
            with self.subTest(payload=payload):
                result = subprocess.run(
                    [sys.executable, str(Path(policy.__file__)), "--check-results"],
                    env={
                        **env,
                        **({"CI_NEEDS": payload} if payload is not None else {}),
                    },
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, status, result.stderr)
                if status:
                    self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
