"""Signed IPA verification uses synthetic ZIPs and a fake codesign command."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "mobile/scripts/verify-ios-ipa.py"
BUNDLE = "com.jvictormaynard.clarify"
TEAM = "8K353P3496"
CLOUD = json.loads((ROOT / "mobile/app.json").read_text())["expo"]["ios"]["infoPlist"][
    "ClarifyCloudURL"
]


class IPAHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.ipa = self.root / "Clarify.ipa"
        self.cwd = self.root / "source"
        self.cwd.mkdir()
        self.env = {
            k: v
            for k, v in os.environ.items()
            if k in {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT"}
        }
        self.calls = []
        self.entitlement_override = {}
        self.write_ipa()
        self.write_config("1.2.3", "8")

    def execute(self, *, cli=False, extra_args=()):
        argv = [str(SCRIPT), str(self.ipa), *extra_args]
        old = Path.cwd()
        output = io.StringIO()
        errors = io.StringIO()
        try:
            os.chdir(self.cwd)
            with (
                patch.dict(os.environ, self.env, clear=True),
                patch.object(sys, "argv", argv),
                patch("subprocess.run", self.fake_run),
                redirect_stdout(output),
                redirect_stderr(errors),
            ):
                module = runpy.run_path(
                    str(SCRIPT), run_name="__main__" if cli else "helper_test"
                )
                if not cli:
                    module["main"]()
        finally:
            os.chdir(old)
            self.last_stdout = output.getvalue()
            self.last_stderr = errors.getvalue()
        return json.loads(self.ipa.with_name("verification.json").read_text())

    def write_config(self, version, build):
        (self.cwd / "app.json").write_text(
            json.dumps(
                {
                    "expo": dict(
                        version=version,
                        ios=dict(
                            buildNumber=build, infoPlist=dict(ClarifyCloudURL=CLOUD)
                        ),
                    )
                }
            )
        )
        license_path = self.cwd / "third-party/KeyboardHostBundleID/LICENSE"
        license_path.parent.mkdir(parents=True, exist_ok=True)
        license_path.write_bytes(
            (ROOT / "mobile/third-party/KeyboardHostBundleID/LICENSE").read_bytes()
        )

    def write_ipa(self, *, extra=None, bundle_build="8", cloud=CLOUD):
        with zipfile.ZipFile(self.ipa, "w") as archive:
            for name, suffix in [
                ("Payload/Clarify.app", ""),
                ("Payload/Clarify.app/PlugIns/ClarifyKeyboard.appex", ".keyboard"),
                ("Payload/Clarify.app/PlugIns/ClarifyActivity.appex", ".activity"),
            ]:
                info = dict(
                    CFBundleIdentifier=BUNDLE + suffix,
                    CFBundleShortVersionString="1.2.3",
                    CFBundleVersion=bundle_build,
                )
                executable = {
                    "": "Clarify",
                    ".keyboard": "ClarifyKeyboard",
                    ".activity": "ClarifyActivity",
                }[suffix]
                info["CFBundleExecutable"] = executable
                if not suffix:
                    info["ClarifyCloudURL"] = cloud
                archive.writestr(name + "/Info.plist", plistlib.dumps(info))
                archive.writestr(
                    name + "/" + executable,
                    b"\xcf\xfa\xed\xfe\x0c\x00\x00\x01"
                    + b"\x00" * 24
                    + suffix.encode(),
                )
                archive.writestr(
                    name + "/embedded.mobileprovision", b"synthetic profile"
                )
            archive.writestr(
                "Payload/Clarify.app/PlugIns/ClarifyKeyboard.appex/KeyboardHostBundleID.LICENSE",
                (ROOT / "mobile/third-party/KeyboardHostBundleID/LICENSE").read_bytes(),
            )
            if extra:
                archive.writestr(*extra)

    def fake_run(self, argv, **kwargs):
        self.calls.append(tuple(argv))
        self.assertEqual(argv[0], "codesign")
        if "--verify" in argv:
            return SimpleNamespace(stdout=b"", returncode=0)
        name = Path(argv[-1]).name
        suffix = {
            "Clarify.app": "",
            "ClarifyKeyboard.appex": ".keyboard",
            "ClarifyActivity.appex": ".activity",
        }[name]
        entitlements = {
            "com.apple.developer.team-identifier": TEAM,
            "application-identifier": TEAM + "." + BUNDLE + suffix,
            "com.apple.security.application-groups": ["group." + BUNDLE],
        }
        entitlements.update(self.entitlement_override)
        return SimpleNamespace(stdout=plistlib.dumps(entitlements), returncode=0)

    def test_cli_preserves_the_verified_receipt(self):
        result = self.execute(cli=True)
        expected = {
            "sha256": hashlib.sha256(self.ipa.read_bytes()).hexdigest(),
            "bytes": self.ipa.stat().st_size,
            "bundles": [
                {"bundleId": BUNDLE + suffix, "version": "1.2.3", "build": "8"}
                for suffix in ("", ".activity", ".keyboard")
            ],
        }
        self.assertEqual(result, expected)
        self.assertEqual(self.last_stdout, json.dumps(expected) + "\n")
        self.assertEqual(
            self.ipa.with_name("verification.json").read_text(),
            json.dumps(expected, indent=2) + "\n",
        )

    def test_cli_requires_exactly_one_ipa_argument(self):
        for args in ([], [str(self.ipa), "--extra"]):
            result = subprocess.run(
                [sys.executable, str(SCRIPT), *args],
                cwd=self.cwd,
                env=self.env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Use verify-ios-ipa.py IPA", result.stderr)
            self.assertEqual(result.stdout, "")

    def test_cli_opens_ipa_before_reading_bundle_config(self):
        (self.cwd / "app.json").write_text(json.dumps({"expo": {}}))
        for kind, expected in (
            ("missing", FileNotFoundError),
            ("invalid", zipfile.BadZipFile),
        ):
            with self.subTest(ipa=kind):
                if kind == "missing":
                    self.ipa.unlink()
                else:
                    self.ipa.write_bytes(b"not a ZIP")
                with self.assertRaises(expected):
                    self.execute(cli=True)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.last_stdout, "")
                self.assertEqual(self.last_stderr, "")

    def test_cli_version_mismatch_does_not_read_build_number(self):
        config = json.loads((self.cwd / "app.json").read_text())
        config["expo"]["version"] = "0.0.1"
        del config["expo"]["ios"]["buildNumber"]
        (self.cwd / "app.json").write_text(json.dumps(config))
        with self.assertRaisesRegex(
            ValueError, "Artifact version does not match source"
        ):
            self.execute(cli=True)
        self.assertEqual(self.calls, [])

    def test_cli_codesign_cleans_its_temporary_directory(self):
        temporary_directory = tempfile.TemporaryDirectory
        directories = []
        normal_run = self.fake_run

        def record_directory(*args, **kwargs):
            directory = temporary_directory(*args, **kwargs)
            directories.append(Path(directory.name))
            return directory

        def failing(argv, **kwargs):
            self.calls.append(tuple(argv))
            raise subprocess.CalledProcessError(1, argv, stderr=b"synthetic failure")

        for fails in (False, True):
            with self.subTest(codesign_fails=fails):
                self.calls = []
                self.fake_run = failing if fails else normal_run
                with patch("tempfile.TemporaryDirectory", record_directory):
                    if fails:
                        with self.assertRaises(subprocess.CalledProcessError) as error:
                            self.execute(cli=True)
                    else:
                        self.execute(cli=True)
                app = directories[-1] / "Payload/Clarify.app"
                expected = []
                for bundle in (
                    app,
                    app / "PlugIns/ClarifyActivity.appex",
                    app / "PlugIns/ClarifyKeyboard.appex",
                ):
                    expected.append(
                        ("codesign", "--verify", "--deep", "--strict", str(bundle))
                    )
                    if fails:
                        self.assertEqual(tuple(error.exception.cmd), expected[0])
                        break
                    expected.append(
                        ("codesign", "-d", "--entitlements", ":-", str(bundle))
                    )
                self.assertEqual(self.calls, expected)

    def test_cli_keeps_digest_sidecar_if_receipt_size_read_fails(self):
        digest = hashlib.sha256(self.ipa.read_bytes()).hexdigest()
        normal_read = Path.read_bytes
        normal_stat = Path.stat
        digest_read = False

        def read_bytes(path):
            nonlocal digest_read
            if path == self.ipa:
                digest_read = True
            return normal_read(path)

        def stat(path, *args, **kwargs):
            if path == self.ipa and digest_read:
                raise OSError("synthetic receipt size failure")
            return normal_stat(path, *args, **kwargs)

        with (
            patch.object(Path, "read_bytes", read_bytes),
            patch.object(Path, "stat", stat),
        ):
            with self.assertRaisesRegex(OSError, "synthetic receipt size failure"):
                self.execute(cli=True)
        self.assertEqual(
            self.ipa.with_suffix(".ipa.sha256").read_text(), digest + "  Clarify.ipa\n"
        )
        self.assertFalse(self.ipa.with_name("verification.json").exists())

    def corrupt_ipa(self, kind):
        marker = "SYNTHETIC_PRIVATE_MARKER"
        if kind == "crc":
            payload = b"synthetic unique CRC payload"
            self.write_ipa(extra=("Payload/Clarify.app/" + marker, payload))
            raw = bytearray(self.ipa.read_bytes())
            raw[raw.index(payload)] ^= 1
            self.ipa.write_bytes(raw)
            expected = zipfile.BadZipFile
        else:
            self.write_ipa()
            with zipfile.ZipFile(self.ipa) as archive:
                entries = {
                    item.filename: archive.read(item) for item in archive.infolist()
                }
            entries["Payload/Clarify.app/Info.plist"] = (
                '<plist version="1.0"><dict><key>number</key><integer>'
                + marker
                + "</integer></dict></plist>"
            ).encode()
            with zipfile.ZipFile(self.ipa, "w") as archive:
                for name, content in entries.items():
                    archive.writestr(name, content)
            expected = ValueError
        return (marker, expected)

    def test_cli_reports_crc_and_plist_errors(self):
        for kind in ("crc", "plist"):
            with self.subTest(kind=kind):
                marker, expected = self.corrupt_ipa(kind)
                with self.assertRaisesRegex(expected, marker) as failure:
                    self.execute(cli=True)
                self.assertEqual(self.last_stdout, "")
                self.assertEqual(self.last_stderr, "")
                self.assertFalse(self.ipa.with_name("verification.json").exists())
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), str(self.ipa)],
                    cwd=self.cwd,
                    env=self.env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(
                    result.stderr.splitlines()[-1].endswith(
                        expected.__name__ + ": " + str(failure.exception)
                    ),
                    result.stderr,
                )

    def test_zip_escapes_aliases_and_links_are_rejected_before_codesign(self):
        backslash = zipfile.ZipInfo("Payload/escape")
        backslash.filename = backslash.orig_filename = "Payload\\escape"
        link = zipfile.ZipInfo("Payload/link")
        link.create_system = 3
        link.external_attr = 41471 << 16
        for name in [
            "../escape",
            "/absolute",
            "Payload/../escape",
            "C:/escape",
            backslash,
            "Payload//Clarify.app/Info.plist",
            "Payload/Clarify.app/Info.plist.",
            link,
        ]:
            with self.subTest(name=name):
                self.write_ipa(extra=(name, b"target"))
                self.calls = []
                with self.assertRaises(ValueError):
                    self.execute()
                self.assertFalse(any((call[0] == "codesign" for call in self.calls)))
        self.assertFalse((self.root / "escape").exists())

    def test_signature_identity_debug_and_shared_group_rejections_remain(self):
        for fields in [
            {"com.apple.developer.team-identifier": "OTHER"},
            {"get-task-allow": True},
            {"application-identifier": "wrong"},
            {"com.apple.security.application-groups": []},
        ]:
            with self.subTest(fields=fields):
                self.entitlement_override = fields
                with self.assertRaises(ValueError):
                    self.execute()

    def test_wrong_bundle_version_cloud_license_and_missing_profile_are_rejected(self):
        for kwargs, message in [
            (dict(bundle_build="9"), "Artifact version does not match source"),
            (
                dict(cloud="https://example.com"),
                "Artifact must use the declared production endpoint",
            ),
        ]:
            with self.subTest(kwargs=kwargs):
                self.write_ipa(**kwargs)
                with self.assertRaisesRegex(ValueError, message):
                    self.execute()
        self.write_ipa()
        with zipfile.ZipFile(self.ipa) as archive:
            changed_license = {
                info.filename: archive.read(info) for info in archive.infolist()
            }
        changed_license[
            "Payload/Clarify.app/PlugIns/ClarifyKeyboard.appex/KeyboardHostBundleID.LICENSE"
        ] = b"synthetic changed license"
        with zipfile.ZipFile(self.ipa, "w") as archive:
            for name, content in changed_license.items():
                archive.writestr(name, content)
        with self.assertRaisesRegex(
            ValueError, "Bundled third-party license differs from source"
        ):
            self.execute()
        for removed, error, message in [
            (
                "Payload/Clarify.app/embedded.mobileprovision",
                ValueError,
                "Missing distribution profile",
            ),
            (
                "Payload/Clarify.app/PlugIns/ClarifyKeyboard.appex/KeyboardHostBundleID.LICENSE",
                FileNotFoundError,
                "KeyboardHostBundleID\\.LICENSE",
            ),
        ]:
            self.write_ipa()
            with zipfile.ZipFile(self.ipa) as source:
                entries = [
                    (info, source.read(info))
                    for info in source.infolist()
                    if info.filename != removed
                ]
            with zipfile.ZipFile(self.ipa, "w") as target:
                for info, data in entries:
                    target.writestr(info, data)
            with self.assertRaisesRegex(error, message):
                self.execute()

    def test_import_exposes_functions_without_config_reads_or_codesign(self):
        with patch(
            "subprocess.run",
            side_effect=AssertionError("Import must have no command effects"),
        ):
            module = runpy.run_path(str(SCRIPT), run_name="ipa_helper_import")
        self.assertTrue(callable(module["verify_ipa"]))

    def test_codesign_failure_never_creates_a_verification_receipt(self):
        normal = self.fake_run

        def failing(argv, **kwargs):
            if argv[0] == "codesign":
                raise subprocess.CalledProcessError(
                    1, argv, stderr=b"synthetic failure"
                )
            return normal(argv, **kwargs)

        self.fake_run = failing
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute()
        self.assertFalse(self.ipa.with_name("verification.json").exists())

    def test_unexpected_nested_bundle_is_rejected(self):
        self.write_ipa(
            extra=("Payload/Clarify.app/Watch/Unexpected.app/Info.plist", b"data")
        )
        with self.assertRaisesRegex(ValueError, "nested"):
            self.execute()


if __name__ == "__main__":
    unittest.main()
