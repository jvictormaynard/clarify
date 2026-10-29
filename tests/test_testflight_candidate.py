"""An internal candidate must retain its exact open PR, CI and upload identity."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest

from scripts import testflight_candidate as candidate
from scripts.release_delivery import ReleaseError


SOURCE = "a" * 40
BASE = "b" * 40
REPO = "jvictormaynard/clarify"
TAG = "ios/pr-200/v0.12.0-build40"


class CandidateAPI:
    def __init__(self):
        self.pr = {
            "number": 200,
            "state": "open",
            "draft": False,
            "merged": False,
            "mergeable": True,
            "head": {"sha": SOURCE, "repo": {"full_name": REPO}},
            "base": {"ref": "main", "repo": {"full_name": REPO}},
        }
        self.main = BASE
        self.tag_source = SOURCE
        self.permission = "write"
        self.run = {
            "id": 10,
            "workflow_id": 20,
            "event": "pull_request",
            "repository": {"full_name": REPO},
            "head_repository": {"full_name": REPO},
            "head_sha": SOURCE,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
            "pull_requests": [
                {"number": 200, "head": {"sha": SOURCE}, "base": {"sha": BASE}}
            ],
        }
        self.jobs = [
            {"name": name, "status": "completed", "conclusion": "success"}
            for name in [
                "CI required",
                "Mobile checks",
                "iOS validation / Native tests and unsigned build",
            ]
        ]
        self.old_runs = []
        self.upload_jobs = {}
        self.source_apps = {}
        self.edits = []
        self.reservation = {
            "schema": 1,
            "component": "mobile",
            "version": "0.12.0",
            "base_sha": BASE,
            "notes": "Test the computer pairing flow in the existing internal group.",
            "evidence": {
                "build": "40",
                "highest_build": "39",
                "pending_builds_checked": True,
                "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "report_url": "https://github.com/jvictormaynard/clarify/pull/200",
            },
        }

    def request(self, method, path, body=None, **kwargs):
        if method != "GET":
            self.edits.append((method, path))
            raise AssertionError("Candidate gate cannot write")
        if path == "/pulls/200":
            return deepcopy(self.pr)
        if path == "/git/ref/heads/main":
            return {"object": {"sha": self.main}}
        if path.startswith("/git/ref/tags/"):
            return {"object": {"sha": self.tag_source, "type": "commit"}}
        if path == "/collaborators/maintainer/permission":
            return {"permission": self.permission}
        if path.startswith("/compare/"):
            return {"status": "ahead", "merge_base_commit": {"sha": BASE}}
        if path == "/actions/workflows/20":
            return {"path": ".github/workflows/ci.yml", "name": "CI"}
        raise AssertionError(path)

    def file(self, path, ref, **kwargs):
        if path == ".github/testflight-candidate.json":
            return json.dumps(self.reservation)
        if path == "mobile/app.json":
            if ref in self.source_apps:
                return json.dumps({"expo": self.source_apps[ref]})
            return json.dumps(
                {
                    "expo": {
                        "version": "0.11.0" if ref == BASE else "0.12.0",
                        "ios": {
                            "buildNumber": "39" if ref == BASE else "40",
                            "bundleIdentifier": "com.jvictormaynard.clarify",
                        },
                    }
                }
            )
        raise AssertionError(path)

    def pages(self, path, key=None):
        if path.startswith("/actions/workflows/ci.yml/runs?"):
            return [deepcopy(self.run)]
        if path.startswith("/actions/workflows/ios-testflight.yml/runs"):
            if "head_sha=" in path:
                requested = path.split("head_sha=", 1)[1].split("&", 1)[0]
                return [
                    deepcopy(run)
                    for run in self.old_runs
                    if run.get("head_sha") == requested
                ]
            return deepcopy(self.old_runs)
        if path.startswith("/actions/runs/10/jobs?"):
            return deepcopy(self.jobs)
        if path in self.upload_jobs:
            return deepcopy(self.upload_jobs[path])
        raise AssertionError(path)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.api = CandidateAPI()

    def verify(self, **overrides):
        args = dict(
            source=SOURCE,
            tag=TAG,
            pr_number=200,
            actor="maintainer",
            run_id=30,
            run_attempt=1,
        )
        args.update(overrides)
        return candidate.verify_candidate(self.api, **args)

    def test_ready_current_pr_with_native_ci_can_publish_without_mutating_github(self):
        self.assertEqual(self.verify(), "publish")
        self.assertEqual(self.api.edits, [])

    def test_closed_draft_foreign_or_changed_pr_cannot_publish(self):
        changes = [
            {"state": "closed"},
            {"draft": True},
            {"mergeable": None},
            {"head": {"sha": "c" * 40, "repo": {"full_name": REPO}}},
            {"head": {"sha": SOURCE, "repo": {"full_name": "other/fork"}}},
        ]
        for change in changes:
            with self.subTest(change=change):
                self.api = CandidateAPI()
                self.api.pr.update(change)
                with self.assertRaises(ReleaseError):
                    self.verify()

    def test_stable_tag_or_different_tag_source_cannot_publish_candidate(self):
        with self.assertRaises(ReleaseError):
            self.verify(tag="ios/v0.12.0-build40")
        self.api.tag_source = "c" * 40
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_pending_failed_missing_or_stale_native_ci_cannot_publish(self):
        for field, value in [
            ("status", "in_progress"),
            ("conclusion", "failure"),
            ("head_sha", "c" * 40),
            ("event", "push"),
        ]:
            with self.subTest(field=field):
                self.api = CandidateAPI()
                self.api.run[field] = value
                with self.assertRaises(ReleaseError):
                    self.verify()
        self.api = CandidateAPI()
        self.api.jobs.pop()
        with self.assertRaises(ReleaseError):
            self.verify()
        self.api = CandidateAPI()
        self.api.run["pull_requests"][0]["base"]["sha"] = "c" * 40
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_read_only_actor_cannot_authorize_signing(self):
        self.api.permission = "read"
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_missing_pending_check_old_reservation_or_reserved_build_blocks_upload(
        self,
    ):
        for key, value in [
            ("pending_builds_checked", False),
            ("checked_at", "2026-01-01T00:00:00Z"),
            ("highest_build", "40"),
        ]:
            with self.subTest(key=key):
                self.api = CandidateAPI()
                self.api.reservation["evidence"][key] = value
                with self.assertRaises(ReleaseError):
                    self.verify()

    def prior_upload(self, conclusion):
        self.api.old_runs = [
            {
                "id": 29,
                "run_attempt": 1,
                "head_sha": SOURCE,
                "head_branch": TAG,
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "failure",
            }
        ]
        self.api.upload_jobs["/actions/runs/29/attempts/1/jobs"] = [
            {
                "name": "Test, sign and upload iOS",
                "status": "completed",
                "steps": [
                    {
                        "name": "Upload directly to App Store Connect",
                        "conclusion": conclusion,
                    }
                ],
            }
        ]

    def test_confirmed_upload_resumes_availability_without_another_upload(self):
        self.prior_upload("success")
        self.assertEqual(self.verify(), "availability")

    def test_upload_on_another_ref_with_same_app_identity_is_not_repeated(self):
        self.prior_upload("success")
        self.api.old_runs[0]["head_branch"] = "another-candidate-ref"
        self.assertEqual(self.verify(), "availability")

    def test_uncertain_upload_is_never_retried(self):
        for conclusion in ["failure", "cancelled", None]:
            with self.subTest(conclusion=conclusion):
                self.prior_upload(conclusion)
                with self.assertRaises(ReleaseError):
                    self.verify()

    def test_same_identity_uploaded_from_another_sha_blocks_current_candidate(self):
        self.prior_upload("success")
        self.api.old_runs[0]["head_sha"] = "c" * 40
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_uncertain_upload_from_another_sha_blocks_current_candidate(self):
        self.prior_upload("cancelled")
        self.api.old_runs[0]["head_sha"] = "c" * 40
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_other_build_or_app_does_not_block_this_identity(self):
        for ios in [
            {"buildNumber": "39", "bundleIdentifier": "com.jvictormaynard.clarify"},
            {"buildNumber": "40", "bundleIdentifier": "com.example.other"},
        ]:
            with self.subTest(ios=ios):
                self.api = CandidateAPI()
                self.prior_upload("cancelled")
                self.api.old_runs[0]["head_sha"] = "c" * 40
                self.api.source_apps["c" * 40] = {"version": "0.12.0", "ios": ios}
                self.assertEqual(self.verify(), "publish")

    def test_old_push_upload_of_same_identity_also_blocks_new_source(self):
        self.prior_upload("success")
        self.api.old_runs[0].update(head_sha="c" * 40, event="push")
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_active_same_identity_from_other_sha_blocks_publication(self):
        self.prior_upload("skipped")
        self.api.old_runs[0].update(head_sha="c" * 40, status="in_progress")
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_skipped_other_sha_upload_allows_new_candidate(self):
        self.prior_upload("skipped")
        self.api.old_runs[0]["head_sha"] = "c" * 40
        self.assertEqual(self.verify(), "publish")

    def test_latest_skipped_attempt_does_not_hide_earlier_foreign_sha_upload(self):
        self.prior_upload("success")
        self.api.old_runs[0].update(head_sha="c" * 40, run_attempt=2)
        self.api.upload_jobs["/actions/runs/29/attempts/2/jobs"] = [
            {
                "name": "Test, sign and upload iOS",
                "status": "completed",
                "steps": [
                    {
                        "name": "Upload directly to App Store Connect",
                        "conclusion": "skipped",
                    }
                ],
            }
        ]
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_known_skipped_upload_can_be_retried(self):
        self.prior_upload("skipped")
        self.assertEqual(self.verify(), "publish")

    def test_retry_of_same_workflow_after_upload_only_checks_availability(self):
        self.api.upload_jobs["/actions/runs/30/attempts/1/jobs"] = [
            {
                "name": "Test, sign and upload iOS",
                "status": "completed",
                "steps": [
                    {
                        "name": "Upload directly to App Store Connect",
                        "conclusion": "success",
                    }
                ],
            }
        ]
        self.assertEqual(self.verify(run_attempt=2), "availability")


if __name__ == "__main__":
    unittest.main()
