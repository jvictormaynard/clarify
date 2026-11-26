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
MACOS_ZIP = "Clarify-macos-arm64.zip"
MACOS_CHECKSUM = "Clarify-macos-arm64.zip.sha256"


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
        for name in candidate.allowed_assets("preview", self.identity["version"]):
            (self.files / name).write_bytes(name.encode())
        self.manifest = candidate.seal(self.files, self.root / "bundle", self.identity)

    def write_macos_zip(self, *, omit=None):
        with zipfile.ZipFile(self.files / MACOS_ZIP, "w") as archive:
            for name in (
                "Clarify.app/Contents/Info.plist",
                "Clarify.app/Contents/MacOS/Clarify",
                "Clarify.app/Contents/Helpers/Clarify Desktop.app/Contents/MacOS/Clarify Desktop",
                "LICENSE",
                "THIRD_PARTY_NOTICES.md",
                "Clarify-qt-NOTICES.txt",
                "Clarify-macos.sbom.json",
                "Clarify-macos-NOTICES.txt",
                "Clarify-settings-NOTICES.txt",
                "Clarify-crypto-NOTICES.txt",
            ):
                if name != omit:
                    archive.writestr(name, "fixture")
        return self.write_macos_checksum()

    def write_macos_checksum(self):
        checksum = hashlib.sha256((self.files / MACOS_ZIP).read_bytes()).hexdigest()
        line = f"{checksum}  {MACOS_ZIP}\n"
        (self.files / MACOS_CHECKSUM).write_bytes(line.encode("ascii"))
        return line

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
            set(self.manifest["assets"]), candidate.allowed_assets("preview", "1.2.3")
        )
        self.assertNotIn("Clarify-portable-update.json", self.manifest["assets"])
        self.assertTrue({MACOS_ZIP, MACOS_CHECKSUM} <= self.manifest["assets"].keys())
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

    def test_macos_asset_cutoff_preserves_legacy_stable_and_covers_every_preview(self):
        macos_assets = {MACOS_ZIP, MACOS_CHECKSUM}
        windows_assets = candidate.release.ASSETS
        for channel, version, expected in (
            ("stable", "0.17.9", windows_assets),
            ("stable", "0.18.0", windows_assets),
            ("stable", "0.18.1", windows_assets | macos_assets),
            (
                "preview",
                "0.18.0",
                windows_assets
                - {"Clarify-portable-update.json", "Clarify-portable-update.json.sig"}
                | macos_assets
                | {"Clarify-preview.json"},
            ),
        ):
            with self.subTest(channel=channel, version=version):
                self.assertEqual(candidate.allowed_assets(channel, version), expected)

    def test_macos_zip_and_checksum_require_provenance_for_the_exact_source(self):
        with patch.object(candidate.subprocess, "run") as run:
            candidate.verify_provenance(self.files, self.identity)
        verified = {
            Path(call.args[0][3]).name: call.args[0] for call in run.call_args_list
        }
        for name in (MACOS_ZIP, MACOS_CHECKSUM):
            command = verified[name]
            for flag, value in (
                ("--source-digest", SOURCE),
                ("--source-ref", "refs/heads/topic"),
                ("--signer-digest", SOURCE),
            ):
                self.assertEqual(command[command.index(flag) + 1], value)

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
        candidate.extract(data, digest, self.root / "good", self.identity)
        with self.assertRaises(ReleaseError):
            candidate.extract(
                data, "sha256:" + "0" * 64, self.root / "bad", self.identity
            )
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
                    self.identity,
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
                self.identity,
            )
        (self.root / "bundle" / MACOS_CHECKSUM).unlink()
        data = self.archive()
        with self.assertRaisesRegex(ReleaseError, "archive paths"):
            candidate.extract(
                data,
                "sha256:" + hashlib.sha256(data).hexdigest(),
                self.root / "bad",
                self.identity,
            )
        self.assertFalse((self.root / "bad").exists())
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
        self.write_macos_zip()
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
            (self.files / MACOS_CHECKSUM).write_bytes(b"invalid checksum")
            with self.assertRaisesRegex(ReleaseError, "macOS ZIP checksum"):
                candidate.verify_payload(self.files, self.identity)

    def test_macos_transfer_rejects_windows_files_without_replacing_outputs(self):
        incoming = self.root / "incoming"
        incoming.mkdir()
        self.write_macos_zip()
        for name in (MACOS_ZIP, MACOS_CHECKSUM):
            (self.files / name).replace(incoming / name)
        windows = self.files / "Clarify.exe"
        (incoming / windows.name).write_bytes(b"other executable")
        with self.assertRaisesRegex(ReleaseError, "transfer inventory"):
            candidate.stage_macos_inputs(incoming, self.files)
        self.assertEqual(windows.read_bytes(), b"Clarify.exe")
        self.assertFalse((self.files / MACOS_ZIP).exists())
        (incoming / windows.name).unlink()
        candidate.stage_macos_inputs(incoming, self.files)
        self.assertEqual(windows.read_bytes(), b"Clarify.exe")
        self.assertTrue((self.files / MACOS_ZIP).is_file())

    def test_macos_zip_requires_checksum_bundle_and_notices_without_extraction(self):
        line = self.write_macos_zip()
        with patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError):
            candidate.verify_macos_payload(self.files)
        for text in (
            line.replace("  ", " "),
            line.replace(MACOS_ZIP, "other.zip"),
            " " + line,
        ):
            (self.files / MACOS_CHECKSUM).write_bytes(text.encode("ascii"))
            with (
                self.subTest(text=text),
                self.assertRaisesRegex(ReleaseError, "checksum differs"),
            ):
                candidate.verify_macos_payload(self.files)
        for name in ("Clarify.app/Contents/MacOS/Clarify", "Clarify-macos.sbom.json"):
            self.write_macos_zip(omit=name)
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(ReleaseError, "distribution files"),
            ):
                candidate.verify_macos_payload(self.files)
        self.write_macos_zip()
        # Change file data but keep the ZIP directory and outer checksum valid.
        package = self.files / MACOS_ZIP
        package.write_bytes(package.read_bytes().replace(b"fixture", b"damaged", 1))
        self.write_macos_checksum()
        with self.assertRaisesRegex(ReleaseError, "macOS ZIP is corrupt"):
            candidate.verify_macos_payload(self.files)

    def test_stable_payload_verifies_a_real_signature_and_rejects_a_wrong_signed_source(
        self,
    ):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.exceptions import InvalidSignature

        key = Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32)
        expected = candidate.identity(
            SOURCE, "refs/tags/v1.2.3", 123, 1, "stable", "1.2.3"
        )
        self.write_macos_zip()
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

    def producer(self, *, separate_windows=False):
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

        def successful_job(name, steps):
            return {
                "name": name,
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
                "steps": [
                    {
                        "name": step,
                        "status": "completed",
                        "conclusion": "success",
                        "number": number,
                    }
                    for number, step in enumerate(steps, start=1)
                ],
            }

        channel, version = self.identity["channel"], self.identity["version"]
        job = successful_job(
            candidate.BUILD_JOB,
            candidate.producer_steps(
                channel, version, separate_windows=separate_windows
            ),
        )
        jobs = [job]
        if separate_windows:
            jobs.append(
                successful_job(
                    candidate.WINDOWS_BUILD_JOB,
                    [
                        *candidate.windows_producer_steps(channel),
                        "Upload Windows candidate inputs",
                    ],
                )
            )
        if candidate.release.desktop_requires_macos(channel, version):
            jobs.append(
                successful_job(
                    "Build macOS candidate inputs",
                    (
                        "Build Apple Silicon app",
                        "Package and verify macOS candidate inputs",
                        "Upload macOS candidate inputs",
                    ),
                )
            )
        routes = {
            "/actions/runs/123": run,
            "/actions/workflows/8": {
                "path": candidate.WORKFLOW,
                "name": "Desktop Release",
            },
            "/actions/artifacts/456": artifact,
            "/actions/runs/123/artifacts": [artifact],
            "/actions/runs/123/attempts/1/jobs": jobs,
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

    def test_parallel_producer_requires_windows_inputs_from_same_attempt(self):
        api, routes, _, seal_job, artifact = self.producer(separate_windows=True)
        candidate.authenticate(api, self.identity, 456, artifact["digest"])
        jobs = routes["/actions/runs/123/attempts/1/jobs"]
        windows = next(
            job for job in jobs if job["name"] == candidate.WINDOWS_BUILD_JOB
        )
        windows["run_attempt"] = 2
        with self.assertRaisesRegex(
            candidate.release.ReleaseError, "Windows candidate"
        ):
            candidate.authenticate(api, self.identity, 456, artifact["digest"])
        windows["run_attempt"] = 1
        seal_job["steps"].pop(0)
        with self.assertRaisesRegex(candidate.release.ReleaseError, "Download Windows"):
            candidate.authenticate(api, self.identity, 456, artifact["digest"])

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

    def test_macos_requires_current_sibling_job_and_download_before_seal(self):
        api, routes, _, windows, artifact = self.producer()
        jobs = routes["/actions/runs/123/attempts/1/jobs"]
        macos = jobs.pop()
        with self.assertRaisesRegex(ReleaseError, "Build macOS candidate inputs"):
            candidate.authenticate(api, self.identity, 456, artifact["digest"])
        jobs.append(macos)
        download = next(
            step
            for step in windows["steps"]
            if step["name"] == "Download macOS candidate inputs"
        )
        for obj, field, value in (
            (macos, "run_attempt", 2),
            (macos, "conclusion", "failure"),
            (download, "conclusion", "skipped"),
            (download, "number", len(windows["steps"]) + 1),
            *((step, "conclusion", "skipped") for step in macos["steps"]),
        ):
            with (
                self.subTest(job_or_step=obj["name"], field=field),
                patch.dict(obj, {field: value}),
            ):
                with self.assertRaises(ReleaseError):
                    candidate.authenticate(api, self.identity, 456, artifact["digest"])

    def test_windows_acceptance_must_cover_final_candidate_and_be_fresh(self):
        now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
        stable = candidate.identity(
            SOURCE, "refs/tags/v0.18.0", 123, 1, "stable", "0.18.0"
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
            ("macos_accepted", True),
            ("schema", 2),
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
            SOURCE, "refs/tags/v0.18.0", 123, 1, "stable", "0.18.0"
        )
        for path in (self.root / "bundle").iterdir():
            path.unlink()
        (self.root / "bundle").rmdir()
        (self.files / "Clarify-preview.json").unlink()
        for name in candidate.allowed_assets("stable", "0.18.0"):
            (self.files / name).write_bytes(name.encode())
        candidate.seal(self.files, self.root / "bundle", self.identity)
        api, uploader, downloader = self.publication_api()
        api.tag = SOURCE
        with (
            patch.object(candidate, "verify_acceptance_report") as acceptance,
            patch.object(
                candidate.release,
                "verify_source",
                return_value={"component": "desktop", "version": "0.18.0"},
            ) as source,
            patch.object(candidate, "download", side_effect=downloader),
        ):
            api.file = lambda *_: "## [0.18.0] - 2026-10-31\n\n- Correct startup.\n"
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

    def test_stable_build_uses_reviewed_source_after_main_advances(self):
        expected = candidate.identity(
            SOURCE, "refs/tags/v1.2.3", 123, 1, "stable", "1.2.3"
        )
        api = object()
        with (
            patch.object(
                candidate.release, "verify_source", return_value={"version": "1.2.3"}
            ) as source,
            patch.object(candidate.release, "require_new_desktop_release") as newer,
        ):
            candidate.verify_source(api, expected, building=True)
        source.assert_called_once_with(api, "desktop", SOURCE, "v1.2.3")
        newer.assert_called_once()

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
        for path, accept in (
            ("/actions/artifacts/456/zip", "application/vnd.github+json"),
            ("/releases/assets/789", "application/octet-stream"),
        ):
            with (
                self.subTest(path=path),
                patch.object(candidate, "build_opener", return_value=opener),
                patch.object(
                    candidate, "urlopen", return_value=io.BytesIO(b"candidate")
                ) as redirected,
            ):
                self.assertEqual(candidate.download(API(), path), b"candidate")
                redirected.assert_called_once_with(location, timeout=60)
                request = opener.open.call_args.args[0]
                self.assertEqual(
                    request.get_header("Authorization"), "Bearer " + API.token
                )
                self.assertEqual(request.get_header("Accept"), accept)
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
        stable = candidate.identity(
            SOURCE, "refs/tags/v0.18.1", 123, 1, "stable", "0.18.1"
        )
        evidence = {
            "schema": 2,
            "source_sha": SOURCE,
            "candidate_digest": "sha256:" + "d" * 64,
            "windows_accepted": True,
            "macos_accepted": True,
            "checked_at": "2026-10-31T11:00:00Z",
            "report_url": "https://github.com/jvictormaynard/clarify/issues/123#issuecomment-456",
        }
        report = {
            "html_url": evidence["report_url"],
            "user": {"login": "maintainer"},
            "updated_at": evidence["checked_at"],
            "body": "Windows and macOS acceptance passed.\n```clarify-candidate-acceptance\n"
            + json.dumps(evidence)
            + "\n```",
        }

        class API:
            def request(self, method, path):
                return (
                    {"permission": "write"} if path.endswith("/permission") else report
                )

        candidate.verify_acceptance_report(
            API(), stable, "sha256:" + "d" * 64, evidence, now
        )
        legacy = {
            key: value for key, value in evidence.items() if key != "macos_accepted"
        }
        legacy["schema"] = 1
        for invalid in (
            legacy,
            dict(evidence, macos_accepted=False),
            dict(evidence, windows_accepted=False),
        ):
            with self.subTest(evidence=invalid), self.assertRaises(ReleaseError):
                candidate.acceptance(stable, evidence["candidate_digest"], invalid, now)
        with patch.dict(
            report,
            body=report["body"].replace(
                '"macos_accepted": true', '"macos_accepted": 1'
            ),
        ):
            with self.assertRaises(ReleaseError):
                candidate.verify_acceptance_report(
                    API(), stable, evidence["candidate_digest"], evidence, now
                )
        report["body"] = report["body"].replace("d" * 64, "e" * 64)
        with self.assertRaisesRegex(ReleaseError, "exact candidate"):
            candidate.verify_acceptance_report(
                API(), stable, "sha256:" + "d" * 64, evidence, now
            )


if __name__ == "__main__":
    unittest.main()
