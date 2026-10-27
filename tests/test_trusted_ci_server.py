"""Server subprocess imports without a database, network or dependency install."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import trusted_ci


class TrustedServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="clarify-server-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.execution = self.root / "execution"
        self.server = self.execution / "server"
        self.hostile = self.root / "hostile"
        self.calls = []
        self.logs = []
        files = {
            "execution/shared/__init__.py": "",
            "execution/shared/localization.py": "ORIGIN = 'execution'\n",
            "execution/server/cloud/__init__.py": "",
            "execution/server/cloud/service/__init__.py": "",
            "execution/server/cloud/service/accounts.py": "from shared.localization import ORIGIN\nassert ORIGIN == 'execution'\n",
            "execution/server/django/__init__.py": """import json, os
from pathlib import Path

def setup():
    from cloud.service import accounts
    from shared import localization
    assert accounts.ORIGIN == 'execution'
    assert Path.cwd().name == 'server'

def observation(stage):
    from shared import localization
    print(json.dumps(dict(stage=stage, cwd=os.getcwd(),
        shared_file=localization.__file__, pythonpath=os.environ.get('PYTHONPATH'))))
""",
            "execution/server/django/__main__.py": """import sys
from django import setup, observation
assert sys.argv[1:] == ['makemigrations', '--check', '--dry-run', '--settings', 'cloud.settings']
setup()
observation('makemigrations')
""",
            "execution/server/django/test/__init__.py": "",
            "execution/server/django/test/runner.py": """from pathlib import Path
from django import observation

class DiscoverRunner:
    def __init__(self, *, interactive):
        assert interactive is False

    def run_tests(self, labels):
        assert labels == ['cloud.service.tests']
        observation('DiscoverRunner')
        return int(Path('reject-runner').exists())
""",
            "hostile/shared/__init__.py": "",
            "hostile/shared/localization.py": "raise RuntimeError('Hostile shared import')\n",
            "hostile/hostile_only_for_server_probe.py": "raise RuntimeError('Hostile path')\n",
            "hostile/sitecustomize.py": "from pathlib import Path\nPath(__file__).with_name('loaded').write_text('unsafe')\n",
        }
        for name, content in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.job = object.__new__(trusted_ci.Job)
        self.job.execution = self.execution
        self.job.python = Path(sys.executable)
        self.job.source_sha = "a" * 40
        self.job.metadata = self.root / "metadata"
        self.job.metadata.mkdir()
        self.job.tools = {}
        self.job.env = {**os.environ, "PYTHONPATH": str(self.hostile)}

        def command(args, **kwargs):
            self.calls.append((list(map(str, args)), kwargs))
            is_django = args[1:3] == ["-m", "django"] or (
                len(args) > 2 and args[1] == "-c" and "DiscoverRunner" in args[2]
            )
            if is_django:
                log = trusted_ci.Job.command(self.job, args, **kwargs)
                self.logs.append(log)
                return log
            # pip, other suites, sync helpers and Docker are recorded, not run.

        self.job.command = command

    def run_server(self):
        # The existing health gate sees a local in-memory response, not HTTP.
        with patch.object(
            trusted_ci,
            "urlopen",
            side_effect=lambda *a, **k: io.BytesIO(b'{"status":"ok"}'),
        ):
            self.job.server()

    def test_django_commands_import_shared_from_validated_execution_root(self):
        try:
            self.run_server()
        except subprocess.CalledProcessError:
            self.fail(
                "\n".join(
                    path.read_text(encoding="utf-8")
                    for path in (self.job.metadata / "logs").glob("*.log")
                )
            )
        observed = [json.loads(path.read_text(encoding="utf-8")) for path in self.logs]
        self.assertEqual(
            [row["stage"] for row in observed], ["makemigrations", "DiscoverRunner"]
        )
        for row in observed:
            self.assertEqual(Path(row["cwd"]), self.server)
            self.assertEqual(row["pythonpath"], str(self.execution))
            self.assertEqual(
                Path(row["shared_file"]), self.execution / "shared/localization.py"
            )
        self.assertFalse((self.hostile / "loaded").exists())

    def test_explicit_path_is_scoped_to_only_the_two_django_calls(self):
        original = dict(self.job.env)
        self.run_server()
        overrides = [
            (args, kwargs) for args, kwargs in self.calls if kwargs.get("extra_env")
        ]
        self.assertEqual(len(overrides), 2)
        self.assertTrue(
            all(
                kwargs["extra_env"] == {"PYTHONPATH": str(self.execution)}
                for _, kwargs in overrides
            )
        )
        self.assertEqual(self.job.env, original)
        self.assertEqual(self.job.env["PYTHONPATH"], str(self.hostile))
        self.assertTrue(any(args[:2] == ["docker", "exec"] for args, _ in self.calls))
        self.assertEqual(self.calls[-1][0][:3], ["docker", "rm", "-f"])

    def test_hostile_inherited_pythonpath_stays_removed_for_other_commands(self):
        log = trusted_ci.Job.command(
            self.job,
            [
                self.job.python,
                "-c",
                "import os, importlib.util; assert 'PYTHONPATH' not in os.environ; assert importlib.util.find_spec('hostile_only_for_server_probe') is None; print('filtered')",
            ],
            cwd=self.server,
        )
        self.assertEqual(log.read_text(encoding="utf-8").strip(), "filtered")
        self.assertFalse((self.hostile / "loaded").exists())

    def test_discoverrunner_failure_still_blocks_the_docker_gate(self):
        (self.server / "reject-runner").touch()
        with self.assertRaises(subprocess.CalledProcessError) as failure:
            self.run_server()
        self.assertEqual(failure.exception.returncode, 1)
        self.assertEqual(len(self.logs), 1)
        self.assertEqual(
            json.loads(self.logs[0].read_text(encoding="utf-8"))["stage"],
            "makemigrations",
        )
        self.assertFalse(any(args[0] == "docker" for args, _ in self.calls))


if __name__ == "__main__":
    unittest.main()
