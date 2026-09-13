import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_PATH = (
    ROOT / ".agents" / "skills" / "clarify-release" / "scripts" / "release_preflight.py"
)


def load_preflight():
    spec = importlib.util.spec_from_file_location(
        "clarify_release_preflight", PREFLIGHT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load release preflight module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREFLIGHT = load_preflight()


class ReleasePreflightVersionTests(unittest.TestCase):
    def test_qt_sources_are_required_in_both_release_tracks(self):
        for assets in (
            PREFLIGHT.SIGNED_REQUIRED_ASSETS,
            PREFLIGHT.COMMUNITY_REQUIRED_ASSETS,
        ):
            self.assertIn("Clarify-qt-sources.zip", assets)
        for name in (
            "scripts/qt_distribution.py",
            "scripts/qt_sources.json",
            "docs/qt-distribution.md",
        ):
            self.assertIn(name, PREFLIGHT.REQUIRED_FILES)

    @staticmethod
    def write_metadata(root, module_version, package_version):
        (root / "version.py").write_text(
            f'"""Packaged version."""\n\n__version__ = "{module_version}"\n',
            encoding="utf-8",
        )
        (root / "package.json").write_text(
            json.dumps({"name": "clarify", "version": package_version}),
            encoding="utf-8",
        )

    def test_matching_module_and_package_versions_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_metadata(root, "1.2.3", "1.2.3")

            self.assertEqual(PREFLIGHT.version_consistency_failures(root, "1.2.3"), [])

    def test_preflight_rejects_module_or_package_version_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_metadata(root, "1.2.4", "1.2.3")
            failures = PREFLIGHT.version_consistency_failures(root, "1.2.3")
            self.assertIn(
                "version.py does not match the proposed release version", failures
            )
            self.assertNotIn(
                "package.json does not match the proposed release version", failures
            )

            self.write_metadata(root, "1.2.3", "1.2.4")
            failures = PREFLIGHT.version_consistency_failures(root, "1.2.3")
            self.assertNotIn(
                "version.py does not match the proposed release version", failures
            )
            self.assertIn(
                "package.json does not match the proposed release version", failures
            )


if __name__ == "__main__":
    unittest.main()
