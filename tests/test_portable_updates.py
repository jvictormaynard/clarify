"""Update trust tests use generated keys and temporary executable fixtures."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import threading

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from portable_updates import (
    PortableUpdateError,
    PortableUpdatePolicy,
    PortableReleaseTransport,
    replace_and_restart,
    verify_binary,
    verify_manifest,
)


class ReleaseFixture(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.policy = PortableUpdatePolicy(self.key.public_key().public_bytes_raw())
        self.binary = b"MZ-test-executable"
        self.payload = {
            "schema_version": 1,
            "repository": "jvictormaynard/clarify",
            "channel": "stable",
            "version": "0.5.1",
            "tag": "v0.5.1",
            "source_sha": "a" * 40,
            "asset": "Clarify.exe",
            "url": "https://github.com/jvictormaynard/clarify/releases/download/v0.5.1/Clarify.exe",
            "sha256": hashlib.sha256(self.binary).hexdigest(),
            "size": len(self.binary),
        }

    def encoded(self, payload=None):
        data = json.dumps(self.payload if payload is None else payload).encode()
        return data, self.key.sign(data)


class ManifestTests(ReleaseFixture):
    def test_verified_manifest_binds_version_source_and_executable(self):
        release = verify_manifest(*self.encoded(), self.policy, "0.5.0", "v0.5.1")
        self.assertEqual(release.version, "0.5.1")
        self.assertEqual(release.source_sha, "a" * 40)
        self.assertEqual(release.size, len(self.binary))

    def test_changed_manifest_and_wrong_key_are_rejected(self):
        data, signature = self.encoded()
        for modified, sig in (
            (data.replace(b"0.5.1", b"0.5.2"), signature),
            (data, Ed25519PrivateKey.generate().sign(data)),
        ):
            with self.subTest(data=modified), self.assertRaises(PortableUpdateError):
                verify_manifest(modified, sig, self.policy, "0.5.0")

    def test_rollback_equal_and_prerelease_versions_are_rejected(self):
        for version in ("0.4.9", "0.5.0", "0.5.1-beta.1", "0.5.1+local", "00.5.1"):
            payload = {**self.payload, "version": version, "tag": "v" + version}
            with self.subTest(version=version), self.assertRaises(PortableUpdateError):
                verify_manifest(*self.encoded(payload), self.policy, "0.5.0")

    def test_signed_but_unexpected_release_fields_are_rejected(self):
        fields = (
            ("repository", "attacker/clarify"),
            ("channel", "preview"),
            ("tag", "v0.5.2"),
            ("asset", "installer.exe"),
            ("url", "https://example.com/Clarify.exe"),
            ("url", self.payload["url"] + "?token=1"),
            ("source_sha", "bad"),
            ("sha256", "bad"),
            ("size", True),
            ("size", 0),
            ("size", self.policy.maximum_download_bytes + 1),
            ("schema_version", True),
        )
        for field, value in fields:
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(PortableUpdateError),
            ):
                verify_manifest(
                    *self.encoded({**self.payload, field: value}), self.policy, "0.5.0"
                )

    def test_release_api_tag_cannot_select_a_different_signed_release(self):
        with self.assertRaises(PortableUpdateError):
            verify_manifest(*self.encoded(), self.policy, "0.5.0", "v0.5.2")

    def test_duplicate_and_unknown_fields_and_large_documents_are_rejected(self):
        data, _ = self.encoded()
        variants = (
            data[:-1] + b', "version": "0.5.2"}',
            data[:-1] + b', "command": "run arbitrary code"}',
            data + b" " * 32768,
        )
        for variant in variants:
            with (
                self.subTest(length=len(variant)),
                self.assertRaises(PortableUpdateError),
            ):
                verify_manifest(variant, self.key.sign(variant), self.policy, "0.5.0")

    def test_binary_is_rechecked_and_rejects_a_symlink(self):
        release = verify_manifest(*self.encoded(), self.policy, "0.5.0")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Clarify.exe"
            path.write_bytes(self.binary)
            verify_binary(path, release)
            path.write_bytes(b"MZ-tampered-binary")
            with self.assertRaises(PortableUpdateError):
                verify_binary(path, release)
            path.write_bytes(self.binary)
            link = Path(directory) / "link.exe"
            try:
                link.symlink_to(path)
            except OSError:
                return  # Windows accounts can lack the symlink privilege.
            with self.assertRaises(PortableUpdateError):
                verify_binary(link, release)


class DownloadTests(ReleaseFixture):
    def test_interrupted_and_oversized_downloads_leave_no_executable(self):
        release = verify_manifest(*self.encoded(), self.policy, "0.5.0")
        for chunks in ((self.binary[:3], requests_error()), (self.binary + b"extra",)):
            with (
                self.subTest(chunks=chunks),
                tempfile.TemporaryDirectory() as directory,
            ):
                response = Mock(status_code=200, headers={})

                def stream(chunk_size):
                    for chunk in chunks:
                        if isinstance(chunk, Exception):
                            raise chunk
                        yield chunk

                response.iter_content.side_effect = stream
                session = Mock()
                session.__enter__ = Mock(return_value=session)
                session.__exit__ = Mock(return_value=False)
                session.get.return_value = response
                transport = PortableReleaseTransport(self.policy, lambda: session)
                with self.assertRaises(PortableUpdateError):
                    transport.download(release, Path(directory), threading.Event())
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_redirect_is_checked_before_an_insecure_request(self):
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.return_value = Mock(
            status_code=302, headers={"Location": "http://example.com/file"}
        )
        transport = PortableReleaseTransport(self.policy, lambda: session)
        with self.assertRaises(PortableUpdateError):
            transport._bytes("https://github.com/file", 100, threading.Event())
        self.assertEqual(session.get.call_count, 1)

    def test_successful_download_keeps_signed_metadata_and_reports_progress(self):
        release = verify_manifest(*self.encoded(), self.policy, "0.5.0")
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.return_value = Mock(
            status_code=200,
            headers={},
            iter_content=Mock(return_value=iter([self.binary])),
        )
        with tempfile.TemporaryDirectory() as directory:
            progress = []
            path = PortableReleaseTransport(self.policy, lambda: session).download(
                release, Path(directory), threading.Event(), progress.append
            )
            self.assertEqual(path.read_bytes(), self.binary)
            self.assertEqual(
                (Path(directory) / "Clarify-portable-update.json").read_bytes(),
                release.manifest,
            )
            self.assertEqual(progress[-1], 100)


class ReplacementTests(ReleaseFixture):
    def test_replacement_retains_the_previous_version_and_restarts_once(self):
        release = verify_manifest(*self.encoded(), self.policy, "0.5.0")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "ClarifyVoice.exe"
            candidate = Path(directory) / "download.exe"
            target.write_bytes(b"MZ-previous-version")
            candidate.write_bytes(self.binary)
            launch = Mock(return_value=object())
            backup = replace_and_restart(
                release,
                candidate,
                target,
                "a" * 32,
                hashlib.sha256(target.read_bytes()).hexdigest(),
                launch,
                lambda child: True,
            )
            self.assertEqual(target.read_bytes(), self.binary)
            self.assertEqual(backup.read_bytes(), b"MZ-previous-version")
            launch.assert_called_once_with(target)

    def test_failed_startup_restores_previous_executable(self):
        release = verify_manifest(*self.encoded(), self.policy, "0.5.0")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "Clarify.exe"
            candidate = Path(directory) / "download.exe"
            target.write_bytes(b"MZ-previous-version")
            candidate.write_bytes(self.binary)
            launch = Mock(return_value=object())
            with self.assertRaises(PortableUpdateError):
                replace_and_restart(
                    release,
                    candidate,
                    target,
                    "b" * 32,
                    hashlib.sha256(target.read_bytes()).hexdigest(),
                    launch,
                    lambda child: False,
                )
            self.assertEqual(target.read_bytes(), b"MZ-previous-version")
            self.assertEqual(launch.call_count, 2)

    def test_changed_candidate_or_installation_never_replaces_or_launches(self):
        release = verify_manifest(*self.encoded(), self.policy, "0.5.0")
        for candidate_bytes, original_sha in (
            (self.binary + b"tampered", "0" * 64),
            (self.binary, "0" * 64),
        ):
            with (
                self.subTest(candidate=candidate_bytes),
                tempfile.TemporaryDirectory() as directory,
            ):
                target = Path(directory) / "Clarify.exe"
                candidate = Path(directory) / "download.exe"
                target.write_bytes(b"MZ-previous-version")
                candidate.write_bytes(candidate_bytes)
                launch = Mock()
                with self.assertRaises(PortableUpdateError):
                    replace_and_restart(
                        release,
                        candidate,
                        target,
                        "c" * 32,
                        original_sha,
                        launch,
                        lambda child: True,
                    )
                self.assertEqual(target.read_bytes(), b"MZ-previous-version")
                launch.assert_not_called()


def requests_error():
    import requests

    return requests.ConnectionError("Injected download interruption")
