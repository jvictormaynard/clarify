"""Node module identity at the trusted Settings runner boundary."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts import trusted_ci


class TrustedPlaywrightTests(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            self.skipTest("Node is required for the module-resolution regression")
        self.temporary = tempfile.TemporaryDirectory(prefix="clarify-playwright-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.trusted = self.root / "trusted"
        self.execution = self.root / "execution"
        self.calls = []
        packages = ("@playwright/test", "playwright", "playwright-core")
        lock = {"packages": {}}
        for side, origin in ((self.trusted, "MAIN"), (self.execution, "PAYLOAD")):
            for name in packages:
                package = side / "desktop/node_modules" / name
                package.mkdir(parents=True)
                (package / "package.json").write_text(
                    json.dumps({"name": name, "version": "1.63.0", "main": "index.js"}),
                    encoding="utf-8",
                )
                (package / "index.js").write_text(
                    "module.exports = { origin: " + json.dumps(origin) + " };",
                    encoding="utf-8",
                )
                lock["packages"]["node_modules/" + name] = {"version": "1.63.0"}
        (self.trusted / "desktop/package-lock.json").write_text(
            json.dumps(lock), encoding="utf-8"
        )
        self.config = self.execution / "desktop/playwright.config.cjs"
        self.config.write_text("module.exports = {};\n", encoding="utf-8")
        # The MAIN CLI and a consumer beside the MAIN config/oracles must load
        # the same physical modules, even when both roots have equal versions.
        (self.trusted / "desktop/node_modules/playwright/cli.js").write_text(
            """const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const path = require('node:path');
const consumer = createRequire(path.resolve('playwright.config.cjs'));
for (const name of ['@playwright/test', 'playwright', 'playwright-core']) {
  const expected = require(name);
  assert.equal(expected.origin, 'MAIN');
  assert.strictEqual(consumer(name), expected, `Second module instance: ${name}`);
  assert.equal(consumer.resolve(name), require.resolve(name));
}
console.log('one MAIN runner');
""",
            encoding="utf-8",
        )
        (self.execution / "desktop/node_modules/playwright/cli.js").write_text(
            "throw new Error('The payload CLI must never execute');",
            encoding="utf-8",
        )
        self.job = object.__new__(trusted_ci.Job)
        self.job.trusted = self.trusted
        self.job.execution = self.execution
        self.job.node = Path(self.node)
        self.job.python = Path(sys.executable)
        self.job.metadata = self.root / "metadata"
        self.job.metadata.mkdir()
        self.job.env = dict(os.environ)
        self.job.tools = {}
        self.job.runtime_python = lambda: Path(sys.executable)
        self.job.npm = self.unexpected_install

        def node_tool(area, relative, *args, **kwargs):
            self.calls.append((area, relative, args))
            if relative == "playwright/cli.js" and args[0] == "test":
                return trusted_ci.Job.node_tool(
                    self.job, area, relative, *args, **kwargs
                )
            # No browser/dependency install, build or application is executed.

        self.job.node_tool = node_tool

    def unexpected_install(self, *args, **kwargs):
        self.fail("The regression must not install any dependency")

    def test_main_cli_and_execution_imports_share_one_physical_runner(self):
        try:
            self.job.settings()
        except subprocess.CalledProcessError:
            self.fail(
                "\n".join(
                    path.read_text(encoding="utf-8")
                    for path in (self.job.metadata / "logs").glob("*.log")
                )
            )
        logs = list((self.job.metadata / "logs").glob("*.log"))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].read_text(encoding="utf-8").strip(), "one MAIN runner")
        self.assertEqual(
            self.config.read_text(encoding="utf-8"), "module.exports = {};\n"
        )

    def test_a_second_call_reuses_only_the_known_main_links(self):
        self.job.settings()
        self.job.settings()
        self.assertEqual(len(list((self.job.metadata / "logs").glob("*.log"))), 2)
        for name in ("@playwright/test", "playwright", "playwright-core"):
            self.assertEqual(
                (self.execution / "desktop/node_modules" / name).resolve(),
                (self.trusted / "desktop/node_modules" / name).resolve(),
            )

    def test_a_main_lock_mismatch_blocks_before_rebinding_any_package(self):
        manifest = self.trusted / "desktop/node_modules/playwright-core/package.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["version"] = "0.0.0"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differs from the MAIN lock"):
            self.job.settings()
        for name in ("@playwright/test", "playwright", "playwright-core"):
            package = self.execution / "desktop/node_modules" / name
            self.assertFalse(package.is_symlink())
            self.assertIn("PAYLOAD", (package / "index.js").read_text(encoding="utf-8"))
        self.assertFalse((self.job.metadata / "logs").exists())

    def test_an_unknown_import_link_blocks_without_removing_its_target(self):
        package = self.execution / "desktop/node_modules/playwright-core"
        outside = self.root / "unexpected-package"
        package.rename(outside)
        package.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Unknown Playwright import link"):
            self.job.settings()
        self.assertIn("PAYLOAD", (outside / "index.js").read_text(encoding="utf-8"))
        self.assertFalse(
            (self.execution / "desktop/node_modules/playwright").is_symlink()
        )
        self.assertFalse((self.job.metadata / "logs").exists())

    def test_settings_without_tests_does_not_change_dependency_resolution(self):
        self.job.settings(test=False)
        self.assertFalse(
            any(relative == "playwright/cli.js" for _, relative, _ in self.calls)
        )
        for name in ("@playwright/test", "playwright", "playwright-core"):
            package = self.execution / "desktop/node_modules" / name
            self.assertFalse(package.is_symlink())
            self.assertIn("PAYLOAD", (package / "index.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
