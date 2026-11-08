"""Guard the Windows version resource without building or running Clarify."""

import ast
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts import windows_version


ROOT = Path(__file__).resolve().parents[2]
HAS_PYINSTALLER = importlib.util.find_spec("PyInstaller") is not None


class WindowsVersionTests(unittest.TestCase):
    def test_resource_matches_the_canonical_version_and_repository_identity(self):
        source = ROOT / "version.py"
        version = re.search(
            r'^__version__ = "([0-9.]+)"$', source.read_text("utf-8"), re.MULTILINE
        )[1]
        self.assertEqual(windows_version.read_version(source), version)
        text = windows_version.render_version_info(version)
        self.assertEqual(text, windows_version.render_version_info(version))
        tree = ast.parse(text, mode="eval")
        self.assertEqual(tree.body.func.id, "VSVersionInfo")
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        fixed = next(node for node in calls if node.func.id == "FixedFileInfo")
        fields = {item.arg: ast.literal_eval(item.value) for item in fixed.keywords}
        expected = tuple(map(int, version.split("."))) + (0,)
        self.assertEqual(fields["filevers"], expected)
        self.assertEqual(fields["prodvers"], expected)
        strings = {
            ast.literal_eval(node.args[0]): ast.literal_eval(node.args[1])
            for node in calls
            if node.func.id == "StringStruct"
        }
        self.assertEqual(
            strings,
            {
                "CompanyName": "Joao Victor Maynard Mota",
                "FileDescription": "Clarify",
                "FileVersion": version + ".0",
                "InternalName": "Clarify",
                "LegalCopyright": "Copyright (c) 2026 João Victor Maynard Mota",
                "OriginalFilename": "Clarify.exe",
                "ProductName": "Clarify",
                "ProductVersion": version + ".0",
            },
        )
        self.assertIn(strings["LegalCopyright"], (ROOT / "LICENSE").read_text("utf-8"))
        self.assertIn(
            'Manufacturer="' + strings["CompanyName"] + '"',
            (ROOT / "installer/Clarify.wxs").read_text("utf-8"),
        )

    def test_rejects_versions_that_cannot_be_encoded_without_loss(self):
        for version in (
            "",
            "1.2",
            "1.2.3.0",
            "v1.2.3",
            "01.2.3",
            "1.02.3",
            "1.2.03",
            "1.2.3-beta",
            "1.2.3+build",
            "1.2.3\n",
            "１.2.3",
            "-1.2.3",
            "65536.0.0",
            "0.65536.0",
            "0.0.65536",
        ):
            with self.subTest(version=version), self.assertRaises(ValueError):
                windows_version.render_version_info(version)
        windows_version.render_version_info("65535.65535.65535")
        windows_version.render_version_info("0.0.0")

    def test_version_source_is_a_literal_and_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "version.py"
            sentinel = Path(directory) / "executed"
            for content in (
                "",
                '__version__ = "1.2.3"\n__version__ = "2.0.0"',
                '__version__ = ".".join(["1", "2", "3"])',
                "__version__ = 123",
                '__version__ = "1.2.3"\n__version__ += ".4"',
                f'__version__ = "1.2.3"\nopen({str(sentinel)!r}, "w").close()',
            ):
                source.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaises(ValueError):
                    windows_version.read_version(source)
                self.assertFalse(sentinel.exists())

    def test_cli_rejects_invalid_source_without_replacing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "version.py"
            output = Path(directory) / "version.txt"
            source.write_text('__version__ = "1.2.3-beta"', encoding="utf-8")
            output.write_bytes(b"previous resource")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/windows_version.py"),
                    "--version-source",
                    str(source),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), b"previous resource")

    @unittest.skipUnless(HAS_PYINSTALLER and os.name == "nt", "Windows PyInstaller")
    def test_pyinstaller_loads_resource_and_pe_gate_rejects_missing_or_stale_fields(
        self,
    ):
        import PyInstaller
        from PyInstaller.utils.win32 import versioninfo

        with tempfile.TemporaryDirectory() as directory:
            resource = Path(directory) / "version.txt"
            resource.write_text(
                windows_version.render_version_info("2.17.300"), encoding="utf-8"
            )
            info = versioninfo.load_version_info_from_text_file(str(resource))
            self.assertEqual(info.ffi.fileVersionMS, (2 << 16) | 17)
            self.assertEqual(info.ffi.fileVersionLS, 300 << 16)
            self.assertEqual(info.ffi.productVersionMS, (2 << 16) | 17)
            self.assertEqual(info.ffi.productVersionLS, 300 << 16)
            bootloader = next(
                (Path(PyInstaller.__file__).parent / "bootloader").glob("*/runw.exe")
            )
            executable = Path(directory) / "Clarify.exe"
            shutil.copyfile(bootloader, executable)
            with self.assertRaisesRegex(ValueError, "no RT_VERSION"):
                windows_version.verify_pe_version(executable, "2.17.300")
            versioninfo.write_version_info_to_executable(str(executable), info)
            windows_version.verify_pe_version(executable, "2.17.300")
            with self.assertRaises(ValueError):
                windows_version.verify_pe_version(executable, "2.17.301")
            for field in ("fileVersionLS", "productVersionLS"):
                original = getattr(info.ffi, field)
                setattr(info.ffi, field, 299 << 16)
                versioninfo.write_version_info_to_executable(str(executable), info)
                with self.subTest(field=field), self.assertRaises(ValueError):
                    windows_version.verify_pe_version(executable, "2.17.300")
                setattr(info.ffi, field, original)
            table = info.kids[0].kids[0]
            for key in ("FileVersion", "ProductVersion"):
                field = next(field for field in table.kids if field.name == key)
                original = field.val
                field.val = "2.17.299.0"
                versioninfo.write_version_info_to_executable(str(executable), info)
                with self.subTest(key=key), self.assertRaises(ValueError):
                    windows_version.verify_pe_version(executable, "2.17.300")
                field.val = original
            table.kids = [field for field in table.kids if field.name != "FileVersion"]
            versioninfo.write_version_info_to_executable(str(executable), info)
            with self.assertRaises(ValueError):
                windows_version.verify_pe_version(executable, "2.17.300")
            executable.write_bytes(b"invalid PE")
            with self.assertRaises(ValueError):
                windows_version.verify_pe_version(executable, "2.17.300")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/windows_version.py"),
                    "--check-pe",
                    str(executable),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Cannot read", result.stderr)


if __name__ == "__main__":
    unittest.main()
