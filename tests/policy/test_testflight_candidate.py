"""The store handoff reads one immutable, source-bound TestFlight evidence bundle."""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import app_store_handoff as store
from scripts.release_delivery import ReleaseError

SOURCE = "a" * 40
TAG = "ios/v1.2.3-build42"


class TestFlightCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.verification = {"sha256": "d" * 64, "bytes": 123, "bundles": []}
        self.receipt = {
            "state": "confirmed",
            "source": SOURCE,
            "run_id": "123",
            "attempt": "1",
            "ipa_sha256": "d" * 64,
        }
        self.availability = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "processing": "VALID",
        }
        self.write_inputs()

    def write_inputs(self):
        for name, value in (
            ("verification.json", self.verification),
            ("upload-receipt.json", self.receipt),
            ("testflight-availability.json", self.availability),
        ):
            (self.inputs / name).write_text(json.dumps(value), encoding="utf-8")

    def test_sealed_receipts_bind_ipa_source_run_attempt_and_each_file(self):
        output = self.root / "evidence"
        store.seal_evidence(self.inputs, output, SOURCE, TAG, 123, 1)
        manifest = json.loads((output / store.EVIDENCE_MANIFEST).read_text())
        self.assertEqual(manifest["source_sha"], SOURCE)
        self.assertEqual(manifest["tag"], TAG)
        self.assertEqual(manifest["run_attempt"], 1)
        self.assertEqual(set(manifest["files"]), store.EVIDENCE_FILES)
        for name, record in manifest["files"].items():
            self.assertEqual(
                record["sha256"],
                hashlib.sha256((output / name).read_bytes()).hexdigest(),
            )
        with self.assertRaises(ReleaseError):
            store.seal_evidence(self.inputs, output, SOURCE, TAG, 123, 1)

    def test_uncertain_upload_wrong_ipa_source_or_attempt_cannot_be_sealed(self):
        original = deepcopy(self.receipt)
        for key, value in (
            ("state", "uncertain"),
            ("state", "started"),
            ("source", "b" * 40),
            ("ipa_sha256", "e" * 64),
            ("attempt", "2"),
            ("run_id", "456"),
        ):
            self.receipt = dict(original, **{key: value})
            self.write_inputs()
            with self.subTest(key=key), self.assertRaises(ReleaseError):
                store.seal_evidence(self.inputs, self.root / "bad", SOURCE, TAG, 123, 1)

    def test_handoff_download_authenticates_artifact_id_digest_and_exact_files(self):
        store.seal_evidence(self.inputs, self.root / "bundle", SOURCE, TAG, 123, 1)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for path in (self.root / "bundle").iterdir():
                archive.writestr(path.name, path.read_bytes())
        data = stream.getvalue()
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        artifact = {
            "id": 456,
            "name": "clarify-testflight-candidate-123-1",
            "expired": False,
            "digest": digest,
            "workflow_run": {"id": 123, "head_sha": SOURCE},
        }

        class API:
            def request(self, method, path):
                if method != "GET":
                    raise AssertionError(
                        "Handoff must not mutate Apple or GitHub release state"
                    )
                return artifact

            def pages(self, path, key=None):
                return [artifact]

        with (
            patch.object(store, "verify_producer") as producer,
            patch.object(store.candidate, "download", return_value=data),
        ):
            store.authenticated_evidence(
                API(), SOURCE, TAG, 123, 1, 456, digest, self.root / "downloaded"
            )
            self.assertEqual(producer.call_count, 2)
            for key, value in (
                ("id", 789),
                ("name", "clarify-ios-evidence-" + SOURCE),
                ("expired", True),
                ("digest", "sha256:" + "0" * 64),
            ):
                previous = artifact[key]
                artifact[key] = value
                with self.subTest(key=key), self.assertRaises(ReleaseError):
                    store.authenticated_evidence(
                        API(), SOURCE, TAG, 123, 1, 456, digest, self.root / "bad"
                    )
                artifact[key] = previous


if __name__ == "__main__":
    unittest.main()
