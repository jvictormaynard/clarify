"""PR evidence must authenticate exact integration and cannot suppress main gates."""

import copy
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import zipfile

from ci import evidence
from ci.tasks import JOBS, STANDARD


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.head, self.base, self.pr_head, self.tested, self.tree = [
            c * 40 for c in "abcde"
        ]
        self.now = datetime.now(timezone.utc)
        self.source = {
            "sha": self.head,
            "tree": self.tree,
            "parents": [self.base, self.pr_head],
        }
        self.needs = {
            "plan": {"result": "success", "outputs": dict.fromkeys(JOBS, "true")},
            "policy": {"result": "success"},
            **{j: {"result": "success"} for j in JOBS},
        }
        self.proof = {
            "schema": 1,
            "repository": evidence.REPOSITORY,
            "workflow": evidence.WORKFLOW,
            "run_id": 10,
            "attempt": 2,
            "source": {**self.source, "sha": self.tested},
            "pr": {"number": 7, "base": self.base, "head": self.pr_head},
            "needs": self.needs,
        }
        self.run = {
            "id": 10,
            "run_attempt": 2,
            "repository": {"full_name": evidence.REPOSITORY},
            "head_repository": {"full_name": evidence.REPOSITORY},
            "path": evidence.WORKFLOW,
            "name": "CI",
            "event": "pull_request",
            "status": "completed",
            "conclusion": "success",
            "head_sha": self.pr_head,
            "updated_at": self.now.isoformat(),
        }
        self.pr = {
            "number": 7,
            "merged_at": self.now.isoformat(),
            "merge_commit_sha": self.head,
            "base": {"ref": "main", "repo": {"full_name": evidence.REPOSITORY}},
            "head": {
                "sha": self.pr_head,
                "repo": {"full_name": evidence.REPOSITORY, "fork": False},
            },
        }
        self.env = {
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_REPOSITORY": evidence.REPOSITORY,
        }
        self.paths = ["desktop/src/app.tsx"]
        self.after = None
        self.artifact = {
            "name": "ci-proof-10-2",
            "id": 12,
            "expired": False,
            "size_in_bytes": 1000,
        }
        self.jobs = {
            "total_count": 1,
            "jobs": [
                {"name": "CI required", "status": "completed", "conclusion": "success"}
            ],
        }
        self.addCleanup(patch.stopall)
        patch.object(
            evidence, "source", side_effect=lambda *args: copy.deepcopy(self.source)
        ).start()
        patch.object(
            evidence.impact, "changed_paths", side_effect=lambda *args: self.paths
        ).start()

    def archive(self, artifact_id):
        return self.data

    def get(self, path):
        if path.startswith("git/commits/"):
            return {
                "sha": path.split("/")[-1],
                "tree": {"sha": self.tree},
                "parents": [{"sha": p} for p in self.source["parents"]],
            }
        if path.startswith("commits/"):
            return [self.pr]
        if path.startswith("actions/workflows/"):
            return {"total_count": 1, "workflow_runs": [self.run]}
        if path.endswith("/jobs?per_page=100"):
            return self.jobs
        if path.endswith("/artifacts?per_page=100"):
            return {"total_count": 1, "artifacts": [self.artifact]}
        result = self.after if self.after is not None and self.reads else self.run
        self.reads += 1
        return result

    def seal(self, raw=None, names=("proof.json",)):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name in names:
                archive.writestr(
                    name, raw if raw is not None else json.dumps(self.proof)
                )
        self.data = buffer.getvalue()
        self.artifact["digest"] = "sha256:" + hashlib.sha256(self.data).hexdigest()
        self.reads = 0

    def auth(self, reference=None):
        return evidence.authenticate(Path("."), self.head, self, reference, self.now)

    def test_selective_success_only_and_native_release_compatibility(self):
        self.needs["plan"]["outputs"]["qt"] = "false"
        self.needs["qt"]["result"] = "skipped"
        self.seal()
        coverage, identity = self.auth()
        self.assertEqual(coverage, set(JOBS) - {"qt", "mobile", "ios", "installer"})
        remaining, reference = evidence.plan(
            Path("."), self.head, set(JOBS), self.env, self
        )
        self.assertEqual(remaining, {"qt", "mobile", "ios", "installer", "package"})
        self.assertEqual(json.loads(reference), identity)
        needs = copy.deepcopy(self.needs)
        needs["plan"]["outputs"].update(
            {j: str(j in remaining).lower() for j in JOBS}, reuse=reference
        )
        needs.update(
            {j: {"result": "success" if j in remaining else "skipped"} for j in JOBS}
        )
        self.seal()
        evidence.validate(Path("."), self.head, set(JOBS), needs, self.env, self)
        needs["plan"]["outputs"]["mobile"] = "false"
        needs["mobile"]["result"] = "skipped"
        with self.assertRaises(ValueError):
            evidence.validate(Path("."), self.head, set(JOBS), needs, self.env, self)

    def test_proof_mutations_cannot_authorize_main(self):
        cases = [
            ("schema", 2),
            ("extra", True),
            ("repository", "foreign/repo"),
            ("workflow", ".github/workflows/other.yml"),
            ("run_id", 11),
            ("attempt", 1),
            ("source", {**self.proof["source"], "parents": [self.pr_head, self.base]}),
            ("source", {**self.proof["source"], "tree": "f" * 40}),
            ("source", {**self.proof["source"], "sha": "bad"}),
            ("pr", {**self.proof["pr"], "base": "f" * 40}),
            ("pr", {**self.proof["pr"], "number": 8}),
            ("needs", {**self.needs, "qt": {"result": "skipped"}}),
        ]
        original = copy.deepcopy(self.proof)
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.proof = {**original, key: value}
                self.seal()
                with self.assertRaises(ValueError):
                    self.auth()
        self.proof = original

    def test_wrong_producer_fork_event_attempt_and_age(self):
        original = copy.deepcopy(self.run)
        for key, value in [
            ("repository", {"full_name": "foreign/repo"}),
            ("head_repository", {"full_name": "fork/repo"}),
            ("path", "other.yml"),
            ("event", "push"),
            ("name", "other"),
            ("status", "in_progress"),
            ("conclusion", "failure"),
            ("head_sha", self.tested),
            ("updated_at", (self.now - timedelta(hours=25)).isoformat()),
        ]:
            with self.subTest(key=key):
                self.run = {**original, key: value}
                self.seal()
                with self.assertRaises(ValueError):
                    self.auth()
        self.run = original
        for mutation in (
            {"run_attempt": 3},
            {"status": "in_progress"},
            {"conclusion": "failure"},
        ):
            self.after = {**original, **mutation}
            self.seal()
            with self.assertRaises(ValueError):
                self.auth()
        self.after = None
        self.pr["head"]["repo"]["fork"] = True
        self.seal()
        with self.assertRaises(ValueError):
            self.auth()

    def test_archive_bounds_inventory_duplicate_fields_and_digest(self):
        for raw, names in [
            ('{"schema":1,"schema":1}', ("proof.json",)),
            ("x" * (evidence.LIMIT + 1), ("proof.json",)),
            ("{}", ("../proof.json",)),
            ("{}", ("proof.json", "extra")),
        ]:
            self.seal(raw, names)
            with self.assertRaises(ValueError):
                self.auth()
        self.seal()
        self.data += b"corrupt"
        with self.assertRaises(ValueError):
            self.auth()
        self.seal()
        self.artifact["size_in_bytes"] = evidence.LIMIT + 1
        with self.assertRaises(ValueError):
            self.auth()
        with self.assertRaises(zipfile.BadZipFile):
            evidence.unpack(
                b"bad zip", "sha256:" + hashlib.sha256(b"bad zip").hexdigest()
            )

    def test_control_bootstrap_bounds_and_normal_events(self):
        for path in [
            "ci/evidence.py",
            "ci/tests/other.mjs",
            ".github/actions/a/action.yml",
            ".github/workflows/ci.yml",
            "scripts/ci.py",
            "scripts/test_suites.py",
            "pyproject.toml",
            "tests/__init__.py",
            "scripts/sync_locales.py",
        ]:
            with self.subTest(path=path):
                self.paths = [path]
                self.seal()
                self.assertEqual(
                    evidence.plan(Path("."), self.head, STANDARD, self.env, self),
                    (STANDARD, ""),
                )
        for path in ["desktop/src/app.tsx", "mobile/src/foo.ts", "README.md"]:
            self.assertFalse(evidence.control_change([path]))
        # Release intent is reviewed data, not a change to the CI mechanism.
        self.paths = [".github/release-intent.json", "mobile/app.json"]
        self.seal()
        remaining, reference = evidence.plan(
            Path("."), self.head, STANDARD, self.env, self
        )
        self.assertEqual(remaining, {"mobile", "ios"})
        self.assertTrue(reference)
        for name in ["schedule", "workflow_dispatch", "pull_request"]:
            env = {**self.env, "GITHUB_EVENT_NAME": name}
            self.assertEqual(
                evidence.plan(Path("."), self.head, STANDARD, env, self), (STANDARD, "")
            )

    def test_api_uncertainty_falls_back_but_required_fails_closed(self):
        self.seal()
        with patch.object(self, "get", side_effect=OSError("offline")):
            self.assertEqual(
                evidence.plan(Path("."), self.head, STANDARD, self.env, self),
                (STANDARD, ""),
            )
            needs = copy.deepcopy(self.needs)
            needs["plan"]["outputs"]["reuse"] = json.dumps(
                {
                    "run_id": 10,
                    "attempt": 2,
                    "artifact_id": 12,
                    "digest": self.artifact["digest"],
                }
            )
            with self.assertRaises(OSError):
                evidence.validate(Path("."), self.head, STANDARD, needs, self.env, self)
        needs = copy.deepcopy(self.needs)
        needs["plan"]["outputs"].update(dict.fromkeys(JOBS, "false"))
        needs.update({j: {"result": "skipped"} for j in JOBS})
        with self.assertRaises(ValueError):
            evidence.validate(Path("."), self.head, STANDARD, needs, self.env, self)
        self.seal()
        with self.assertRaises(ValueError):
            self.auth(
                {
                    "run_id": 10,
                    "attempt": 1,
                    "artifact_id": 12,
                    "digest": self.artifact["digest"],
                }
            )

    def test_release_coverage_binds_main_receipt_and_never_counts_skipped_jobs(self):
        self.run.update(event="push", head_branch="main", head_sha=self.head)
        self.artifact["name"] = "ci-proof-10-2"
        self.needs["plan"]["outputs"]["ios"] = "false"
        self.needs["ios"]["result"] = "skipped"
        self.proof = {
            "schema": 2,
            "repository": evidence.REPOSITORY,
            "workflow": evidence.WORKFLOW,
            "run_id": 10,
            "attempt": 2,
            "source": self.source,
            "needs": self.needs,
            "coverage": sorted(set(JOBS) - {"ios"}),
            "reused": [],
        }
        api = Mock(token="fixture-token")
        api.request.side_effect = lambda method, path: self.get(path.lstrip("/"))
        self.seal()
        with patch.object(evidence.GitHub, "archive", side_effect=lambda _: self.data):
            self.assertEqual(
                evidence.release_coverage(api, self.run, self.head), set(JOBS) - {"ios"}
            )
            self.proof["coverage"].append("ios")
            self.seal()
            with self.assertRaises(ValueError):
                evidence.release_coverage(api, self.run, self.head)
            self.proof["coverage"].remove("ios")
            self.seal()
            for mutation in (
                {"run_attempt": 3},
                {"head_sha": "f" * 40},
                {"event": "pull_request"},
                {"conclusion": "failure"},
            ):
                self.after = {**self.run, **mutation}
                self.reads = 1
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    evidence.release_coverage(api, self.run, self.head)
            self.after = None
            self.artifact["digest"] = "sha256:" + "0" * 64
            with self.assertRaises(ValueError):
                evidence.release_coverage(api, self.run, self.head)

    def test_transport_keeps_token_on_api_and_uses_json_accept(self):
        from urllib.error import HTTPError
        from unittest.mock import Mock
        import os

        api = evidence.GitHub()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"archive"
        redirect = HTTPError(
            "api",
            302,
            "redirect",
            {"Location": "https://example.blob.core.windows.net/proof"},
            None,
        )
        with (
            patch.dict(os.environ, {"GH_TOKEN": "fixture-token"}),
            patch.object(
                api.opener, "open", side_effect=[redirect, response]
            ) as opened,
        ):
            self.assertEqual(api.archive(12), b"archive")
            api_request, storage_request = [
                call.args[0] for call in opened.call_args_list
            ]
            self.assertEqual(
                api_request.get_header("Accept"), "application/vnd.github+json"
            )
            self.assertEqual(
                api_request.get_header("Authorization"), "Bearer fixture-token"
            )
            self.assertIsNone(storage_request.get_header("Authorization"))
        for target in [
            "https://evil.example/proof",
            "http://example.blob.core.windows.net/proof",
            "https://user@example.blob.core.windows.net/proof",
        ]:
            redirect = HTTPError("api", 302, "redirect", {"Location": target}, None)
            with (
                patch.dict(os.environ, {"GH_TOKEN": "fixture-token"}),
                patch.object(api.opener, "open", side_effect=redirect),
                self.assertRaises(ValueError),
            ):
                api.archive(12)
        response.read.return_value = b"x" * (evidence.LIMIT + 1)
        with (
            patch.dict(os.environ, {"GH_TOKEN": "fixture-token"}),
            patch.object(api.opener, "open", return_value=response),
            self.assertRaises(ValueError),
        ):
            api.archive(12)

    def test_remote_source_and_aggregate_are_authenticated(self):
        self.seal()
        original = self.get
        for revision in [self.head, self.tested]:

            def changed(path):
                result = original(path)
                if path == "git/commits/" + revision:
                    result["tree"]["sha"] = "f" * 40
                return result

            with (
                patch.object(self, "get", side_effect=changed),
                self.assertRaises(ValueError),
            ):
                self.auth()
        self.jobs["jobs"][0]["conclusion"] = "skipped"
        with self.assertRaises(ValueError):
            self.auth()
        self.jobs["jobs"][0]["conclusion"] = "success"
        self.source["parents"] = [self.base]
        with self.assertRaises(ValueError):
            self.auth()

    def test_age_boundary_and_unselected_success_do_not_expand_coverage(self):
        self.needs["plan"]["outputs"]["qt"] = "false"
        self.run["updated_at"] = (self.now - timedelta(hours=24)).isoformat()
        self.seal()
        coverage, _ = self.auth()
        self.assertNotIn("qt", coverage)
        self.run["updated_at"] = (
            self.now - timedelta(hours=24, microseconds=1)
        ).isoformat()
        self.seal()
        with self.assertRaises(ValueError):
            self.auth()

    def test_receipt_must_have_exact_identity_fields(self):
        self.seal()
        needs = copy.deepcopy(self.needs)
        needs["plan"]["outputs"]["reuse"] = "null"
        remaining = {"mobile", "ios", "installer", "package"}
        needs["plan"]["outputs"].update({j: str(j in remaining).lower() for j in JOBS})
        needs.update(
            {j: {"result": "success" if j in remaining else "skipped"} for j in JOBS}
        )
        with self.assertRaises(ValueError):
            evidence.validate(Path("."), self.head, set(JOBS), needs, self.env, self)

    def test_emission_binds_event_and_rejects_failed_or_wrong_checkout(self):
        import tempfile

        env = {
            **self.env,
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_SHA": self.head,
            "GITHUB_RUN_ID": "10",
            "GITHUB_RUN_ATTEMPT": "2",
        }
        event = {
            "number": 7,
            "pull_request": {"base": {"sha": self.base}, "head": {"sha": self.pr_head}},
        }
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "proof.json"
            evidence.emit(Path("."), env, event, self.needs, destination)
            proof = json.loads(destination.read_text())
            self.assertEqual(proof["source"], self.source)
            self.assertEqual(proof["needs"], self.needs)
            self.assertEqual(proof["pr"], self.proof["pr"])
            self.needs["policy"]["result"] = "failure"
            with self.assertRaises(ValueError):
                evidence.emit(Path("."), env, event, self.needs, destination)
            self.needs["policy"]["result"] = "success"
            event["pull_request"]["base"]["sha"] = "f" * 40
            with self.assertRaises(ValueError):
                evidence.emit(Path("."), env, event, self.needs, destination)

    def test_main_receipt_records_verified_reuse_without_inventing_native_coverage(
        self,
    ):
        import tempfile

        env = {
            **self.env,
            "GITHUB_SHA": self.head,
            "GITHUB_RUN_ID": "20",
            "GITHUB_RUN_ATTEMPT": "1",
        }
        selected = {"python", "static"}
        needs = copy.deepcopy(self.needs)
        needs["plan"]["outputs"].update(
            {j: str(j == "static").lower() for j in JOBS},
            reuse=json.dumps(
                {
                    "run_id": 10,
                    "attempt": 2,
                    "artifact_id": 12,
                    "digest": "sha256:" + "0" * 64,
                }
            ),
        )
        needs.update(
            {j: {"result": "success" if j == "static" else "skipped"} for j in JOBS}
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(evidence.impact, "event_jobs", return_value=selected),
            patch.object(evidence, "authenticate", return_value=({"python"}, {})),
        ):
            destination = Path(directory) / "proof.json"
            evidence.emit(Path("."), env, {"before": self.base}, needs, destination)
            receipt = json.loads(destination.read_text())
            self.assertEqual(receipt["schema"], 2)
            self.assertEqual(set(receipt["coverage"]), selected)
            self.assertEqual(receipt["reused"], ["python"])
            needs["static"]["result"] = "failure"
            with self.assertRaises(ValueError):
                evidence.emit(Path("."), env, {"before": self.base}, needs, destination)
