import json
import unittest


from update_security import (
    DowngradeError,
    ManifestError,
    UpdatePolicy,
    parse_release_manifest,
    require_newer_version,
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


class ManifestValidationTests(unittest.TestCase):
    def test_accepts_exact_expected_release_identity(self):
        manifest = parse_release_manifest(manifest_bytes(), POLICY)
        self.assertEqual(manifest.version, "0.2.0")
        self.assertEqual(manifest.asset.name, POLICY.installer_asset)

    def test_rejects_mismatched_asset_url(self):
        with self.assertRaises(ManifestError):
            parse_release_manifest(
                manifest_bytes(url="https://example.com/update.msi"), POLICY
            )

    def test_rejects_mismatched_publisher(self):
        with self.assertRaises(ManifestError):
            parse_release_manifest(
                manifest_bytes(publisher_common_name="Someone Else"), POLICY
            )

    def test_rejects_duplicate_json_fields(self):
        payload = (
            manifest_bytes()
            .decode()
            .replace('"schema_version":1', '"schema_version":1,"schema_version":1')
        )
        with self.assertRaises(ManifestError):
            parse_release_manifest(payload.encode(), POLICY)

    def test_refuses_downgrade_and_ignores_same_version(self):
        manifest = parse_release_manifest(manifest_bytes("0.2.0"), POLICY)
        self.assertFalse(require_newer_version("0.2.0", manifest))
        with self.assertRaises(DowngradeError):
            require_newer_version("0.3.0", manifest)
        self.assertTrue(require_newer_version("0.1.2", manifest))


if __name__ == "__main__":
    unittest.main()
