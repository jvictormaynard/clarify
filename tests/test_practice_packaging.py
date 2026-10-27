"""Import practice from the explicit deployment stage, outside the checkout."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PracticePackagingTests(unittest.TestCase):
    def test_explicit_desktop_stage_contains_importable_practice_modules(self):
        script = (ROOT / "scripts/deploy.ps1").read_text(encoding="utf-8")
        desktop = ROOT / "clarify/desktop"
        with TemporaryDirectory() as directory:
            stage = Path(directory)
            destination = stage / "clarify/desktop"
            destination.mkdir(parents=True)
            shutil.copy2(ROOT / "clarify/__init__.py", stage / "clarify")
            shutil.copy2(desktop / "__init__.py", destination)
            for source in desktop.glob("qml_*.py"):
                shutil.copy2(source, destination)
            for name in re.findall(
                r'Join-Path \$repoQmlPython ["\']([^"\']+\.py)["\']', script
            ):
                shutil.copy2(desktop / name, destination)
            backend = re.search(
                r"foreach \(\$backendModule in @\((.*?)\)\)", script, re.S
            ).group(1)
            for name in re.findall(r'"([^"]+)"', backend):
                shutil.copy2(ROOT / name, stage)
            shared = re.search(
                r"foreach \(\$catalogFile in @\((.*?)\)\)", script, re.S
            ).group(1)
            (stage / "shared").mkdir()
            for name in re.findall(r'"([^"]+)"', shared):
                shutil.copy2(ROOT / "shared" / name, stage / "shared")
            shutil.copy2(ROOT / "local_asr_manifest.json", stage)
            shutil.copytree(ROOT / "local_asr_manifests", stage / "local_asr_manifests")
            command = (
                "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                "import clarify.desktop.qml_app; "
                "from clarify.desktop import dictation_practice, practice_local_model; "
                "assert all(Path(m.__file__).is_relative_to(Path(sys.argv[1])) "
                "for m in (dictation_practice, practice_local_model))"
            )
            result = subprocess.run(
                [sys.executable, "-I", "-c", command, str(stage)],
                cwd=stage,
                env={
                    **os.environ,
                    "CLARIFY_DATA_DIR": str(stage / "profile"),
                    "QT_QPA_PLATFORM": "offscreen",
                },
                capture_output=True,
                text=True,
                timeout=45,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
