"""Use synthetic archive bytes and fake system/API adapters only."""

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import warnings
import zipfile

from scripts import qa_device_archive as qa


UUID = bytes.fromhex("123456781234123412341234567890ab")
UUID_TEXT = "12345678-1234-1234-1234-1234567890ab"
LICENSE = b"Synthetic retained third-party license\n"
CLOUD = "https://synthetic.example.invalid"


def macho(platform=2, *, commands=None, kind=2, with_uuid=False):
    if commands is None:
        commands = struct.pack("<6I", 0x32, 24, platform, 0, 0, 0)
    if with_uuid:
        commands += struct.pack("<2I", 0x1B, 24) + UUID
    count, offset = 0, 0
    while offset < len(commands):
        count += 1
        size = struct.unpack_from("<I", commands, offset + 4)[0]
        if size < 8:
            break
        offset += size
    return (
        struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, kind, count, len(commands), 0, 0)
        + commands
    )


def write_zip(
    path, entries, *, compression=zipfile.ZIP_DEFLATED, extra=b"", local_extra=None
):
    with zipfile.ZipFile(path, "w") as archive:
        for name, (data, mode) in entries.items():
            item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            item.create_system = 3
            item.external_attr = mode << 16
            item.compress_type = compression
            item.extra = extra if local_extra is None else local_extra
            archive.writestr(item, data)
            item.extra = extra


def fixture_entries():
    files = {
        qa.ARCHIVE_ROOT + "/Info.plist": (
            plistlib.dumps(
                {
                    "ArchiveVersion": 2,
                    "ApplicationProperties": {
                        "ApplicationPath": "Applications/Clarify.app",
                        "CFBundleIdentifier": qa.BUNDLE,
                    },
                    "CreationDate": "synthetic-original-metadata",
                }
            ),
            stat.S_IFREG | 0o644,
        ),
        qa.APP_PATH + "/main.jsbundle": (
            b"inert synthetic JS resource",
            stat.S_IFREG | 0o644,
        ),
        qa.APP_PATH + "/Assets.car": (b"synthetic asset data", stat.S_IFREG | 0o644),
        qa.LICENSE_PATH: (LICENSE, stat.S_IFREG | 0o644),
    }
    for identifier, path, executable, extension in qa.BUNDLE_LAYOUT:
        info = {
            "CFBundleIdentifier": identifier,
            "CFBundleExecutable": executable,
            "CFBundleShortVersionString": "1.2.3",
            "CFBundleVersion": "8",
            "CFBundlePackageType": "APPL" if extension is None else "XPC!",
        }
        if extension:
            info["NSExtension"] = {"NSExtensionPointIdentifier": extension}
        else:
            info["ClarifyCloudURL"] = CLOUD
        files[path + "/Info.plist"] = plistlib.dumps(info), stat.S_IFREG | 0o644
        files[path + "/" + executable] = (
            macho(with_uuid=True) + b"synthetic-image",
            stat.S_IFREG | 0o755,
        )
    files[qa.APP_PATH + "/Frameworks/Vendor.framework/Vendor"] = (
        macho(
            kind=6,
            commands=struct.pack("<6I", 0x32, 24, 2, 0, 0, 0)
            + struct.pack("<4I", 0x1D, 16, 0, 0),
        ),
        stat.S_IFREG | 0o755,
    )
    files[qa.APP_PATH + "/Frameworks/Vendor.framework/Info.plist"] = (
        plistlib.dumps({"CFBundleExecutable": "Vendor", "CFBundlePackageType": "FMWK"}),
        stat.S_IFREG | 0o644,
    )
    files[
        qa.ARCHIVE_ROOT + "/dSYMs/Clarify.app.dSYM/Contents/Resources/DWARF/Clarify"
    ] = (
        macho(commands=struct.pack("<2I", 0x1B, 24) + UUID, kind=10),
        stat.S_IFREG | 0o644,
    )
    return files


def manifest_for(entries):
    return [
        {
            "path": name.rstrip("/"),
            "kind": "directory" if name.endswith("/") else "file",
            "mode": mode & 0o777,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for name, (data, mode) in sorted(entries.items())
    ]


def envelope_for(path, entries, policy):
    """Independently rebind mutated bytes so negative tests reach their rule."""
    manifest = manifest_for(entries)
    by_path = {record["path"]: record for record in manifest}
    bundles, code = [], []
    primary_paths = {
        path + "/" + executable for _, path, executable, _ in qa.BUNDLE_LAYOUT
    }
    for identifier, bundle, executable, _ in qa.BUNDLE_LAYOUT:
        subset = [
            {**record, "path": record["path"][len(bundle) + 1 :]}
            for record in manifest
            if record["path"].startswith(bundle + "/")
        ]
        binary = by_path[bundle + "/" + executable]
        bundles.append(
            {
                "id": identifier,
                "path": bundle,
                "sha256": qa.digest(qa.canonical(subset)),
                "info_plist_sha256": by_path[bundle + "/Info.plist"]["sha256"],
                "executable": executable,
                "executable_sha256": binary["sha256"],
                "executable_bytes": binary["bytes"],
                "architectures": ["arm64"],
                "platform": "ios-device",
                "embedded_entitlements": None,
            }
        )
    for record in manifest:
        name = record["path"]
        if name in primary_paths:
            kind, platform, uuids = "primary", "ios-device", [UUID_TEXT]
        elif ".framework/" in name and name.endswith("/Vendor"):
            kind, platform, uuids = "framework", "ios-device", []
        elif ".dSYM/" in name:
            kind, platform, uuids = "dsym", None, [UUID_TEXT]
        else:
            continue
        code.append(
            {
                "path": name,
                "kind": kind,
                "sha256": record["sha256"],
                "architectures": ["arm64"],
                "platform": platform,
                "uuids": uuids,
            }
        )
    return {
        **deepcopy(policy.context),
        "archive": {
            "filename": qa.ARCHIVE_NAME,
            "root": qa.ARCHIVE_ROOT,
            "bytes": path.stat().st_size,
            "sha256": qa.digest(path.read_bytes()),
            "manifest_sha256": qa.digest(qa.canonical(manifest)),
        },
        "bundles": bundles,
        "code_objects": code,
    }


class FakeAPI:
    def __init__(self, policy, controls, outer):
        context = policy.context
        self.policy, self.controls, self.outer = policy, controls, outer
        self.calls = []
        self.main_data = {"sha": context["base_sha"]}
        self.pr = {
            "number": context["pr"],
            "state": "open",
            "draft": False,
            "head": {
                "sha": context["source_sha"],
                "repo": {"full_name": qa.REPOSITORY},
            },
            "base": {
                "sha": context["base_sha"],
                "ref": "main",
                "repo": {"full_name": qa.REPOSITORY},
            },
        }
        self.commits = {
            sha: {"sha": sha, "tree": {"sha": tree}}
            for sha, tree in (
                (context["source_sha"], context["source_tree"]),
                (context["base_sha"], context["base_tree"]),
            )
        }
        run_id, attempt = (
            context["producer"]["run_id"],
            context["producer"]["run_attempt"],
        )
        self.run_data = {
            "id": run_id,
            "run_attempt": attempt,
            "workflow_id": context["workflow"]["id"],
            "path": qa.WORKFLOW,
            "head_sha": context["trusted_sha"],
            "head_branch": "main",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "repository": {"full_name": qa.REPOSITORY},
        }
        self.jobs_data = {"run_id": run_id, "run_attempt": attempt, "jobs": []}
        for job_id, name, steps in (
            (101, policy.producer_job_name, policy.producer_steps),
            (102, policy.final_job_name, policy.final_steps),
        ):
            self.jobs_data["jobs"].append(
                {
                    "id": job_id,
                    "name": name,
                    "run_id": run_id,
                    "head_sha": context["trusted_sha"],
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": step, "status": "completed", "conclusion": "success"}
                        for step in steps
                    ],
                }
            )
        self.artifact_data = {
            "id": 73,
            "name": "clarify-ios-qa-unsigned-" + context["source_sha"],
            "digest": "sha256:" + qa.digest(outer),
            "expired": False,
            "size_in_bytes": len(outer),
            "workflow_run": {"id": run_id, "head_sha": context["trusted_sha"]},
        }
        self.log = qa.format_artifact_record(
            artifact_id=73,
            artifact_digest=qa.digest(outer),
            source_sha=context["source_sha"],
            run_id=run_id,
            run_attempt=attempt,
        ).encode()
        self.workflow = {
            "jobs": {
                context["producer"]["job_key"]: {
                    "name": policy.producer_job_name,
                    "steps": [
                        {
                            "name": policy.uploader_step,
                            "uses": policy.upload_action,
                            "with": {
                                "name": "clarify-ios-qa-unsigned-${{ inputs.source_sha }}",
                                "overwrite": False,
                            },
                        }
                    ],
                },
                "final": {
                    "name": policy.final_job_name,
                    "steps": [
                        {
                            "name": policy.recorder_step,
                            "run": "python -m scripts.qa_device_archive-recorder",
                        }
                    ],
                },
            }
        }

    def main(self):
        self.calls.append("main")
        return deepcopy(self.main_data)

    def pull_request(self, number):
        self.calls.append("pr")
        return deepcopy(self.pr)

    def commit(self, sha):
        self.calls.append("commit")
        return deepcopy(self.commits[sha])

    def control(self, sha, path):
        self.calls.append("control")
        return self.controls[path]

    def workflow_document(self, data):
        # Fake parser. The production parser is supplied by the MAIN caller.
        if data != self.controls[qa.WORKFLOW]:
            raise AssertionError("Parser received unauthenticated bytes")
        return deepcopy(self.workflow)

    def run(self, run_id, attempt):
        self.calls.append("run")
        return deepcopy(self.run_data)

    def jobs(self, run_id, attempt):
        self.calls.append("jobs")
        return deepcopy(self.jobs_data)

    def artifact(self, artifact_id):
        self.calls.append("artifact")
        return deepcopy(self.artifact_data)

    def job_log(self, job_id):
        if job_id != 102:
            raise AssertionError("Only MAIN final job logs are authorized")
        self.calls.append("final_log")
        return self.log

    def download_artifact(self, artifact_id, destination, *, max_bytes):
        self.calls.append("download")
        if len(self.outer) > max_bytes:
            raise AssertionError("Unbounded download")
        destination.write_bytes(self.outer)


