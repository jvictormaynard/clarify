"""Exercise the trusted IPA helper with synthetic ZIPs and fake codesign."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
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


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mobile/scripts/verify-ios-ipa.py"
# Git results are injected by the fixtures, including in Git-free execution roots.
BASE = "d" * 40
BASE_TREE = "e" * 40
SOURCE = "a" * 40
BUNDLE = "com.jvictormaynard.clarify"
TEAM = "8K353P3496"
CLOUD = json.loads((ROOT / "mobile/app.json").read_text())["expo"]["ios"]["infoPlist"][
    "ClarifyCloudURL"
]


class IPAHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.qa = self.root / "clarify-ios-qa"
        (self.qa / "input").mkdir(parents=True)
        (self.qa / "output").mkdir()
        self.ipa = self.qa / "output/Clarify.ipa"
        self.archive = self.qa / "input/unsigned.xcarchive.zip"
        self.archive.write_bytes(b"synthetic unsigned archive data")
        self.context_path = self.qa / "context.json"
        self.cwd = self.root / "untrusted-cwd"
        self.cwd.mkdir()
        self.write_ipa()
        self.context = dict(
            schema=1,
            repository="jvictormaynard/clarify",
            pr=179,
            source_sha=SOURCE,
            source_tree="b" * 40,
            trusted_sha=BASE,
            base_sha=BASE,
            base_tree=BASE_TREE,
            workflow=dict(
                id=99, path=".github/workflows/ios-qa.yml", blob_sha="f" * 40
            ),
            version="1.2.3",
            build="8",
            tag="ios/pr-179/v1.2.3-build8",
            run_id=33986942056,
            run_attempt=1,
            artifact=dict(
                id=123,
                name="clarify-ios-qa-unsigned-" + SOURCE,
                run_id=33986942056,
                run_attempt=1,
                sha256=hashlib.sha256(self.archive.read_bytes()).hexdigest(),
                bytes=self.archive.stat().st_size,
            ),
            ipa=dict(
                sha256=hashlib.sha256(self.ipa.read_bytes()).hexdigest(),
                bytes=self.ipa.stat().st_size,
            ),
            bundles=self.bundle_bindings(),
        )
        self.env = dict(
            RUNNER_TEMP=str(self.root),
            GITHUB_REPOSITORY="jvictormaynard/clarify",
            GITHUB_EVENT_NAME="workflow_dispatch",
            GITHUB_REF="refs/heads/main",
            GITHUB_SHA=BASE,
            QA_WORKFLOW_SHA=BASE,
            QA_WORKFLOW_ID="99",
            QA_WORKFLOW_REF="jvictormaynard/clarify/.github/workflows/ios-qa.yml@refs/heads/main",
            GITHUB_RUN_ID="33986942056",
            GITHUB_RUN_ATTEMPT="1",
        )
        self.calls = []
        self.entitlement_override = {}
        self.write_config("1.2.3", "8")

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
                    b"\xcf\xfa\xed\xfe\x0c\x00\x00\x01" + b"\0" * 24 + suffix.encode(),
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
        if argv[:2] == ["git", "rev-parse"]:
            value = (
                BASE_TREE
                if argv[2].endswith("^{tree}")
                else "f" * 40
                if ":.github/" in argv[2]
                else BASE
            )
            return SimpleNamespace(stdout=value + "\n", returncode=0)
        if argv[:2] == ["git", "diff"]:
            return SimpleNamespace(stdout="", returncode=0)
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

    def execute(
        self, *, qa=True, context_path=None, raw_context=None, cli=False, extra_args=()
    ):
        self.context_path.write_text(
            raw_context if raw_context is not None else json.dumps(self.context),
            encoding="utf-8",
        )
        argv = [str(SCRIPT), str(self.ipa)]
        if qa:
            argv += ["--qa-context", str(context_path or self.context_path)]
        argv += list(extra_args)
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

    def test_stable_cli_retains_the_original_receipt_and_uses_no_qa_context(self):
        result = self.execute(qa=False, cli=True)
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
        self.assertEqual(
            self.execute(qa=False, cli=True, extra_args=("--ignored", "value")),
            expected,
        )
        self.assertEqual(self.last_stdout, json.dumps(expected) + "\n")

    def test_stable_cli_without_ipa_preserves_config_before_argument_errors(self):
        for configured in (True, False):
            with self.subTest(configured=configured):
                if not configured:
                    (self.cwd / "app.json").unlink()
                result = subprocess.run(
                    [sys.executable, str(SCRIPT)],
                    cwd=self.cwd,
                    env=self.env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                terminal = result.stderr.splitlines()[-1]
                if configured:
                    self.assertEqual(terminal, "IndexError: list index out of range")
                else:
                    self.assertTrue(terminal.startswith("FileNotFoundError:"))
                    self.assertIn("app.json", terminal)

    def test_stable_cli_opens_ipa_before_reading_bundle_config(self):
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
                    self.execute(qa=False, cli=True)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.last_stdout, "")
                self.assertEqual(self.last_stderr, "")

    def test_stable_cli_version_mismatch_does_not_read_build_number(self):
        config = json.loads((self.cwd / "app.json").read_text())
        config["expo"]["version"] = "0.0.1"
        del config["expo"]["ios"]["buildNumber"]
        (self.cwd / "app.json").write_text(json.dumps(config))
        with self.assertRaisesRegex(
            ValueError, "Artifact version does not match source"
        ):
            self.execute(qa=False, cli=True)
        self.assertEqual(self.calls, [])

    def test_stable_cli_codesign_uses_the_original_temporary_root(self):
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
                            self.execute(qa=False, cli=True)
                    else:
                        self.execute(qa=False, cli=True)
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

    def test_stable_cli_keeps_digest_sidecar_if_receipt_size_read_fails(self):
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
                self.execute(qa=False, cli=True)
        self.assertEqual(
            self.ipa.with_suffix(".ipa.sha256").read_text(),
            digest + "  Clarify.ipa\n",
        )
        self.assertFalse(self.ipa.with_name("verification.json").exists())

    def test_qa_cli_rejects_extra_arguments_before_verification(self):
        with self.assertRaises(SystemExit) as failure:
            self.execute(cli=True, extra_args=("--ignored",))
        self.assertEqual(failure.exception.code, 1)
        self.assertEqual(self.last_stderr, "QA IPA verification failed.\n")
        self.assertEqual(self.calls, [])
        self.assertFalse(self.ipa.with_name("verification.json").exists())

    def corrupt_ipa(self, kind):
        marker = "SYNTHETIC_PRIVATE_MARKER"
        if kind == "crc":
            payload = b"synthetic unique CRC payload"
            self.write_ipa(extra=("Payload/Clarify.app/" + marker, payload))
            self.context["bundles"] = self.bundle_bindings()
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
            self.context["bundles"] = self.bundle_bindings()
            expected = ValueError
        self.refresh_ipa_digest()
        return marker, expected

    def test_qa_cli_sanitizes_crc_and_plist_errors_without_a_receipt(self):
        for kind in ("crc", "plist"):
            with self.subTest(kind=kind):
                marker, _ = self.corrupt_ipa(kind)
                with self.assertRaises(SystemExit) as failure:
                    self.execute(cli=True)
                self.assertEqual(failure.exception.code, 1)
                self.assertEqual(self.last_stdout, "")
                self.assertEqual(self.last_stderr, "QA IPA verification failed.\n")
                self.assertNotIn(marker, self.last_stderr)
                self.assertFalse(self.ipa.with_name("verification.json").exists())
                self.assertFalse(self.ipa.with_suffix(".ipa.sha256").exists())

    def test_stable_cli_preserves_original_crc_and_plist_exceptions(self):
        for kind in ("crc", "plist"):
            with self.subTest(kind=kind):
                marker, expected = self.corrupt_ipa(kind)
                with self.assertRaisesRegex(expected, marker) as failure:
                    self.execute(qa=False, cli=True)
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

    def test_qa_uses_context_and_trusted_license_even_from_a_candidate_cwd(self):
        self.write_config("0.0.1", "7")
        (self.cwd / "third-party/KeyboardHostBundleID/LICENSE").write_text(
            "untrusted license"
        )
        result = self.execute()
        self.assertEqual(result["qa"]["source_sha"], SOURCE)
        self.assertEqual(result["qa"]["artifact"], self.context["artifact"])
        self.assertTrue(result["artifactDigestVerified"])
        self.assertFalse(result["workflowArtifactProvenanceVerified"])

    def refresh_ipa_digest(self):
        self.context["ipa"] = dict(
            sha256=hashlib.sha256(self.ipa.read_bytes()).hexdigest(),
            bytes=self.ipa.stat().st_size,
        )

    def bundle_bindings(self):
        with zipfile.ZipFile(self.ipa) as archive:
            files = {
                entry.filename: archive.read(entry) for entry in archive.infolist()
            }
        result = []
        for suffix, location, executable in [
            ("", "Payload/Clarify.app", "Clarify"),
            (
                ".keyboard",
                "Payload/Clarify.app/PlugIns/ClarifyKeyboard.appex",
                "ClarifyKeyboard",
            ),
            (
                ".activity",
                "Payload/Clarify.app/PlugIns/ClarifyActivity.appex",
                "ClarifyActivity",
            ),
        ]:
            records = [
                {
                    "path": name[len(location) + 1 :],
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                for name, data in files.items()
                if name.startswith(location + "/")
            ]
            records.sort(key=lambda entry: entry["path"])
            binary = files[location + "/" + executable]
            result.append(
                dict(
                    id=BUNDLE + suffix,
                    path=location,
                    executable=executable,
                    sha256=hashlib.sha256(
                        json.dumps(records, separators=(",", ":")).encode()
                    ).hexdigest(),
                    executable_sha256=hashlib.sha256(binary).hexdigest(),
                    executable_bytes=len(binary),
                )
            )
        return result

    def test_context_rejects_arbitrary_fields_types_sha_and_other_run_compositions(
        self,
    ):
        original = deepcopy(self.context)
        mutations = [
            lambda c: c.update(endpoint="https://example.com"),
            lambda c: c.update(notes="arbitrary"),
            lambda c: c.update(schema=True),
            lambda c: c.update(pr=180),
            lambda c: c.update(base_sha="b" * 40),
            lambda c: c.update(source_sha=SOURCE + "\n"),
            lambda c: c.update(build="08"),
            lambda c: c.update(version="1.2.3-beta"),
            lambda c: c.update(tag="ios/v1.2.3-build8"),
            lambda c: c.update(run_attempt=2),
            lambda c: c["artifact"].update(id=True),
            lambda c: c["artifact"].update(path="any"),
            lambda c: c["artifact"].update(run_id="1"),
            lambda c: c["ipa"].update(bytes=0),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.context = deepcopy(original)
                mutate(self.context)
                self.calls = []
                with self.assertRaises(ValueError):
                    self.execute()
                self.assertFalse(any(call[0] == "codesign" for call in self.calls))

    def test_duplicate_context_keys_are_rejected(self):
        raw = json.dumps(self.context).replace(
            '"schema": 1', '"schema": 1, "schema": 1'
        )
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.execute(raw_context=raw)

    def test_context_must_be_the_exact_absolute_regular_file(self):
        for filename in [
            "context.json",
            self.root / "elsewhere.json",
            self.qa / "input/../context.json",
        ]:
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.execute(context_path=filename)
        outside = self.root / "elsewhere.json"
        outside.write_text(json.dumps(self.context))
        self.context_path.unlink()
        os.link(outside, self.context_path)
        with self.assertRaisesRegex(ValueError, "regular file"):
            self.execute()

    def test_changed_artifact_or_ipa_bytes_block_before_codesign(self):
        for filename in [self.archive, self.ipa]:
            with self.subTest(filename=filename):
                original = filename.read_bytes()
                filename.write_bytes(original + b"changed")
                self.calls = []
                with self.assertRaises(ValueError):
                    self.execute()
                self.assertFalse(any(call[0] == "codesign" for call in self.calls))
                filename.write_bytes(original)

    def test_zip_escapes_aliases_and_links_are_rejected_before_codesign(self):
        backslash = zipfile.ZipInfo("Payload/escape")
        backslash.filename = backslash.orig_filename = "Payload\\escape"
        link = zipfile.ZipInfo("Payload/link")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
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
                self.refresh_ipa_digest()
                self.calls = []
                with self.assertRaises(ValueError):
                    self.execute()
                self.assertFalse(any(call[0] == "codesign" for call in self.calls))
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
                self.refresh_ipa_digest()
                self.context["bundles"] = self.bundle_bindings()
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
        self.refresh_ipa_digest()
        self.context["bundles"] = self.bundle_bindings()
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
                r"KeyboardHostBundleID\.LICENSE",
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
            self.refresh_ipa_digest()
            self.context["bundles"] = self.bundle_bindings()
            with self.assertRaisesRegex(error, message):
                self.execute()

    def test_context_cannot_enable_a_tag_run_or_another_trusted_checkout(self):
        self.env["GITHUB_REF"] = "refs/tags/ios/pr-179/v1.2.3-build8"
        with self.assertRaises(ValueError):
            self.execute()
        self.env["GITHUB_REF"] = "refs/heads/main"
        self.env["QA_WORKFLOW_SHA"] = "b" * 40
        with self.assertRaises(ValueError):
            self.execute()

    def test_import_exposes_functions_without_config_reads_or_codesign(self):
        with patch(
            "subprocess.run",
            side_effect=AssertionError("Import must have no command effects"),
        ):
            module = runpy.run_path(str(SCRIPT), run_name="qa_helper_import")
        self.assertTrue(callable(module["verify_ipa"]))

    def test_qa_rejects_symlinked_ipa(self):
        outside = self.root / "outside.ipa"
        outside.write_bytes(self.ipa.read_bytes())
        self.ipa.unlink()
        try:
            os.symlink(outside, self.ipa)
        except OSError:
            self.skipTest("This Windows account cannot create filesystem symlinks")
        with self.assertRaisesRegex(ValueError, "links"):
            self.execute()

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
        self.refresh_ipa_digest()
        with self.assertRaisesRegex(ValueError, "nested"):
            self.execute()

    def test_tree_workflow_and_bundle_bindings_cannot_be_substituted(self):
        original = deepcopy(self.context)
        mutations = [
            lambda c: c.update(source_tree="main"),
            lambda c: c.update(base_tree="c" * 40),
            lambda c: c["workflow"].update(id=100),
            lambda c: c["workflow"].update(path=".github/workflows/other.yml"),
            lambda c: c["workflow"].update(blob_sha="0" * 40),
            lambda c: c["bundles"][0].update(sha256="0" * 64),
            lambda c: c["bundles"][1].update(executable_sha256="0" * 64),
            lambda c: c["bundles"][2].update(path="../activity"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.context = deepcopy(original)
                mutate(self.context)
                self.calls = []
                with self.assertRaises(ValueError):
                    self.execute()
                self.assertFalse(any(call[0] == "codesign" for call in self.calls))

    def test_a_matching_digest_does_not_make_a_script_an_ios_executable(self):
        with zipfile.ZipFile(self.ipa) as archive:
            entries = {item.filename: archive.read(item) for item in archive.infolist()}
        entries["Payload/Clarify.app/Clarify"] = b"#!/bin/sh\necho unsafe\n" * 4
        with zipfile.ZipFile(self.ipa, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        self.refresh_ipa_digest()
        self.context["bundles"] = self.bundle_bindings()
        with self.assertRaisesRegex(ValueError, "Mach-O"):
            self.execute()


if __name__ == "__main__":
    unittest.main()
