import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.delivery_policy import affected_components, changed_paths, event_components
from unittest.mock import patch


class DeliveryPolicyTests(unittest.TestCase):
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
                self.assertTrue(
                    all(
                        event_components(
                            Path("."), event_name, event, "a" * 40
                        ).values()
                    )
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
        for revision in ("main", "-Sfixture", "a" * 39, "a" * 40 + "\n"):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                changed_paths(Path("."), revision, "a" * 40)

    def test_documentation_does_not_select_product_validation(self):
        paths = [
            "docs/development.md",
            "server/README.md",
            "mobile/README.md",
            "AGENTS.md",
        ]
        self.assertEqual(
            affected_components(paths),
            {"desktop": False, "server": False, "ios": False},
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
                    {"desktop": True, "server": True, "ios": True},
                )

    def test_platform_changes_select_only_their_component(self):
        for path, component in (
            ("clarify/desktop/qml/Main.qml", "desktop"),
            ("desktop/src/App.tsx", "desktop"),
            ("server/start.py", "server"),
            ("mobile/app.json", "ios"),
        ):
            with self.subTest(path=path):
                selected = affected_components([path])
                self.assertEqual(
                    [name for name, value in selected.items() if value], [component]
                )

    def test_ci_changes_revalidate_all_components(self):
        self.assertTrue(all(affected_components([".github/workflows/ci.yml"]).values()))

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


if __name__ == "__main__":
    unittest.main()