class FakeRunner:
    def __init__(self, owner, *, fail=None):
        self.owner, self.fail, self.calls = owner, fail, []

    def __call__(self, command, *, cwd, env):
        command = tuple(command)
        self.calls.append(command)
        if command[-1] in {"install", "clean"}:
            self.owner.assertEqual(
                command[1:3], ("-I", str(self.owner.trusted / qa.SIGNING_HELPER))
            )
            if command[-1] == "install":
                self.owner.assertIn("download", self.owner.api.calls)
                self.owner.assertTrue(
                    (cwd / "frozen" / qa.APP_PATH / "Clarify").is_file()
                )
                options_dir = self.owner.runner_temp / "clarify-signing"
                options_dir.mkdir()
                options = {
                    "method": "app-store-connect",
                    "destination": "export",
                    "teamID": qa.TEAM,
                    "signingStyle": "manual",
                    "signingCertificate": "Apple Distribution",
                    "provisioningProfiles": {
                        identifier: f"12345678-1234-1234-1234-{index:012d}"
                        for index, (identifier, *_rest) in enumerate(
                            qa.BUNDLE_LAYOUT, 1
                        )
                    },
                    "manageAppVersionAndBuildNumber": False,
                    "uploadSymbols": True,
                }
                if self.fail == "options":
                    options["destination"] = "upload"
                (options_dir / "ExportOptions.plist").write_bytes(
                    plistlib.dumps(options)
                )
                if self.fail == "install":
                    return SimpleNamespace(
                        returncode=1,
                        stdout=b"credential",
                        stderr=b"https://secret.invalid",
                    )
            else:
                if self.fail == "cleanup":
                    return SimpleNamespace(returncode=1)
                import shutil

                shutil.rmtree(
                    self.owner.runner_temp / "clarify-signing", ignore_errors=True
                )
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        if command[:2] == ("/usr/bin/xcodebuild", "-exportArchive"):
            self.owner.assertEqual(len(command), 8)
            self.owner.assertNotIn("-allowProvisioningUpdates", command)
            if self.fail == "export":
                return SimpleNamespace(
                    returncode=65, stdout=b"token", stderr=b"https://secret.invalid"
                )
            output = Path(command[5])
            entries = {}
            for name, (data, mode) in self.owner.entries.items():
                if not name.startswith(qa.APP_PATH + "/"):
                    continue
                entries[name.replace(qa.APP_PATH, "Payload/Clarify.app")] = data, mode
            for identifier, bundle, *_rest in qa.BUNDLE_LAYOUT:
                entries[
                    bundle.replace(qa.APP_PATH, "Payload/Clarify.app")
                    + "/embedded.mobileprovision"
                ] = b"synthetic-profile", stat.S_IFREG | 0o644
            write_zip(output / "Clarify.ipa", entries)
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        if command[0] == "/usr/bin/codesign":
            self.owner.assertIn(command[1], {"--verify", "-d"})
            if self.fail == "signature":
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"secret")
            if command[1] == "--verify":
                return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            name = Path(command[-1]).name
            suffix = {
                "Clarify.app": "",
                "ClarifyKeyboard.appex": ".keyboard",
                "ClarifyActivity.appex": ".activity",
            }[name]
            identifier = qa.BUNDLE + suffix
            entitlements = {
                "application-identifier": qa.TEAM + "." + identifier,
                "com.apple.developer.team-identifier": qa.TEAM,
                "get-task-allow": False,
                "keychain-access-groups": [qa.TEAM + "." + identifier],
                "beta-reports-active": True,
            }
            if suffix != ".activity":
                entitlements["com.apple.security.application-groups"] = [
                    "group." + qa.BUNDLE
                ]
            return SimpleNamespace(
                returncode=0, stdout=plistlib.dumps(entitlements), stderr=b""
            )
        raise AssertionError("Unexpected command after keys")


