import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

import requests

from update_security import (
    IntegrityError,
    ManifestError,
    SignatureError,
    SignatureIdentity,
    UpdatePolicy,
    UpdateTransportError,
    download_atomic,
    parse_release_manifest,
    prepare_update,
    launch_prepared_update,
    PreparedUpdate,
)


POLICY = UpdatePolicy(
    repository="jvictormaynard/clarify",
    channel="stable",
    manifest_asset="Clarify-release-manifest.cab",
    installer_asset="Clarify-windows-x64.msi",
    publisher_common_name="Joao Victor Maynard Mota",
    require_rfc3161_timestamp=True,
    maximum_download_bytes=1024 * 1024,
)


def manifest_bytes(version="0.2.0", **asset_overrides):
    asset = {
        "name": POLICY.installer_asset,
        "url": (
            "https://github.com/jvictormaynard/clarify/"
            f"releases/download/v{version}/{POLICY.installer_asset}"
        ),
        "sha256": "a" * 64,
        "size": 3,
        "publisher_common_name": POLICY.publisher_common_name,
    }
    asset.update(asset_overrides)
    return json.dumps(
        {
            "schema_version": 1,
            "version": version,
            "release_tag": f"v{version}",
            "channel": "stable",
            "asset": asset,
        },
        separators=(",", ":"),
    ).encode()


