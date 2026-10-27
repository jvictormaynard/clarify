"""QA decisions use fake API data; no credentials or Apple calls are needed."""

from copy import deepcopy
import contextlib
from datetime import datetime, timezone
from email.message import Message
from functools import lru_cache
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from urllib.error import HTTPError
import zipfile

from scripts import testflight_qa as qa
from scripts.release_delivery import ReleaseError


ROOT = Path(__file__).resolve().parents[1]
SOURCE, BASE, OLD = "a" * 40, "b" * 40, "c" * 40
REPO = "jvictormaynard/clarify"
NOW = datetime(2026, 10, 27, 5, tzinfo=timezone.utc)
QA_PATH = ".github/workflows/ios-qa.yml"
STABLE = ".github/workflows/ios-testflight.yml"


def app(build="8"):
    return {
        "expo": {
            "version": "1.2.3",
            "ios": {
                "buildNumber": build,
                "bundleIdentifier": "com.jvictormaynard.clarify",
            },
        }
    }


def metadata():
    # Synthetic identities are not a reservation for the real application.
    return dict(
        schema=1,
        pr=179,
        source_sha=SOURCE,
        base_sha=BASE,
        app_id="6820869157",
        bundle_id="com.jvictormaynard.clarify",
        version="1.2.3",
        build="8",
        tag="ios/pr-179/v1.2.3-build8",
        relay_host=None,
        reservation=dict(
            highest_build="7",
            pending_builds_checked=True,
            checked_at="2026-10-27T04:00:00Z",
            report_url=f"https://github.com/{REPO}/pull/179#issuecomment-1",
        ),
    )


def context():
    return dict(
        repository=REPO,
        event="workflow_dispatch",
        ref="refs/heads/main",
        workflow_ref=f"{REPO}/{QA_PATH}@refs/heads/main",
        workflow_sha=BASE,
        checkout_sha=BASE,
        sha=BASE,
        actor="maintainer",
        triggering_actor="maintainer",
        run_id=90,
        run_attempt=1,
        mode="preflight",
    )


class FakeGitHub:
    def __init__(self):
        self.main = BASE
        self.pr_reads = 0
        self.change_on_recheck = False
        self.pr = dict(
            number=179,
            state="open",
            draft=False,
            merged=False,
            mergeable=True,
            mergeable_state="clean",
            head=dict(sha=SOURCE, ref="codex/feature", repo=dict(full_name=REPO)),
            base=dict(sha=BASE, ref="main", repo=dict(full_name=REPO)),
        )
        self.files = {}
        policy_paths = [
            ".github/workflows/ci.yml",
            ".github/workflows/ios-validation.yml",
            ".github/workflows/server-validation.yml",
            ".github/workflows/dependency-audit.yml",
            "scripts/delivery_policy.py",
            "scripts/release_delivery.py",
        ]
        for path in policy_paths:
            for source in [BASE, SOURCE]:
                self.files[path, source] = (ROOT / path).read_text(encoding="utf-8")
        self.files["mobile/app.json", SOURCE] = json.dumps(app())
        self.files["mobile/app.json", BASE] = json.dumps(app("7"))
        self.files["shared/computer_connect.json", SOURCE] = json.dumps(
            dict(schema_version=1, relay_host=None, relay_port=443)
        )
        self.files[QA_PATH, BASE] = "trusted read-only QA workflow"
        self.files[STABLE, BASE] = (ROOT / STABLE).read_text(encoding="utf-8")
        for source in (SOURCE, OLD):
            self.files[STABLE, source] = self.files[STABLE, BASE]
            for helper in qa.STABLE_APPLE_HELPERS:
                self.files[helper, source] = (ROOT / helper).read_text(encoding="utf-8")
        self.files[".github/actions/settings-build/action.yml", SOURCE] = (
            ROOT / ".github/actions/settings-build/action.yml"
        ).read_text(encoding="utf-8")
        self.files[".github/actions/settings-build/action.yml", BASE] = self.files[
            ".github/actions/settings-build/action.yml", SOURCE
        ]
        self.paths = [dict(filename="mobile/app.json", status="modified")]
        self.runs = {}
        self.jobs = {}
        names = [
            "Select component validation",
            "Repository checks",
            "CI required",
            "Mobile checks",
            "iOS validation / Native keyboard and library tests",
            "iOS validation / Unsigned app and extensions build",
            "iOS validation / Native tests and unsigned build",
        ]
        for identifier, source, event in [
            (10, SOURCE, "pull_request"),
            (11, BASE, "push"),
        ]:
            self.runs[source] = [
                dict(
                    id=identifier,
                    run_attempt=1,
                    workflow_id=1,
                    repository=dict(full_name=REPO),
                    head_repository=dict(full_name=REPO),
                    head_sha=source,
                    head_branch="main" if event == "push" else "codex/feature",
                    event=event,
                    path=".github/workflows/ci.yml",
                    status="completed",
                    conclusion="success",
                    pull_requests=[
                        dict(number=179, head=dict(sha=SOURCE), base=dict(sha=BASE))
                    ],
                )
            ]
            self.jobs[identifier, 1] = [
                dict(
                    name=name, head_sha=source, status="completed", conclusion="success"
                )
                for name in names
            ]
            api_steps = {
                "iOS validation / Native keyboard and library tests": [
                    "Run npm run test:native",
                    "Test native keyboard and library integration",
                ],
                "iOS validation / Unsigned app and extensions build": [
                    "Compile app and extensions without signing or upload",
                ],
                "iOS validation / Native tests and unsigned build": [
                    "Require native tests and unsigned compilation",
                ],
            }
            for job in self.jobs[identifier, 1]:
                if job["name"] in api_steps:
                    job["steps"] = [
                        dict(name=name, status="completed", conclusion="success")
                        for name in api_steps[job["name"]]
                    ]
        self.history = [
            dict(
                id=12,
                head_sha=BASE,
                path=qa.CI_PATH,
                repository=dict(full_name=REPO),
                run_attempt=1,
                status="completed",
                conclusion="success",
            )
        ]
        self.permissions = {"maintainer": "maintain"}
        self.calls = []

    def request(self, method, path, *args, **kwargs):
        self.calls.append((method, path))
        if method != "GET":
            raise AssertionError("The gate must not mutate GitHub")
        if path == "/pulls/179":
            self.pr_reads += 1
            result = deepcopy(self.pr)
            if self.change_on_recheck and self.pr_reads > 1:
                result["head"]["sha"] = OLD
            return result
        if path == "/git/ref/heads/main":
            return dict(object=dict(sha=self.main))
        if path.startswith("/collaborators/"):
            role = self.permissions.get(path.split("/")[2], "read")
            return dict(
                permission="write" if role == "maintain" else role, role_name=role
            )
        if path.startswith("/compare/"):
            return dict(status="ahead", merge_base_commit=dict(sha=BASE))
        if path.startswith("/git/ref/tags/"):
            return dict(object=dict(type="commit", sha=SOURCE))
        if path == "/actions/workflows/1":
            return dict(id=1, name="CI", path=".github/workflows/ci.yml")
        raise AssertionError(path)

    def file(self, path, ref, **kwargs):
        return self.files[path, ref]

    def pages(self, path, key=None):
        self.calls.append(("GET", path))
        if path == "/pulls/179/files":
            return deepcopy(self.paths)
        if path.startswith("/actions/workflows/ci.yml/runs?"):
            source = path.split("head_sha=")[1].split("&")[0]
            event = path.split("event=")[1].split("&")[0]
            return deepcopy([run for run in self.runs[source] if run["event"] == event])
        if path == "/actions/workflows":
            return [
                dict(id=1, name="CI", path=qa.CI_PATH),
                dict(id=2, name="iOS TestFlight", path=STABLE),
                dict(id=3, name="iOS internal QA preflight", path=QA_PATH),
            ]
        if path == "/actions/runs":
            return deepcopy(self.history)
        if path in [
            "/actions/workflows/ios-testflight.yml/runs",
            "/actions/workflows/ios-qa.yml/runs",
        ]:
            target = STABLE if "ios-testflight" in path else QA_PATH
            return deepcopy([r for r in self.history if r["path"] == target])
        if path.startswith("/actions/runs/"):
            parts = path.split("/")
            return deepcopy(self.jobs[int(parts[3]), int(parts[5])])
        raise AssertionError(path)

    def prior(self, outcome, *, source=SOURCE, attempt=1, identifier=80, path=STABLE):
        self.history = [
            dict(
                id=identifier,
                run_attempt=attempt,
                head_sha=source,
                repository=dict(full_name=REPO),
                path=path,
                status="completed",
            )
        ]
        self.files["mobile/app.json", source] = json.dumps(app())
        for current in range(1, attempt + 1):
            self.jobs[identifier, current] = [
                dict(
                    name="Test, sign and upload iOS",
                    status="completed",
                    conclusion="success",
                    steps=[
                        dict(
                            name="Upload directly to App Store Connect",
                            status="completed",
                            conclusion=outcome,
                        )
                    ],
                )
            ]