class ArchiveBoundaryTests(unittest.TestCase):
    def setUp(self):
        # The path guard checks ancestors, including the OS temp directory's
        # sticky bit. Use a canonical checkout parent for this private fixture.
        self.temporary = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parent
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runner_temp, self.trusted = self.root / "runner", self.root / "trusted"
        self.runner_temp.mkdir()
        self.trusted.mkdir()
        self.controls = {
            qa.WORKFLOW: b"synthetic MAIN YAML bytes",
            qa.SIGNING_HELPER: b"inert fake signing helper",
            qa.MODULE: b"inert fake module",
        }
        for name, data in self.controls.items():
            path = self.trusted / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        context = {
            "schema": 1,
            "kind": "clarify-ios-qa-unsigned-archive",
            "trust_model": "reviewed-source-internal-qa-v1",
            "repository": qa.REPOSITORY,
            "pr": 23,
            "source_sha": "a" * 40,
            "source_tree": "b" * 40,
            "base_sha": "c" * 40,
            "base_tree": "d" * 40,
            "trusted_sha": "c" * 40,
            "app_id": qa.APP_ID,
            "bundle_id": qa.BUNDLE,
            "version": "1.2.3",
            "build": "8",
            "tag": "ios/pr-23/v1.2.3-build8",
            "relay_host": None,
            "workflow": {
                "id": 19,
                "path": qa.WORKFLOW,
                "blob_sha": qa.git_blob(self.controls[qa.WORKFLOW]),
            },
            "producer": {"run_id": 71, "run_attempt": 2, "job_key": "archive"},
            "controls": {
                name: qa.git_blob(data) for name, data in self.controls.items()
            },
            "recipe": {
                "id": "device-release-v1",
                "configuration": "Release",
                "sdk": "iphoneos",
                "destination": "generic/platform=iOS",
                "architectures": ["arm64"],
                "code_signing_allowed": False,
                "xcode_build": "16A123",
                "sdk_version": "18.0",
            },
            "entitlements_policy": deepcopy(qa.ENTITLEMENTS_POLICY),
        }
        self.policy = qa.ArchivePolicy(
            context=context,
            cloud_url=CLOUD,
            license_sha256=qa.digest(LICENSE),
            producer_job_name="Unsigned Device archive",
            producer_steps=("Authenticate MAIN", "Archive", "Upload archive"),
            final_job_name="MAIN final",
            final_steps=("Recheck MAIN", "Record archive"),
            uploader_step="Upload archive",
            recorder_step="Record archive",
            upload_action="actions/upload-artifact@" + "f" * 40,
        )
        self.entries = fixture_entries()
        self.archive = self.root / qa.ARCHIVE_NAME
        self.refresh()
        external = patch.object(
            qa.subprocess,
            "run",
            side_effect=AssertionError("External process forbidden"),
        )
        external.start()
        self.addCleanup(external.stop)

    def refresh(self):
        write_zip(self.archive, self.entries)
        self.envelope = envelope_for(self.archive, self.entries, self.policy)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(qa.ARCHIVE_NAME, self.archive.read_bytes())
            archive.writestr(qa.ENVELOPE_NAME, qa.canonical(self.envelope))
        self.api = FakeAPI(self.policy, self.controls, stream.getvalue())

    def inspect(self):
        return qa.inspect(self.archive, qa.canonical(self.envelope), self.policy)

    def sign(self, runner):
        with patch.dict(os.environ, {"HOME": str(self.root / "fake-home")}, clear=True):
            return qa.sign_export(
                api=self.api,
                policy=self.policy,
                artifact_id=73,
                runner_temp=self.runner_temp,
                trusted_root=self.trusted,
                runner=runner,
            )

    def mutate_plist(self, bundle, key, value):
        name = bundle + "/Info.plist"
        info = plistlib.loads(self.entries[name][0])
        info[key] = value
        self.entries[name] = plistlib.dumps(info), self.entries[name][1]
        self.refresh()

    def test_producer_creates_fresh_output_and_calls_real_pack(self):
        from scripts import testflight_qa as caller

        job = Mock()
        job.execution = self.root / "execution"
        job.metadata = self.root / "metadata"

        def compile_archive(*args, **kwargs):
            produced = self.root / "compiled"
            qa._extract(self.archive, produced, qa.zip_manifest(self.archive))
            (produced / qa.ARCHIVE_ROOT).rename(job.metadata / qa.ARCHIVE_ROOT)

        job.command.side_effect = compile_archive
        output = self.root / "new-artifact"
        self.assertFalse(output.exists())

        def source_mode(path):
            relative = path.relative_to(job.metadata).as_posix()
            return 0o755 if path.is_dir() else self.entries[relative][1] & 0o777

        # Supply POSIX fixture modes on Windows; caller and pack remain real.
        with patch.object(qa, "_source_mode", side_effect=source_mode):
            result = caller.produce_archive(job, self.policy, output)
        self.assertEqual(
            qa.inspect(
                output / qa.ARCHIVE_NAME,
                (output / qa.ENVELOPE_NAME).read_bytes(),
                self.policy,
            ),
            result,
        )
        before = {path.name: path.read_bytes() for path in output.iterdir()}
        with self.assertRaises(FileExistsError):
            caller.produce_archive(job, self.policy, output)
        self.assertEqual(job.command.call_count, 1)
        self.assertEqual(
            {path.name: path.read_bytes() for path in output.iterdir()}, before
        )
        empty = self.root / "existing-empty"
        empty.mkdir()
        with self.assertRaises(FileExistsError):
            caller.produce_archive(job, self.policy, empty)
        self.assertEqual(job.command.call_count, 1)

    def test_simulator_is_not_device(self):
        with self.assertRaisesRegex(qa.ArchiveError, "device platform"):
            qa.inspect_macho(macho(7), primary=True)

    def test_zip_escape_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            archive = Path(directory) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../escaped", b"untrusted")
            with self.assertRaisesRegex(qa.ArchiveError, "Unsafe archive path"):
                qa.zip_manifest(archive)

    def test_complete_archive_inventory_and_absent_entitlements(self):
        result = self.inspect()
        self.assertEqual(result, self.envelope)
        self.assertEqual(
            [bundle["embedded_entitlements"] for bundle in result["bundles"]],
            [None] * 3,
        )
        self.assertEqual(
            [obj["kind"] for obj in result["code_objects"]].count("primary"), 3
        )
        self.assertEqual(
            next(obj for obj in result["code_objects"] if obj["kind"] == "dsym")[
                "uuids"
            ],
            [UUID_TEXT],
        )

    def test_pack_preserves_all_bytes_modes_metadata_and_is_deterministic(self):
        source = self.root / "source" / qa.ARCHIVE_ROOT
        for name, (data, mode) in self.entries.items():
            path = source.parent / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(mode & 0o777)

        def source_mode(path):
            relative = path.relative_to(source.parent).as_posix()
            return 0o755 if path.is_dir() else self.entries[relative][1] & 0o777

        outputs = [self.root / "pack1", self.root / "pack2"]
        for output in outputs:
            output.mkdir()
            # Windows cannot create POSIX execute bits. Feed synthetic source
            # modes at the filesystem adapter; ZIP byte/mode checks remain real.
            with patch.object(qa, "_source_mode", side_effect=source_mode):
                envelope = qa.pack(source, output, self.policy)
            self.assertEqual(
                qa.inspect(
                    output / qa.ARCHIVE_NAME,
                    (output / qa.ENVELOPE_NAME).read_bytes(),
                    self.policy,
                ),
                envelope,
            )
            with zipfile.ZipFile(output / qa.ARCHIVE_NAME) as archive:
                for name, (data, mode) in self.entries.items():
                    self.assertEqual(archive.read(name), data)
                    self.assertEqual(archive.getinfo(name).external_attr >> 16, mode)
                    self.assertEqual(
                        archive.getinfo(name).date_time, (1980, 1, 1, 0, 0, 0)
                    )
        self.assertEqual(
            (outputs[0] / qa.ARCHIVE_NAME).read_bytes(),
            (outputs[1] / qa.ARCHIVE_NAME).read_bytes(),
        )

    def test_bad_paths_unicode_and_file_directory_conflicts(self):
        cases = [
            "/absolute",
            "../escape",
            "a/../b",
            "a\\b",
            "C:/data",
            "a//b",
            "a/./b",
            "a. /b",
            "a./b",
            "nul.txt",
            "a/\0suffix",
            "cafe\u0301",
            "/".join(["a"] * 33),
            "a" * 1025,
        ]
        for name in cases:
            with self.subTest(path=repr(name)):
                # NUL must reach the original central name, not ZipInfo's writer
                # truncation. Direct path policy is the same extraction guard.
                with self.assertRaisesRegex(qa.ArchiveError, "Unsafe archive path"):
                    qa.safe_name(name)
        for entries in (
            {"A/x": (b"x", stat.S_IFREG | 0o644), "a/y": (b"y", stat.S_IFREG | 0o644)},
            {
                "node": (b"file", stat.S_IFREG | 0o644),
                "node/child": (b"child", stat.S_IFREG | 0o644),
            },
        ):
            write_zip(self.archive, entries)
            with self.assertRaisesRegex(qa.ArchiveError, "collision|conflict"):
                qa.zip_manifest(self.archive)

    def test_zip_duplicate_links_special_nodes_and_encryption(self):
        for mode in (
            stat.S_IFLNK | 0o777,
            stat.S_IFIFO | 0o644,
            stat.S_IFSOCK | 0o644,
            stat.S_IFREG | 0o4755,
        ):
            with self.subTest(mode=mode):
                write_zip(self.archive, {"link": (b"target", mode)})
                with self.assertRaisesRegex(qa.ArchiveError, "special node"):
                    qa.zip_manifest(self.archive)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.archive, "w") as archive:
                archive.writestr("same", b"1")
                archive.writestr("same", b"2")
        with self.assertRaisesRegex(qa.ArchiveError, "Duplicate"):
            qa.zip_manifest(self.archive)
        write_zip(self.archive, {"data": (b"data", stat.S_IFREG | 0o644)})
        data = bytearray(self.archive.read_bytes())
        central = data.index(b"PK\x01\x02")
        struct.pack_into("<H", data, central + 8, 1)
        self.archive.write_bytes(data)
        with self.assertRaisesRegex(qa.ArchiveError, "Encrypted"):
            qa.zip_manifest(self.archive)

    def test_native_ipa_allows_only_timestamp_metadata_without_rewriting_bytes(self):
        timestamp = struct.pack("<HHii", 0x5855, 8, 100, 200)
        write_zip(
            self.archive,
            {"Payload/data": (b"retained bytes", stat.S_IFREG | 0o644)},
            extra=timestamp,
            local_extra=struct.pack("<HHiiHH", 0x5855, 12, 100, 200, 501, 20),
        )
        original = self.archive.read_bytes()
        with self.assertRaisesRegex(qa.ArchiveError, "metadata extra"):
            qa.zip_manifest(self.archive)
        manifest = qa.zip_manifest(self.archive, _ipa=True)
        self.assertEqual(manifest[0]["path"], "Payload/data")
        self.assertEqual(manifest[0]["mode"], 0o644)
        self.assertEqual(
            manifest[0]["sha256"], hashlib.sha256(b"retained bytes").hexdigest()
        )
        self.assertEqual(self.archive.read_bytes(), original)
        qa._extract(self.archive, self.root / "ipa-data", manifest)
        self.assertEqual(
            (self.root / "ipa-data/Payload/data").read_bytes(), b"retained bytes"
        )
        with self.assertRaisesRegex(qa.ArchiveError, "metadata extra"):
            qa.zip_manifest(self.archive, _transport=True)

    def test_native_ipa_rejects_other_metadata_and_link_nodes(self):
        timestamp = struct.pack("<HHii", 0x5855, 8, 100, 200)
        for extra in (
            timestamp * 2,
            struct.pack("<HH", 0x5855, 7) + b"x" * 7,
            struct.pack("<HH", 0x5855, 12) + b"x" * 12,
            struct.pack("<HH", 0x756E, 8) + b"x" * 8,
        ):
            with self.subTest(extra=extra.hex()):
                write_zip(
                    self.archive, {"data": (b"data", stat.S_IFREG | 0o644)}, extra=extra
                )
                with self.assertRaisesRegex(qa.ArchiveError, "metadata extra"):
                    qa.zip_manifest(self.archive, _ipa=True)
        write_zip(
            self.archive, {"link": (b"target", stat.S_IFLNK | 0o777)}, extra=timestamp
        )
        with self.assertRaisesRegex(qa.ArchiveError, "special node"):
            qa.zip_manifest(self.archive, _ipa=True)

    def test_native_ipa_checks_local_timestamp_metadata_separately(self):
        timestamp = struct.pack("<HHii", 0x5855, 8, 100, 200)
        for tag, size in ((0x756E, 8), (0x5855, 7), (0x5855, 12)):
            with self.subTest(tag=tag, size=size):
                write_zip(
                    self.archive,
                    {"data": (b"data", stat.S_IFREG | 0o644)},
                    extra=timestamp,
                )
                data = bytearray(self.archive.read_bytes())
                name_size = struct.unpack_from("<H", data, 26)[0]
                struct.pack_into("<HH", data, 30 + name_size, tag, size)
                self.archive.write_bytes(data)
                with self.assertRaisesRegex(qa.ArchiveError, "local metadata extra"):
                    qa.zip_manifest(self.archive, _ipa=True)
        for extra in (timestamp * 2, struct.pack("<HH", 0x5855, 14) + b"x" * 14):
            with self.subTest(local_extra=extra.hex()):
                write_zip(
                    self.archive,
                    {"data": (b"data", stat.S_IFREG | 0o644)},
                    extra=timestamp,
                    local_extra=extra,
                )
                with self.assertRaisesRegex(qa.ArchiveError, "local metadata extra"):
                    qa.zip_manifest(self.archive, _ipa=True)

    def test_native_ipa_timestamps_reach_real_export_inspection(self):
        original = write_zip
        timestamp = struct.pack("<HHii", 0x5855, 8, 100, 200)
        with patch(
            __name__ + ".write_zip",
            side_effect=lambda path, entries: original(
                path,
                entries,
                extra=timestamp,
                local_extra=struct.pack("<HHiiHH", 0x5855, 12, 100, 200, 501, 20),
            ),
        ):
            result = self.sign(FakeRunner(self))
        self.assertEqual(len(result["receipt"]["ipa"]["bundles"]), 3)
        self.assertIs(result["receipt"]["delivery_eligible"], False)

    def test_zip_crc_truncation_bombs_and_bounded_limits(self):
        write_zip(
            self.archive,
            {"data": (b"unique-payload", stat.S_IFREG | 0o644)},
            compression=zipfile.ZIP_STORED,
        )
        original = self.archive.read_bytes()
        self.archive.write_bytes(original.replace(b"unique-payload", b"broken-payload"))
        with self.assertRaisesRegex(qa.ArchiveError, "CRC"):
            qa.zip_manifest(self.archive)
        self.archive.write_bytes(original[:-15])
        with self.assertRaisesRegex(qa.ArchiveError, "ZIP structure"):
            qa.zip_manifest(self.archive)
        write_zip(self.archive, {"bomb": (b"\0" * (2 * 1024**2), stat.S_IFREG | 0o644)})
        with self.assertRaisesRegex(qa.ArchiveError, "bomb"):
            qa.zip_manifest(self.archive)
        self.refresh()
        for limits, message in (
            (qa.Limits(entries=1), "entry limit"),
            (qa.Limits(file_bytes=16), "expanded size"),
            (qa.Limits(expanded_bytes=16), "expanded size"),
            (qa.Limits(zip_bytes=16), "ZIP size"),
            (qa.Limits(depth=2), "Unsafe archive path"),
            (qa.Limits(path_bytes=12), "Unsafe archive path"),
        ):
            with (
                self.subTest(limits=limits),
                self.assertRaisesRegex(qa.ArchiveError, message),
            ):
                qa.zip_manifest(self.archive, limits=limits)

    def test_outer_container_limit_is_separate_from_inner_file_limit(self):
        outer = self.root / "outer.zip"
        write_zip(
            outer,
            {
                qa.ARCHIVE_NAME: (b"inner-container" * 40, stat.S_IFREG | 0o600),
                qa.ENVELOPE_NAME: (b"{}", stat.S_IFREG | 0o600),
            },
        )
        limits = qa.Limits(file_bytes=32, zip_bytes=4096)
        with self.assertRaisesRegex(qa.ArchiveError, "expanded size"):
            qa.zip_manifest(outer, limits=limits)
        manifest = qa.zip_manifest(outer, limits=limits, _transport=True)
        self.assertEqual(len(manifest), 2)
        qa._extract(
            outer, self.root / "outer-data", manifest, limits=limits, transport=True
        )
        self.assertEqual(
            (self.root / "outer-data" / qa.ARCHIVE_NAME).read_bytes(),
            b"inner-container" * 40,
        )

    def test_source_hardlink_symlink_and_reparse_guards(self):
        path = self.root / "linked"
        target = self.root / "target"
        target.write_bytes(b"data")
        os.link(target, path)
        with self.assertRaisesRegex(qa.ArchiveError, "Hardlinks"):
            qa.file_digest(path)
        fake = SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o755, st_file_attributes=0x400, st_nlink=1
        )
        with patch.object(Path, "lstat", return_value=fake):
            with self.assertRaisesRegex(qa.ArchiveError, "reparse"):
                qa._node(self.root)
        fake = SimpleNamespace(
            st_mode=stat.S_IFLNK | 0o777, st_file_attributes=0, st_nlink=1
        )
        with patch.object(Path, "lstat", return_value=fake):
            with self.assertRaisesRegex(qa.ArchiveError, "Links"):
                qa._node(self.root)

    def test_bundle_semantics_after_rebinding_all_hashes(self):
        original = fixture_entries()
        cases = [
            (qa.APP_PATH, "CFBundleVersion", "9", "version/build"),
            (qa.APP_PATH, "CFBundleShortVersionString", "9.9.9", "version/build"),
            (qa.APP_PATH, "CFBundleIdentifier", "wrong.identity", "identity"),
            (qa.APP_PATH, "CFBundleExecutable", "Other", "identity"),
            (
                qa.APP_PATH,
                "ClarifyCloudURL",
                "https://private.invalid",
                "cloud endpoint",
            ),
            (
                qa.BUNDLE_LAYOUT[1][1],
                "NSExtension",
                {"NSExtensionPointIdentifier": "wrong"},
                "extension type",
            ),
        ]
        for bundle, key, value, message in cases:
            with self.subTest(key=key):
                self.entries = deepcopy(original)
                self.mutate_plist(bundle, key, value)
                with self.assertRaisesRegex(qa.ArchiveError, message):
                    self.inspect()

    def test_missing_extra_bundle_resource_and_build_input(self):
        original = fixture_entries()
        for name, action, message in (
            (qa.LICENSE_PATH, "delete", "keyboard license"),
            (qa.APP_PATH + "/main.jsbundle", "delete", "essential app resource"),
            (qa.APP_PATH + "/PlugIns/Extra.appex/Info.plist", "add", "layout"),
            (
                qa.ARCHIVE_ROOT + "/Products/Applications/Other.app/Info.plist",
                "add",
                "layout",
            ),
            (qa.APP_PATH + "/Pods/data", "add", "build inputs"),
            (qa.APP_PATH + "/build.sh", "add", "build scripts"),
        ):
            with self.subTest(path=name):
                self.entries = deepcopy(original)
                if action == "delete":
                    del self.entries[name]
                else:
                    self.entries[name] = b"data", stat.S_IFREG | 0o644
                self.refresh()
                with self.assertRaisesRegex(qa.ArchiveError, message):
                    self.inspect()

    def test_platform_framework_and_load_command_boundaries(self):
        for platform in (6, 7, 1):
            with (
                self.subTest(platform=platform),
                self.assertRaisesRegex(qa.ArchiveError, "device platform"),
            ):
                qa.inspect_macho(macho(platform), primary=True)
        for data, message in (
            (macho(commands=struct.pack("<2I", 0x32, 4096)), "load bounds"),
            (macho(commands=struct.pack("<4I", 0x1D, 16, 0, 0)), "Signed primary"),
            (
                macho(commands=struct.pack("<6I", 0x32, 24, 2, 0, 0, 0) * 2),
                "device platform",
            ),
            (b"\xce\xfa\xed\xfe" + b"\0" * 28, "thin ARM64"),
        ):
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(qa.ArchiveError, message),
            ):
                qa.inspect_macho(data, primary=True)
        name = qa.APP_PATH + "/Frameworks/Vendor.framework/Vendor"
        self.entries[name] = macho(7, kind=6), stat.S_IFREG | 0o755
        self.refresh()
        with self.assertRaisesRegex(qa.ArchiveError, "device platform"):
            self.inspect()

    def test_diagnostic_uploader_is_separate_and_strictly_bounded(self):
        steps = self.api.workflow["jobs"]["archive"]["steps"]
        diagnostics = {
            "name": "Retain unsigned archive diagnostics",
            "uses": self.policy.upload_action,
            "if": "always()",
            "with": {
                "name": "clarify-ios-qa-archive-diagnostics-${{ github.run_id }}-${{ github.run_attempt }}",
                "path": "${{ runner.temp }}/clarify-trusted-ci/logs/\n${{ runner.temp }}/clarify-trusted-ci/archive-phases/\n",
                "overwrite": False,
            },
        }
        original = deepcopy(steps)
        steps.append(deepcopy(diagnostics))
        qa.authenticate(self.api, self.policy, 73, self.root / "valid-diagnostics.zip")
        variants = [
            [diagnostics],
            [*original, diagnostics, diagnostics],
            [*original, diagnostics | {"uses": "actions/upload-artifact@unknown"}],
            [*original, diagnostics | {"if": "success()"}],
            [*original, diagnostics | {"with": diagnostics["with"] | {"path": "**/*"}}],
            [
                *original,
                diagnostics | {"with": diagnostics["with"] | {"overwrite": True}},
            ],
        ]
        for index, variant in enumerate(variants):
            with self.subTest(index=index):
                steps[:] = deepcopy(variant)
                with self.assertRaisesRegex(qa.ArchiveError, "uploader"):
                    qa.authenticate(
                        self.api, self.policy, 73, self.root / f"invalid-{index}.zip"
                    )

    def test_framework_library_can_be_readable_without_exec_permission(self):
        name = qa.APP_PATH + "/Frameworks/Vendor.framework/Vendor"
        data, _ = self.entries[name]
        self.entries[name] = data, stat.S_IFREG | 0o644
        self.refresh()
        result = self.inspect()
        self.assertTrue(
            any(
                item["path"] == name and item["kind"] == "framework"
                for item in result["code_objects"]
            )
        )
        self.entries[name] = b"not Mach-O", stat.S_IFREG | 0o644
        self.refresh()
        with self.assertRaisesRegex(qa.ArchiveError, "Missing Mach-O code object"):
            self.inspect()
        self.entries[name] = data, stat.S_IFREG
        self.refresh()
        with self.assertRaisesRegex(qa.ArchiveError, "framework executable"):
            self.inspect()

    def test_framework_must_bind_its_declared_executable(self):
        name = qa.APP_PATH + "/Frameworks/Vendor.framework/Info.plist"
        self.entries[name] = (
            plistlib.dumps(
                {"CFBundleExecutable": "Missing", "CFBundlePackageType": "FMWK"}
            ),
            stat.S_IFREG | 0o644,
        )
        self.refresh()
        with self.assertRaisesRegex(qa.ArchiveError, "framework executable"):
            self.inspect()

    def test_strict_envelope_and_separate_hash_domains(self):
        invalid = qa.canonical(self.envelope)[:-1] + b',"schema":1}'
        with self.assertRaisesRegex(qa.ArchiveError, "Duplicate JSON"):
            qa.load_envelope(invalid)
        for path in (("unknown",), ("workflow", "unknown"), ("bundles", 0, "unknown")):
            value = deepcopy(self.envelope)
            target = value
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = True
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(qa.ArchiveError, "fields"),
            ):
                qa.load_envelope(qa.canonical(value))
        with self.assertRaisesRegex(qa.ArchiveError, "size limit"):
            qa.load_envelope(b" " * (qa.MAX_ENVELOPE + 1))
        self.envelope["archive"]["sha256"] = self.api.artifact_data["digest"][7:]
        with self.assertRaisesRegex(qa.ArchiveError, "Envelope differs"):
            self.inspect()

    def test_record_unique_strict_utf8_and_final_channel(self):
        valid = self.api.log
        for log, message in (
            (valid + b"\n" + valid, "duplicate"),
            (b"\xff", "Malformed"),
            (b"x" * (qa.MAX_LOG + 1), "size limit"),
            (b"prefix " + valid, "Unknown"),
            (b"", "Missing"),
        ):
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(qa.ArchiveError, message),
            ):
                qa.parse_artifact_record(
                    log, source_sha="a" * 40, run_id=71, run_attempt=2
                )
        record = qa.parse_artifact_record(
            b"2026-10-27T00:00:00.123Z " + valid,
            source_sha="a" * 40,
            run_id=71,
            run_attempt=2,
        )
        self.assertEqual(record["artifact_id"], 73)
        with self.assertRaisesRegex(qa.ArchiveError, "identity"):
            qa.parse_artifact_record(
                valid, source_sha="a" * 40, run_id=71, run_attempt=3
            )

    def test_authentication_rejects_raw_api_mismatches_before_install(self):
        mutations = [
            (lambda api: api.main_data.update(sha="f" * 40), "MAIN/base/trusted"),
            (lambda api: api.pr["head"].update(sha="f" * 40), "Current PR"),
            (
                lambda api: api.commits["a" * 40]["tree"].update(sha="f" * 40),
                "tree binding",
            ),
            (lambda api: api.run_data.update(run_attempt=1), "run/attempt/workflow"),
            (
                lambda api: api.run_data.update(head_sha="a" * 40),
                "run/attempt/workflow",
            ),
            (lambda api: api.run_data.update(path="other.yml"), "run/attempt/workflow"),
            (lambda api: api.jobs_data.update(run_attempt=1), "exact-attempt"),
            (lambda api: api.jobs_data["jobs"].pop(0), "producer/final job"),
            (
                lambda api: api.jobs_data["jobs"].append(
                    deepcopy(api.jobs_data["jobs"][0])
                ),
                "producer/final job",
            ),
            (
                lambda api: api.jobs_data["jobs"][0]["steps"][0].update(
                    conclusion="failure"
                ),
                "producer/final step",
            ),
            (
                lambda api: api.jobs_data["jobs"][0]["steps"].pop(),
                "producer/final step",
            ),
            (
                lambda api: api.artifact_data.update(digest="sha256:" + "0" * 64),
                "API artifact",
            ),
            (lambda api: api.artifact_data.update(expired=True), "API artifact"),
            (
                lambda api: api.artifact_data["workflow_run"].update(id=999),
                "API artifact",
            ),
            (lambda api: api.artifact_data.update(size_in_bytes=1), "digest/size"),
            (lambda api: setattr(api, "outer", api.outer + b"changed"), "digest/size"),
            (
                lambda api: setattr(api, "log", api.log + b"\n" + api.log),
                "duplicate archive",
            ),
            (
                lambda api: api.workflow["jobs"]["archive"]["steps"][0]["with"].update(
                    overwrite=True
                ),
                "uploader",
            ),
            (
                lambda api: api.workflow["jobs"]["archive"]["steps"][0].update(
                    uses="actions/upload-artifact@main"
                ),
                "uploader",
            ),
        ]
        for mutate, message in mutations:
            with self.subTest(message=message):
                self.refresh()
                mutate(self.api)
                runner = FakeRunner(self)
                with self.assertRaisesRegex(qa.ArchiveError, message):
                    self.sign(runner)
                self.assertEqual(runner.calls, [])
                self.assertEqual(list(self.runner_temp.iterdir()), [])

    def test_bad_inspection_never_installs_credentials(self):
        self.mutate_plist(qa.APP_PATH, "CFBundleVersion", "9")
        runner = FakeRunner(self)
        with self.assertRaisesRegex(qa.ArchiveError, "version/build"):
            self.sign(runner)
        self.assertEqual(runner.calls, [])

    def test_export_receipt_stays_ineligible_and_commands_are_fixed(self):
        runner = FakeRunner(self)
        result = self.sign(runner)
        receipt = result["receipt"]
        self.assertEqual(receipt["status"], "compatibilidade_nativa_não_verificada")
        self.assertIs(receipt["delivery_eligible"], False)
        self.assertIs(receipt["workflowArtifactProvenanceVerified"], False)
        self.assertEqual(
            len(
                {
                    receipt["artifact"]["sha256"],
                    receipt["archive"]["sha256"],
                    receipt["ipa"]["sha256"],
                }
            ),
            3,
        )
        self.assertEqual(runner.calls[0][-1], "install")
        self.assertEqual(runner.calls[1][:2], ("/usr/bin/xcodebuild", "-exportArchive"))
        self.assertEqual(runner.calls[-1][-1], "clean")
        self.assertEqual(
            len([cmd for cmd in runner.calls if cmd[0] == "/usr/bin/codesign"]), 6
        )
        self.assertTrue(result["ipa_path"].is_file())
        self.assertFalse((self.runner_temp / "clarify-signing").exists())

    def test_partial_install_export_and_inspection_failure_always_clean(self):
        for failure, message in (
            ("install", "installation failed"),
            ("export", "export unsupported"),
            ("signature", "signature inspection"),
            ("options", "Unsafe export"),
        ):
            with self.subTest(failure=failure):
                runner = FakeRunner(self, fail=failure)
                with self.assertRaisesRegex(qa.ArchiveError, message) as error:
                    self.sign(runner)
                self.assertNotIn("secret", str(error.exception))
                self.assertNotIn("https", str(error.exception))
                self.assertEqual(runner.calls[-1][-1], "clean")
                self.assertEqual(list(self.runner_temp.iterdir()), [])
                if failure == "export":
                    self.assertEqual(len(runner.calls), 3)

    def test_cleanup_failure_is_a_blocker(self):
        runner = FakeRunner(self, fail="cleanup")
        with self.assertRaisesRegex(qa.ArchiveError, "cleanup failed"):
            self.sign(runner)
        self.assertEqual(runner.calls[-1][-1], "clean")
        self.assertFalse(
            any(
                path.name.startswith("clarify-device-archive-")
                for path in self.runner_temp.iterdir()
            )
        )

    def test_freeze_detects_tampering_before_install(self):
        original = qa._inspect_data

        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            if kwargs.get("extraction"):
                (kwargs["extraction"] / qa.APP_PATH / "Clarify").write_bytes(
                    b"tampered"
                )
            return result

        runner = FakeRunner(self)
        with patch.object(qa, "_inspect_data", side_effect=mutate):
            with self.assertRaisesRegex(qa.ArchiveError, "Frozen archive bytes"):
                self.sign(runner)
        self.assertEqual(runner.calls, [])

    def test_freeze_rejects_an_added_file_before_install(self):
        original = qa._inspect_data

        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            if kwargs.get("extraction"):
                (kwargs["extraction"] / qa.APP_PATH / "extra-resource").write_bytes(
                    b"added"
                )
            return result

        runner = FakeRunner(self)
        with patch.object(qa, "_inspect_data", side_effect=mutate):
            with self.assertRaisesRegex(qa.ArchiveError, "Frozen archive inventory"):
                self.sign(runner)
        self.assertEqual(runner.calls, [])

    def test_signed_entitlement_policy_is_minimal(self):
        base = {
            "application-identifier": qa.TEAM + "." + qa.BUNDLE,
            "com.apple.developer.team-identifier": qa.TEAM,
            "com.apple.security.application-groups": ["group." + qa.BUNDLE],
        }
        qa._signed_entitlements(base, qa.BUNDLE)
        for key, value, message in (
            ("get-task-allow", True, "identity/policy"),
            ("keychain-access-groups", ["remote.all"], "keychain"),
            ("unknown-entitlement", True, "identity/policy"),
            ("com.apple.security.application-groups", ["group.new"], "app group"),
        ):
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(qa.ArchiveError, message),
            ):
                qa._signed_entitlements({**base, key: value}, qa.BUNDLE)

    def test_cli_sign_export_blocks_without_api_transport(self):
        with patch("sys.stderr", new_callable=io.StringIO) as output:
            self.assertEqual(qa.main(["sign-export"]), 1)
        self.assertNotIn("https://", output.getvalue())

    def publication_result(self):
        self.policy.context.update(pr=179, tag="ios/pr-179/v1.2.3-build8")
        (self.trusted / "mobile/app.json").parent.mkdir(parents=True, exist_ok=True)
        (self.trusted / "mobile/app.json").write_text(
            json.dumps({"expo": {"ios": {"infoPlist": {"ClarifyCloudURL": CLOUD}}}}),
            encoding="utf-8",
        )
        license_path = self.trusted / "mobile/third-party/KeyboardHostBundleID/LICENSE"
        license_path.parent.mkdir(parents=True, exist_ok=True)
        license_path.write_bytes(LICENSE)
        for name in (
            "mobile/scripts/verify-ios-ipa.py",
            "mobile/scripts/publish-testflight.cjs",
        ):
            data = (Path(__file__).resolve().parents[1] / name).read_bytes()
            self.controls[name] = data
            (self.trusted / name).write_bytes(data)
            self.policy.context["controls"][name] = qa.git_blob(data)
        self.entries[qa.APP_PATH + "/caf\u00e9.txt"] = (
            b"non-ASCII manifest path",
            stat.S_IFREG | 0o644,
        )
        self.entries[qa.APP_PATH + "/empty/"] = b"", stat.S_IFDIR | 0o755
        self.refresh()
        return self.sign(FakeRunner(self))

    def publication_env(self):
        return {
            "GITHUB_RUN_ID": "91",
            "GITHUB_RUN_ATTEMPT": "3",
            "CLARIFY_ASC_KEY_ID": "ABC123DE45",
            "CLARIFY_ASC_ISSUER_ID": "12345678-1234-1234-1234-1234567890ab",
            "CLARIFY_ASC_KEY_P8": "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
            "CLARIFY_IOS_CERTIFICATE_PASSWORD": "certificate-secret",
            "UNRELATED_SECRET": "unrelated-secret",
        }

    def publication_runner(self, calls, *, fail=None, mutate_verification=None):
        def run(command, *, cwd, env):
            calls.append(command)
            self.assertFalse(
                any(
                    "SECRET" in key or key.startswith(("CLARIFY_ASC_", "CLARIFY_IOS_"))
                    for key in env
                )
            )
            if "--qa-context" in command:
                self.assertEqual(cwd, self.trusted / "mobile")
                self.assertEqual(
                    command[1:3],
                    ("-I", str(self.trusted / "mobile/scripts/verify-ios-ipa.py")),
                )
                self.assertEqual(command[-2], "--qa-context")
                # Run the real trusted R6 verifier with synthetic git/signature
                # responses. It must read the fixed inner ZIP and write its sidecar.
                spec = importlib.util.spec_from_file_location("qa_r6_test", command[2])
                helper = importlib.util.module_from_spec(spec)
                exec(
                    compile(Path(command[2]).read_bytes(), command[2], "exec"),
                    helper.__dict__,
                )

                def native(argv, **kwargs):
                    if argv[0] == "git":
                        value = {
                            "HEAD": "c" * 40,
                            "c" * 40 + "^{tree}": "d" * 40,
                            "c" * 40 + ":" + qa.WORKFLOW: self.policy.context[
                                "workflow"
                            ]["blob_sha"],
                        }.get(argv[-1], "")
                        return SimpleNamespace(stdout=value, returncode=0)
                    self.assertEqual(argv[0], "codesign")
                    suffix = {
                        "Clarify.app": "",
                        "ClarifyKeyboard.appex": ".keyboard",
                        "ClarifyActivity.appex": ".activity",
                    }[Path(argv[-1]).name]
                    entitlements = {
                        "application-identifier": qa.TEAM + "." + qa.BUNDLE + suffix,
                        "com.apple.developer.team-identifier": qa.TEAM,
                        "com.apple.security.application-groups": ["group." + qa.BUNDLE],
                    }
                    return SimpleNamespace(
                        stdout=plistlib.dumps(entitlements), returncode=0
                    )

                with (
                    patch.dict(os.environ, env, clear=True),
                    patch.object(helper.subprocess, "run", side_effect=native),
                ):
                    verification = helper.verify_ipa(command[3], qa_context=command[5])
                if mutate_verification:
                    mutate_verification(verification)
                    Path(command[3]).with_name("verification.json").write_text(
                        json.dumps(verification), encoding="utf-8"
                    )
                return SimpleNamespace(
                    returncode=1 if fail == "verify" else 0,
                    stdout=b"secret",
                    stderr=b"secret",
                )
            self.assertEqual(
                command[:7],
                (
                    "/usr/bin/xcrun",
                    "altool",
                    "--upload-app",
                    "--type",
                    "ios",
                    "--file",
                    str(self.runner_temp / "clarify-ios-qa/output/Clarify.ipa"),
                ),
            )
            self.assertEqual(
                command[7:],
                (
                    "--apiKey",
                    "ABC123DE45",
                    "--apiIssuer",
                    "12345678-1234-1234-1234-1234567890ab",
                ),
            )
            receipt = qa.decode(
                (
                    self.runner_temp / "clarify-ios-qa/output/upload-receipt.json"
                ).read_bytes()
            )
            self.assertEqual(receipt["status"], "started")
            key = Path(env["API_PRIVATE_KEYS_DIR"]) / "AuthKey_ABC123DE45.p8"
            self.assertEqual(
                key.read_text(), self.publication_env()["CLARIFY_ASC_KEY_P8"]
            )
            if os.name != "nt":
                self.assertEqual(key.stat().st_mode & 0o777, 0o600)
                self.assertEqual(key.parent.stat().st_mode & 0o777, 0o700)
            if fail == "timeout":
                raise qa.subprocess.TimeoutExpired(command, 1, output=b"secret")
            return SimpleNamespace(
                returncode=1 if fail == "upload" else 0,
                stdout=b"secret",
                stderr=b"secret",
            )

        return run

    def prepare_publication(self, result, runner):
        return qa.prepare_qa_context(
            result,
            self.policy,
            runner_temp=self.runner_temp,
            trusted_root=self.trusted,
            run_id=91,
            run_attempt=3,
            runner=runner,
        )

    def upload_publication(self, prepared, runner):
        with patch.dict(os.environ, self.publication_env(), clear=True):
            return qa.upload_qa_context(
                prepared,
                self.policy,
                runner_temp=self.runner_temp,
                trusted_root=self.trusted,
                runner=runner,
            )

    def test_publication_stages_real_export_with_r6_hashes_then_uploads_once(self):
        result, calls = self.publication_result(), []
        runner = self.publication_runner(calls)
        with patch.dict(os.environ, self.publication_env(), clear=True):
            prepared = self.prepare_publication(result, runner)
        context = prepared["context"]
        self.assertEqual(
            set(prepared),
            {
                "context",
                "context_path",
                "ipa_path",
                "verification_path",
                "receipt_path",
            },
        )
        self.assertEqual(
            prepared["verification_path"],
            self.runner_temp / "clarify-ios-qa/output/verification.json",
        )
        self.assertEqual(
            context["artifact"]["sha256"], result["receipt"]["archive"]["sha256"]
        )
        self.assertNotEqual(
            context["artifact"]["sha256"], result["receipt"]["artifact"]["sha256"]
        )
        self.assertEqual((context["run_id"], context["run_attempt"]), (91, 3))
        self.assertEqual(
            (context["artifact"]["run_id"], context["artifact"]["run_attempt"]), (71, 2)
        )
        app = result["workspace"] / "signed-inspection/Payload/Clarify.app"
        records = [
            {
                "path": path.relative_to(app).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in app.rglob("*")
            if path.is_file()
        ]
        records.sort(key=lambda item: item["path"])
        expected = hashlib.sha256(
            json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        self.assertEqual(context["bundles"][0]["sha256"], expected)
        self.assertNotEqual(expected, result["receipt"]["ipa"]["bundles"][0]["sha256"])
        self.assertEqual(prepared["context_path"].read_bytes(), qa.canonical(context))
        self.assertLessEqual(prepared["context_path"].stat().st_size, 8192)
        self.assertEqual(len(calls), 1)
        self.assertFalse(prepared["receipt_path"].exists())
        receipt = self.upload_publication(prepared, runner)
        self.assertEqual(receipt["status"], "confirmed")
        self.assertEqual(receipt["qa"], context)
        self.assertIs(receipt["delivery_eligible"], False)
        self.assertIs(receipt["workflowArtifactProvenanceVerified"], False)
        self.assertEqual(qa.decode(prepared["receipt_path"].read_bytes()), receipt)
        self.assertFalse((self.runner_temp / "clarify-upload").exists())
        with self.assertRaises(qa.ArchiveError):
            self.upload_publication(prepared, runner)
        self.assertEqual(len(calls), 2)

    def test_publication_rejects_changed_data_policy_run_and_verification_before_upload(
        self,
    ):
        result, calls = self.publication_result(), []
        runner = self.publication_runner(calls)
        prepared = self.prepare_publication(result, runner)
        for key in ("ipa_path", "context_path", "verification_path"):
            path, original = prepared[key], prepared[key].read_bytes()
            path.write_bytes(b"changed")
            with self.subTest(path=key), self.assertRaises(qa.ArchiveError):
                self.upload_publication(prepared, runner)
            path.write_bytes(original)
        archive = self.runner_temp / "clarify-ios-qa/input" / qa.ARCHIVE_NAME
        original = archive.read_bytes()
        archive.write_bytes(b"changed")
        with self.assertRaises(qa.ArchiveError):
            self.upload_publication(prepared, runner)
        archive.write_bytes(original)
        substituted = {**prepared, "ipa_path": result["ipa_path"]}
        with self.assertRaises(qa.ArchiveError):
            self.upload_publication(substituted, runner)
        verification = qa.decode(prepared["verification_path"].read_bytes())
        verification["workflowArtifactProvenanceVerified"] = True
        prepared["verification_path"].write_bytes(qa.canonical(verification))
        with self.assertRaises(qa.ArchiveError):
            self.upload_publication(prepared, runner)
        verification["workflowArtifactProvenanceVerified"] = False
        prepared["verification_path"].write_bytes(qa.canonical(verification))
        self.policy.context["source_tree"] = "e" * 40
        with self.assertRaises(qa.ArchiveError):
            self.upload_publication(prepared, runner)
        self.policy.context["source_tree"] = "b" * 40
        with patch.dict(
            os.environ,
            {**self.publication_env(), "GITHUB_RUN_ATTEMPT": "4"},
            clear=True,
        ):
            with self.assertRaises(qa.ArchiveError):
                qa.upload_qa_context(
                    prepared,
                    self.policy,
                    runner_temp=self.runner_temp,
                    trusted_root=self.trusted,
                    runner=runner,
                )
        self.assertEqual(len(calls), 1)
        self.assertFalse(prepared["receipt_path"].exists())

    def test_publication_uncertain_upload_blocks_retry_and_always_removes_keys(self):
        original_runner = self.runner_temp
        for failure in ("upload", "timeout"):
            with self.subTest(failure=failure):
                self.runner_temp = original_runner / failure
                self.runner_temp.mkdir()
                result, calls = self.publication_result(), []
                runner = self.publication_runner(calls, fail=failure)
                prepared = self.prepare_publication(result, runner)
                with (
                    patch("sys.stdout", new_callable=io.StringIO) as out,
                    patch("sys.stderr", new_callable=io.StringIO) as err,
                ):
                    with self.assertRaises(qa.ArchiveError) as error:
                        self.upload_publication(prepared, runner)
                self.assertNotIn("secret", str(error.exception))
                self.assertEqual(out.getvalue() + err.getvalue(), "")
                self.assertEqual(
                    qa.decode(prepared["receipt_path"].read_bytes())["status"],
                    "uncertain",
                )
                self.assertFalse((self.runner_temp / "clarify-upload").exists())
                with self.assertRaises(qa.ArchiveError):
                    self.upload_publication(prepared, runner)
                self.assertEqual(len(calls), 2)

    def test_publication_rejects_reused_stage_and_changed_trusted_helper(self):
        result, calls = self.publication_result(), []
        runner = self.publication_runner(calls)
        helper = self.trusted / "mobile/scripts/publish-testflight.cjs"
        original = helper.read_bytes()
        helper.write_bytes(b"changed")
        with self.assertRaises(qa.ArchiveError):
            self.prepare_publication(result, runner)
        self.assertEqual(calls, [])
        helper.write_bytes(original)
        self.prepare_publication(result, runner)
        with self.assertRaises(qa.ArchiveError):
            self.prepare_publication(result, runner)
        self.assertEqual(len(calls), 1)

    def test_publication_rejects_verifier_failure_or_dishonest_sidecar(self):
        original_runner = self.runner_temp
        for failure in ("verify", "sidecar", "signed"):
            with self.subTest(failure=failure):
                self.runner_temp = original_runner / failure
                self.runner_temp.mkdir()
                result, calls = self.publication_result(), []
                if failure == "signed":
                    (
                        result["workspace"]
                        / "signed-inspection/Payload/Clarify.app/Clarify"
                    ).write_bytes(b"changed")
                runner = self.publication_runner(
                    calls,
                    fail=failure,
                    mutate_verification=(
                        lambda value: value.update(bundleDigestsVerified=False)
                    )
                    if failure == "sidecar"
                    else None,
                )
                with self.assertRaises(qa.ArchiveError):
                    self.prepare_publication(result, runner)
                self.assertEqual(len(calls), 1)
                self.assertFalse((self.runner_temp / "clarify-upload").exists())

    def test_publication_key_write_failure_cleans_without_upload(self):
        result, calls = self.publication_result(), []
        runner = self.publication_runner(calls)
        prepared = self.prepare_publication(result, runner)
        original_open = Path.open

        def fail_key(path, *args, **kwargs):
            if path.suffix == ".p8":
                raise OSError("Synthetic key-file failure")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", fail_key):
            with self.assertRaises(OSError):
                self.upload_publication(prepared, runner)
        self.assertEqual(len(calls), 1)
        self.assertFalse((self.runner_temp / "clarify-upload").exists())
        self.assertFalse(prepared["receipt_path"].exists())


if __name__ == "__main__":
    unittest.main()
