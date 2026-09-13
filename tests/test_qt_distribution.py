import io
import json
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from scripts.qt_distribution import (
    digest,
    download_verified,
    notice_entries,
    source_url,
)


class QtDistributionTests(unittest.TestCase):
    def test_sources_use_the_reviewed_version_and_official_host(self):
        manifest = json.loads(
            (
                Path(__file__).resolve().parents[1] / "scripts/qt_sources.json"
            ).read_text()
        )
        self.assertEqual(len(manifest["archives"]), 6)
        for entry in manifest["archives"]:
            self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
            url = source_url(entry["name"], manifest["version"])
            self.assertTrue(url.startswith("https://download.qt.io/official_releases/"))
            self.assertTrue(url.endswith("-6.11.1.tar.xz"))

    def test_verified_cache_is_reused_but_corruption_fails_closed(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.tar.xz"
            path.write_bytes(b"fixture")
            with patch("scripts.qt_distribution.requests.get") as get:
                download_verified("https://unused.invalid", path, digest(path))
                get.assert_not_called()
                with self.assertRaisesRegex(ValueError, "Cached source checksum"):
                    download_verified("https://unused.invalid", path, "0" * 64)
            self.assertEqual(path.read_bytes(), b"fixture")

    def test_failed_download_is_not_promoted(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.tar.xz"
            response = Mock()
            response.iter_content.return_value = [b"wrong"]
            with patch("scripts.qt_distribution.requests.get") as get:
                get.return_value.__enter__.return_value = response
                with self.assertRaisesRegex(ValueError, "Source checksum"):
                    download_verified("https://unused.invalid", path, "0" * 64)
            self.assertFalse(path.exists())
            self.assertFalse(path.with_suffix(".xz.part").exists())

    def test_attribution_includes_referenced_license_without_extracting_files(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.tar.xz"
            files = {
                "qt/LICENSES/LGPL-3.0-only.txt": "test LGPL fixture",
                "qt/3rdparty/qt_attribution.json": json.dumps(
                    {"LicenseFile": "terms.txt"}
                ),
                "qt/3rdparty/terms.txt": "test custom terms",
                "qt/source.cpp": "not a notice",
            }
            with tarfile.open(path, "w:xz") as archive:
                for name, value in files.items():
                    data = value.encode()
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            notices = dict(notice_entries(path))
            self.assertEqual(notices["qt/3rdparty/terms.txt"], "test custom terms")
            self.assertNotIn("qt/source.cpp", notices)
            self.assertFalse((Path(temporary) / "qt").exists())

    def test_builds_and_release_tracks_ship_qt_notices_and_sources(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("build.ps1", "deploy.ps1"):
            script = (root / "scripts" / name).read_text()
            self.assertIn("qt_distribution.py", script)
            self.assertIn("Clarify-qt-NOTICES.txt", script)
        for name in ("release.yml", "community-release.yml"):
            workflow = (root / ".github/workflows" / name).read_text()
            self.assertIn("dist\\Clarify-qt-NOTICES.txt", workflow)
            self.assertEqual(workflow.count("dist/Clarify-qt-sources.zip"), 2)
            self.assertIn("dist\\Clarify-qt-sources.zip `", workflow)


if __name__ == "__main__":
    unittest.main()
