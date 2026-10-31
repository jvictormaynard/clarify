"""Settings cancellation stops its owned process tree before profile cleanup."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(
    sys.platform in {"win32", "linux"}, "Browser ownership requires Linux or Windows"
)
class SettingsProcessTreeTests(unittest.TestCase):
    def test_foreign_proc_permissions_do_not_hide_owned_descendants(self):
        import runpy

        supervisor = runpy.run_path(str(ROOT / "desktop/scripts/process-job.py"))
        foreign, owned = MagicMock(), MagicMock()
        foreign.name, owned.name = "1", str(os.getpid() + 100000)
        foreign.__truediv__.return_value.read_bytes.side_effect = PermissionError(
            "foreign process"
        )
        fields = [b"S", str(os.getpid()).encode(), *([b"0"] * 17), b"12345"]
        # Linux process names need not be UTF-8 and can contain closing brackets.
        owned.__truediv__.return_value.read_bytes.return_value = (
            b"123 (name ) \xff) " + b" ".join(fields)
        )
        with patch.object(
            supervisor["Path"], "iterdir", return_value=iter((foreign, owned))
        ):
            self.assertEqual(supervisor["descendants"](), {int(owned.name): b"12345"})

    def test_cancellation_stops_the_browser_runner_and_its_descendant(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required for the process-tree regression")
        helper = (ROOT / "desktop/scripts/stop-process-tree.mjs").as_uri()
        script = """
import { once } from 'node:events';
import { spawnOwned, stopProcessTree } from HELPER;
const parent = spawnOwned(process.execPath, ['-e', `
  const { spawn } = require('node:child_process');
  const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { detached: true, windowsHide: true });
  console.log(child.pid);
  setInterval(() => {}, 1000);
`], { ownDetached: true, windowsHide: true, stdio: ['ignore', 'pipe', 'inherit'] });
const timeout = setTimeout(() => { stopProcessTree(parent); process.exitCode = 1; }, 10000);
try {
  const [data] = await once(parent.stdout, 'data');
  const exited = once(parent, 'exit');
  stopProcessTree(parent);
  await exited;
  console.log(JSON.stringify({ descendant: Number(data.toString().trim()) }));
} finally {
  clearTimeout(timeout);
}
""".replace("HELPER", json.dumps(helper))
        result = subprocess.run(
            [node, "--input-type=module", "-e", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=45,
        )
        descendant = json.loads(result.stdout)["descendant"]
        self.assert_stopped(descendant)

    def assert_stopped(self, descendant):
        if os.name == "nt":
            import _winapi

            try:
                handle = _winapi.OpenProcess(0x1000 | 0x0001, False, descendant)
            except OSError as error:
                self.assertEqual(error.winerror, 87)
            else:
                try:
                    code = _winapi.GetExitCodeProcess(handle)
                    if code == 259:
                        _winapi.TerminateProcess(handle, 1)
                    self.assertNotEqual(code, 259, "The descendant is still running")
                finally:
                    _winapi.CloseHandle(handle)
        else:
            try:
                os.kill(descendant, 0)
            except ProcessLookupError:
                return
            # A killed process can remain a zombie until the host init reaps it.
            status = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(descendant)],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            self.assertTrue(not status or status.startswith("Z"))

    def test_abnormal_runner_exit_stops_its_descendant_before_returning(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required for the process owner regression")
        helper = (ROOT / "desktop/scripts/stop-process-tree.mjs").as_uri()
        script = """
import { once } from 'node:events';
import { spawnOwned, stopProcessTree } from HELPER;
const parent = spawnOwned(process.execPath, ['-e', `
  const { spawn } = require('node:child_process');
  const child = spawn(process.execPath, ['-e', 'console.log(process.pid); setInterval(() => {}, 1000)'],
    { detached: true, windowsHide: true, stdio: ['ignore', 'pipe', 'inherit'] });
  child.stdout.once('data', data => { process.stdout.write(data); process.exit(7); });
`], { ownDetached: true, stdio: ['ignore', 'pipe', 'inherit'], windowsHide: true });
let output = '';
parent.stdout.on('data', data => { output += data; });
const timeout = setTimeout(() => stopProcessTree(parent), 35000);
try {
  const [code] = await once(parent, 'close');
  console.log(JSON.stringify({ code, descendant: Number(output.trim()) }));
} finally {
  clearTimeout(timeout);
  stopProcessTree(parent);
}
""".replace("HELPER", json.dumps(helper))
        result = subprocess.run(
            [node, "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        observed = json.loads(result.stdout)
        self.assertEqual(observed["code"], 7, result.stderr)
        self.assertGreater(observed["descendant"], 0)
        self.assert_stopped(observed["descendant"])

    def test_owned_arguments_are_data_and_empty_quotes_and_slashes_survive(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required for the process owner regression")
        values = [
            "space value",
            'quoted"value',
            "trailing" + chr(92),
            "",
            "a" + chr(0xE7) + "o",
        ]
        helper = (ROOT / "desktop/scripts/stop-process-tree.mjs").as_uri()
        script = """
import { once } from 'node:events';
import { spawnOwned, stopProcessTree } from HELPER;
const parent = spawnOwned(process.execPath, ['-e', 'console.log(JSON.stringify(process.argv.slice(1)))', ...VALUES],
  { ownDetached: true, stdio: ['ignore', 'pipe', 'inherit'], windowsHide: true });
let output = '';
parent.stdout.on('data', data => { output += data; });
try {
  const [code] = await once(parent, 'close');
  if (code !== 0) throw new Error('Owned child failed: ' + code);
  process.stdout.write(output);
} finally { stopProcessTree(parent); }
""".replace("HELPER", json.dumps(helper)).replace("VALUES", json.dumps(values))
        result = subprocess.run(
            [node, "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout), values)
