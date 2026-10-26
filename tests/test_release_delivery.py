"""Release effects use a local fake HTTP server, never GitHub or Apple."""

import base64
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from scripts import release_delivery as delivery

SOURCE = "a" * 40
BASE = "b" * 40
TAG_OBJECT = "c" * 40
REPOSITORY = "jvictormaynard/clarify"
ROOT = Path(__file__).resolve().parents[1]


class FakeGitHub(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.respond("GET")

    def do_POST(self):
        self.respond("POST")

    def respond(self, method):
        state = self.server.state
        parsed = urlsplit(self.path)
        path = parsed.path.removeprefix("/repos/" + REPOSITORY)
        query = parse_qs(parsed.query)
        body = (
            json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if method == "POST"
            else None
        )
        state.calls.append((method, path, body))
        status = 200
        value = None
        if method == "GET" and path.startswith("/contents/"):
            data = state.files.get((path.removeprefix("/contents/"), query["ref"][0]))
            if data is not None:
                value = {
                    "type": "file",
                    "encoding": "base64",
                    "content": base64.b64encode(data.encode()).decode(),
                }
            else:
                status = 404
        elif method == "GET" and path == "/git/ref/heads/main":
            value = {"object": {"sha": state.main}}
        elif method == "GET" and path.startswith("/git/ref/tags/"):
            value = (
                None
                if state.tag is None
                else {
                    "object": state.tag
                    if isinstance(state.tag, dict)
                    else {"sha": state.tag, "type": "commit"}
                }
            )
            status = 404 if value is None else 200
        elif method == "GET" and path.startswith("/git/ref/heads/release-preparation/"):
            status = 404
        elif method == "GET" and path.startswith("/releases/tags/"):
            value = state.release
            status = 404 if value is None else 200
        elif method == "GET" and path.endswith("/runs"):
            value = {
                "workflow_runs": [state.run]
                if path == "/actions/workflows/ci.yml/runs"
                else state.publication_runs
            }
        elif method == "GET" and path in state.routes:
            value = state.routes[path]
        elif method == "POST" and path == "/git/tags":
            value = {"sha": TAG_OBJECT}
        elif method == "POST" and path == "/git/refs":
            if body["ref"].startswith("refs/tags/"):
                state.tag = SOURCE
            value = {"ref": body["ref"]}
        elif method == "POST" and path.endswith("/dispatches"):
            state.publication_runs = [
                {
                    "id": 999,
                    "head_sha": SOURCE,
                    "head_branch": body["ref"],
                    "event": "workflow_dispatch",
                    "status": "queued",
                    "conclusion": None,
                }
            ]
            status = 204
        elif method == "POST" and path in {"/git/trees", "/git/commits"}:
            value = {"sha": "d" * 40}
        elif method == "POST" and path == "/pulls":
            value = {"html_url": "https://github.com/jvictormaynard/clarify/pull/200"}
        else:
            state.unexpected.append((method, path))
            status = 500
        encoded = b"" if status == 204 else json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class ReleaseDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.api = delivery.GitHub(
            "fake-test-token", f"http://127.0.0.1:{cls.server.server_port}"
        )

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.server.state = self
        self.calls = []
        self.unexpected = []
        self.main = SOURCE
        self.tag = None
        self.release = None
        self.publication_runs = []
        self.intent = {
            "schema": 1,
            "component": "desktop",
            "version": "1.2.4",
            "base_sha": BASE,
            "notes": "Fix clipboard restoration. Windows acceptance passed.",
            "evidence": {
                "tested_sha": BASE,
                "windows_accepted": True,
                "report_url": "https://github.com/jvictormaynard/clarify/issues/123#issuecomment-100",
            },
        }
        self.run = {
            "id": 42,
            "workflow_id": 7,
            "repository": {"full_name": REPOSITORY},
            "head_repository": {"full_name": REPOSITORY},
            "event": "push",
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
            "head_sha": SOURCE,
            "path": ".github/workflows/ci.yml",
        }
        self.pr = {
            "number": 200,
            "merged": True,
            "state": "closed",
            "merge_commit_sha": SOURCE,
            "title": "release: prepare desktop v1.2.4",
            "merged_by": {"login": "maintainer"},
            "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
            "head": {
                "ref": "release-preparation/v1.2.4",
                "repo": {"full_name": REPOSITORY},
            },
        }
        paths = [
            ".github/release-intent.json",
            "version.py",
            "package.json",
            "CHANGELOG.md",
        ]
        self.changes = [{"filename": path, "status": "modified"} for path in paths]
        self.jobs = [
            {"name": name, "status": "completed", "conclusion": "success"}
            for name in (
                "Tests (ubuntu-latest)",
                "Tests (windows-latest)",
                "Package Windows executable",
                "CI required",
                "Mobile checks",
                "iOS validation / Native tests and unsigned build",
            )
        ]
        self.routes = {
            "/releases": [],
            "/actions/runs/42": self.run,
            "/actions/workflows/7": {"name": "CI", "path": ".github/workflows/ci.yml"},
            "/actions/runs/42/jobs": {"jobs": self.jobs},
            "/commits/" + SOURCE + "/pulls": [{"number": 200}],
            "/pulls/200": self.pr,
            "/pulls/200/files": self.changes,
            "/collaborators/maintainer/permission": {"permission": "admin"},
            "/compare/" + BASE + "..." + SOURCE: {
                "status": "ahead",
                "total_commits": 2,
                "files": self.changes,
            },
            "/git/commits/" + SOURCE: {"tree": {"sha": "e" * 40}},
        }
        self.files = {
            ("version.py", BASE): '__version__ = "1.2.3"\n',
            ("package.json", BASE): '{"version": "1.2.3"}',
            ("version.py", SOURCE): '__version__ = "1.2.4"\n',
            ("package.json", SOURCE): '{"version": "1.2.4"}',
            (
                "CHANGELOG.md",
                SOURCE,
            ): "## [Unreleased]\n\n## [1.2.4] - 2026-10-25\n\n### Fixed\n\n- Fix clipboard restoration.\n\n[Unreleased]: https://github.com/jvictormaynard/clarify/compare/v1.2.4...HEAD\n",
            (
                "mobile/app.json",
                BASE,
            ): '{"expo":{"version":"0.9.1","ios":{"buildNumber":"32"}}}',
            (
                "mobile/app.json",
                SOURCE,
            ): '{"expo":{"version":"0.9.2","ios":{"buildNumber":"33"}}}',
        }
        self.save_intent()
        self.event = {
            "repository": {"full_name": REPOSITORY},
            "workflow_run": deepcopy(self.run),
        }

    def tearDown(self):
        self.assertEqual(self.unexpected, [])

    def save_intent(self):
        self.files[(".github/release-intent.json", SOURCE)] = json.dumps(self.intent)

    def mutations(self):
        return [(path, body) for method, path, body in self.calls if method == "POST"]

    def promote(self):
        return delivery.promote(self.api, self.event)

    def mobile(self):
        self.intent.update(
            component="mobile",
            version="0.9.2",
            evidence={
                "build": "33",
                "highest_build": "32",
                "pending_builds_checked": True,
                "checked_at": "2026-10-25T12:00:00Z",
                "report_url": "https://github.com/jvictormaynard/clarify/actions/runs/100",
            },
        )
        self.pr["title"] = "release: prepare mobile ios/v0.9.2-build33"
        self.pr["head"]["ref"] = "release-preparation/ios/v0.9.2-build33"
        self.changes[:] = [
            {"filename": path, "status": "modified"}
            for path in (".github/release-intent.json", "mobile/app.json")
        ]
        self.save_intent()

    def test_green_preparation_creates_exact_annotated_tag_and_explicit_dispatch(self):
        self.assertEqual(self.promote(), "dispatched")
        self.assertEqual(
            self.mutations(),
            [
                (
                    "/git/tags",
                    {
                        "tag": "v1.2.4",
                        "message": "Clarify v1.2.4",
                        "object": SOURCE,
                        "type": "commit",
                    },
                ),
                ("/git/refs", {"ref": "refs/tags/v1.2.4", "sha": TAG_OBJECT}),
                (
                    "/actions/workflows/community-release.yml/dispatches",
                    {"ref": "v1.2.4", "inputs": {"source_sha": SOURCE}},
                ),
            ],
        )

    def test_mobile_dispatch_preserves_exact_build_and_disables_tests_only(self):
        self.mobile()
        self.assertEqual(self.promote(), "dispatched")
        self.assertEqual(
            self.mutations()[-1],
            (
                "/actions/workflows/ios-testflight.yml/dispatches",
                {
                    "ref": "ios/v0.9.2-build33",
                    "inputs": {"source_sha": SOURCE, "tests_only": "false"},
                },
            ),
        )

    def test_mobile_promotion_and_publication_need_no_desktop_jobs(self):
        self.mobile()
        desktop_jobs = {
            "Tests (ubuntu-latest)",
            "Tests (windows-latest)",
            "Package Windows executable",
        }
        original_jobs = deepcopy(self.jobs)
        self.routes["/actions/runs/999/jobs"] = {
            "jobs": [{"name": "release_gate", "conclusion": "success"}]
        }
        for desktop_conclusion in (None, "skipped"):
            with self.subTest(desktop_conclusion=desktop_conclusion):
                self.jobs[:] = [
                    dict(job, conclusion=desktop_conclusion)
                    if job["name"] in desktop_jobs
                    else job
                    for job in deepcopy(original_jobs)
                    if desktop_conclusion is not None or job["name"] not in desktop_jobs
                ]
                self.tag = None
                self.publication_runs = []
                self.calls.clear()
                self.assertEqual(self.promote(), "dispatched")
                self.assertEqual(
                    self.mutations()[-1][0],
                    "/actions/workflows/ios-testflight.yml/dispatches",
                )
                self.calls.clear()
                self.assertEqual(
                    delivery.verify_publication(
                        self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 999
                    ),
                    "publish",
                )
                self.assertEqual(self.mutations(), [])

    def test_final_ci_gate_must_be_unique_completed_and_successful(self):
        original_jobs = deepcopy(self.jobs)
        for component, tag in (
            ("desktop", "v1.2.4"),
            ("mobile", "ios/v0.9.2-build33"),
        ):
            if component == "mobile":
                self.mobile()
            self.tag = SOURCE
            for outcome in (
                "absent",
                "skipped",
                "failure",
                "cancelled",
                "pending",
                "duplicate",
            ):
                with self.subTest(component=component, outcome=outcome):
                    self.jobs[:] = deepcopy(original_jobs)
                    self.publication_runs = []
                    gate = next(
                        job for job in self.jobs if job["name"] == "CI required"
                    )
                    if outcome == "absent":
                        self.jobs.remove(gate)
                    elif outcome == "duplicate":
                        self.jobs.append(dict(gate))
                    elif outcome == "pending":
                        gate.update(status="in_progress", conclusion=None)
                    else:
                        gate["conclusion"] = outcome
                    self.calls.clear()
                    with self.assertRaisesRegex(delivery.ReleaseError, "CI required"):
                        self.promote()
                    with self.assertRaisesRegex(delivery.ReleaseError, "CI required"):
                        delivery.verify_publication(
                            self.api, component, SOURCE, tag, 900
                        )
                    self.assertEqual(self.mutations(), [])

    def test_component_ci_jobs_are_required_before_promotion_or_publication(self):
        original_jobs = deepcopy(self.jobs)
        for component, tag, names in (
            (
                "desktop",
                "v1.2.4",
                (
                    "Tests (ubuntu-latest)",
                    "Tests (windows-latest)",
                    "Package Windows executable",
                ),
            ),
            (
                "mobile",
                "ios/v0.9.2-build33",
                ("Mobile checks", "iOS validation / Native tests and unsigned build"),
            ),
        ):
            if component == "mobile":
                self.mobile()
            self.tag = SOURCE
            for name in names:
                for outcome in ("absent", "skipped", "failure", "cancelled"):
                    with self.subTest(component=component, job=name, outcome=outcome):
                        self.jobs[:] = deepcopy(original_jobs)
                        self.publication_runs = []
                        job = next(job for job in self.jobs if job["name"] == name)
                        if outcome == "absent":
                            self.jobs.remove(job)
                        else:
                            job["conclusion"] = outcome
                        self.calls.clear()
                        with self.assertRaises(delivery.ReleaseError):
                            self.promote()
                        with self.assertRaises(delivery.ReleaseError):
                            delivery.verify_publication(
                                self.api, component, SOURCE, tag, 900
                            )
                        self.assertEqual(self.mutations(), [])

    def test_code_push_without_release_intent_has_no_release_effect(self):
        self.files.pop((".github/release-intent.json", SOURCE))
        self.assertEqual(self.promote(), "no-intent")
        self.assertEqual(self.mutations(), [])

    def test_docs_or_code_push_with_prior_intent_has_no_release_effect(self):
        self.pr["merge_commit_sha"] = BASE
        self.assertEqual(self.promote(), "no-preparation-pr")
        self.assertEqual(self.mutations(), [])

    def test_ci_failure_wrong_workflow_sha_fork_and_stale_are_rejected(self):
        mutations = [
            {"conclusion": "failure"},
            {"status": "in_progress"},
            {"event": "pull_request"},
            {"head_branch": "feature"},
            {"path": ".github/workflows/fake.yml"},
            {"head_sha": BASE},
            {"head_repository": {"full_name": "fork/clarify"}},
            {"repository": {"full_name": "fork/clarify"}},
        ]
        for changes in mutations:
            with self.subTest(changes=changes):
                saved = deepcopy(self.run)
                self.run.update(changes)
                with self.assertRaises(delivery.ReleaseError):
                    self.promote()
                self.run.clear()
                self.run.update(saved)
        self.main = BASE
        with self.assertRaisesRegex(delivery.ReleaseError, "stale"):
            self.promote()
        self.assertEqual(self.mutations(), [])

    def test_event_repository_and_workflow_identity_are_rechecked_via_api(self):
        self.event["repository"]["full_name"] = "fork/clarify"
        with self.assertRaisesRegex(delivery.ReleaseError, "event repository"):
            self.promote()
        self.event["repository"]["full_name"] = REPOSITORY
        self.routes["/actions/workflows/7"]["path"] = ".github/workflows/other.yml"
        with self.assertRaisesRegex(delivery.ReleaseError, "workflow identity"):
            self.promote()
        self.assertEqual(self.mutations(), [])

    def test_preparation_title_main_base_and_merge_are_required(self):
        self.pr["title"] = "release: unrelated work"
        with self.assertRaisesRegex(delivery.ReleaseError, "PR identity"):
            self.promote()
        self.pr["title"] = "release: prepare desktop v1.2.4"
        self.pr["base"]["ref"] = "other-branch"
        with self.assertRaisesRegex(delivery.ReleaseError, "canonical main"):
            self.promote()
        self.pr["base"]["ref"] = "main"
        self.pr["merged"] = False
        self.assertEqual(self.promote(), "no-preparation-pr")
        self.assertEqual(self.mutations(), [])

    def test_annotated_tag_is_peeled_to_exact_source(self):
        self.tag = {"sha": TAG_OBJECT, "type": "tag"}
        self.routes["/git/tags/" + TAG_OBJECT] = {
            "object": {"sha": SOURCE, "type": "commit"}
        }
        self.assertEqual(self.promote(), "dispatched")
        self.assertEqual(len(self.mutations()), 1)

    def test_official_api_main_path_suffix_is_valid_but_other_refs_fail(self):
        self.run["path"] = ".github/workflows/ci.yml@main"
        self.assertEqual(self.promote(), "dispatched")
        self.calls.clear()
        self.run["path"] = ".github/workflows/ci.yml@feature"
        with self.assertRaisesRegex(delivery.ReleaseError, "workflow path"):
            self.promote()
        self.assertEqual(self.mutations(), [])

    def test_absent_preparation_token_fails_before_any_http_write(self):
        with self.assertRaisesRegex(delivery.ReleaseError, "configured GitHub token"):
            delivery.GitHub("")
        self.assertEqual(self.calls, [])

    def test_required_checks_must_be_green_and_present(self):
        self.jobs[0]["conclusion"] = "skipped"
        with self.assertRaisesRegex(delivery.ReleaseError, "Required CI job"):
            self.promote()
        self.assertEqual(self.mutations(), [])

    def test_mobile_requires_native_validation(self):
        self.mobile()
        self.jobs.pop()
        with self.assertRaisesRegex(
            delivery.ReleaseError, "iOS validation / Native tests and unsigned build"
        ):
            self.promote()
        self.assertEqual(self.mutations(), [])

    def test_preparation_requires_canonical_pr_maintainer_and_metadata_only(self):
        self.pr["head"]["repo"]["full_name"] = "fork/clarify"
        with self.assertRaisesRegex(delivery.ReleaseError, "canonical main"):
            self.promote()
        self.pr["head"]["repo"]["full_name"] = REPOSITORY
        self.routes["/collaborators/maintainer/permission"] = {"permission": "read"}
        with self.assertRaisesRegex(delivery.ReleaseError, "maintainer"):
            self.promote()
        self.routes["/collaborators/maintainer/permission"] = {"permission": "write"}
        self.changes.append({"filename": "workflows.py", "status": "modified"})
        with self.assertRaisesRegex(delivery.ReleaseError, "only its release metadata"):
            self.promote()
        self.assertEqual(self.mutations(), [])

    def test_code_changed_since_windows_acceptance_is_rejected(self):
        comparison = self.routes["/compare/" + BASE + "..." + SOURCE]
        comparison["files"] = self.changes + [
            {"filename": "workflows.py", "status": "modified"}
        ]
        with self.assertRaisesRegex(delivery.ReleaseError, "after acceptance"):
            self.promote()
        self.assertEqual(self.mutations(), [])

    def test_same_tag_is_dispatched_without_recreating_and_rerun_is_inert(self):
        self.tag = SOURCE
        self.assertEqual(self.promote(), "dispatched")
        self.assertEqual(len(self.mutations()), 1)
        self.assertEqual(self.promote(), "already-dispatched")
        self.assertEqual(len(self.mutations()), 1)

    def test_existing_tag_mismatch_never_moves_tag(self):
        self.tag = BASE
        with self.assertRaisesRegex(delivery.ReleaseError, "never move"):
            self.promote()
        self.assertEqual(self.mutations(), [])

    def test_existing_complete_release_is_not_republished(self):
        self.tag = SOURCE
        self.release = {
            "draft": False,
            "prerelease": False,
            "assets": [{"name": name} for name in delivery.ASSETS],
        }
        self.assertEqual(self.promote(), "already-published")
        self.assertEqual(self.mutations(), [])

    def test_partial_release_is_not_overwritten(self):
        self.tag = SOURCE
        self.release = {"draft": True, "assets": [{"name": "Clarify.exe"}]}
        with self.assertRaisesRegex(delivery.ReleaseError, "incomplete"):
            self.promote()
        self.assertEqual(self.mutations(), [])

    def test_publisher_verifies_exact_tag_green_ci_and_plan_without_main_race(self):
        self.tag = SOURCE
        self.main = BASE  # A later main push must not select different release code.
        self.assertEqual(
            delivery.verify_publication(self.api, "desktop", SOURCE, "v1.2.4", 1000),
            "publish",
        )
        self.tag = BASE
        with self.assertRaisesRegex(delivery.ReleaseError, "Immutable tag"):
            delivery.verify_publication(self.api, "desktop", SOURCE, "v1.2.4", 1000)
        self.assertEqual(self.mutations(), [])

    def test_superseded_desktop_release_cannot_be_promoted_or_published(self):
        self.tag = SOURCE
        for published in ("v1.2.4", "v1.2.5", "v2.0.0"):
            with self.subTest(published=published):
                self.routes["/releases"] = [
                    {"tag_name": published, "draft": False, "prerelease": False}
                ]
                with self.assertRaisesRegex(delivery.ReleaseError, "superseded"):
                    self.promote()
                self.main = BASE
                with self.assertRaisesRegex(delivery.ReleaseError, "superseded"):
                    delivery.verify_publication(
                        self.api, "desktop", SOURCE, "v1.2.4", 1000
                    )
                self.main = SOURCE
        self.assertEqual(self.mutations(), [])

    def test_older_drafts_and_prereleases_do_not_supersede_desktop_release(self):
        self.tag = SOURCE
        self.main = BASE
        self.routes["/releases"] = [
            {"tag_name": "v1.2.3", "draft": False, "prerelease": False},
            {"tag_name": "v2.0.0", "draft": True, "prerelease": False},
            {"tag_name": "v2.0.1", "draft": False, "prerelease": True},
            {"tag_name": "ios/v2.0.0-build50", "draft": False, "prerelease": False},
        ]
        self.assertEqual(
            delivery.verify_publication(self.api, "desktop", SOURCE, "v1.2.4", 1000),
            "publish",
        )
        self.assertEqual(self.mutations(), [])

    def test_corrected_mobile_dispatch_can_follow_a_gate_failure_without_upload(self):
        self.mobile()
        self.tag = SOURCE
        self.publication_runs = [
            {
                "id": 900,
                "event": "workflow_dispatch",
                "head_sha": SOURCE,
                "head_branch": "ios/v0.9.2-build33",
                "status": "completed",
                "conclusion": "failure",
            }
        ]
        safe_jobs = [
            {"name": "release_gate", "conclusion": "failure", "status": "completed"},
            {
                "name": "Test, sign and upload iOS",
                "conclusion": "skipped",
                "status": "completed",
            },
        ]
        self.routes["/actions/runs/900/jobs"] = {"jobs": safe_jobs}
        self.assertEqual(
            delivery.verify_publication(
                self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 1000
            ),
            "publish",
        )
        # Latest jobs alone cannot prove that an earlier attempt never uploaded.
        self.publication_runs[0]["run_attempt"] = 2
        for outcome in ("success", "failure", "cancelled", None):
            with self.subTest(prior_upload=outcome):
                self.routes["/actions/runs/900/attempts/1/jobs"] = {
                    "jobs": [
                        {"name": "release_gate", "conclusion": "success"},
                        {
                            "name": "Test, sign and upload iOS",
                            "steps": [
                                {
                                    "name": "Upload directly to App Store Connect",
                                    "conclusion": outcome,
                                }
                            ],
                        },
                    ]
                }
                with self.assertRaisesRegex(delivery.ReleaseError, "prior upload"):
                    delivery.verify_publication(
                        self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 1000
                    )
        self.assertEqual(self.mutations(), [])

    def test_mobile_status_runs_on_release_tag_do_not_suppress_upload(self):
        self.mobile()
        self.tag = SOURCE
        self.publication_runs = [
            {
                "id": 900,
                "event": "workflow_dispatch",
                "head_sha": SOURCE,
                "head_branch": "ios/v0.9.2-build33",
                "status": "completed",
                "conclusion": "success",
            }
        ]
        self.routes["/actions/runs/900/jobs"] = {
            "jobs": [{"name": "release_gate", "conclusion": "skipped"}]
        }
        self.assertEqual(
            delivery.verify_publication(
                self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 1000
            ),
            "publish",
        )

    def test_older_mobile_run_cannot_reupload_after_a_replacement_run(self):
        self.mobile()
        self.tag = SOURCE
        replacement = {
            "id": 1000,
            "event": "workflow_dispatch",
            "head_sha": SOURCE,
            "head_branch": "ios/v0.9.2-build33",
            "status": "completed",
            "conclusion": "success",
        }
        self.publication_runs = [replacement]
        self.routes["/actions/runs/1000/jobs"] = {
            "jobs": [{"name": "release_gate", "conclusion": "success"}]
        }
        self.routes["/actions/runs/900/attempts/1/jobs"] = {
            "jobs": [{"name": "release_gate", "conclusion": "failure"}]
        }
        self.assertEqual(
            delivery.verify_publication(
                self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 900, 2
            ),
            "skip",
        )
        for status, conclusion in (
            ("completed", "failure"),
            ("completed", "cancelled"),
            ("in_progress", None),
        ):
            with self.subTest(status=status, conclusion=conclusion):
                replacement.update(status=status, conclusion=conclusion)
                with self.assertRaisesRegex(delivery.ReleaseError, "prior upload"):
                    delivery.verify_publication(
                        self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 900, 2
                    )
        self.assertEqual(self.mutations(), [])

    def test_concurrent_checks_only_mobile_run_cannot_block_signed_upload(self):
        self.mobile()
        self.tag = SOURCE
        checks = {
            "id": 1000,
            "event": "workflow_dispatch",
            "head_sha": SOURCE,
            "head_branch": "ios/v0.9.2-build33",
            "status": "in_progress",
            "conclusion": None,
            "run_attempt": 1,
        }
        self.publication_runs = [checks]
        self.routes["/actions/runs/1000/jobs"] = {
            "jobs": [{"name": "release_gate", "conclusion": "skipped"}]
        }
        self.assertEqual(
            delivery.verify_publication(
                self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 900
            ),
            "publish",
        )
        # Current skipped gates do not erase uncertain earlier upload history.
        checks["run_attempt"] = 2
        self.routes["/actions/runs/1000/attempts/1/jobs"] = {
            "jobs": [{"name": "release_gate", "conclusion": "success"}]
        }
        with self.assertRaisesRegex(delivery.ReleaseError, "prior upload"):
            delivery.verify_publication(
                self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 900
            )
        self.assertEqual(self.mutations(), [])

    def test_new_queued_mobile_dispatch_waits_without_blocking_the_active_upload(self):
        self.mobile()
        self.tag = SOURCE
        queued = {
            "id": 1000,
            "event": "workflow_dispatch",
            "head_sha": SOURCE,
            "head_branch": "ios/v0.9.2-build33",
            "status": "queued",
            "conclusion": None,
            "run_attempt": 1,
        }
        self.publication_runs = [queued]
        for queued_id in (899, 1000):
            with self.subTest(queued_id=queued_id):
                queued["id"] = queued_id
                self.routes[f"/actions/runs/{queued_id}/jobs"] = {"jobs": []}
                self.assertEqual(
                    delivery.verify_publication(
                        self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 900
                    ),
                    "publish",
                )
        # A queued rerun can have uploaded in an earlier attempt.
        queued["run_attempt"] = 2
        with self.assertRaisesRegex(delivery.ReleaseError, "prior upload"):
            delivery.verify_publication(
                self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 900
            )
        self.assertEqual(self.mutations(), [])

    def test_mobile_publication_rerun_does_not_upload_twice(self):
        self.mobile()
        self.tag = SOURCE
        self.publication_runs = [
            {
                "id": 900,
                "event": "workflow_dispatch",
                "head_sha": SOURCE,
                "head_branch": "ios/v0.9.2-build33",
                "status": "completed",
                "conclusion": "success",
            }
        ]
        self.routes["/actions/runs/900/jobs"] = {
            "jobs": [{"name": "release_gate", "conclusion": "success"}]
        }
        self.assertEqual(
            delivery.verify_publication(
                self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 1000
            ),
            "skip",
        )
        self.publication_runs[0]["conclusion"] = "failure"
        with self.assertRaisesRegex(delivery.ReleaseError, "prior upload"):
            delivery.verify_publication(
                self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 1000
            )
        # Rerunning the original failed run is permitted for operator repair.
        self.assertEqual(
            delivery.verify_publication(
                self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 900
            ),
            "publish",
        )

    def test_versions_manual_evidence_unknown_fields_and_builds_fail_closed(self):
        for invalid in (
            "1.02.3",
            "v1.2.3",
            "1.2.3-rc.1",
            "1.2.3;echo x",
            "1.2.3\n",
            "65536.0.0",
        ):
            with (
                self.subTest(version=invalid),
                self.assertRaises(delivery.ReleaseError),
            ):
                delivery.version(invalid)
        for update in (
            {"windows_accepted": False},
            {"tested_sha": SOURCE},
            {"report_url": "https://example.com/report"},
        ):
            evidence = dict(self.intent["evidence"])
            self.intent["evidence"].update(update)
            with self.assertRaises(delivery.ReleaseError):
                delivery.validate_intent(self.intent)
            self.intent["evidence"] = evidence
        self.intent["extra"] = True
        with self.assertRaises(delivery.ReleaseError):
            delivery.validate_intent(self.intent)
        self.intent.pop("extra")
        self.mobile()
        for update in (
            {"build": "32"},
            {"build": "033"},
            {"build": "-1"},
            {"pending_builds_checked": False},
            {"checked_at": "yesterday"},
        ):
            evidence = dict(self.intent["evidence"])
            self.intent["evidence"].update(update)
            with self.assertRaises(delivery.ReleaseError):
                delivery.validate_intent(self.intent)
            self.intent["evidence"] = evidence
        with self.assertRaises(delivery.ReleaseError):
            delivery.decode('{"schema":1,"schema":1}')

    def test_packaged_version_mismatch_is_rejected(self):
        self.files[("package.json", SOURCE)] = '{"version":"1.2.5"}'
        with self.assertRaisesRegex(delivery.ReleaseError, "versions differ"):
            self.promote()
        self.assertEqual(self.mutations(), [])

    def test_release_metadata_cannot_hide_product_code_or_config_changes(self):
        self.files[("version.py", SOURCE)] += "print('unexpected product code')\n"
        with self.assertRaisesRegex(delivery.ReleaseError, "Only desktop version"):
            self.promote()
        self.files[("version.py", SOURCE)] = '__version__ = "1.2.4"\n'
        self.files[("package.json", SOURCE)] = (
            '{"version":"1.2.4","scripts":{"build":"unexpected"}}'
        )
        with self.assertRaisesRegex(delivery.ReleaseError, "Only desktop version"):
            self.promote()
        self.mobile()
        app = json.loads(self.files[("mobile/app.json", SOURCE)])
        app["expo"]["plugins"] = ["unreviewed-plugin"]
        self.files[("mobile/app.json", SOURCE)] = json.dumps(app)
        with self.assertRaisesRegex(delivery.ReleaseError, "Only mobile version"):
            self.promote()
        self.assertEqual(self.mutations(), [])

    def test_rerun_after_successful_upload_only_completes_availability(self):
        self.mobile()
        self.tag = SOURCE
        self.routes["/actions/runs/900/attempts/1/jobs"] = {
            "jobs": [
                {
                    "steps": [
                        {
                            "name": "Upload directly to App Store Connect",
                            "conclusion": "success",
                        }
                    ]
                }
            ]
        }
        self.assertEqual(
            delivery.verify_publication(
                self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 900, 2
            ),
            "availability",
        )
        self.routes["/actions/runs/900/attempts/1/jobs"]["jobs"][0]["steps"][0][
            "conclusion"
        ] = "failure"
        with self.assertRaisesRegex(delivery.ReleaseError, "ambiguous"):
            delivery.verify_publication(
                self.api, "mobile", SOURCE, "ios/v0.9.2-build33", 900, 2
            )
        self.assertEqual(self.mutations(), [])

    def test_preparation_creates_future_metadata_only_and_draft_pr(self):
        evidence = dict(self.intent["evidence"], tested_sha=SOURCE)
        result = delivery.prepare(
            self.api, "desktop", "1.2.5", evidence, "Fix clipboard restoration."
        )
        self.assertEqual(result, "https://github.com/jvictormaynard/clarify/pull/200")
        tree = self.mutations()[0][1]["tree"]
        files = {item["path"]: item["content"] for item in tree}
        self.assertEqual(
            set(files),
            {
                "version.py",
                "package.json",
                "CHANGELOG.md",
                ".github/release-intent.json",
            },
        )
        self.assertIn('__version__ = "1.2.5"', files["version.py"])
        self.assertEqual(json.loads(files["package.json"])["version"], "1.2.5")
        self.assertIn(
            "[1.2.5]: https://github.com/jvictormaynard/clarify/compare/v1.2.4...v1.2.5",
            files["CHANGELOG.md"],
        )
        self.assertTrue(self.mutations()[-1][1]["draft"])
        self.assertFalse(
            any(
                path.endswith("/dispatches") or path == "/git/tags"
                for path, _ in self.mutations()
            )
        )

    def test_mobile_preparation_requires_recent_pending_build_check(self):
        self.mobile()
        now = datetime(2026, 10, 25, 13, tzinfo=timezone.utc)
        evidence = dict(self.intent["evidence"], build="34", highest_build="33")
        self.assertIn(
            "/pull/200",
            delivery.prepare(self.api, "mobile", "0.9.2", evidence, "Fix typing.", now),
        )
        files = {
            item["path"]: item["content"] for item in self.mutations()[0][1]["tree"]
        }
        self.assertEqual(set(files), {"mobile/app.json", ".github/release-intent.json"})
        self.assertEqual(
            json.loads(files["mobile/app.json"])["expo"]["ios"]["buildNumber"], "34"
        )
        self.calls.clear()
        evidence["checked_at"] = "2026-10-23T12:00:00Z"
        with self.assertRaisesRegex(delivery.ReleaseError, "within 24 hours"):
            delivery.prepare(self.api, "mobile", "0.9.2", evidence, "Fix typing.", now)
        self.assertEqual(self.mutations(), [])


if __name__ == "__main__":
    unittest.main()
