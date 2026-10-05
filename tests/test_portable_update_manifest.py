"""Release signing uses generated test keys and isolated binary fixtures."""

from pathlib import Path
import tempfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from portable_updates import (
    MANIFEST_ASSET,
    SIGNATURE_ASSET,
    PortableUpdateError,
    verify_manifest,
)
from scripts.create_portable_update_manifest import create_manifest
from test_portable_updates import ReleaseFixture


class ReleaseSigningTests(ReleaseFixture):
    def test_release_output_verifies_with_the_packaged_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "Clarify.exe").write_bytes(self.binary)
            created = create_manifest(
                directory, "0.5.1", "a" * 40, self.key.private_bytes_raw(), self.policy
            )
            verified = verify_manifest(
                (directory / MANIFEST_ASSET).read_bytes(),
                (directory / SIGNATURE_ASSET).read_bytes(),
                self.policy,
                "0.5.0",
            )
            self.assertEqual(created, verified)

    def test_wrong_key_missing_source_or_non_executable_cannot_be_published(self):
        for key, source, binary in (
            (Ed25519PrivateKey.generate().private_bytes_raw(), "a" * 40, self.binary),
            (self.key.private_bytes_raw(), "main", self.binary),
            (self.key.private_bytes_raw(), "a" * 40, b"not an executable"),
        ):
            with (
                self.subTest(source=source),
                tempfile.TemporaryDirectory() as temporary,
            ):
                directory = Path(temporary)
                (directory / "Clarify.exe").write_bytes(binary)
                with self.assertRaises(PortableUpdateError):
                    create_manifest(directory, "0.5.1", source, key, self.policy)
                self.assertFalse((directory / MANIFEST_ASSET).exists())
