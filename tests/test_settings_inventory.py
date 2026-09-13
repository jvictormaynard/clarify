import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.settings_inventory import (
    dependency_notices,
    inventory,
    license_texts,
    merge_bom,
)


ROOT = Path(__file__).resolve().parents[1]


class SettingsInventoryTests(unittest.TestCase):
    def test_vendored_texts_match_pinned_hashes(self):
        root = ROOT / "desktop/licenses"
        manifest = json.loads((root / "manifest.json").read_text())
        self.assertTrue(manifest)
        for ref, entries in manifest.items():
            self.assertTrue(entries, ref)
            for entry in entries:
                path = (root / entry["file"]).resolve()
                self.assertTrue(path.is_relative_to(root.resolve()))
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"]
                )
                self.assertTrue(entry["source"].startswith("https://"))

    def test_unknown_missing_license_and_tampering_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "dependency"
            dependency.mkdir()
            (root / "licenses").mkdir()
            manifest = root / "licenses/manifest.json"
            manifest.write_text("{}")
            with self.assertRaisesRegex(ValueError, "Review missing"):
                dependency_notices(root, "pkg:npm/test@1", dependency)
            notice = root / "licenses/LICENSE"
            notice.write_text("license fixture")
            entry = {
                "file": "LICENSE",
                "source": "https://example.test/LICENSE",
                "sha256": "0" * 64,
            }
            manifest.write_text(json.dumps({"pkg:npm/test@1": [entry]}))
            with self.assertRaisesRegex(ValueError, "checksum"):
                dependency_notices(root, "pkg:npm/test@1", dependency)
            entry["sha256"] = hashlib.sha256(notice.read_bytes()).hexdigest()
            manifest.write_text(json.dumps({"pkg:npm/test@1": [entry]}))
            self.assertEqual(
                dependency_notices(root, "pkg:npm/test@1", dependency)[0][1],
                "license fixture",
            )

    def test_explicit_license_cannot_escape_dependency_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dependency").mkdir()
            (root / "LICENSE").write_text("not owned by this dependency")
            with self.assertRaisesRegex(ValueError, "escapes"):
                license_texts(root / "dependency", "../LICENSE")

    def test_npm_and_cargo_graph_preserve_runtime_and_build_scopes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "node_modules/example"
            package.mkdir(parents=True)
            (package / "LICENSE").write_text("npm license fixture")
            npm = {
                "metadata": {
                    "component": {"bom-ref": "root", "purl": "pkg:npm/settings@1"}
                },
                "components": [
                    {
                        "bom-ref": "example",
                        "purl": "pkg:npm/example@1",
                        "type": "library",
                        "name": "example",
                        "version": "1",
                        "properties": [
                            {
                                "name": "cdx:npm:package:path",
                                "value": "node_modules/example",
                            }
                        ],
                    }
                ],
                "dependencies": [
                    {"ref": "root", "dependsOn": ["example"]},
                    {"ref": "example", "dependsOn": []},
                ],
            }
            packages, nodes = [], []
            for name in ("root", "runtime", "build", "macro"):
                path = root / name
                path.mkdir()
                (path / "LICENSE").write_text(f"{name} license fixture")
                packages.append(
                    {
                        "id": name,
                        "name": name,
                        "version": "1.0",
                        "source": "registry+fixture",
                        "manifest_path": str(path / "Cargo.toml"),
                        "license": "MIT/Apache-2.0",
                        "targets": [
                            {"kind": ["proc-macro" if name == "macro" else "lib"]}
                        ],
                    }
                )
                nodes.append({"id": name, "deps": []})
            nodes[0]["deps"] = [
                {"pkg": name, "dep_kinds": [{"kind": kind}]}
                for name, kind in (
                    ("runtime", None),
                    ("build", "build"),
                    ("macro", None),
                )
            ]
            cargo = {"packages": packages, "resolve": {"root": "root", "nodes": nodes}}
            bom, notices = inventory(root, npm, cargo)
            components = {c["name"]: c for c in bom["components"]}
            self.assertEqual(components["runtime"]["scope"], "required")
            self.assertEqual(components["build"]["scope"], "excluded")
            self.assertEqual(components["macro"]["scope"], "excluded")
            self.assertEqual(
                components["runtime"]["licenses"], [{"expression": "MIT OR Apache-2.0"}]
            )
            self.assertIn("npm license fixture", notices)
            self.assertIn(
                "https://crates.io/api/v1/crates/runtime/1.0/download", notices
            )
            refs = {
                bom["metadata"]["component"]["bom-ref"],
                *(c["bom-ref"] for c in bom["components"]),
            }
            for edge in bom["dependencies"]:
                self.assertIn(edge["ref"], refs)
                self.assertLessEqual(set(edge["dependsOn"]), refs)
            base = {
                "metadata": {"component": {"bom-ref": "python-app"}},
                "components": [{"bom-ref": "sox", "name": "SoX"}],
                "dependencies": [{"ref": "python-app", "dependsOn": ["sox"]}],
            }
            merged = merge_bom(base, bom)
            self.assertIn("sox", {c["bom-ref"] for c in merged["components"]})
            self.assertEqual(merged, merge_bom(copy.deepcopy(merged), bom))


if __name__ == "__main__":
    unittest.main()