class AtomicDownloadTests(unittest.TestCase):
    class Response:
        def __init__(self, content, *, content_length=None):
            self.content = content
            self.url = "https://objects.githubusercontent.com/signed"
            self.headers = {}
            if content_length is not None:
                self.headers["Content-Length"] = str(content_length)

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            del chunk_size
            yield self.content[:1]
            yield self.content[1:]

    def test_download_is_published_only_after_size_and_checksum_match(self):
        data = b"msi"
        session = SimpleNamespace(
            get=Mock(return_value=self.Response(data, content_length=3))
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "update.msi"
            download_atomic(
                POLICY.manifest_url,
                destination,
                maximum_bytes=10,
                expected_size=3,
                expected_sha256=hashlib.sha256(data).hexdigest(),
                session=session,
            )
            self.assertEqual(destination.read_bytes(), data)
            self.assertFalse(Path(str(destination) + ".part").exists())

    def test_interrupted_or_tampered_download_removes_partial_file(self):
        session = SimpleNamespace(get=Mock(return_value=self.Response(b"bad")))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "update.msi"
            with self.assertRaises(IntegrityError):
                download_atomic(
                    POLICY.manifest_url,
                    destination,
                    maximum_bytes=10,
                    expected_size=3,
                    expected_sha256="0" * 64,
                    session=session,
                )
            self.assertFalse(destination.exists())
            self.assertFalse(Path(str(destination) + ".part").exists())


class PrepareUpdateTests(unittest.TestCase):
    def test_transport_failure_is_exposed_as_typed_update_error(self):
        def unavailable(*_args, **_kwargs):
            raise requests.ConnectionError("network unavailable")

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(UpdateTransportError) as raised:
                prepare_update(
                    "0.1.2",
                    Path(directory),
                    policy=POLICY,
                    downloader=unavailable,
                )

        self.assertEqual(
            str(raised.exception), "secure update service is temporarily unavailable"
        )
        self.assertIsInstance(raised.exception.__cause__, requests.ConnectionError)

    def test_verifies_container_before_manifest_and_installer_after_download(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            calls = []

            def downloader(url, destination, **kwargs):
                calls.append(("download", url, destination.name, kwargs))
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(
                    b"cab" if destination.suffix == ".cab" else b"msi"
                )
                return destination

            def verifier(path, publisher, *, require_timestamp):
                calls.append(("verify", path.name, publisher))
                self.assertTrue(require_timestamp)
                return SignatureIdentity(publisher, "AB" * 20, "Trusted TSA", "CD" * 20)

            def extractor(cab, output):
                calls.append(("extract", cab.name))
                output.mkdir(parents=True)
                manifest = output / "release-manifest.json"
                manifest.write_bytes(manifest_bytes())
                return manifest

            prepared = prepare_update(
                "0.1.2",
                cache,
                policy=POLICY,
                signature_verifier=verifier,
                manifest_extractor=extractor,
                downloader=downloader,
            )
            self.assertEqual(prepared.manifest.version, "0.2.0")
            self.assertEqual(prepared.installer_path.read_bytes(), b"msi")
            self.assertEqual(
                prepared.installer_path,
                cache / "0.2.0" / POLICY.installer_asset,
            )
            self.assertEqual(list(cache.glob(".update-staging-*")), [])
            self.assertEqual(
                [call[0] for call in calls],
                ["download", "verify", "extract", "download", "verify"],
            )

    def test_current_version_does_not_download_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            downloads = []

            def downloader(url, destination, **kwargs):
                downloads.append(destination.name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"cab")
                return destination

            def extractor(cab, output):
                del cab
                output.mkdir(parents=True)
                manifest = output / "release-manifest.json"
                manifest.write_bytes(manifest_bytes("0.1.2"))
                return manifest

            prepared = prepare_update(
                "0.1.2",
                cache,
                policy=POLICY,
                signature_verifier=lambda path, publisher, require_timestamp: (
                    SignatureIdentity(publisher, "AB" * 20, "Trusted TSA", "CD" * 20)
                ),
                manifest_extractor=extractor,
                downloader=downloader,
            )
            self.assertIsNone(prepared)
            self.assertEqual(downloads, [POLICY.manifest_asset])
            self.assertEqual(list(cache.rglob(POLICY.manifest_asset)), [])
            self.assertEqual(list(cache.glob(".update-staging-*")), [])

    def test_cab_verification_failure_cleans_staging_and_preserves_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            verified_installer = cache / "0.2.0" / POLICY.installer_asset
            verified_installer.parent.mkdir(parents=True)
            verified_installer.write_bytes(b"previously-verified")

            def downloader(url, destination, **kwargs):
                del url, kwargs
                destination.write_bytes(b"untrusted-cab")
                return destination

            def reject_signature(path, publisher, *, require_timestamp):
                del path, publisher, require_timestamp
                raise SignatureError("publisher mismatch")

            with self.assertRaises(SignatureError):
                prepare_update(
                    "0.1.2",
                    cache,
                    policy=POLICY,
                    signature_verifier=reject_signature,
                    downloader=downloader,
                )
            self.assertEqual(verified_installer.read_bytes(), b"previously-verified")
            self.assertEqual(list(cache.rglob(POLICY.manifest_asset)), [])
            self.assertEqual(list(cache.glob(".update-staging-*")), [])

    def test_manifest_extraction_or_parse_failure_cleans_staged_cab(self):
        for failure in ("extract", "parse"):
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as directory,
            ):
                cache = Path(directory)

                def downloader(url, destination, **kwargs):
                    del url, kwargs
                    destination.write_bytes(b"signed-cab")
                    return destination

                def verifier(path, publisher, *, require_timestamp):
                    del path, require_timestamp
                    return SignatureIdentity(
                        publisher, "AB" * 20, "Trusted TSA", "CD" * 20
                    )

                def extractor(cab, output):
                    del cab
                    if failure == "extract":
                        raise ManifestError("cannot extract")
                    output.mkdir(parents=True)
                    manifest = output / "release-manifest.json"
                    manifest.write_bytes(b"not-json")
                    return manifest

                with self.assertRaises(ManifestError):
                    prepare_update(
                        "0.1.2",
                        cache,
                        policy=POLICY,
                        signature_verifier=verifier,
                        manifest_extractor=extractor,
                        downloader=downloader,
                    )
                self.assertEqual(list(cache.rglob(POLICY.manifest_asset)), [])
                self.assertEqual(list(cache.glob(".update-staging-*")), [])

    def test_msi_signature_failure_preserves_previous_verified_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            verified_installer = cache / "0.2.0" / POLICY.installer_asset
            verified_installer.parent.mkdir(parents=True)
            verified_installer.write_bytes(b"previously-verified")

            def downloader(url, destination, **kwargs):
                del url, kwargs
                destination.write_bytes(
                    b"cab" if destination.suffix == ".cab" else b"untrusted-msi"
                )
                return destination

            def verifier(path, publisher, *, require_timestamp):
                del require_timestamp
                if path.suffix == ".msi":
                    raise SignatureError("publisher mismatch")
                return SignatureIdentity(publisher, "AB" * 20, "Trusted TSA", "CD" * 20)

            def extractor(cab, output):
                del cab
                output.mkdir(parents=True)
                manifest = output / "release-manifest.json"
                manifest.write_bytes(manifest_bytes())
                return manifest

            with self.assertRaises(SignatureError):
                prepare_update(
                    "0.1.2",
                    cache,
                    policy=POLICY,
                    signature_verifier=verifier,
                    manifest_extractor=extractor,
                    downloader=downloader,
                )
            self.assertEqual(verified_installer.read_bytes(), b"previously-verified")
            self.assertEqual(list(cache.rglob("*.msi")), [verified_installer])
            self.assertEqual(list(cache.glob(".update-staging-*")), [])


class ReleaseManifestScriptTests(unittest.TestCase):
    def test_generated_manifest_round_trips_through_strict_parser(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            installer = Path(directory) / POLICY.installer_asset
            output = Path(directory) / "release-manifest.json"
            installer.write_bytes(b"msi")
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts" / "create_release_manifest.py"),
                    "--version",
                    "0.2.0",
                    "--installer",
                    str(installer),
                    "--output",
                    str(output),
                    "--policy",
                    str(root / "distribution" / "update-policy.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=root,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            parsed = parse_release_manifest(output.read_bytes(), POLICY)
            self.assertEqual(parsed.asset.sha256, hashlib.sha256(b"msi").hexdigest())


class LaunchPreparedUpdateTests(unittest.TestCase):
    def test_revalidates_bytes_and_signature_immediately_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            installer = Path(directory) / POLICY.installer_asset
            installer.write_bytes(b"msi")
            manifest = parse_release_manifest(
                manifest_bytes(sha256=hashlib.sha256(b"msi").hexdigest()), POLICY
            )
            prepared = PreparedUpdate(
                manifest=manifest,
                installer_path=installer,
                signer=SignatureIdentity(
                    POLICY.publisher_common_name,
                    "AB" * 20,
                    "Trusted TSA",
                    "CD" * 20,
                ),
            )
            verifier = Mock(return_value=prepared.signer)
            runner = Mock()
            with patch("update_security.platform.system", return_value="Windows"):
                launch_prepared_update(
                    prepared, signature_verifier=verifier, runner=runner
                )
            verifier.assert_called_once_with(
                installer,
                POLICY.publisher_common_name,
                require_timestamp=True,
            )
            runner.assert_called_once()

            installer.write_bytes(b"bad")
            with patch("update_security.platform.system", return_value="Windows"):
                with self.assertRaises(IntegrityError):
                    launch_prepared_update(
                        prepared, signature_verifier=verifier, runner=runner
                    )


if __name__ == "__main__":
    unittest.main()
