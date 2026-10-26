"""Load meeting modules from the explicit stage, without the source checkout."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MeetingPackagingTests(unittest.TestCase):
    def test_deployment_stage_resolves_all_meeting_imports(self):
        script = (ROOT / "scripts/deploy.ps1").read_text(encoding="utf-8")
        with TemporaryDirectory() as directory:
            stage = Path(directory)
            desktop = stage / "clarify/desktop"
            desktop.mkdir(parents=True)
            for name in (
                "clarify/__init__.py",
                "clarify/desktop/__init__.py",
                "clarify/desktop/qml_meetings.py",
            ):
                shutil.copy2(ROOT / name, stage / name)
            for variable, source, target in (
                ("backendModule", ROOT, stage),
                ("catalogFile", ROOT / "shared", stage / "shared"),
            ):
                target.mkdir(exist_ok=True)
                block = re.search(
                    r"foreach \(\$" + variable + r" in @\((.*?)\)\)", script, re.S
                ).group(1)
                for name in re.findall(r'"([^"]+)"', block):
                    shutil.copy2(source / name, target)
            shutil.copy2(ROOT / "local_asr_manifest.json", stage)
            shutil.copytree(ROOT / "local_asr_manifests", stage / "local_asr_manifests")
            command = (
                "import importlib,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
                "names=('clarify.desktop.qml_meetings','account_meetings','meeting_capture','meeting_provider',"
                "'meeting_store','meeting_workflow','windows_meeting_audio','shared.meeting_contract'); "
                "modules=[importlib.import_module(name) for name in names]; "
                "assert all(Path(m.__file__).is_relative_to(Path(sys.argv[1])) for m in modules)"
            )
            result = subprocess.run(
                [sys.executable, "-I", "-c", command, str(stage)],
                cwd=stage,
                env={
                    **os.environ,
                    "CLARIFY_DATA_DIR": str(stage / "profile"),
                    "APPDATA": str(stage / "profile"),
                    "LOCALAPPDATA": str(stage / "profile"),
                    "QT_QPA_PLATFORM": "offscreen",
                },
                capture_output=True,
                text=True,
                timeout=45,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