class QATests(unittest.TestCase):
    def setUp(self):
        self.api, self.data, self.ctx = FakeGitHub(), metadata(), context()

    def verify(self):
        return qa.evaluate(self.api, self.data, self.ctx, now=NOW)

    def test_exact_ready_candidate_is_eligible_but_has_no_packaging_proof(self):
        result = self.verify()
        self.assertEqual(result["decision"], "eligible-preflight")
        self.assertFalse(result["packaging_proven"])
        self.assertFalse(result["upload_enabled"])
        self.assertEqual(result["base_sha"], BASE)
        self.assertTrue(all(method == "GET" for method, _ in self.api.calls))

    def test_documented_maintain_role_is_accepted_without_accepting_plain_write(self):
        request = self.api.request
        role = "maintain"

        def permission(method, path, *args, **kwargs):
            if path.startswith("/collaborators/"):
                return {
                    "permission": "admin" if role == "admin" else "write",
                    "role_name": role,
                }
            return request(method, path, *args, **kwargs)

        self.api.request = permission
        self.assertEqual(self.verify()["decision"], "eligible-preflight")
        for role in ("write", "custom-role", "unknown"):
            with self.subTest(role=role), self.assertRaises(ReleaseError):
                self.verify()
        role = "admin"
        self.assertEqual(self.verify()["decision"], "eligible-preflight")

    def test_confirmed_same_source_requires_explicit_availability_mode(self):
        self.api.prior("success")
        self.assertEqual(self.verify()["decision"], "availability-required")

    def test_existing_upload_uses_current_evidence_without_reserving_its_build_again(
        self,
    ):
        self.api.prior("success")
        self.data["reservation"]["highest_build"] = self.data["build"]
        self.assertEqual(self.verify()["decision"], "availability-required")
        self.api.prior("skipped")
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_skipped_upload_requires_known_workflow_and_verifier(self):
        for helper in (STABLE, *qa.STABLE_APPLE_HELPERS):
            with self.subTest(helper=helper):
                self.api = FakeGitHub()
                self.api.prior("skipped", source=OLD)
                self.api.files[helper, OLD] = (
                    "unknown implementation with another uploader"
                )
                with self.assertRaisesRegex(
                    ReleaseError, "Unknown historical upload implementation"
                ):
                    self.verify()

    def test_a_former_uploader_in_another_workflow_is_not_hidden_by_its_current_file(
        self,
    ):
        self.api.prior("skipped", source=OLD, path=qa.CI_PATH)
        self.api.files[qa.CI_PATH, OLD] = "historical code with an Apple upload"
        with self.assertRaisesRegex(ReleaseError, "Unknown historical"):
            self.verify()

    def test_authenticated_validation_workflow_history_does_not_count_as_upload(self):
        self.api.prior("skipped", path=qa.CI_PATH)
        self.assertEqual(self.verify()["decision"], "eligible-preflight")

    def test_exact_main_manual_validation_can_follow_a_selective_push(self):
        manual = deepcopy(self.api.runs[BASE][0])
        manual.update(id=12, event="workflow_dispatch")
        self.api.runs[BASE].append(manual)
        self.api.jobs[12, 1] = deepcopy(self.api.jobs[11, 1])
        for job in self.api.jobs[11, 1]:
            if job["name"] in {qa.NATIVE_JOB, "Mobile checks"}:
                job["conclusion"] = "skipped"
        self.assertEqual(self.verify()["base_ci_run"], 12)
        manual["head_sha"] = OLD
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_split_native_jobs_and_their_aggregate_must_all_succeed(self):
        native = "iOS validation / Native keyboard and library tests"
        build = "iOS validation / Unsigned app and extensions build"
        self.assertEqual(self.verify()["decision"], "eligible-preflight")
        for name in (native, build):
            job = next(row for row in self.api.jobs[10, 1] if row["name"] == name)
            job["conclusion"] = "skipped"
            with self.subTest(job=name), self.assertRaises(ReleaseError):
                self.verify()
            job["conclusion"] = "success"

    def test_all_ambiguous_attempts_and_unknown_job_histories_block(self):
        for outcome in ["failure", "cancelled", "timed_out", None, "unknown"]:
            with self.subTest(outcome=outcome):
                self.api = FakeGitHub()
                self.api.prior(outcome)
                with self.assertRaises(ReleaseError):
                    self.verify()
        self.api = FakeGitHub()
        self.api.prior("skipped")
        self.api.jobs[80, 1] = []
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_prior_foreign_source_success_blocks_but_skipped_upload_does_not(self):
        self.api.prior("success", source=OLD)
        with self.assertRaises(ReleaseError):
            self.verify()
        self.api.prior("skipped", source=OLD)
        self.assertEqual(self.verify()["decision"], "eligible-preflight")

    def test_same_run_earlier_attempt_is_not_ignored(self):
        self.api.prior("success", identifier=90, attempt=2, path=QA_PATH)
        self.ctx["run_attempt"] = 2
        self.api.files[QA_PATH, SOURCE] = (
            "unknown older implementation that could upload"
        )
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_pr_change_during_gate_blocks(self):
        self.api.change_on_recheck = True
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_only_trusted_main_and_manual_maintainer_dispatch_can_run(self):
        changes = [
            ("ref", "refs/tags/ios/pr-179/v1.2.3-build8"),
            ("workflow_sha", OLD),
            ("checkout_sha", OLD),
            ("event", "push"),
            ("workflow_ref", f"{REPO}/{QA_PATH}@refs/heads/feature"),
            ("repository", "someone/clarify"),
            ("triggering_actor", "reader"),
        ]
        for key, value in changes:
            with self.subTest(key=key):
                self.ctx = context()
                self.ctx[key] = value
                with self.assertRaises(ReleaseError):
                    self.verify()

    def test_apple_effect_modes_are_blocked_before_any_api_calls(self):
        for mode in ["upload", "availability", "auto", "unknown"]:
            with self.subTest(mode=mode):
                self.ctx["mode"] = mode
                with self.assertRaises(ReleaseError):
                    self.verify()
                self.assertEqual(self.api.calls, [])

    def test_strict_metadata_rejects_arbitrary_data_or_old_reservations(self):
        mutations = [
            lambda d: d.update(model="anything"),
            lambda d: d.update(endpoint="https://example.com"),
            lambda d: d.update(schema=True),
            lambda d: d.update(pr=180),
            lambda d: d.update(source_sha="main"),
            lambda d: d.update(relay_host="example.com"),
            lambda d: d.update(app_id="123"),
            lambda d: d.update(tag="ios/v1.2.3-build8"),
            lambda d: d["reservation"].update(highest_build="8"),
            lambda d: d["reservation"].update(pending_builds_checked=False),
            lambda d: d["reservation"].update(checked_at="2026-10-25T05:00:00Z"),
            lambda d: d["reservation"].update(checked_at="2026-10-27T06:00:00Z"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.data = metadata()
                mutate(self.data)
                with self.assertRaises(ReleaseError):
                    self.verify()

    def test_ci_from_another_base_cannot_replace_new_composition(self):
        self.api.runs[SOURCE][0]["pull_requests"][0]["base"]["sha"] = OLD
        with self.assertRaises(ReleaseError):
            self.verify()
        self.api = FakeGitHub()
        self.api.main = OLD
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_failed_skipped_missing_unknown_native_checks_block_on_both_sources(self):
        for identifier in [10, 11]:
            for outcome in ["failure", "skipped", "cancelled", "timed_out", None]:
                with self.subTest(identifier=identifier, outcome=outcome):
                    self.api = FakeGitHub()
                    self.api.jobs[identifier, 1][-1]["conclusion"] = outcome
                    with self.assertRaises(ReleaseError):
                        self.verify()
            self.api = FakeGitHub()
            self.api.jobs[identifier, 1].pop()
            with self.assertRaises(ReleaseError):
                self.verify()
        self.api = FakeGitHub()
        self.api.jobs[10, 1][-1]["steps"][0]["conclusion"] = "skipped"
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_pr_cannot_omit_desktop_checks_by_changing_policy(self):
        self.api.files["scripts/delivery_policy.py", SOURCE] = "all_checks_are_optional"
        with self.assertRaises(ReleaseError):
            self.verify()
        self.api = FakeGitHub()
        self.api.paths.append(dict(filename="workflows.py", status="modified"))
        with self.assertRaises(ReleaseError):
            self.verify()  # The trusted policy also requires the desktop jobs.

    def test_candidate_workflow_edits_and_renames_block(self):
        for change in [
            dict(filename=STABLE, status="modified"),
            dict(
                filename="docs/old.md", previous_filename=qa.CI_PATH, status="renamed"
            ),
        ]:
            with self.subTest(change=change):
                self.api.paths = [change]
                with self.assertRaises(ReleaseError):
                    self.verify()

    def test_old_push_history_and_all_attempts_are_checked_across_shas(self):
        self.api.prior("success", source=OLD, attempt=2)
        self.api.history[0]["event"] = "push"
        self.api.jobs[80, 2][0]["steps"][0]["conclusion"] = "skipped"
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_unknown_historical_job_blocks_even_for_another_declared_build(self):
        self.api.prior("skipped", source=OLD)
        self.api.files["mobile/app.json", OLD] = json.dumps(app("6"))
        self.api.jobs[80, 1][0]["name"] = "A legacy uploader with unknown behavior"
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_current_retry_requires_its_earlier_history(self):
        self.ctx["run_attempt"] = 2
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_closed_draft_foreign_conflicting_pr_and_legacy_branch_block(self):
        mutations = [
            lambda p: p.update(state="closed"),
            lambda p: p.update(draft=True),
            lambda p: p.update(merged=True),
            lambda p: p.update(mergeable=None),
            lambda p: p["head"].update(ref="codex/ios-testflight"),
            lambda p: p["head"]["repo"].update(full_name="someone/clarify"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.api = FakeGitHub()
                mutate(self.api.pr)
                with self.assertRaises(ReleaseError):
                    self.verify()

    def test_duplicate_json_fields_are_rejected(self):
        with self.assertRaises(ReleaseError):
            qa.decode('{"schema":1,"schema":1}')

    def test_large_realistic_run_ids_and_pending_merge_review_are_supported(self):
        self.ctx["run_id"] = 33986942056
        self.api.pr["mergeable_state"] = "blocked"
        self.assertEqual(self.verify()["decision"], "eligible-preflight")

    def test_changed_historical_upload_implementation_is_not_interpreted_as_proof(self):
        self.api.prior("success")
        self.api.files[STABLE, SOURCE] = "old unknown push uploader"
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_other_version_build_upload_does_not_claim_candidate_availability(self):
        self.api.prior("success", source=OLD)
        self.api.files["mobile/app.json", OLD] = json.dumps(app("6"))
        self.assertEqual(self.verify()["decision"], "eligible-preflight")

    def test_changed_main_during_gate_fails_closed(self):
        request = self.api.request
        reads = 0

        def change_main(method, path, *args, **kwargs):
            nonlocal reads
            result = request(method, path, *args, **kwargs)
            if path == "/git/ref/heads/main":
                reads += 1
                if reads > 1:
                    return {"object": {"sha": OLD}}
            return result

        self.api.request = change_main
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_unknown_workflow_inventory_blocks_even_without_an_ios_name(self):
        pages = self.api.pages

        def unknown_workflow(path, key=None):
            result = pages(path, key)
            if path == "/actions/workflows":
                result.append(
                    dict(
                        id=999, name="legacy workflow", path=".github/workflows/old.yml"
                    )
                )
            return result

        self.api.pages = unknown_workflow
        with self.assertRaises(ReleaseError):
            self.verify()

    def test_empty_history_requires_audited_reconciliation_instead_of_assuming_no_upload(
        self,
    ):
        self.api.history = []
        with self.assertRaisesRegex(ReleaseError, "Missing historical inventory"):
            self.verify()

    def test_trusted_checkout_local_action_requires_its_exact_historical_blob(self):
        self.assertEqual(self.verify()["decision"], "eligible-preflight")
        self.api.files[".github/actions/settings-build/action.yml", BASE] = (
            "changed action"
        )
        with self.assertRaisesRegex(
            ReleaseError, "Unknown historical workflow implementation"
        ):
            self.verify()


class ValidationArtifactRecordTests(unittest.TestCase):
    def setUp(self):
        self.record = dict(
            artifact_id=101,
            artifact_name="clarify-qa-validation-33986942056-2",
            artifact_digest="sha256:" + "d" * 64,
            run_id=33986942056,
            run_attempt=2,
        )
        self.line = "CLARIFY_QA_VALIDATION_ARTIFACT " + json.dumps(self.record)

    def parse(self, text):
        return qa.parse_validation_artifact_record(
            text, run_id=33986942056, run_attempt=2
        )

    def test_upload_outputs_form_one_record_and_plain_or_timestamped_logs_roundtrip(
        self,
    ):
        line = qa.format_validation_artifact_record(
            artifact_id=101,
            artifact_digest="d" * 64,
            run_id=33986942056,
            run_attempt=2,
        )
        self.assertEqual(self.parse(line), self.record)
        self.assertEqual(
            self.parse(
                "Run trusted recorder\n2026-10-27T07:00:00.1234567Z " + line + "\n"
            ),
            self.record,
        )

    def test_record_cannot_change_attempt_artifact_identity_or_typed_digest(self):
        for changes in (
            {"run_id": 33986942057},
            {"run_attempt": 1},
            {"artifact_id": True},
            {"artifact_id": 2**53},
            {"artifact_name": "another-artifact"},
            {"artifact_digest": "d" * 64},
            {"artifact_digest": "sha256:" + "D" * 64},
            {"download_url": "https://untrusted.invalid/"},
        ):
            with self.subTest(changes=changes):
                value = dict(self.record, **changes)
                with self.assertRaises(ReleaseError):
                    self.parse("CLARIFY_QA_VALIDATION_ARTIFACT " + json.dumps(value))

    def test_missing_duplicate_malformed_or_unknown_log_record_fails_closed(self):
        duplicate_key = self.line.replace(
            '"artifact_id": 101', '"artifact_id":101,"artifact_id":102'
        )
        for text in (
            "",
            self.line + "\n" + self.line,
            duplicate_key,
            "unrecognized-prefix " + self.line,
            "CLARIFY_QA_VALIDATION_ARTIFACT {",
            "x" * (1024 * 1024 + 1),
        ):
            with self.subTest(length=len(text)):
                with self.assertRaises(ReleaseError):
                    self.parse(text)

    def test_validation_requires_model_a_and_does_not_accept_preflight_or_bool_schema(
        self,
    ):
        qa.check_validation_trust_model(
            {"schema": 1, "trust_model": "reviewed-source-internal-qa-v1"}
        )
        for value in (
            {"schema": 1, "decision": "eligible-preflight"},
            {"schema": True, "trust_model": "reviewed-source-internal-qa-v1"},
            {"schema": 1, "trust_model": "assertions-attested"},
        ):
            with self.subTest(value=value):
                with self.assertRaises(ReleaseError):
                    qa.check_validation_trust_model(value)


class TrustedValidationManifestTests(unittest.TestCase):
    """The builder consumes a MAIN plan and API job facts, never product reports."""

    def setUp(self):
        self.contract = {
            key: dict(
                job_name="Trusted validation / " + key,
                required_steps=["Authenticate trusted controls", "Validate " + key],
            )
            for key in qa.VALIDATION_KEYS
        }
        selected = [key for key in qa.VALIDATION_KEYS if key in qa.VALIDATION_MINIMUM]
        self.plan = dict(
            schema=1,
            kind="clarify-trusted-ci-plan",
            trust_model=qa.VALIDATION_TRUST_MODEL,
            source_sha=SOURCE,
            source_tree="d" * 40,
            base_sha=BASE,
            base_tree="e" * 40,
            trusted_sha=BASE,
            components={key: key in {"mobile", "ios"} for key in qa.COMPONENT_JOBS},
            selected_keys=selected,
            checks={key: self.contract[key] for key in selected},
            controls={"scripts/trusted_ci.py": "f" * 40},
        )
        self.workflow = dict(id=99, path=QA_PATH, blob_sha="1" * 40)
        self.jobs = [
            dict(
                id=1000 + index,
                run_id=90,
                head_sha=BASE,
                name=self.contract[key]["job_name"],
                status="completed",
                conclusion="success",
                steps=[
                    dict(
                        number=number,
                        name=name,
                        status="completed",
                        conclusion="success",
                    )
                    for number, name in enumerate(
                        self.contract[key]["required_steps"], 1
                    )
                ],
            )
            for index, key in enumerate(selected)
        ]

    def build(self):
        return qa.validation_manifest(
            self.plan,
            self.contract,
            self.jobs,
            workflow=self.workflow,
            run_id=90,
            run_attempt=2,
        )

    def test_manifest_records_selected_api_checks_and_exact_main_source_bindings(self):
        result = self.build()
        self.assertEqual(result["trust_model"], "reviewed-source-internal-qa-v1")
        self.assertEqual(result["source_sha"], SOURCE)
        self.assertEqual(result["trusted_sha"], BASE)
        self.assertEqual(result["checks"]["ios_native"]["job_id"], self.jobs[3]["id"])
        self.assertEqual(list(result["checks"]), self.plan["selected_keys"])
        self.assertEqual(result["controls"], self.plan["controls"])
        self.assertNotIn("approval", result)
        self.assertNotIn("final_job_success", result)
        self.assertNotIn("assertions_attested", result)
        result["controls"]["scripts/trusted_ci.py"] = "2" * 40
        self.assertEqual(self.plan["controls"]["scripts/trusted_ci.py"], "f" * 40)

    def test_real_adapter_plan_and_check_contract_feed_the_manifest_builder(self):
        from scripts import trusted_ci
        from tests.test_trusted_ci import GitFixture

        with tempfile.TemporaryDirectory() as temporary:
            trusted_path = Path(temporary) / "trusted"
            trusted_path.mkdir()
            trusted = GitFixture(trusted_path)
            base = trusted.commit(
                {
                    "scripts/trusted_ci.py": "# synthetic control data, never imported\n",
                    "docs/note.md": "Before\n",
                }
            )
            source_path = Path(temporary) / "source"
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--no-hardlinks",
                    str(trusted_path),
                    str(source_path),
                ],
                check=True,
                capture_output=True,
            )
            source = GitFixture(source_path)
            head = source.commit({"docs/note.md": "After\n"})
            plan = trusted_ci.build_plan(trusted_path, source_path, base, base, head)
            jobs = [
                dict(
                    id=100 + index,
                    run_id=90,
                    head_sha=base,
                    name=trusted_ci.CHECKS[key]["job_name"],
                    status="completed",
                    conclusion="success",
                    steps=[
                        dict(
                            number=number,
                            name=name,
                            status="completed",
                            conclusion="success",
                        )
                        for number, name in enumerate(
                            trusted_ci.CHECKS[key]["required_steps"], 1
                        )
                    ],
                )
                for index, key in enumerate(plan["selected_keys"])
            ]
            result = qa.validation_manifest(
                plan,
                trusted_ci.CHECKS,
                jobs,
                workflow=self.workflow,
                run_id=90,
                run_attempt=1,
            )
            self.assertEqual(result["source_sha"], head)
            self.assertEqual(
                result["source_tree"], source.git("rev-parse", "HEAD^{tree}")
            )
            self.assertEqual(
                result["controls"]["scripts/trusted_ci.py"],
                trusted.git("rev-parse", base + ":scripts/trusted_ci.py"),
            )
            self.assertEqual(list(result["checks"]), plan["selected_keys"])

    def test_selected_jobs_and_required_steps_must_be_unique_completed_and_successful(
        self,
    ):
        for state in ["failure", "skipped", "cancelled", "timed_out", "unknown", None]:
            for target in ["job", "step"]:
                with self.subTest(state=state, target=target):
                    original = deepcopy(self.jobs)
                    row = self.jobs[0] if target == "job" else self.jobs[0]["steps"][0]
                    row["conclusion"] = state
                    with self.assertRaises(ReleaseError):
                        self.build()
                    self.jobs = original
        for mutate in [
            lambda: self.jobs.append(deepcopy(self.jobs[0])),
            lambda: self.jobs.pop(),
            lambda: self.jobs[0]["steps"].append(deepcopy(self.jobs[0]["steps"][0])),
            lambda: self.jobs[0]["steps"].reverse(),
            lambda: self.jobs[0].update(run_id=91),
            lambda: self.jobs[0].update(head_sha=SOURCE),
            lambda: self.jobs[0].update(status="in_progress"),
            lambda: self.jobs[0].update(id=True),
        ]:
            original = deepcopy(self.jobs)
            mutate()
            with self.assertRaises(ReleaseError):
                self.build()
            self.jobs = original

    def test_plan_cannot_omit_native_minimum_or_redefine_a_required_control(self):
        for mutate in [
            lambda: self.plan["selected_keys"].remove("ios_native"),
            lambda: self.plan["selected_keys"].reverse(),
            lambda: self.plan["checks"].pop("ios_build"),
            lambda: self.plan["checks"]["ios_native"].update(required_steps=[]),
            lambda: self.plan["components"].update(ios=False),
            lambda: self.plan["components"].update(desktop=1),
            lambda: self.plan.update(kind="candidate-report"),
            lambda: self.plan.update(approval=True),
            lambda: self.plan["controls"].update({"../other.py": "f" * 40}),
            lambda: self.plan["controls"].update({"scripts/other.py": None}),
        ]:
            original = deepcopy(self.plan)
            # Copy the nested contract values so mutation is limited to the plan.
            self.plan = deepcopy(self.plan)
            mutate()
            with self.assertRaises(ReleaseError):
                self.build()
            self.plan = original


class ValidationTransportTests(unittest.TestCase):
    """The consumer authenticates API observations before reading a receipt."""

    @classmethod
    def setUpClass(cls):
        from scripts import trusted_ci
        from tests.test_trusted_ci import GitFixture

        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.repo = GitFixture(cls.root)
        cls.repo.git("config", "core.autocrlf", "false")
        cls.repo.git("config", "core.eol", "lf")
        paths = [
            QA_PATH,
            ".github/workflows/ci.yml",
            ".github/workflows/ios-validation.yml",
            ".github/workflows/server-validation.yml",
            ".github/workflows/dependency-audit.yml",
            ".github/actions/settings-build/action.yml",
            "scripts/testflight_qa.py",
            "scripts/trusted_ci.py",
            "scripts/release_delivery.py",
            "scripts/delivery_policy.py",
            "pyproject.toml",
        ]
        cls.base = cls.repo.commit(
            {path: (ROOT / path).read_text(encoding="utf-8") for path in paths}
            | {
                "mobile/app.json": json.dumps(app()),
                "shared/computer_connect.json": json.dumps(
                    dict(schema_version=1, relay_host=None, relay_port=8765)
                ),
                "docs/note.md": "Before",
            }
        )
        cls.source = cls.repo.commit({"docs/note.md": "After"})
        cls.repo.git("checkout", "--quiet", cls.base)
        cls.git_cache = staticmethod(lru_cache(maxsize=128)(trusted_ci.git))
        cls.trees = {
            revision: cls.repo.git("rev-parse", revision + "^{tree}")
            for revision in (cls.base, cls.source)
        }
        cls.plan = trusted_ci.build_plan(
            cls.root, cls.root, cls.base, cls.base, cls.source
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        from scripts import trusted_ci

        cache = patch.object(trusted_ci, "git", side_effect=self.git_cache)
        cache.start()
        self.addCleanup(cache.stop)
        self.inputs = dict(
            source_sha=self.source, base_sha=self.base, trusted_sha=self.base
        )
        self.ctx = context() | dict(
            mode="validate",
            workflow_sha=self.base,
            checkout_sha=self.base,
            sha=self.base,
        )
        self.run = dict(
            id=90,
            run_attempt=1,
            workflow_id=99,
            path=QA_PATH,
            head_sha=self.base,
            head_branch="main",
            event="workflow_dispatch",
            status="completed",
            conclusion="success",
            repository=dict(full_name=REPO),
            head_repository=dict(full_name=REPO),
            referenced_workflows=[
                dict(
                    path=f"{REPO}/{path}@refs/heads/main",
                    sha=self.base,
                    ref="refs/heads/main",
                )
                for path in [
                    ".github/workflows/ci.yml",
                    ".github/workflows/ios-validation.yml",
                ]
            ],
        )
        self.jobs = [
            dict(
                id=1000 + index,
                run_id=90,
                run_attempt=1,
                head_sha=self.base,
                name=trusted_ci.CHECKS[key]["job_name"],
                status="completed",
                conclusion="success",
                steps=[
                    dict(number=n, name=name, status="completed", conclusion="success")
                    for n, name in enumerate(
                        trusted_ci.CHECKS[key]["required_steps"], 1
                    )
                ],
            )
            for index, key in enumerate(self.plan["selected_keys"])
        ]
        self.final = dict(
            id=2000,
            run_id=90,
            run_attempt=1,
            head_sha=self.base,
            name="Finalize trusted validation",
            status="completed",
            conclusion="success",
            steps=[
                dict(
                    number=8,
                    name="Upload trusted validation manifest",
                    status="completed",
                    conclusion="success",
                ),
                dict(
                    number=11,
                    name="Record trusted validation artifact",
                    status="completed",
                    conclusion="success",
                ),
            ],
        )
        self.api = self
        self.calls = []
        self.manifest = None
        self.blob = b""
        self.log = b""
        self.artifact = {}

    def request(self, method, path, *args, **kwargs):
        self.calls.append((method, path))
        if path == "/git/ref/heads/main":
            return {"object": {"sha": self.base}}
        if path == "/pulls/179":
            return dict(
                number=179,
                state="open",
                draft=False,
                merged=False,
                mergeable=True,
                head=dict(sha=self.source, ref="preview", repo=dict(full_name=REPO)),
                base=dict(sha=self.base, ref="main", repo=dict(full_name=REPO)),
            )
        if path.startswith("/collaborators/"):
            return dict(role_name="maintain", permission="write")
        if path.startswith("/compare/"):
            return dict(status="ahead", merge_base_commit=dict(sha=self.base))
        if path.startswith("/git/commits/"):
            revision = path.rsplit("/", 1)[1]
            return dict(sha=revision, tree=dict(sha=self.trees[revision]))
        if path.startswith("/actions/workflows/"):
            return dict(id=99, path=QA_PATH)
        if path == "/actions/runs/90/attempts/1":
            return self.run
        if path == "/actions/artifacts/101":
            return self.artifact
        raise AssertionError(path)

    def file(self, path, ref, **kwargs):
        return self.git_cache(self.root, "show", ref + ":" + path).decode().strip()

    def pages(self, path, key=None):
        self.calls.append(("PAGES", path))
        self.assertEqual(path, "/actions/runs/90/attempts/1/jobs")
        self.assertEqual(key, "jobs")
        return self.jobs + [self.final]

    def binary(self, path, *, limit):
        self.calls.append(("BINARY", path))
        value = self.log if path == "/actions/jobs/2000/logs" else self.blob
        self.assertIn(path, {"/actions/jobs/2000/logs", "/actions/artifacts/101/zip"})
        if len(value) > limit:
            raise ReleaseError("Download exceeds limit")
        return value

    def finalize(self):
        return qa.finalize_validation(
            self.api, self.inputs, self.ctx, trusted_repo=self.root
        )

    def prepare_artifact(self, entries=None):
        self.manifest = self.finalize()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in entries or [
                ("validation.json", qa.canonical_validation_json(self.manifest))
            ]:
                archive.writestr(name, data)
        self.blob = stream.getvalue()
        digest = hashlib.sha256(self.blob).hexdigest()
        self.artifact = dict(
            id=101,
            name="clarify-qa-validation-90-1",
            digest="sha256:" + digest,
            expired=False,
            workflow_run=dict(
                id=90, head_sha=self.base, repository_id=1, head_repository_id=1
            ),
        )
        self.log = qa.format_validation_artifact_record(
            artifact_id=101, artifact_digest=digest, run_id=90, run_attempt=1
        ).encode()
        self.calls = []

    def consume(self):
        return qa.consume_validation(
            self.api, self.inputs, self.ctx, trusted_repo=self.root
        )

    def test_final_recomputes_main_plan_and_consumer_binds_final_job_log(self):
        self.prepare_artifact()
        self.assertEqual(self.consume(), self.manifest)
        self.assertEqual(
            [p for method, p in self.calls if method == "BINARY"],
            ["/actions/jobs/2000/logs", "/actions/artifacts/101/zip"],
        )
        self.assertEqual(self.manifest["source_sha"], self.source)
        self.assertNotIn("final_job_success", self.manifest)

    def test_api_origin_composition_graph_and_current_pr_fail_closed(self):
        self.prepare_artifact()
        mutations = [
            lambda: self.run.update(head_sha=self.source),
            lambda: self.run.update(run_attempt=2),
            lambda: self.run.update(id=91),
            lambda: self.run.update(path=".github/workflows/ci.yml"),
            lambda: self.run.update(workflow_id=98),
            lambda: self.run.update(event="pull_request"),
            lambda: self.run.update(head_repository=dict(full_name="foreign/repo")),
            lambda: self.run.update(workflow_sha=self.source),
            lambda: self.run["referenced_workflows"][0].update(sha=self.source),
            lambda: self.run["referenced_workflows"][0].update(
                path="foreign/repo/ci.yml@main"
            ),
            lambda: self.run.update(referenced_workflows=[]),
            lambda: self.run["referenced_workflows"].append(
                deepcopy(self.run["referenced_workflows"][0])
            ),
        ]
        original = deepcopy(self.run)
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                mutate()
                with self.assertRaises(ReleaseError):
                    self.consume()
                self.run = deepcopy(original)
        for change in [
            dict(source_sha=BASE),
            dict(base_sha=SOURCE),
            dict(trusted_sha=SOURCE),
        ]:
            with self.subTest(change=change), self.assertRaises(ReleaseError):
                qa.finalize_validation(
                    self.api, self.inputs | change, self.ctx, trusted_repo=self.root
                )
        with patch.object(self, "request", wraps=self.request) as request:
            original_request = request._mock_wraps
            request.side_effect = lambda method, path, *a, **kw: (
                original_request(method, path) | {"draft": True}
                if path == "/pulls/179"
                else original_request(method, path, *a, **kw)
            )
            with self.assertRaises(ReleaseError):
                self.consume()

    def test_final_and_required_results_cannot_be_skipped_reordered_or_duplicated(self):
        self.prepare_artifact()
        for state in ["skipped", "failure", "cancelled", "timed_out", "unknown", None]:
            for row in [
                self.run,
                self.final,
                self.final["steps"][0],
                self.jobs[0],
                self.jobs[0]["steps"][0],
            ]:
                with self.subTest(state=state, row=row.get("name")):
                    old = row["conclusion"]
                    row["conclusion"] = state
                    with self.assertRaises(ReleaseError):
                        self.consume()
                    row["conclusion"] = old
        for mutate in [
            lambda: self.jobs.append(deepcopy(self.final)),
            lambda: self.jobs.append(deepcopy(self.jobs[0])),
            lambda: self.final["steps"].reverse(),
            lambda: self.final["steps"].append(deepcopy(self.final["steps"][0])),
            lambda: self.final.update(run_attempt=2),
        ]:
            jobs, final = deepcopy(self.jobs), deepcopy(self.final)
            mutate()
            with self.assertRaises(ReleaseError):
                self.consume()
            self.jobs, self.final = jobs, final

    def test_log_limits_utf8_spoof_and_duplicate_record_block(self):
        self.prepare_artifact()
        original = self.log
        for value in [
            b"x" * (1024 * 1024 + 1),
            b"\xff",
            b"",
            original + b"\n" + original,
            b"echo " + original,
            b"\x1b[32m" + original,
            original.replace(b'"artifact_id":101', b'"artifact_id":"***"'),
        ]:
            with self.subTest(value=value[:40]):
                self.log = value
                with self.assertRaises(ReleaseError):
                    self.consume()

    def test_artifact_binding_and_data_zip_are_strict(self):
        self.prepare_artifact()
        original = deepcopy(self.artifact)
        for change in [
            dict(id=102),
            dict(name="candidate"),
            dict(expired=True),
            dict(digest="sha256:" + "0" * 64),
            dict(workflow_run=dict(id=91, head_sha=self.base)),
            dict(workflow_run=dict(id=90, head_sha=self.source)),
        ]:
            self.artifact = original | change
            with self.subTest(change=change), self.assertRaises(ReleaseError):
                self.consume()
        self.artifact = original
        self.blob += b"tampered"
        with self.assertRaises(ReleaseError):
            self.consume()
        for entries in [
            [("../validation.json", b"{}")],
            [("validation.json", b"{}"), ("extra", b"x")],
            [("validation.json", b"{}"), ("validation.json", b"{}")],
            [("validation.json", b"x" * (256 * 1024))],
        ]:
            self.prepare_artifact(entries)
            with self.assertRaises(ReleaseError):
                self.consume()
        self.prepare_artifact([("validation.json", b'{"schema":1}')])
        with self.assertRaises(ReleaseError):
            self.consume()

    def test_archive_jobs_are_only_allowed_as_skipped_in_validation(self):
        self.prepare_artifact()
        extra = [
            dict(id=3000 + n, name=name, status="completed", conclusion="skipped")
            for n, name in enumerate(sorted(qa.ARCHIVE_JOB_NAMES))
        ]
        self.jobs.extend(extra)
        self.assertEqual(self.consume(), self.manifest)
        extra[0]["conclusion"] = "success"
        with self.assertRaises(ReleaseError):
            self.consume()
        extra[0].update(conclusion="skipped", name="Unknown archive job")
        with self.assertRaises(ReleaseError):
            self.consume()

    def test_final_can_finish_before_its_own_success_but_consumer_cannot(self):
        self.prepare_artifact()
        self.run.update(status="in_progress", conclusion=None)
        self.final.update(status="in_progress", conclusion=None)
        self.assertEqual(self.finalize(), self.manifest)
        with self.assertRaises(ReleaseError):
            self.consume()

    def test_main_controls_trees_identity_and_mutable_checks_remain_required(self):
        self.prepare_artifact()
        original_request = self.request
        for endpoint, replacement in [
            ("/git/ref/heads/main", dict(object=dict(sha=OLD))),
            ("/git/commits/" + self.source, dict(sha=self.source, tree=dict(sha=OLD))),
            ("/actions/workflows/99", dict(id=99, path=".github/workflows/ci.yml")),
            (
                "/collaborators/maintainer/permission",
                dict(permission="write", role_name="write"),
            ),
        ]:
            with (
                self.subTest(endpoint=endpoint),
                patch.object(
                    self,
                    "request",
                    side_effect=lambda method, path, *a, **kw: (
                        replacement
                        if path == endpoint
                        else original_request(method, path, *a, **kw)
                    ),
                ),
                self.assertRaises(ReleaseError),
            ):
                self.consume()
        for path in [
            QA_PATH,
            ".github/actions/settings-build/action.yml",
            "scripts/release_delivery.py",
        ]:
            file = self.root / path
            original = file.read_bytes()
            try:
                file.write_bytes(original + b"\n# changed control\n")
                with (
                    self.subTest(path=path),
                    self.assertRaisesRegex(ReleaseError, "Git blob"),
                ):
                    self.finalize()
            finally:
                file.write_bytes(original)
        original_file = self.file
        with (
            patch.object(
                self,
                "file",
                side_effect=lambda path, ref, **kw: (
                    json.dumps(
                        app()
                        | {
                            "expo": app()["expo"]
                            | {
                                "ios": {
                                    "buildNumber": "8",
                                    "bundleIdentifier": "foreign",
                                }
                            }
                        }
                    )
                    if path == "mobile/app.json"
                    else original_file(path, ref, **kw)
                ),
            ),
            self.assertRaises(ReleaseError),
        ):
            self.finalize()
        # A native floor cannot be removed by an apparently valid report/plan.
        plan = deepcopy(self.plan)
        plan["selected_keys"].remove("ios_native")
        with (
            patch.object(qa.trusted_ci, "build_plan", return_value=plan),
            self.assertRaises(ReleaseError),
        ):
            self.finalize()
        with self.assertRaises(ReleaseError):
            qa.finalize_validation(
                self.api,
                self.inputs,
                self.ctx,
                trusted_repo=self.root,
                outputs=dict(selected_keys="[]"),
            )
        for effect in ["upload", "availability"]:
            self.calls = []
            with self.assertRaises(ReleaseError):
                qa.finalize_validation(
                    self.api,
                    self.inputs,
                    self.ctx | {"mode": effect},
                    trusted_repo=self.root,
                )
            self.assertEqual(self.calls, [])

    def test_symlink_zip_and_unavailable_job_log_have_no_fallback(self):
        entry = zipfile.ZipInfo("validation.json")
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        self.prepare_artifact([(entry, b"target")])
        with self.assertRaisesRegex(ReleaseError, "Unsafe"):
            self.consume()
        self.prepare_artifact()
        with patch.object(
            self, "binary", side_effect=ReleaseError("HTTP 404")
        ) as download:
            with self.assertRaises(ReleaseError):
                self.consume()
            download.assert_called_once_with(
                "/actions/jobs/2000/logs", limit=1024 * 1024
            )

    def test_candidate_workflow_is_not_authority_and_self_claimed_manifest_is_rejected(
        self,
    ):
        original_file = self.file
        with patch.object(
            self,
            "file",
            side_effect=lambda path, ref, **kw: (
                "candidate CI differs and is never executed"
                if ref == self.source and path.startswith(".github/")
                else original_file(path, ref, **kw)
            ),
        ):
            manifest = self.finalize()
        for key, value in [
            ("source_tree", OLD),
            ("controls", {"scripts/trusted_ci.py": OLD}),
            (
                "checks",
                {
                    key: item
                    for key, item in manifest["checks"].items()
                    if key != "ios_native"
                },
            ),
        ]:
            altered = manifest | {key: value}
            self.prepare_artifact(
                [("validation.json", qa.canonical_validation_json(altered))]
            )
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ReleaseError, "MAIN/API"),
            ):
                self.consume()


class ValidationRuntimeTests(unittest.TestCase):
    def test_dispatch_event_and_runtime_are_authority_and_record_uses_upload_outputs(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            event = Path(temporary) / "event.json"
            inputs = dict(
                mode="validate", source_sha=SOURCE, base_sha=BASE, trusted_sha=BASE
            )
            event.write_text(json.dumps(dict(inputs=inputs)), encoding="utf-8")
            env = dict(
                GITHUB_EVENT_PATH=str(event),
                GITHUB_REPOSITORY=REPO,
                GITHUB_EVENT_NAME="workflow_dispatch",
                GITHUB_REF="refs/heads/main",
                GITHUB_SHA=BASE,
                GITHUB_WORKFLOW_SHA=BASE,
                GITHUB_WORKFLOW_REF=f"{REPO}/{QA_PATH}@refs/heads/main",
                GITHUB_ACTOR="maintainer",
                GITHUB_TRIGGERING_ACTOR="maintainer",
                GITHUB_RUN_ID="90",
                GITHUB_RUN_ATTEMPT="1",
                QA_CANDIDATE='{"command":"untrusted"}',
                QA_SOURCE_SHA=OLD,
                QA_WORKFLOW_SHA=OLD,
                QA_UPLOAD_ARTIFACT_ID="101",
                QA_UPLOAD_ARTIFACT_DIGEST="d" * 64,
            )
            output = io.StringIO()
            with (
                patch.dict(os.environ, env, clear=True),
                patch.object(qa.subprocess, "run", return_value=Mock(stdout=BASE)),
                patch.object(qa, "ValidationGitHub") as api,
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(qa.main(["record"]), 0)
                api.assert_not_called()
            self.assertEqual(
                qa.parse_validation_artifact_record(
                    output.getvalue(), run_id=90, run_attempt=1
                )["artifact_id"],
                101,
            )
            output = io.StringIO()
            with (
                patch.dict(os.environ, env, clear=True),
                patch.object(qa.subprocess, "run", return_value=Mock(stdout=BASE)),
                patch.object(qa, "ValidationGitHub"),
                patch.object(qa, "_validation_origin") as origin,
                patch.object(qa, "_validation_current_source"),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(qa.main(["validate"]), 0)
                self.assertEqual(
                    origin.call_args.args[1],
                    dict(source_sha=SOURCE, base_sha=BASE, trusted_sha=BASE),
                )
                self.assertEqual(origin.call_args.args[2]["workflow_sha"], BASE)
            self.assertEqual(
                json.loads(output.getvalue()),
                dict(apple_enabled=False, validation_enabled=True),
            )
            inputs["source_sha"] = "a" * 39
            event.write_text(json.dumps(dict(inputs=inputs)), encoding="utf-8")
            with (
                patch.dict(os.environ, env, clear=True),
                self.assertRaises(ReleaseError),
            ):
                qa._runtime_validation_inputs(context())

    def test_binary_redirects_are_bounded_https_and_never_forward_credentials(self):
        headers = Message()
        headers["Location"] = "https://artifacts.example.invalid/blob?private=signed"
        response = io.BytesIO(b"log data")
        response.status = 200
        opener = Mock()
        opener.open.side_effect = [
            HTTPError("https://api.github.com", 302, "redirect", headers, None),
            response,
        ]
        with patch.object(qa, "build_opener", return_value=opener):
            self.assertEqual(
                qa.ValidationGitHub("private-token").binary(
                    "/actions/jobs/2000/logs", limit=20
                ),
                b"log data",
            )
        requests = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual(
            requests[0].get_header("Authorization"), "Bearer private-token"
        )
        self.assertIsNone(requests[1].get_header("Authorization"))
        for location in [
            "http://artifacts.example.invalid/file",
            "https://user:password@example.invalid/file",
        ]:
            headers.replace_header("Location", location)
            opener.open.reset_mock(side_effect=True)
            opener.open.side_effect = [
                HTTPError("https://api.github.com", 302, "redirect", headers, None)
            ]
            with (
                patch.object(qa, "build_opener", return_value=opener),
                self.assertRaises(ReleaseError),
            ):
                qa.ValidationGitHub("private-token").binary(
                    "/actions/jobs/2000/logs", limit=20
                )
            self.assertEqual(opener.open.call_count, 1)
        for status in [404, 403, 500]:
            opener.open.side_effect = HTTPError(
                "https://private.invalid/signed", status, "private", Message(), None
            )
            with (
                patch.object(qa, "build_opener", return_value=opener),
                self.assertRaises(ReleaseError) as failure,
            ):
                qa.ValidationGitHub("private-token").binary(
                    "/actions/jobs/2000/logs", limit=20
                )
            self.assertNotIn("private", str(failure.exception))
        headers.replace_header("Location", "https://artifacts.example.invalid/file")
        opener.open.reset_mock(side_effect=True)
        opener.open.side_effect = [
            HTTPError("https://api.github.com", 302, "redirect", headers, None)
            for _ in range(4)
        ]
        with (
            patch.object(qa, "build_opener", return_value=opener),
            self.assertRaises(ReleaseError),
        ):
            qa.ValidationGitHub("private-token").binary(
                "/actions/jobs/2000/logs", limit=20
            )
        self.assertEqual(opener.open.call_count, 4)


class MaterializedHelperTests(unittest.TestCase):
    """Run helper oracles from the Git-free layout used by trusted recipes."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for relative in (
            "tests/test_ios_qa_helpers.py",
            "mobile/tests/testflight-qa.test.ts",
            "mobile/scripts/verify-ios-ipa.py",
            "mobile/scripts/publish-testflight.cjs",
            "mobile/app.json",
            "mobile/eas.json",
            "mobile/third-party/KeyboardHostBundleID/LICENSE",
        ):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC"}
        }
        self.environment.update(
            HOME=str(self.root),
            USERPROFILE=str(self.root),
            APPDATA=str(self.root / "appdata"),
            LOCALAPPDATA=str(self.root / "localappdata"),
            TMP=str(self.root),
            TEMP=str(self.root),
            GIT_CEILING_DIRECTORIES=str(self.root.parent),
            PYTHONDONTWRITEBYTECODE="1",
        )
        self.assertFalse((self.root / ".git").exists())

    def run_oracles(self, command, *, cwd):
        result = subprocess.run(
            command,
            cwd=cwd,
            env=self.environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_python_helper_oracles_run_without_git_metadata(self):
        self.run_oracles(
            [
                sys.executable,
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_ios_qa_helpers.py",
                "-v",
            ],
            cwd=self.root,
        )

    @unittest.skipUnless(shutil.which("node"), "Node is required for mobile oracles")
    def test_mobile_helper_oracles_run_without_git_metadata(self):
        self.run_oracles(
            [
                shutil.which("node"),
                "--experimental-strip-types",
                "--test",
                "tests/testflight-qa.test.ts",
            ],
            cwd=self.root / "mobile",
        )


class DeviceArchiveGlueTests(unittest.TestCase):
    """Caller effects use stubs; archive inspection remains in its own suite."""

    def setUp(self):
        # Keep real path guards active without inheriting /tmp's sticky bit.
        self.temporary = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parent
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.inputs = dict(source_sha=SOURCE, base_sha=BASE, trusted_sha=BASE)
        self.ctx = context() | {"mode": "archive"}
        self.candidate = metadata()
        del self.candidate["reservation"]
        self.api = Mock()
        self.api.file.return_value = json.dumps(app())
        self.api.request.return_value = dict(object=dict(type="commit", sha=SOURCE))
        self.plan = self.inputs | dict(source_tree="1" * 40, base_tree="2" * 40)
        self.workflow = dict(id=99, path=QA_PATH, blob_sha="3" * 40)
        self.toolchain = dict(xcode_build="26F123", sdk_version="26.6")

    def test_archive_identity_does_not_require_history_or_reserve_a_build(self):
        self.assertEqual(
            qa.archive_identity(self.api, self.candidate, self.inputs),
            self.candidate,
        )
        self.api.pages.assert_not_called()
        for key, value in (
            ("source_sha", OLD),
            ("base_sha", OLD),
            ("build", "9"),
            ("tag", "ios/pr-179/v1.2.3-build9"),
            ("relay_host", "host"),
            ("reservation", {}),
            ("endpoint", "https://example.invalid"),
        ):
            with self.subTest(key=key), self.assertRaises(ReleaseError):
                qa.archive_identity(
                    self.api, self.candidate | {key: value}, self.inputs
                )

    def test_policy_uses_main_controls_observed_toolchain_and_exact_validation(self):
        from scripts import qa_device_archive as archive

        controls = {
            path: archive.git_blob(path.encode())
            for path in (QA_PATH, archive.MODULE, archive.SIGNING_HELPER)
        }
        self.workflow["blob_sha"] = controls[QA_PATH]
        main_app = app()
        main_app["expo"]["ios"]["infoPlist"] = {
            "ClarifyCloudURL": "https://clarify-api.victormaynard.com"
        }
        self.api.control.side_effect = lambda sha, path: (
            json.dumps(main_app).encode()
            if path == "mobile/app.json"
            else path.encode()
        )
        inputs = self.inputs | dict(
            candidate=self.candidate,
            validation_run_id=80,
            validation_run_attempt=2,
            producer_run_id=90,
            producer_run_attempt=1,
        )
        with (
            patch.object(
                qa, "_validation_origin", return_value=(self.plan, {}, self.workflow)
            ),
            patch.object(qa, "consume_validation") as consume,
            patch.object(qa, "archive_controls", return_value=controls),
            patch.object(qa, "archive_identity", return_value=self.candidate),
            patch.object(qa, "_validation_current_source"),
        ):
            result = qa.archive_policy(
                self.api, inputs, self.ctx, self.toolchain, trusted_repo=self.root
            )
        result.validate()
        self.assertEqual(result.context["recipe"]["configuration"], "Release")
        self.assertEqual(result.context["recipe"]["xcode_build"], "26F123")
        self.assertEqual(result.context["producer"]["run_id"], 90)
        self.assertEqual(result.context["controls"], controls)
        self.assertEqual(consume.call_args.args[2]["run_id"], 80)
        self.assertEqual(consume.call_args.args[2]["run_attempt"], 2)
        self.assertNotIn("reservation", result.context)

    def test_runtime_modes_ids_and_composition_are_strict(self):
        event = self.root / "event.json"
        values = self.inputs | dict(
            mode="archive",
            candidate=json.dumps(self.candidate),
            validation_run_id="80",
            validation_run_attempt="2",
        )
        with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event)}):
            for delta in (
                {},
                {"mode": "upload"},
                {"trusted_sha": OLD},
                {"validation_run_id": "0"},
                {"validation_run_attempt": "101"},
                {"producer_run_id": "90"},
                {"extra": "value"},
            ):
                event.write_text(json.dumps(dict(inputs=values | delta)))
                if delta:
                    with self.subTest(delta=delta), self.assertRaises(ReleaseError):
                        qa._runtime_archive_inputs(self.ctx, "archive")
                else:
                    result = qa._runtime_archive_inputs(self.ctx, "archive")
                    self.assertEqual(result["producer_run_id"], 90)
                    self.assertEqual(result["validation_run_attempt"], 2)
            values.update(
                mode="sign-export-proof",
                producer_run_id="81",
                producer_run_attempt="1",
                archive_artifact_id="101",
            )
            event.write_text(json.dumps(dict(inputs=values)))
            self.assertEqual(
                qa._runtime_archive_inputs(self.ctx, "sign-export-proof")[
                    "archive_artifact_id"
                ],
                101,
            )
            values["producer_run_id"] = "90"
            event.write_text(json.dumps(dict(inputs=values)))
            with self.assertRaises(ReleaseError):
                qa._runtime_archive_inputs(self.ctx, "sign-export-proof")

    def test_producer_uses_adapter_and_device_release_then_verifies_before_pack(self):
        job = Mock()
        job.execution = self.root / "execution"
        job.metadata = self.root / "metadata"
        policy = Mock(context={"producer": {"run_id": 90}})
        calls = Mock()
        calls.attach_mock(job, "job")
        with patch.object(qa.device_archive, "pack") as pack:
            calls.attach_mock(pack, "pack")
            qa.produce_archive(job, policy, self.root / "artifact")
        args = job.command.call_args.args[0]
        self.assertIn("Release", args)
        self.assertIn("iphoneos", args)
        self.assertIn("generic/platform=iOS", args)
        self.assertIn("ARCHS=arm64", args)
        self.assertIn("CODE_SIGNING_ALLOWED=NO", args)
        self.assertEqual(args[-1], "archive")
        self.assertNotIn("Simulator", " ".join(map(str, args)))
        names = [c[0] for c in calls.mock_calls]
        self.assertLess(names.index("job.verify_source"), names.index("pack"))
        self.assertLess(names.index("job.verify_controls"), names.index("pack"))
        job.command.side_effect = RuntimeError("inert candidate failure")
        job.reset_mock()
        with patch.object(qa.device_archive, "pack") as pack:
            with self.assertRaises(RuntimeError):
                qa.produce_archive(job, policy, self.root / "failed-artifact")
            job.verify_source.assert_called_once()
            job.verify_controls.assert_called_once()
            pack.assert_not_called()

    def test_recorder_authenticates_producer_and_api_without_downloading(self):
        policy = Mock()
        policy.context = dict(
            source_sha=SOURCE,
            trusted_sha=BASE,
            producer=dict(run_id=90, run_attempt=1, job_key="archive"),
            workflow=dict(id=99),
        )
        policy.producer_job_name = qa.ARCHIVE_JOB_NAME
        policy.producer_steps = qa.ARCHIVE_STEPS
        policy.final_job_name = qa.ARCHIVE_FINAL_JOB_NAME
        self.api.run.return_value = dict(
            id=90,
            run_attempt=1,
            workflow_id=99,
            path=QA_PATH,
            head_sha=BASE,
            head_branch="main",
            event="workflow_dispatch",
            status="in_progress",
            conclusion=None,
            repository=dict(full_name=REPO),
        )
        producer = dict(
            id=201,
            name=qa.ARCHIVE_JOB_NAME,
            run_id=90,
            head_sha=BASE,
            status="completed",
            conclusion="success",
            steps=[
                dict(name=n, status="completed", conclusion="success")
                for n in qa.ARCHIVE_STEPS
            ],
        )
        final = dict(
            id=202,
            name=qa.ARCHIVE_FINAL_JOB_NAME,
            run_id=90,
            head_sha=BASE,
            status="in_progress",
            conclusion=None,
        )
        self.api.jobs.return_value = dict(
            run_id=90, run_attempt=1, jobs=[producer, final]
        )
        self.api.artifact.return_value = dict(
            id=101,
            name="clarify-ios-qa-unsigned-" + SOURCE,
            digest="sha256:" + "d" * 64,
            expired=False,
            size_in_bytes=100,
            workflow_run=dict(id=90, head_sha=BASE),
        )
        line = qa.record_archive(self.api, policy, 101, "d" * 64)
        self.assertEqual(
            qa.device_archive.parse_artifact_record(
                line, source_sha=SOURCE, run_id=90, run_attempt=1
            )["artifact_id"],
            101,
        )
        self.api.download_artifact.assert_not_called()
        self.api.job_log.assert_not_called()
        for target, key, bad in (
            (self.api.run.return_value, "run_attempt", 2),
            (self.api.artifact.return_value, "name", "clarify-ios-qa-unsigned-" + OLD),
            (self.api.artifact.return_value, "digest", "sha256:" + "e" * 64),
            (self.api.jobs.return_value, "run_id", 91),
            (final, "id", 201),
        ):
            previous = target[key]
            target[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                qa.record_archive(self.api, policy, 101, "d" * 64)
            target[key] = previous

    def test_stream_download_is_bounded_and_redirect_drops_token(self):
        headers = Message()
        headers.add_header("Location", "https://artifact.example/opaque")
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.side_effect = [b"1234", b"5", b""]
        opener = Mock()
        opener.open.side_effect = [
            HTTPError("https://api.github.com", 302, "redirect", headers, None),
            response,
        ]
        api = qa.ArchiveGitHub("inert", trusted_repo=self.root)
        with patch.object(qa, "build_opener", return_value=opener):
            target = self.root / "artifact.zip"
            with self.assertRaises(ReleaseError):
                api.download_artifact(101, target, max_bytes=4)
        self.assertFalse(target.exists())
        self.assertIsNotNone(
            opener.open.call_args_list[0].args[0].get_header("Authorization")
        )
        self.assertIsNone(
            opener.open.call_args_list[1].args[0].get_header("Authorization")
        )
        self.assertTrue(
            all(c.args[0] <= 1024 * 1024 for c in response.read.call_args_list)
        )

    def test_signer_delegates_to_existing_boundary_and_discards_private_workspace(self):
        inputs = self.inputs | dict(archive_artifact_id=101)
        workspace = self.root / "private"
        workspace.mkdir()
        receipt = dict(
            delivery_eligible=False, workflowArtifactProvenanceVerified=False
        )
        with (
            patch.object(qa, "ROOT", self.root / "trusted"),
            patch.dict(
                os.environ, {"GH_TOKEN": "inert", "RUNNER_TEMP": str(self.root)}
            ),
            patch.object(qa, "ArchiveGitHub", return_value=self.api),
            patch.object(qa, "observe_archive_toolchain", return_value=self.toolchain),
            patch.object(qa, "archive_policy", return_value="MAIN policy") as policy,
            patch.object(
                qa.device_archive,
                "sign_export",
                return_value=dict(workspace=workspace, receipt=receipt),
            ) as export,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            qa.run_archive_command("sign-export-proof", inputs, self.ctx)
            self.assertEqual(export.call_args.kwargs["artifact_id"], 101)
            self.assertEqual(export.call_args.kwargs["policy"], "MAIN policy")
            self.assertFalse(workspace.exists())
            self.assertEqual(
                json.loads(
                    (self.root / "archive-proof/archive-receipt.json").read_bytes()
                ),
                receipt,
            )
            export.reset_mock()
            policy.side_effect = ReleaseError("Wrong validation source/run/attempt")
            with self.assertRaises(ReleaseError):
                qa.run_archive_command("sign-export-proof", inputs, self.ctx)
            export.assert_not_called()

    def test_main_control_cache_returns_raw_git_bytes_after_api_tree_binding(self):
        data = b"MAIN bytes\n"
        path = self.root / "scripts/qa_device_archive.py"
        path.parent.mkdir()
        path.write_bytes(data)
        blob = qa.device_archive.git_blob(data)
        api = qa.ArchiveGitHub("inert", trusted_repo=self.root)
        with (
            patch.object(
                qa.trusted_ci, "git", side_effect=[BASE.encode(), ("1" * 40).encode()]
            ),
            patch.object(
                qa.trusted_ci,
                "git_tree",
                return_value={
                    "scripts/qa_device_archive.py": dict(blob=blob, mode="100644")
                },
            ),
            patch.object(
                qa.trusted_ci, "git_blobs", return_value={blob: data}
            ) as blobs,
            patch.object(
                qa,
                "archive_controls",
                return_value={"scripts/qa_device_archive.py": blob},
            ),
            patch.object(
                api, "commit", return_value=dict(sha=BASE, tree=dict(sha="1" * 40))
            ) as commit,
        ):
            self.assertEqual(api.control(BASE, "scripts/qa_device_archive.py"), data)
            self.assertEqual(api.control(BASE, "scripts/qa_device_archive.py"), data)
            blobs.assert_called_once()
            commit.assert_called_once_with(BASE)
            with self.assertRaises(ReleaseError):
                api.control(BASE, "candidate.py")
            api._controls.clear()
        with (
            patch.object(
                qa.trusted_ci, "git", side_effect=[BASE.encode(), ("1" * 40).encode()]
            ),
            patch.object(
                api, "commit", return_value=dict(sha=BASE, tree=dict(sha="2" * 40))
            ),
            patch.object(qa.trusted_ci, "git_blobs") as blobs,
            self.assertRaises(ReleaseError),
        ):
            api.control(BASE, "scripts/qa_device_archive.py")
        blobs.assert_not_called()

    def test_jobs_expose_only_the_successful_final_log(self):
        api = qa.ArchiveGitHub("inert", trusted_repo=self.root)
        jobs = [
            dict(
                id=201,
                name=qa.ARCHIVE_JOB_NAME,
                run_id=90,
                status="completed",
                conclusion="success",
            ),
            dict(
                id=202,
                name=qa.ARCHIVE_FINAL_JOB_NAME,
                run_id=90,
                status="completed",
                conclusion="success",
            ),
        ]
        with (
            patch.object(api, "pages", return_value=jobs),
            patch.object(api, "binary", return_value=b"final log") as binary,
        ):
            self.assertEqual(api.jobs(90, 1)["run_attempt"], 1)
            self.assertEqual(api.job_log(202), b"final log")
            with self.assertRaises(ReleaseError):
                api.job_log(201)
            binary.assert_called_once()
            for name, conclusion in (
                ("Unknown job", "skipped"),
                (qa.ARCHIVE_SIGN_JOB_NAME, "success"),
            ):
                jobs.append(
                    dict(id=203, name=name, status="completed", conclusion=conclusion)
                )
                with self.subTest(name=name), self.assertRaises(ReleaseError):
                    api.jobs(90, 1)
                jobs.pop()

    def test_yaml_parser_rejects_duplicate_keys_aliases_and_tags(self):
        # CI uses MAIN's dependency; local checks can use a read-only test copy.
        node = os.environ.get("CLARIFY_QA_TEST_NODE") or shutil.which("node")
        library = Path(
            os.environ.get(
                "CLARIFY_QA_TEST_YAML_MODULE", ROOT / "desktop/node_modules/yaml"
            )
        )
        if not node or not library.is_dir():
            self.skipTest("MAIN locked YAML dependency is not installed")

        def parse(data):
            return qa.safe_workflow_document(
                data, trusted_repo=self.root, node=node, yaml_module=library
            )

        self.assertEqual(
            parse(b"on: workflow_dispatch\njobs: {}\n"),
            {"on": "workflow_dispatch", "jobs": {}},
        )
        for data in (
            b"jobs: {}\njobs: {}\n",
            b"jobs: &a {}\nx: *a\n",
            b"jobs: !unsafe {}\n",
            b"jobs: !!map {}\n",
            b"jobs: {}\n---\njobs: {}\n",
        ):
            with self.subTest(data=data), self.assertRaises(ReleaseError):
                parse(data)


class DeviceExecutableDataTests(unittest.TestCase):
    """Synthetic Mach-O headers prove data checks, not compilation or signing."""

    @staticmethod
    def executable(platform=2, *, extra=(), cpu=0x0100000C, subtype=0, kind=2):
        commands = [struct.pack("<6I", 0x32, 24, platform, 0x100400, 0x1A0000, 0)]
        commands.extend(extra)
        table = b"".join(commands)
        return (
            struct.pack(
                "<8I", 0xFEEDFACF, cpu, subtype, kind, len(commands), len(table), 0, 0
            )
            + table
        )

    def test_device_arm64_is_distinct_from_simulator_and_catalyst(self):
        report = qa.inspect_unsigned_device_executable(self.executable())
        self.assertEqual(
            report,
            {
                "architecture": "arm64",
                "platform": "ios-device",
                "embedded_entitlements": None,
            },
        )
        for platform in [1, 6, 7, 8, 0, 999]:
            with (
                self.subTest(platform=platform),
                self.assertRaisesRegex(ReleaseError, "iOS device platform"),
            ):
                qa.inspect_unsigned_device_executable(self.executable(platform))

    def test_unknown_architecture_file_kind_signature_or_ambiguous_platform_blocks(
        self,
    ):
        inputs = [
            self.executable(cpu=0x01000007),
            self.executable(subtype=2),
            self.executable(kind=6),
            self.executable(extra=[struct.pack("<4I", 0x1D, 16, 100, 40)]),
            self.executable(extra=[struct.pack("<6I", 0x32, 24, 2, 0, 0, 0)]),
            self.executable(extra=[struct.pack("<4I", 0x25, 16, 0x100400, 0x1A0000)]),
            struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 2, 0, 0, 0, 0),
            b"\xca\xfe\xba\xbe" + bytes(60),
        ]
        for data in inputs:
            with self.subTest(header=data[:32]), self.assertRaises(ReleaseError):
                qa.inspect_unsigned_device_executable(data)

    def test_bounded_load_commands_reject_truncation_and_invalid_lengths(self):
        good = self.executable()
        malformed = [
            b"",
            good[:31],
            good[:-1],
            good[:16] + struct.pack("<I", 4097) + good[20:],
            good[:20] + struct.pack("<I", 16 * 1024**2 + 8) + good[24:],
            good[:36] + struct.pack("<I", 0) + good[40:],
            good[:36] + struct.pack("<I", 20) + good[40:],
            good[:-4] + struct.pack("<I", 1),
        ]
        for data in malformed:
            with self.subTest(length=len(data)), self.assertRaises(ReleaseError):
                qa.inspect_unsigned_device_executable(data)


if __name__ == "__main__":
    unittest.main()
