"""Release effects use a local fake HTTP server, never GitHub or Apple."""

import base64
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from scripts import release_delivery as delivery
from scripts import app_store_handoff as store

SOURCE = "a" * 40
BASE = "b" * 40
TAG_OBJECT = "c" * 40
REPOSITORY = "jvictormaynard/clarify"
ROOT = Path(__file__).resolve().parents[2]


class ReleaseNotesTests(unittest.TestCase):
    CHANGELOG = """# Changelog

## [Unreleased]

### Added

- A future feature.

## [1.2.4] - 2026-10-25

### Fixed

- Preserve the user's text, including `code` and [links](https://example.com).

## [1.2.3] - 2026-10-20

### Added

- An older feature.

[Unreleased]: https://example.com/compare/v1.2.4...HEAD
[1.2.4]: https://example.com/compare/v1.2.3...v1.2.4
"""

    def test_notes_include_only_the_requested_version_before_distribution(self):
        notes = delivery.community_release_notes(self.CHANGELOG, "v1.2.4")
        self.assertTrue(
            notes.startswith(
                "### Fixed\n\n- Preserve the user's text, including `code` and "
                "[links](https://example.com).\n"
            )
        )
        self.assertIn(
            "https://github.com/jvictormaynard/clarify/blob/v1.2.4/CHANGELOG.md",
            notes,
        )
        self.assertIn("Windows SmartScreen", notes)
        self.assertEqual(
            delivery.community_release_notes(
                self.CHANGELOG.replace("\n", "\r\n"), "v1.2.4"
            ),
            notes,
        )
        self.assertNotIn("A future feature", notes)
        self.assertNotIn("An older feature", notes)
        self.assertNotIn("[Unreleased]:", notes)
        oldest = delivery.changelog_section(self.CHANGELOG, "1.2.3")
        self.assertEqual(oldest, "### Added\n\n- An older feature.")

    def test_missing_duplicate_undated_and_empty_sections_are_rejected(self):
        documents = [
            "## [Unreleased]\n\n- A future feature.\n",
            self.CHANGELOG + "\n## [1.2.4] - 2026-10-25\n\n- Duplicate.\n",
            "## [1.2.4]\n\n- Missing date.\n",
            "## [1.2.4] - 2026-10-25\n\n### Fixed\n\n<!-- No changes yet. -->\n",
        ]
        for document in documents:
            with self.subTest(document=document):
                with self.assertRaises(delivery.ReleaseError):
                    delivery.community_release_notes(document, "v1.2.4")
        with self.assertRaises(delivery.ReleaseError):
            delivery.community_release_notes(self.CHANGELOG, "main")


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
            "schema": 2,
            "component": "desktop",
            "version": "1.2.4",
            "base_sha": BASE,
            "notes": "Fix clipboard restoration. Windows acceptance passed.",
            "evidence": {
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
                    "/actions/workflows/release.yml/dispatches",
                    {
                        "ref": "v1.2.4",
                        "inputs": {
                            "source_sha": SOURCE,
                            "action": "build-candidate",
                            "channel": "stable",
                        },
                    },
                ),
            ],
        )

    def test_mobile_dispatch_preserves_exact_build_and_selects_testflight_mode(self):
        self.mobile()
        self.assertEqual(self.promote(), "dispatched")
        self.assertEqual(
            self.mutations()[-1],
            (
                "/actions/workflows/ios-testflight.yml/dispatches",
                {
                    "ref": "ios/v0.9.2-build33",
                    "inputs": {"source_sha": SOURCE, "mode": "testflight"},
                },
            ),
        )

    def test_availability_recovery_checks_source_without_repeating_an_ambiguous_upload(
        self,
    ):
        self.mobile()
        self.tag = SOURCE
        self.publication_runs = [
            {
                "id": 800,
                "head_sha": SOURCE,
                "head_branch": "ios/v0.9.2-build33",
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "failure",
            }
        ]
        self.routes["/actions/runs/800/jobs"] = {"jobs": []}
        self.assertEqual(
            delivery.verify_publication(
                self.api,
                "mobile",
                SOURCE,
                "ios/v0.9.2-build33",
                900,
                availability_only=True,
            ),
            "availability",
        )
        self.assertEqual(self.mutations(), [])
        self.tag = BASE
        with self.assertRaises(delivery.ReleaseError):
            delivery.verify_publication(
                self.api,
                "mobile",
                SOURCE,
                "ios/v0.9.2-build33",
                900,
                availability_only=True,
            )

    def test_app_store_handoff_producer_requires_the_exact_completed_signed_delivery(
        self,
    ):
        self.mobile()
        self.tag = SOURCE
        producer = dict(
            self.run,
            id=900,
            workflow_id=9,
            event="workflow_dispatch",
            head_branch="ios/v0.9.2-build33",
            path=".github/workflows/ios-testflight.yml",
            run_attempt=1,
        )
        self.routes["/actions/runs/900"] = producer
        self.routes["/actions/workflows/9"] = {
            "path": ".github/workflows/ios-testflight.yml"
        }
        steps = [
            {"name": name, "conclusion": "success", "status": "completed"}
            for name in (
                "Verify signed app and both extensions",
                "Upload directly to App Store Connect",
                "Verify processing and publish to the existing internal group",
                "Seal TestFlight candidate evidence",
                "Preserve TestFlight candidate evidence",
            )
        ]
        self.routes["/actions/runs/900/attempts/1/jobs"] = {
            "jobs": [
                {
                    "name": "Test, sign and upload iOS",
                    "run_attempt": 1,
                    "status": "completed",
                    "conclusion": "success",
                    "steps": steps,
                }
            ]
        }
        store.verify_producer(self.api, SOURCE, "ios/v0.9.2-build33", 900, 1)
        for key, value in (
            ("head_sha", BASE),
            ("conclusion", "failure"),
            ("event", "push"),
            ("run_attempt", 2),
            ("path", ".github/workflows/ios-qa.yml"),
        ):
            original = producer[key]
            producer[key] = value
            with self.subTest(key=key), self.assertRaises(delivery.ReleaseError):
                store.verify_producer(self.api, SOURCE, "ios/v0.9.2-build33", 900, 1)
            producer[key] = original
        steps[1]["conclusion"] = "skipped"
        with self.assertRaises(delivery.ReleaseError):
            store.verify_producer(self.api, SOURCE, "ios/v0.9.2-build33", 900, 1)
        self.assertEqual(self.mutations(), [])

    def test_manual_app_store_handoff_never_claims_submission_or_public_availability(
        self,
    ):
        self.mobile()
        now = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
        apple_id = "12345678-1234-1234-1234-123456789abc"
        verification = {
            "sha256": "d" * 64,
            "bytes": 123,
            "bundles": [
                {"bundleId": name, "version": "0.9.2", "build": "33"}
                for name in (
                    "com.jvictormaynard.clarify",
                    "com.jvictormaynard.clarify.keyboard",
                    "com.jvictormaynard.clarify.activity",
                )
            ],
        }
        availability = {
            "id": apple_id,
            "version": "0.9.2",
            "build": "33",
            "processing": "VALID",
            "internalState": "IN_BETA_TESTING",
            "group": "Clarify Interno",
            "availableInGroup": True,
            "existingTesters": 1,
        }
        evidence = {
            "report_url": "https://github.com/jvictormaynard/clarify/issues/123",
            "checked_at": "2026-10-30T11:00:00Z",
            "metadata_reviewed": True,
            "native_accepted": True,
            "store_policy_reviewed": True,
            "existing_submissions_checked": True,
            "manual_release": True,
            "store_state": "PREPARE_FOR_SUBMISSION",
        }
        for action, state in (
            ("prepare-submission", "PREPARE_FOR_SUBMISSION"),
            ("prepare-release", "PENDING_DEVELOPER_RELEASE"),
        ):
            evidence["store_state"] = state
            result = store.handoff(
                self.intent, verification, availability, apple_id, action, evidence, now
            )
            self.assertFalse(result["apple_mutation_performed"])
            self.assertFalse(result["public_availability_verified"])
            self.assertEqual(result["ipa_sha256"], "d" * 64)
            for obj, key, value in (
                (availability, "id", "87654321-1234-1234-1234-123456789abc"),
                (availability, "build", "32"),
                (verification, "sha256", "bad"),
                (evidence, "store_state", "WAITING_FOR_REVIEW"),
                (evidence, "checked_at", "2026-10-28T11:00:00Z"),
                (evidence, "store_policy_reviewed", False),
                (evidence, "manual_release", False),
            ):
                original = obj[key]
                obj[key] = value
                with (
                    self.subTest(action=action, key=key),
                    self.assertRaises(delivery.ReleaseError),
                ):
                    store.handoff(
                        self.intent,
                        verification,
                        availability,
                        apple_id,
                        action,
                        evidence,
                        now,
                    )
                obj[key] = original

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
                        delivery.verify_source(self.api, component, SOURCE, tag)
                    self.assertEqual(self.mutations(), [])

    def test_release_consumer_does_not_duplicate_the_ci_component_inventory(self):
        self.jobs[:] = [job for job in self.jobs if job["name"] == "CI required"]
        self.tag = SOURCE
        self.assertEqual(
            delivery.verify_source(self.api, "desktop", SOURCE, "v1.2.4"), self.intent
        )
        self.assertEqual(self.promote(), "dispatched")
        self.assertEqual(self.mutations()[-1][1]["inputs"]["action"], "build-candidate")

    def test_retired_intent_schema_cannot_authorize_a_candidate(self):
        self.intent["schema"] = 1
        with self.assertRaisesRegex(delivery.ReleaseError, "schema"):
            delivery.validate_intent(self.intent)

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
        next(job for job in self.jobs if job["name"] == "CI required")["conclusion"] = (
            "skipped"
        )
        with self.assertRaisesRegex(delivery.ReleaseError, "Required CI job"):
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

    def test_code_changed_since_source_preparation_is_rejected(self):
        comparison = self.routes["/compare/" + BASE + "..." + SOURCE]
        comparison["files"] = self.changes + [
            {"filename": "workflows.py", "status": "modified"}
        ]
        with self.assertRaisesRegex(delivery.ReleaseError, "after preparation"):
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

    def test_candidate_source_authenticates_exact_tag_ci_and_review_after_main_advances(
        self,
    ):
        self.tag = SOURCE
        self.main = BASE
        self.assertEqual(
            delivery.verify_source(self.api, "desktop", SOURCE, "v1.2.4"), self.intent
        )
        self.tag = BASE
        with self.assertRaisesRegex(delivery.ReleaseError, "Immutable tag"):
            delivery.verify_source(self.api, "desktop", SOURCE, "v1.2.4")
        with self.assertRaisesRegex(delivery.ReleaseError, "authenticated candidate"):
            delivery.verify_publication(self.api, "desktop", SOURCE, "v1.2.4", 1000)
        self.assertEqual(self.mutations(), [])

    def test_superseded_desktop_release_cannot_be_promoted(self):
        self.tag = SOURCE
        for published in ("v1.2.4", "v1.2.5", "v2.0.0"):
            self.routes["/releases"] = [
                {"tag_name": published, "draft": False, "prerelease": False}
            ]
            with self.assertRaisesRegex(delivery.ReleaseError, "superseded"):
                self.promote()
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
        evidence = dict(self.intent["evidence"])
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


