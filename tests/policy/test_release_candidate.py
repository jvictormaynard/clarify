"""Candidate boundaries use disposable files and fake GitHub state only."""

from copy import deepcopy
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from urllib.error import HTTPError

from scripts import release_candidate as candidate
from scripts.release_delivery import ReleaseError

SOURCE = "a" * 40


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = self.root / "assets"
        self.files.mkdir()
        self.identity = candidate.identity(
            SOURCE, "refs/heads/topic", 123, 1, "preview", "1.2.3"
        )
        for name in candidate.allowed_assets("preview"):
            (self.files / name).write_bytes(name.encode())
        self.manifest = candidate.seal(self.files, self.root / "bundle", self.identity)

    def archive(self, directory=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for path in (directory or self.root / "bundle").iterdir():
                archive.writestr(path.name, path.read_bytes())
        return stream.getvalue()

    def test_manifest_binds_final_identity_and_every_allowed_asset(self):
        self.assertEqual(self.manifest["source_sha"], SOURCE)
        self.assertEqual(self.manifest["run_attempt"], 1)
        self.assertEqual(
            set(self.manifest["assets"]), candidate.allowed_assets("preview")
        )
        self.assertNotIn("Clarify-portable-update.json", self.manifest["assets"])
        self.assertEqual(self.manifest["tag"], "preview/123-1-aaaaaaaaaaaa")
        for name, record in self.manifest["assets"].items():
            self.assertEqual(
                record,
                {
                    "sha256": hashlib.sha256(name.encode()).hexdigest(),
                    "size": len(name),
                },
            )
        candidate.verify_directory(self.root / "bundle", self.identity)

    def test_changed_extra_missing_or_symlinked_inputs_are_rejected(self):
        bundle = self.root / "bundle"
        (bundle / "Clarify.exe").write_bytes(b"replaced")
        with self.assertRaises(ReleaseError):
            candidate.verify_directory(bundle, self.identity)
        (bundle / "Clarify.exe").write_bytes(b"Clarify.exe")
        (bundle / "extra.txt").write_text("extra")
        with self.assertRaises(ReleaseError):
            candidate.verify_directory(bundle, self.identity)
        (bundle / "extra.txt").unlink()
        (bundle / "Clarify.exe").unlink()
        with self.assertRaises(ReleaseError):
            candidate.verify_directory(bundle, self.identity)
        with patch("pathlib.Path.is_symlink", return_value=True):
            with self.assertRaises(ReleaseError):
                candidate.seal(self.files, self.root / "linked", self.identity)

    def test_archive_digest_paths_duplicates_and_links_fail_before_extraction(self):
        data = self.archive()
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        candidate.extract(data, digest, self.root / "good")
        with self.assertRaises(ReleaseError):
            candidate.extract(data, "sha256:" + "0" * 64, self.root / "bad")
        for name in (
            "../outside",
            "/absolute",
            "C:drive",
            "a\\b",
            "sub/file",
            "Clarify.exe",
        ):
            stream = io.BytesIO(data)
            with zipfile.ZipFile(stream, "a") as archive:
                archive.writestr(name, "attack")
            with self.subTest(name=name), self.assertRaises(ReleaseError):
                candidate.extract(
                    stream.getvalue(),
                    "sha256:" + hashlib.sha256(stream.getvalue()).hexdigest(),
                    self.root / "bad",
                )
        stream = io.BytesIO(data)
        with zipfile.ZipFile(stream, "a") as archive:
            entry = zipfile.ZipInfo("link")
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            archive.writestr(entry, "target")
        with self.assertRaises(ReleaseError):
            candidate.extract(
                stream.getvalue(),
                "sha256:" + hashlib.sha256(stream.getvalue()).hexdigest(),
                self.root / "bad",
            )
        self.assertFalse((self.root / "outside").exists())

    def test_identity_mismatch_and_preview_metadata_are_rejected(self):
        for field, value in (
            ("source_sha", "b" * 40),
            ("channel", "stable"),
            ("version", "9.0.0"),
            ("run_attempt", 2),
        ):
            expected = dict(self.identity, **{field: value})
            with self.subTest(field=field), self.assertRaises(ReleaseError):
                candidate.verify_directory(self.root / "bundle", expected)
        (self.files / "Clarify-portable-update.json").write_text("{}")
        with self.assertRaises(ReleaseError):
            candidate.seal(self.files, self.root / "other", self.identity)

    def test_preview_receipt_from_another_run_is_rejected_even_with_matching_source(
        self,
    ):
        checksum = candidate.file_record(self.files / "Clarify.exe")["sha256"]
        (self.files / "Clarify.exe.sha256").write_text(
            checksum + "  Clarify.exe\n", encoding="ascii"
        )
        receipt = {
            "schema": 1,
            "channel": "preview",
            "source_sha": SOURCE,
            "run_id": "999",
            "run_attempt": 1,
            "tag": self.identity["tag"],
            "version": "1.2.3",
            "updater_enabled": False,
        }
        (self.files / "Clarify-preview.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )
        with zipfile.ZipFile(self.files / "Clarify-windows-x64.zip", "w") as archive:
            for name in ("Clarify.exe", "Clarify.exe.sha256", "Clarify.sbom.json"):
                archive.write(self.files / name, name)
            for name in (
                "LICENSE",
                "THIRD_PARTY_NOTICES.md",
                "Clarify-settings-NOTICES.txt",
                "Clarify-qt-NOTICES.txt",
                "Clarify-crypto-NOTICES.txt",
            ):
                archive.writestr(name, "fixture notice")
        original_record = candidate.file_record

        def record(path):
            value = original_record(path)
            if path.name == "sox-14.4.2-source.tar.gz":
                value["sha256"] = (
                    "b45f598643ffbd8e363ff24d61166ccec4836fea6d3888881b8df53e3bb55f6c"
                )
            return value

        with (
            patch.object(candidate, "file_record", side_effect=record),
            self.assertRaisesRegex(ReleaseError, "Preview identity"),
        ):
            candidate.verify_payload(self.files, self.identity)
        receipt["run_id"] = "123"
        (self.files / "Clarify-preview.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )
        with patch.object(candidate, "file_record", side_effect=record):
            candidate.verify_payload(self.files, self.identity)

    def test_stable_payload_verifies_a_real_signature_and_rejects_a_wrong_signed_source(
        self,
    ):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.exceptions import InvalidSignature

        key = Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32)
        expected = candidate.identity(
            SOURCE, "refs/tags/v1.2.3", 123, 1, "stable", "1.2.3"
        )
        binary = candidate.file_record(self.files / "Clarify.exe")
        (self.files / "Clarify.exe.sha256").write_text(
            binary["sha256"] + "  Clarify.exe\n", encoding="ascii"
        )
        with zipfile.ZipFile(self.files / "Clarify-windows-x64.zip", "w") as archive:
            for name in ("Clarify.exe", "Clarify.exe.sha256", "Clarify.sbom.json"):
                archive.write(self.files / name, name)
            for name in (
                "LICENSE",
                "THIRD_PARTY_NOTICES.md",
                "Clarify-settings-NOTICES.txt",
                "Clarify-qt-NOTICES.txt",
                "Clarify-crypto-NOTICES.txt",
            ):
                archive.writestr(name, "fixture notice")
        document = {
            "schema_version": 1,
            "repository": candidate.release.REPOSITORY,
            "channel": "stable",
            "version": "1.2.3",
            "tag": "v1.2.3",
            "source_sha": SOURCE,
            "asset": "Clarify.exe",
            "url": "https://github.com/jvictormaynard/clarify/releases/download/v1.2.3/Clarify.exe",
            "sha256": binary["sha256"],
            "size": binary["size"],
        }
        policy = {
            "public_key": base64.b64encode(
                key.public_key().public_bytes_raw()
            ).decode(),
            "channel": "stable",
            "algorithm": "Ed25519",
            "repository": candidate.release.REPOSITORY,
        }
        original_read, original_record = Path.read_text, candidate.file_record

        def read(path, *args, **kwargs):
            return (
                json.dumps(policy)
                if path.name == "portable-update-policy.json"
                else original_read(path, *args, **kwargs)
            )

        def record(path):
            value = original_record(path)
            if path.name == "sox-14.4.2-source.tar.gz":
                value["sha256"] = (
                    "b45f598643ffbd8e363ff24d61166ccec4836fea6d3888881b8df53e3bb55f6c"
                )
            return value

        def sign():
            data = json.dumps(document).encode()
            (self.files / "Clarify-portable-update.json").write_bytes(data)
            (self.files / "Clarify-portable-update.json.sig").write_bytes(
                key.sign(data)
            )

        with (
            patch.object(Path, "read_text", read),
            patch.object(candidate, "file_record", side_effect=record),
        ):
            sign()
            candidate.verify_payload(self.files, expected, building=True)
            document["source_sha"] = "b" * 40
            sign()
            with self.assertRaisesRegex(ReleaseError, "Signed update identity"):
                candidate.verify_payload(self.files, expected, building=True)
            (self.files / "Clarify-portable-update.json.sig").write_bytes(bytes(64))
            with self.assertRaises(InvalidSignature):
                candidate.verify_payload(self.files, expected, building=True)

    def producer(self):
        artifact = {
            "id": 456,
            "name": "desktop-candidate-123-1",
            "digest": "sha256:" + "d" * 64,
            "expired": False,
            "workflow_run": {"id": 123, "head_sha": SOURCE},
        }
        run = {
            "id": 123,
            "workflow_id": 8,
            "repository": {"full_name": candidate.release.REPOSITORY},
            "head_repository": {"full_name": candidate.release.REPOSITORY},
            "event": "workflow_dispatch",
            "path": candidate.WORKFLOW,
            "head_sha": SOURCE,
            "head_branch": self.identity["source_ref"].split("/", 2)[2],
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
        }
        job = {
            "name": candidate.BUILD_JOB,
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
            "steps": [
                {"name": name, "status": "completed", "conclusion": "success"}
                for name in candidate.producer_steps(self.identity["channel"])
            ],
        }
        routes = {
            "/actions/runs/123": run,
            "/actions/workflows/8": {
                "path": candidate.WORKFLOW,
                "name": "Desktop Release",
            },
            "/actions/artifacts/456": artifact,
            "/actions/runs/123/artifacts": [artifact],
            "/actions/runs/123/attempts/1/jobs": [job],
        }

        class API:
            def request(self, method, path, *args, **kwargs):
                if method != "GET":
                    raise AssertionError("Authentication must be read only")
                return routes[path]

            def pages(self, path, key=None):
                if path == "/releases":
                    return []
                return self.request("GET", path)

        return API(), routes, run, job, artifact

    def test_producer_checks_selected_attempt_job_steps_and_artifact_identity(self):
        api, routes, run, job, artifact = self.producer()
        candidate.authenticate(api, self.identity, 456, artifact["digest"])
        for obj, field, value in (
            (run, "run_attempt", 2),
            (run, "head_sha", "b" * 40),
            (run, "event", "push"),
            (run, "conclusion", "failure"),
            (run, "path", ".github/workflows/ci.yml"),
            (artifact, "expired", True),
            (artifact, "name", "other"),
            (artifact, "digest", "sha256:" + "e" * 64),
            (job, "conclusion", "failure"),
        ):
            original = obj[field]
            obj[field] = value
            with self.subTest(field=field), self.assertRaises(ReleaseError):
                candidate.authenticate(api, self.identity, 456, "sha256:" + "d" * 64)
            obj[field] = original
        job["steps"][0]["conclusion"] = "skipped"
        with self.assertRaises(ReleaseError):
            candidate.authenticate(api, self.identity, 456, artifact["digest"])

    def test_windows_acceptance_must_cover_final_candidate_and_be_fresh(self):
        now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
        stable = candidate.identity(
            SOURCE, "refs/tags/v1.2.3", 123, 1, "stable", "1.2.3"
        )
        evidence = {
            "schema": 1,
            "source_sha": SOURCE,
            "candidate_digest": "sha256:" + "d" * 64,
            "windows_accepted": True,
            "checked_at": "2026-10-31T11:00:00Z",
            "report_url": "https://github.com/jvictormaynard/clarify/issues/123#issuecomment-456",
        }
        candidate.acceptance(stable, evidence["candidate_digest"], evidence, now)
        for key, value in (
            ("source_sha", "b" * 40),
            ("candidate_digest", "sha256:" + "e" * 64),
            ("windows_accepted", False),
            ("checked_at", "2026-10-29T11:00:00Z"),
            ("report_url", "https://example.com/receipt"),
            ("report_url", "https://github.com/jvictormaynard/clarify/pull/179"),
        ):
            with self.subTest(key=key), self.assertRaises(ReleaseError):
                candidate.acceptance(
                    stable, "sha256:" + "d" * 64, dict(evidence, **{key: value}), now
                )

    def publication_api(self):
        producer_api, routes, run, job, artifact = self.producer()
        outer = self

        class API:
            tag = None
            published = None
            assets = []

            def __init__(self):
                self.writes = []

            def pages(self, path, key=None):
                return (
                    self.assets
                    if path == "/releases/789/assets"
                    else producer_api.pages(path, key)
                )

            def request(self, method, path, body=None, **kwargs):
                if method == "GET":
                    if path == "/releases/latest":
                        return self.published
                    if path.startswith("/git/ref/tags/"):
                        return (
                            None
                            if self.tag is None
                            else {"object": {"type": "commit", "sha": self.tag}}
                        )
                    if path.startswith("/releases/tags/"):
                        return self.published
                    return producer_api.request(method, path)
                self.writes.append((method, path, deepcopy(body)))
                if path == "/git/refs":
                    self.tag = body["sha"]
                elif method == "POST" and path == "/releases":
                    self.published = dict(body, id=789)
                    return self.published
                elif method == "PATCH" and path == "/releases/789":
                    self.published.update(body)
                    return self.published
                else:
                    raise AssertionError((method, path))

        api = API()

        def uploader(_api, release_id, name, path):
            record = candidate.file_record(path)
            asset = {
                "id": 1000 + len(api.assets),
                "name": name,
                "state": "uploaded",
                "size": record["size"],
                "digest": "sha256:" + record["sha256"],
            }
            api.assets.append(asset)
            return asset

        def downloader(_api, path):
            asset = next(
                item
                for item in api.assets
                if path == "/releases/assets/" + str(item["id"])
            )
            return (outer.root / "bundle" / asset["name"]).read_bytes()

        return api, uploader, downloader

    def test_publication_reuses_exact_bytes_once_and_preview_never_becomes_latest(self):
        api, uploader, downloader = self.publication_api()
        before = {
            path.name: path.read_bytes() for path in (self.root / "bundle").iterdir()
        }
        verified = []
        with patch.object(candidate, "download", side_effect=downloader):
            for expected_result in ("published", "already-published"):
                result = candidate.publish(
                    api,
                    self.root / "bundle",
                    self.identity,
                    456,
                    "sha256:" + "d" * 64,
                    {},
                    uploader=uploader,
                    payload=lambda *_: verified.append("payload"),
                    provenance=lambda *_: verified.append("provenance"),
                )
                self.assertEqual(result, expected_result)
        self.assertEqual(verified, ["payload", "provenance"])
        self.assertEqual(len(api.assets), len(before) - 1)
        self.assertEqual(
            [item[1] for item in api.writes],
            ["/git/refs", "/releases", "/releases/789"],
        )
        self.assertTrue(api.published["prerelease"])
        self.assertEqual(api.published["make_latest"], "false")
        self.assertEqual(
            before,
            {path.name: path.read_bytes() for path in (self.root / "bundle").iterdir()},
        )

    def test_partial_or_uncertain_upload_stops_and_cannot_be_retried(self):
        api, uploader, downloader = self.publication_api()

        def uncertain(*args):
            asset = uploader(*args)
            asset["digest"] = None
            return asset

        with self.assertRaisesRegex(ReleaseError, "uncertain"):
            candidate.publish(
                api,
                self.root / "bundle",
                self.identity,
                456,
                "sha256:" + "d" * 64,
                {},
                uploader=uncertain,
                payload=lambda *_: None,
                provenance=lambda *_: None,
            )
        self.assertTrue(api.published["draft"])
        previous_writes = deepcopy(api.writes)
        with self.assertRaisesRegex(ReleaseError, "partial"):
            candidate.publish(
                api,
                self.root / "bundle",
                self.identity,
                456,
                "sha256:" + "d" * 64,
                {},
                uploader=uploader,
                payload=lambda *_: None,
                provenance=lambda *_: None,
            )
        self.assertEqual(api.writes, previous_writes)

    def test_stable_publication_requires_source_and_acceptance_and_sets_latest(self):
        self.identity = candidate.identity(
            SOURCE, "refs/tags/v1.2.3", 123, 1, "stable", "1.2.3"
        )
        for path in (self.root / "bundle").iterdir():
            path.unlink()
        (self.root / "bundle").rmdir()
        (self.files / "Clarify-preview.json").unlink()
        for name in candidate.allowed_assets("stable"):
            (self.files / name).write_bytes(name.encode())
        candidate.seal(self.files, self.root / "bundle", self.identity)
        api, uploader, downloader = self.publication_api()
        api.tag = SOURCE
        with (
            patch.object(candidate, "verify_acceptance_report") as acceptance,
            patch.object(
                candidate.release,
                "verify_source",
                return_value={"component": "desktop", "version": "1.2.3"},
            ) as source,
            patch.object(candidate, "download", side_effect=downloader),
        ):
            api.file = lambda *_: "## [1.2.3] - 2026-10-31\n\n- Correct startup.\n"
            result = candidate.publish(
                api,
                self.root / "bundle",
                self.identity,
                456,
                "sha256:" + "d" * 64,
                {"candidate": "accepted"},
                uploader=uploader,
                payload=lambda *_: None,
                provenance=lambda *_: None,
            )
            self.assertEqual(result, "published")
            self.assertGreaterEqual(acceptance.call_count, 2)
            self.assertGreaterEqual(source.call_count, 2)
        self.assertFalse(api.published["prerelease"])
        self.assertEqual(api.published["make_latest"], "true")
        self.assertEqual(len(api.assets), 8)
        self.assertFalse(any(path == "/git/refs" for _, path, _ in api.writes))

    def test_publication_is_disabled_without_its_separate_opt_in(self):
        environment = {
            "GITHUB_REPOSITORY": candidate.release.REPOSITORY,
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GH_TOKEN": "fake",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch(
                "sys.argv",
                [
                    "candidate",
                    "publish",
                    "--channel",
                    "preview",
                    "--source-sha",
                    SOURCE,
                ],
            ),
            patch.object(candidate.release, "GitHub") as api,
        ):
            with self.assertRaisesRegex(ReleaseError, "disabled"):
                candidate.main()
            api.return_value.request.assert_not_called()

    def test_failing_payload_or_provenance_has_no_publication_effect(self):
        api, uploader, _ = self.publication_api()

        def fail(*args):
            raise ReleaseError("verification failed")

        for payload, provenance in ((fail, lambda *_: None), (lambda *_: None, fail)):
            with self.assertRaises(ReleaseError):
                candidate.publish(
                    api,
                    self.root / "bundle",
                    self.identity,
                    456,
                    "sha256:" + "d" * 64,
                    {},
                    uploader=uploader,
                    payload=payload,
                    provenance=provenance,
                )
            self.assertEqual(api.writes, [])

    def test_signed_download_redirect_never_receives_the_github_token(self):
        class API:
            base = "https://api.github.com/repos/jvictormaynard/clarify"
            token = "test-token-must-stay-on-api-origin"

        location = "https://example.blob.core.windows.net/candidate?signature=test"
        opener = unittest.mock.Mock()
        opener.open.side_effect = HTTPError(
            API.base, 302, "redirect", {"Location": location}, None
        )
        with (
            patch.object(candidate, "build_opener", return_value=opener),
            patch.object(
                candidate, "urlopen", return_value=io.BytesIO(b"candidate")
            ) as redirected,
        ):
            self.assertEqual(
                candidate.download(API(), "/actions/artifacts/456/zip"), b"candidate"
            )
            redirected.assert_called_once_with(location, timeout=60)
            self.assertEqual(
                opener.open.call_args.args[0].get_header("Authorization"),
                "Bearer " + API.token,
            )
        opener.open.side_effect = HTTPError(
            API.base,
            302,
            "redirect",
            {"Location": "https://attacker.example/candidate"},
            None,
        )
        with (
            patch.object(candidate, "build_opener", return_value=opener),
            self.assertRaises(ReleaseError),
        ):
            candidate.download(API(), "/actions/artifacts/456/zip")

    def test_canonical_acceptance_report_must_contain_the_same_candidate(self):
        now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
        evidence = {
            "schema": 1,
            "source_sha": SOURCE,
            "candidate_digest": "sha256:" + "d" * 64,
            "windows_accepted": True,
            "checked_at": "2026-10-31T11:00:00Z",
            "report_url": "https://github.com/jvictormaynard/clarify/issues/123#issuecomment-456",
        }
        report = {
            "html_url": evidence["report_url"],
            "user": {"login": "maintainer"},
            "updated_at": evidence["checked_at"],
            "body": "Windows focus, hotkeys, Settings and update acceptance passed.\n```clarify-candidate-acceptance\n"
            + json.dumps(evidence)
            + "\n```",
        }

        class API:
            def request(self, method, path):
                return (
                    {"permission": "write"} if path.endswith("/permission") else report
                )

        candidate.verify_acceptance_report(
            API(), self.identity, "sha256:" + "d" * 64, evidence, now
        )
        report["body"] = report["body"].replace("d" * 64, "e" * 64)
        with self.assertRaisesRegex(ReleaseError, "exact candidate"):
            candidate.verify_acceptance_report(
                API(), self.identity, "sha256:" + "d" * 64, evidence, now
            )


if __name__ == "__main__":
    unittest.main()
