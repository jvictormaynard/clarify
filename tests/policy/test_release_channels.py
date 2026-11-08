"""Channel controls use temporary source trees and fake GitHub state."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import release_delivery as delivery


class PreviewRuntimePolicyTests(unittest.TestCase):
    def test_preview_build_has_no_usable_update_policy_and_records_source(self):
        from portable_updates import load_policy, PortableUpdateError

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "distribution").mkdir()
            policy = root / "distribution/portable-update-policy.json"
            pin = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
            policy.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "channel": "stable",
                        "public_key": pin,
                        "algorithm": "Ed25519",
                        "repository": "jvictormaynard/clarify",
                        "maximum_download_bytes": 268435456,
                    }
                )
            )
            (root / "version.py").write_text('__version__ = "1.2.3"\n')
            identity = delivery.prepare_desktop_preview(root, "a" * 40, "123")
            self.assertEqual(json.loads(policy.read_text())["channel"], "preview")
            self.assertEqual(identity["source_sha"], "a" * 40)
            self.assertFalse(identity["updater_enabled"])
            self.assertEqual(identity["tag"], "preview/123-1-aaaaaaaaaaaa")
            self.assertEqual(identity["version"], "1.2.3")
            # The exact packaged version and the public key are preserved.
            self.assertEqual(json.loads(policy.read_text())["public_key"], pin)
            self.assertEqual(
                (root / "version.py").read_text(), '__version__ = "1.2.3"\n'
            )
            with patch("portable_updates.sys._MEIPASS", root, create=True):
                with self.assertRaises(PortableUpdateError):
                    load_policy()


if __name__ == "__main__":
    unittest.main()