class DesktopPreviewTests(unittest.TestCase):
    def test_preview_identity_is_unique_and_cannot_enter_the_stable_tag_namespace(self):
        self.assertEqual(
            delivery.preview_tag("a" * 40, "123"), "preview/123-1-aaaaaaaaaaaa"
        )
        for source, run in (("main", "123"), ("a" * 40, "0"), ("a" * 40, "1;exit")):
            with self.subTest(source=source, run=run):
                with self.assertRaises(delivery.ReleaseError):
                    delivery.preview_tag(source, run)

    def test_preview_build_disables_policy_and_records_exact_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "distribution").mkdir()
            policy = root / "distribution/portable-update-policy.json"
            pin = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
            policy.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "channel": "stable",
                        "public_key": pin,
                        "algorithm": "Ed25519",
                        "repository": "jvictormaynard/clarify",
                        "maximum_download_bytes": 268435456,
                    }
                )
            )
            (root / "version.py").write_text('__version__ = "1.2.3"\n')
            identity = delivery.prepare_desktop_preview(root, "a" * 40, "123")
            self.assertEqual(json.loads(policy.read_text())["channel"], "preview")
            self.assertEqual(identity["source_sha"], "a" * 40)
            self.assertFalse(identity["updater_enabled"])
            self.assertEqual(identity["tag"], "preview/123-1-aaaaaaaaaaaa")
            self.assertEqual(identity["version"], "1.2.3")
            # The exact packaged version and the public key are preserved.
            self.assertEqual(json.loads(policy.read_text())["public_key"], pin)
            self.assertEqual(
                (root / "version.py").read_text(), '__version__ = "1.2.3"\n'
            )


if __name__ == "__main__":
    unittest.main()
