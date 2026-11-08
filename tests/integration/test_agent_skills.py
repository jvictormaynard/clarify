"""Check project skill integrity against isolated repositories."""

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_agent_skills import check


class AgentSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clarify-skills-test-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.base = self.repo / ".agents" / "skills"
        self.skill = self.base / "example"
        (self.skill / "agents").mkdir(parents=True)
        self.entrypoint = self.skill / "SKILL.md"
        self.entrypoint.write_text(
            '---\nname: example\ndescription: "A test skill"\n---\n\n'
            "[Reference](../../../guide.md)\n",
            encoding="utf-8",
        )
        self.metadata = self.skill / "agents" / "openai.yaml"
        self.metadata.write_text(
            'interface:\n  display_name: "Example"\npolicy:\n'
            "  allow_implicit_invocation: true\n",
            encoding="utf-8",
        )
        (self.repo / "guide.md").write_text("Reference", encoding="utf-8")
        (self.base / "LICENSE.txt").write_text("MIT test fixture", encoding="utf-8")
        self.manifest = {
            "schema_version": 1,
            "repository": "https://github.com/mattpocock/skills",
            "commit": "a" * 40,
            "project_skills": [],
            "license_file": "LICENSE.txt",
            "license_sha256": hashlib.sha256(b"MIT test fixture").hexdigest(),
            "skills": [
                {
                    "name": "example",
                    "bucket": "engineering",
                    "source_path": "skills/engineering/example",
                    "decision": "adapted",
                    "local_skill": "example",
                    "reason": "Isolated validation fixture",
                    "source_files": {"SKILL.md": "b" * 64},
                }
            ],
        }
        self.write_manifest()

    def write_manifest(self):
        (self.base / "upstream-lock.json").write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )

    def make_explicit_only(self):
        self.entrypoint.write_text(
            self.entrypoint.read_text(encoding="utf-8").replace(
                'description: "A test skill"',
                'description: "A test skill"\ndisable-model-invocation: true',
            ),
            encoding="utf-8",
        )

    def test_valid_project_with_local_reference_passes(self):
        self.assertEqual(check(self.repo), [])

    def test_broken_reference_is_reported(self):
        (self.repo / "guide.md").unlink()
        self.assertTrue(any("missing reference" in e for e in check(self.repo)))

    def test_reference_outside_project_is_rejected(self):
        self.entrypoint.write_text(
            '---\nname: example\ndescription: "Test"\n---\n\n'
            "[Outside](../../../../other-project.md)\n",
            encoding="utf-8",
        )
        self.assertTrue(any("escapes project" in e for e in check(self.repo)))

    def test_example_link_in_code_fence_is_not_a_reference(self):
        with self.entrypoint.open("a", encoding="utf-8") as document:
            document.write("\n```markdown\n[Example](not-a-real-file.md)\n```\n")
        self.assertEqual(check(self.repo), [])

    def test_drive_or_file_uri_cannot_hide_a_global_reference(self):
        for target in (
            "C:/Users/example/global-skill.md",
            "file:///tmp/global-skill.md",
        ):
            with self.subTest(target=target):
                self.entrypoint.write_text(
                    '---\nname: example\ndescription: "Test"\n---\n\n'
                    f"[Outside]({target})\n",
                    encoding="utf-8",
                )
                self.assertTrue(
                    any("unsupported local reference" in e for e in check(self.repo))
                )

    def test_missing_metadata_does_not_pass(self):
        self.metadata.unlink()
        self.assertTrue(check(self.repo))

    def test_explicit_only_flag_conflicts_with_implicit_policy(self):
        self.make_explicit_only()
        self.assertTrue(any("conflicts" in e for e in check(self.repo)))

    def test_explicit_only_skill_with_matching_policy_passes(self):
        self.make_explicit_only()
        self.metadata.write_text(
            self.metadata.read_text(encoding="utf-8").replace("true", "false"),
            encoding="utf-8",
        )
        self.assertEqual(check(self.repo), [])

    def test_unrecorded_skill_is_rejected(self):
        extra = self.base / "extra"
        (extra / "agents").mkdir(parents=True)
        (extra / "SKILL.md").write_text(
            '---\nname: extra\ndescription: "Test"\n---\n\n', encoding="utf-8"
        )
        (extra / "agents" / "openai.yaml").write_text("interface:\n", encoding="utf-8")
        self.assertTrue(any("unexpected=['extra']" in e for e in check(self.repo)))

    def test_excluded_skill_cannot_remain_installed(self):
        self.manifest["skills"][0].update(decision="excluded", local_skill=None)
        self.write_manifest()
        self.assertTrue(any("unexpected=['example']" in e for e in check(self.repo)))

    def test_duplicate_audit_entry_is_rejected(self):
        self.manifest["skills"].append(dict(self.manifest["skills"][0]))
        self.write_manifest()
        self.assertTrue(any("duplicate upstream" in e for e in check(self.repo)))

    def test_mutable_upstream_ref_is_rejected(self):
        self.manifest["commit"] = "main"
        self.write_manifest()
        self.assertTrue(any("immutable SHA" in e for e in check(self.repo)))

    def test_upstream_path_cannot_escape_through_bucket(self):
        self.manifest["skills"][0]["bucket"] = "../../outside"
        self.manifest["skills"][0]["source_path"] = "skills/../../outside/example"
        self.write_manifest()
        self.assertTrue(any("invalid upstream bucket" in e for e in check(self.repo)))

    def test_global_skill_root_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="clarify-outside-root-") as outside:
            self.base.rename(self.repo / "saved-skills")
            try:
                self.base.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Symlink permission unavailable: {exc}")
            self.assertTrue(any("escapes the project" in e for e in check(self.repo)))

    def test_changed_license_is_rejected(self):
        (self.base / "LICENSE.txt").write_text("Modified license", encoding="utf-8")
        self.assertTrue(
            any("license is missing or modified" in e for e in check(self.repo))
        )

    def test_git_checkout_keeps_pinned_license_with_windows_line_endings(self):
        root = Path(__file__).resolve().parents[2]
        upstream = json.loads(
            (root / ".agents/skills/upstream-lock.json").read_text(encoding="utf-8")
        )
        relative = upstream["license_file"]
        canonical = (
            (root / ".agents/skills" / relative).read_bytes().replace(b"\r\n", b"\n")
        )
        license_path = self.base / relative
        license_path.parent.mkdir(parents=True)
        license_path.write_bytes(canonical)
        self.manifest["license_file"] = relative
        self.manifest["license_sha256"] = upstream["license_sha256"]
        self.write_manifest()
        (self.repo / ".gitattributes").write_bytes(
            (root / ".gitattributes").read_bytes()
        )
        environment = dict(os.environ)
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
            environment.pop(name, None)
        environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

        def run_git(*args):
            subprocess.run(
                ["git", "-C", str(self.repo), "-c", "core.autocrlf=true", *args],
                env=environment,
                capture_output=True,
                check=True,
            )

        run_git("init")
        run_git("add", "--", ".gitattributes", ".agents", "guide.md")
        license_path.unlink()
        run_git("checkout-index", "--all", "--force")
        self.assertEqual(check(self.repo), [])
        self.assertEqual(license_path.read_bytes(), canonical)

    def test_global_skill_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="clarify-outside-skill-") as outside:
            try:
                (self.base / "linked").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Symlink permission unavailable: {exc}")
            self.assertTrue(any("regular files" in e for e in check(self.repo)))


if __name__ == "__main__":
    unittest.main()
