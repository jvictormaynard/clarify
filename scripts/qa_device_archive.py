"""MAIN-owned archive policy, data inspection and experimental local export.

The caller owns transport and supplies policy from reviewed MAIN, never from the
artifact. API methods must read the named GitHub endpoints with authenticated
transport. This module compares their facts; no owner-provided verified flag is
accepted. The signing consumer needs a new trusted macOS runner. No candidate
process runs there. Export success remains ineligible for delivery until the
owner establishes native compatibility separately.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from typing import Protocol
import unicodedata
import uuid
import zipfile
import zlib

TEAM = "8K353P3496"
BUNDLE = "com.jvictormaynard.clarify"
APP_ID = "6820869157"
REPOSITORY = "jvictormaynard/clarify"
WORKFLOW = ".github/workflows/ios-qa.yml"
SIGNING_HELPER = "mobile/scripts/ios-signing.py"
QA_VERIFIER = "mobile/scripts/verify-ios-ipa.py"
QA_PUBLISHER = "mobile/scripts/publish-testflight.cjs"
MODULE = "scripts/qa_device_archive.py"
ARCHIVE_ROOT = "Clarify.xcarchive"
ARCHIVE_NAME = "unsigned.xcarchive.zip"
ENVELOPE_NAME = "archive-envelope.json"
APP_PATH = ARCHIVE_ROOT + "/Products/Applications/Clarify.app"
BUNDLE_LAYOUT = (
    (BUNDLE, APP_PATH, "Clarify", None),
    (
        BUNDLE + ".keyboard",
        APP_PATH + "/PlugIns/ClarifyKeyboard.appex",
        "ClarifyKeyboard",
        "com.apple.keyboard-service",
    ),
    (
        BUNDLE + ".activity",
        APP_PATH + "/PlugIns/ClarifyActivity.appex",
        "ClarifyActivity",
        "com.apple.widgetkit-extension",
    ),
)
LICENSE_PATH = BUNDLE_LAYOUT[1][1] + "/KeyboardHostBundleID.LICENSE"
RECORD_PREFIX = "CLARIFY_QA_ARCHIVE_ARTIFACT "
LOG_TRUST_MODEL = "trusted-final-job-log-v1"
MAX_ENVELOPE = 256 * 1024
MAX_LOG = 1024 * 1024
CONTEXT_KEYS = {
    "schema",
    "kind",
    "trust_model",
    "repository",
    "pr",
    "source_sha",
    "source_tree",
    "base_sha",
    "base_tree",
    "trusted_sha",
    "app_id",
    "bundle_id",
    "version",
    "build",
    "tag",
    "relay_host",
    "workflow",
    "producer",
    "controls",
    "recipe",
    "entitlements_policy",
}
ENVELOPE_KEYS = CONTEXT_KEYS | {"archive", "bundles", "code_objects"}
SIGNING_POLICY = {
    "team": TEAM,
    "app_group": "group." + BUNDLE,
    "group_bundles": [BUNDLE, BUNDLE + ".keyboard"],
    "activity_group_absent": True,
    "keychain": "own-application-identifier",
    "get_task_allow": False,
    "beta_reports_active": "existing-boolean-only",
}


class ArchiveError(ValueError):
    """The archive boundary blocked an operation; messages contain no tool output."""


def require(condition, message):
    if not condition:
        raise ArchiveError(message)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True
    ).encode("ascii")


def digest(data):
    return hashlib.sha256(data).hexdigest()


ENTITLEMENTS_POLICY = {
    "id": "clarify-ios-distribution-v1",
    "sha256": digest(canonical(SIGNING_POLICY)),
}


def git_blob(data):
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    ).hexdigest()


def exact(value, keys, label):
    require(
        type(value) is dict and set(value) == set(keys), "Invalid " + label + " fields"
    )


def matches(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def positive(value):
    return type(value) is int and 1 <= value <= 2**53 - 1


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def decode(data, *, maximum=MAX_ENVELOPE):
    require(type(data) is bytes and len(data) <= maximum, "JSON size limit exceeded")
    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ArchiveError("Invalid JSON constant")
            ),
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, ArchiveError):
            raise
        raise ArchiveError("Malformed JSON data") from None


@dataclass(frozen=True)
class Limits:
    """Internal test seam. CLI and envelope cannot change production limits."""

    entries: int = 50_000
    file_bytes: int = 512 * 1024**2
    expanded_bytes: int = 2 * 1024**3
    zip_bytes: int = 2 * 1024**3
    depth: int = 32
    path_bytes: int = 1024
    compression_ratio: int = 1000

    def __post_init__(self):
        for name, maximum in self.__dataclass_fields__.items():
            value = getattr(self, name)
            require(
                positive(value) and value <= maximum.default,
                "Limits may only be reduced",
            )


LIMITS = Limits()


def safe_name(name, limits=LIMITS):
    require(type(name) is str and name, "Unsafe archive path")
    try:
        encoded = name.encode("utf-8")
    except UnicodeError:
        raise ArchiveError("Unsafe archive path") from None
    parts = name.rstrip("/").split("/")
    require(
        not name.startswith("/")
        and "\\" not in name
        and ":" not in name
        and "\0" not in name
        and len(encoded) <= limits.path_bytes
        and len(parts) <= limits.depth
        and unicodedata.normalize("NFC", name) == name
        and all(
            part
            and part not in {".", ".."}
            and not part.endswith((".", " "))
            and not any(ord(char) < 32 or char in '<>"|?*' for char in part)
            and part.split(".")[0].upper()
            not in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10)),
            }
            for part in parts
        ),
        "Unsafe archive path",
    )
    return name.rstrip("/")


def _path_inventory(records, limits=LIMITS):
    """Include implicit parents when checking case collisions and node conflicts."""
    explicit, targets = set(), {}
    for record in records:
        name = safe_name(record["path"], limits)
        require(name not in explicit, "Duplicate archive target")
        explicit.add(name)
        parts = name.split("/")
        for index in range(1, len(parts) + 1):
            path = "/".join(parts[:index])
            kind = record["kind"] if index == len(parts) else "directory"
            folded = path.casefold()
            if folded in targets:
                previous_path, previous_kind = targets[folded]
                require(previous_path == path, "Casefold archive collision")
                require(previous_kind == kind, "Archive file/directory conflict")
            else:
                targets[folded] = path, kind


def _node(path):
    info = path.lstat()
    require(
        not stat.S_ISLNK(info.st_mode)
        and not getattr(info, "st_file_attributes", 0) & 0x400,
        "Links and reparse points are forbidden",
    )
    require(
        stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), "Special archive node"
    )
    require(
        not stat.S_ISREG(info.st_mode) or info.st_nlink == 1, "Hardlinks are forbidden"
    )
    require(not info.st_mode & 0o7000, "Special archive mode")
    return info


def absolute_path(value, *, exists=True):
    path = Path(value)
    require(
        path.is_absolute() and ".." not in path.parts,
        "Expected an absolute bounded path",
    )
    for item in reversed((path, *path.parents)):
        if item.exists() or item.is_symlink():
            _node(item)
        elif item != path or exists:
            raise ArchiveError("Missing path ancestor")
    return path


def file_digest(path, maximum=LIMITS.file_bytes):
    before = _node(path)
    require(
        stat.S_ISREG(before.st_mode) and before.st_size <= maximum,
        "File size limit exceeded",
    )
    result, size = hashlib.sha256(), 0
    with path.open("rb") as incoming:
        opened = os.fstat(incoming.fileno())
        require(
            (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
            "File changed before read",
        )
        while chunk := incoming.read(1024 * 1024):
            size += len(chunk)
            require(size <= maximum, "File size limit exceeded")
            result.update(chunk)
        after = os.fstat(incoming.fileno())
    require(
        size == before.st_size
        and (after.st_ino, after.st_size, after.st_mtime_ns)
        == (before.st_ino, before.st_size, before.st_mtime_ns),
        "File changed during read",
    )
    current = _node(path)
    require(
        (
            current.st_dev,
            current.st_ino,
            current.st_mode,
            current.st_nlink,
            current.st_size,
            current.st_mtime_ns,
        )
        == (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
        ),
        "File changed after read",
    )
    return {"bytes": size, "sha256": result.hexdigest()}


def _zip_items(archive, limits, *, transport=False):
    items = archive.infolist()
    require(len(items) <= limits.entries, "Archive entry limit exceeded")
    records, total = [], 0
    for item in items:
        name = safe_name(item.orig_filename, limits)
        require(item.orig_filename == item.filename, "Changed ZIP path")
        mode = item.external_attr >> 16
        kind = stat.S_IFMT(mode)
        directory = item.is_dir()
        require(
            kind in {0, stat.S_IFREG, stat.S_IFDIR}
            and (kind != stat.S_IFDIR or directory)
            and (kind != stat.S_IFREG or not directory)
            and not mode & 0o7000
            and not item.external_attr & 0x400,
            "ZIP contains a link or special node",
        )
        require(not item.flag_bits & ~0x808, "Encrypted or unsupported ZIP flags")
        require(
            item.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED},
            "Unsupported ZIP compression",
        )
        # Our transport writes no metadata extras. Only ZIP64 is necessary.
        offset = 0
        while offset < len(item.extra):
            require(offset + 4 <= len(item.extra), "Truncated ZIP extra")
            tag, size = struct.unpack_from("<HH", item.extra, offset)
            offset += 4
            require(
                tag == 1 and offset + size <= len(item.extra),
                "Unsupported ZIP link or metadata extra",
            )
            offset += size
        if transport:
            require(
                name in {ARCHIVE_NAME, ENVELOPE_NAME} and not directory,
                "Unexpected GitHub artifact members",
            )
        per_file = (
            limits.zip_bytes
            if transport and name == ARCHIVE_NAME
            else MAX_ENVELOPE
            if transport
            else limits.file_bytes
        )
        total += item.file_size
        require(
            0 <= item.file_size <= per_file
            and total
            <= (
                limits.zip_bytes + MAX_ENVELOPE if transport else limits.expanded_bytes
            ),
            "Archive expanded size limit exceeded",
        )
        require(not directory or item.file_size == 0, "Directory has data")
        require(
            item.file_size <= 1024**2
            or item.file_size <= max(1, item.compress_size) * limits.compression_ratio,
            "Archive compression bomb",
        )
        records.append(
            {
                "path": name,
                "kind": "directory" if directory else "file",
                "mode": mode & 0o777,
                "bytes": item.file_size,
            }
        )
    _path_inventory(records, limits)
    return items, records


def zip_manifest(path, *, limits=LIMITS, _transport=False):
    """Read every entry and CRC before a caller can extract or install keys."""
    path = absolute_path(path)
    require(path.stat().st_size <= limits.zip_bytes, "ZIP size limit exceeded")
    try:
        with zipfile.ZipFile(path) as archive:
            items, records = _zip_items(archive, limits, transport=_transport)
            # Reject split, appended, prefixed and comment-bearing containers.
            # Production limits are below ZIP64 central-directory thresholds;
            # ZIP64 local size extras from our streaming pack remain supported.
            with path.open("rb") as raw:
                require(path.stat().st_size >= 22, "Truncated ZIP end record")
                raw.seek(-22, 2)
                end = raw.read(22)
                (
                    magic,
                    disk,
                    central_disk,
                    count_disk,
                    count,
                    central_size,
                    central_offset,
                    comment,
                ) = struct.unpack("<4s4H2IH", end)
                require(
                    magic == b"PK\x05\x06"
                    and disk == central_disk == comment == 0
                    and count_disk == count == len(items)
                    and archive.start_dir == central_offset
                    and central_offset + central_size == path.stat().st_size - 22,
                    "Invalid ZIP end structure",
                )
                ordered_offsets = sorted(item.header_offset for item in items)
                next_offset = dict(
                    zip(ordered_offsets, [*ordered_offsets[1:], central_offset])
                )
                offsets = set()
                for item in items:
                    require(
                        item.header_offset not in offsets
                        and 0 <= item.header_offset < central_offset,
                        "Duplicate or invalid ZIP local header",
                    )
                    offsets.add(item.header_offset)
                    raw.seek(item.header_offset)
                    header = raw.read(30)
                    require(len(header) == 30, "Truncated ZIP local header")
                    (
                        local_magic,
                        _,
                        flags,
                        compression,
                        _,
                        _,
                        crc,
                        compressed,
                        expanded,
                        name_size,
                        extra_size,
                    ) = struct.unpack("<4s5H3I2H", header)
                    require(
                        local_magic == b"PK\x03\x04"
                        and flags == item.flag_bits
                        and compression == item.compress_type,
                        "ZIP local/central header differs",
                    )
                    encoded_name, extra = raw.read(name_size), raw.read(extra_size)
                    try:
                        name = encoded_name.decode(
                            "utf-8" if flags & 0x800 else "cp437"
                        )
                    except UnicodeError:
                        raise ArchiveError("Invalid ZIP local filename") from None
                    require(name == item.orig_filename, "ZIP local filename differs")
                    offset = 0
                    while offset < len(extra):
                        require(offset + 4 <= len(extra), "Truncated ZIP local extra")
                        tag, size = struct.unpack_from("<HH", extra, offset)
                        offset += 4
                        require(
                            tag == 1 and offset + size <= len(extra),
                            "Unsupported ZIP local metadata extra",
                        )
                        if expanded == 0xFFFFFFFF or compressed == 0xFFFFFFFF:
                            require(size == 16, "Invalid ZIP64 local sizes")
                            expanded, compressed = struct.unpack_from(
                                "<QQ", extra, offset
                            )
                        offset += size
                    require(
                        flags & 8
                        or (
                            crc == item.CRC
                            and compressed == item.compress_size
                            and expanded == item.file_size
                        ),
                        "ZIP local/central sizes differ",
                    )
                    payload_end = raw.tell() + item.compress_size
                    boundary = next_offset[item.header_offset]
                    require(payload_end <= boundary, "Overlapping ZIP entry data")
                    if flags & 8:
                        require(
                            boundary - payload_end in {12, 16, 20, 24},
                            "Invalid ZIP descriptor size",
                        )
                        raw.seek(payload_end)
                        descriptor = raw.read(boundary - payload_end)
                        if descriptor.startswith(b"PK\x07\x08"):
                            descriptor = descriptor[4:]
                        require(len(descriptor) in {12, 20}, "Invalid ZIP descriptor")
                        values = struct.unpack(
                            "<III" if len(descriptor) == 12 else "<IQQ", descriptor
                        )
                        require(
                            values == (item.CRC, item.compress_size, item.file_size),
                            "ZIP descriptor differs",
                        )
                    else:
                        require(
                            payload_end == boundary,
                            "Unexpected data between ZIP entries",
                        )
            for item, record in zip(items, records):
                hashed, size = hashlib.sha256(), 0
                with archive.open(item) as incoming:
                    while chunk := incoming.read(1024 * 1024):
                        size += len(chunk)
                        per_file = (
                            limits.zip_bytes
                            if _transport and record["path"] == ARCHIVE_NAME
                            else MAX_ENVELOPE
                            if _transport
                            else limits.file_bytes
                        )
                        require(
                            size <= record["bytes"] and size <= per_file,
                            "ZIP stream size limit exceeded",
                        )
                        hashed.update(chunk)
                require(size == record["bytes"], "Truncated ZIP entry")
                record["sha256"] = hashed.hexdigest()
        return sorted(records, key=lambda record: record["path"])
    except (
        zipfile.BadZipFile,
        EOFError,
        zlib.error,
        NotImplementedError,
        RuntimeError,
    ):
        raise ArchiveError("Invalid ZIP structure or CRC") from None


def _extract(path, destination, manifest, limits=LIMITS, *, transport=False):
    """Extract known regular data exclusively; never use extractall."""
    destination.mkdir(mode=0o700)
    with zipfile.ZipFile(path) as archive:
        for record in sorted(
            manifest, key=lambda record: (record["path"].count("/"), record["path"])
        ):
            output = destination / record["path"]
            if record["kind"] == "directory":
                output.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            size, hashed = 0, hashlib.sha256()
            with (
                archive.open(record["path"]) as incoming,
                output.open("xb") as outgoing,
            ):
                while chunk := incoming.read(1024 * 1024):
                    size += len(chunk)
                    per_file = (
                        limits.zip_bytes
                        if transport and record["path"] == ARCHIVE_NAME
                        else MAX_ENVELOPE
                        if transport
                        else limits.file_bytes
                    )
                    require(
                        size <= record["bytes"] and size <= per_file,
                        "ZIP stream size limit exceeded",
                    )
                    outgoing.write(chunk)
                    hashed.update(chunk)
            require(
                size == record["bytes"] and hashed.hexdigest() == record["sha256"],
                "ZIP changed during extraction",
            )
            output.chmod(record["mode"])
    for record in sorted(manifest, key=lambda record: -record["path"].count("/")):
        if record["kind"] == "directory":
            (destination / record["path"]).chmod(record["mode"])


def inspect_macho(data, *, primary=False, debug=False, signed=False):
    """Inspect thin ARM64 load commands, without executing candidate code."""
    require(
        type(data) is bytes and 32 <= len(data) <= 32 + 16 * 1024**2,
        "Invalid Mach-O header size",
    )
    magic, cpu, subtype, kind, count, size, _, reserved = struct.unpack_from(
        "<8I", data
    )
    require(
        magic == 0xFEEDFACF
        and cpu == 0x0100000C
        and subtype == 0
        and reserved == 0
        and kind in ({2} if primary else {10} if debug else {2, 6, 8}),
        "Expected thin ARM64 Mach-O kind",
    )
    require(
        1 <= count <= 4096 and size <= 16 * 1024**2 and 32 + size <= len(data),
        "Invalid Mach-O load bounds",
    )
    offset, platforms, uuids, signatures = 32, [], [], 0
    for _ in range(count):
        require(offset + 8 <= 32 + size, "Truncated Mach-O load command")
        command, length = struct.unpack_from("<2I", data, offset)
        require(
            length >= 8 and length % 8 == 0 and offset + length <= 32 + size,
            "Invalid Mach-O load bounds",
        )
        require(
            command not in {0x24, 0x25, 0x2F, 0x30},
            "Ambiguous Mach-O platform metadata",
        )
        if command == 0x1D:
            signatures += 1
            require(not primary or signed, "Signed primary executable")
            require(length == 16, "Invalid code signature command")
        if command == 0x32:
            require(length >= 24, "Truncated Mach-O platform command")
            _, _, platform, _, _, tools = struct.unpack_from("<6I", data, offset)
            require(
                tools <= 1024 and length == 24 + tools * 8, "Invalid Mach-O build tools"
            )
            platforms.append(platform)
        if command == 0x1B:
            require(length == 24, "Invalid Mach-O UUID command")
            uuids.append(str(uuid.UUID(bytes=data[offset + 8 : offset + 24])))
        offset += length
    require(
        offset == 32 + size and signatures <= 1 and len(uuids) <= 1,
        "Conflicting Mach-O load metadata",
    )
    require(
        platforms == [2] or debug and platforms == [],
        "Expected one iOS device platform declaration",
    )
    return {
        "architectures": ["arm64"],
        "platform": "ios-device" if platforms else None,
        "uuids": uuids,
    }


def _macho_prefix(path):
    with path.open("rb") as incoming:
        header = incoming.read(32)
        require(len(header) == 32, "Truncated Mach-O header")
        size = struct.unpack_from("<I", header, 20)[0]
        require(size <= 16 * 1024**2, "Invalid Mach-O load bounds")
        return header + incoming.read(size)


def _validate_context(value):
    exact(value, CONTEXT_KEYS, "policy context")
    require(
        type(value["schema"]) is int
        and value["schema"] == 1
        and value["kind"] == "clarify-ios-qa-unsigned-archive"
        and value["trust_model"] == "reviewed-source-internal-qa-v1"
        and value["repository"] == REPOSITORY
        and value["app_id"] == APP_ID
        and value["bundle_id"] == BUNDLE
        and value["relay_host"] is None,
        "Invalid archive identity",
    )
    require(positive(value["pr"]), "Invalid PR identity")
    for key in ("source_sha", "source_tree", "base_sha", "base_tree", "trusted_sha"):
        require(matches(value[key], r"[0-9a-f]{40}"), "Invalid Git binding")
    require(
        matches(
            value["version"], r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
        )
        and matches(value["build"], r"[1-9][0-9]{0,8}"),
        "Invalid version/build",
    )
    require(
        value["tag"]
        == f"ios/pr-{value['pr']}/v{value['version']}-build{value['build']}",
        "Invalid QA tag",
    )
    workflow = value["workflow"]
    exact(workflow, {"id", "path", "blob_sha"}, "workflow")
    require(
        positive(workflow["id"])
        and workflow["path"] == WORKFLOW
        and matches(workflow["blob_sha"], r"[0-9a-f]{40}"),
        "Invalid workflow binding",
    )
    producer = value["producer"]
    exact(producer, {"run_id", "run_attempt", "job_key"}, "producer")
    require(
        positive(producer["run_id"])
        and type(producer["run_attempt"]) is int
        and 1 <= producer["run_attempt"] <= 100
        and matches(producer["job_key"], r"[a-zA-Z_][a-zA-Z0-9_-]{0,99}"),
        "Invalid producer binding",
    )
    controls = value["controls"]
    require(
        type(controls) is dict and {WORKFLOW, SIGNING_HELPER, MODULE} <= set(controls),
        "Missing MAIN controls",
    )
    for path, blob in controls.items():
        safe_name(path)
        require(matches(blob, r"[0-9a-f]{40}"), "Invalid MAIN control blob")
    require(
        controls[WORKFLOW] == workflow["blob_sha"], "Workflow/control binding differs"
    )
    recipe = value["recipe"]
    exact(
        recipe,
        {
            "id",
            "configuration",
            "sdk",
            "destination",
            "architectures",
            "code_signing_allowed",
            "xcode_build",
            "sdk_version",
        },
        "recipe",
    )
    require(
        matches(recipe["id"], r"[A-Za-z0-9_.-]{1,100}")
        and recipe["configuration"] == "Release"
        and recipe["sdk"] == "iphoneos"
        and recipe["destination"] == "generic/platform=iOS"
        and recipe["architectures"] == ["arm64"]
        and recipe["code_signing_allowed"] is False
        and matches(recipe["xcode_build"], r"[A-Za-z0-9.]{1,40}")
        and matches(recipe["sdk_version"], r"[0-9]+(?:\.[0-9]+){1,2}"),
        "Invalid MAIN archive recipe",
    )
    require(
        value["entitlements_policy"] == ENTITLEMENTS_POLICY,
        "Unknown entitlement policy",
    )


@dataclass(frozen=True)
class ArchivePolicy:
    """Expected tuple resolved by the caller from reviewed MAIN and native plan.

    Job/step names and pinned upload action are MAIN policy, not artifact data.
    The caller must establish that the authenticated workflow implements this
    producer and its unique recorder. No candidate stdout is a proof channel.
    """

    context: dict
    cloud_url: str
    license_sha256: str
    producer_job_name: str
    producer_steps: tuple[str, ...]
    final_job_name: str
    final_steps: tuple[str, ...]
    uploader_step: str
    recorder_step: str
    upload_action: str
    required_resources: tuple[str, ...] = (APP_PATH + "/main.jsbundle",)

    def validate(self):
        _validate_context(self.context)
        require(
            matches(self.cloud_url, r"https://[A-Za-z0-9.-]+(?::[0-9]+)?(?:/[^\s?#]*)?")
            and matches(self.license_sha256, r"[0-9a-f]{64}"),
            "Invalid MAIN resource policy",
        )
        require(
            matches(self.upload_action, r"actions/upload-artifact@[0-9a-f]{40}"),
            "Unpinned uploader",
        )
        for names in (self.producer_steps, self.final_steps):
            require(
                type(names) is tuple
                and names
                and len(set(names)) == len(names)
                and all(type(name) is str and 0 < len(name) <= 200 for name in names),
                "Invalid MAIN step policy",
            )
        require(
            self.uploader_step in self.producer_steps
            and self.recorder_step in self.final_steps,
            "Missing uploader/recorder policy",
        )
        require(
            self.producer_job_name
            and self.final_job_name
            and self.producer_job_name != self.final_job_name,
            "Invalid MAIN job policy",
        )
        for path in self.required_resources:
            require(
                safe_name(path).startswith(APP_PATH + "/"), "Resource outside the app"
            )
        # Bound and copyable JSON; arbitrary executable objects are not policy.
        require(
            len(canonical(self.context)) <= MAX_ENVELOPE, "Policy size limit exceeded"
        )
        return self


def load_envelope(data):
    value = decode(data)
    exact(value, ENVELOPE_KEYS, "archive envelope")
    _validate_context({key: value[key] for key in CONTEXT_KEYS})
    archive = value["archive"]
    exact(
        archive, {"filename", "root", "bytes", "sha256", "manifest_sha256"}, "archive"
    )
    require(
        archive["filename"] == ARCHIVE_NAME
        and archive["root"] == ARCHIVE_ROOT
        and positive(archive["bytes"])
        and archive["bytes"] <= LIMITS.zip_bytes
        and all(
            matches(archive[key], r"[0-9a-f]{64}")
            for key in ("sha256", "manifest_sha256")
        ),
        "Invalid archive binding",
    )
    require(
        type(value["bundles"]) is list and len(value["bundles"]) == 3,
        "Expected three bundle bindings",
    )
    for bundle in value["bundles"]:
        exact(
            bundle,
            {
                "id",
                "path",
                "sha256",
                "info_plist_sha256",
                "executable",
                "executable_sha256",
                "executable_bytes",
                "architectures",
                "platform",
                "embedded_entitlements",
            },
            "bundle",
        )
        require(
            positive(bundle["executable_bytes"])
            and bundle["executable_bytes"] <= LIMITS.file_bytes
            and bundle["embedded_entitlements"] is None,
            "Invalid unsigned bundle binding",
        )
        for key in ("sha256", "info_plist_sha256", "executable_sha256"):
            require(matches(bundle[key], r"[0-9a-f]{64}"), "Invalid bundle hash")
    require(
        type(value["code_objects"]) is list
        and len(value["code_objects"]) <= LIMITS.entries,
        "Invalid code inventory",
    )
    for code in value["code_objects"]:
        exact(
            code,
            {"path", "kind", "sha256", "architectures", "platform", "uuids"},
            "code object",
        )
        safe_name(code["path"])
        require(
            type(code["kind"]) is str
            and code["kind"] in {"primary", "framework", "dylib", "macho", "dsym"}
            and matches(code["sha256"], r"[0-9a-f]{64}")
            and code["architectures"] == ["arm64"]
            and (
                code["platform"] == "ios-device"
                or code["kind"] == "dsym"
                and code["platform"] is None
            )
            and type(code["uuids"]) is list
            and len(code["uuids"]) <= 1
            and all(matches(item, r"[0-9a-f-]{36}") for item in code["uuids"]),
            "Invalid code object",
        )
    return value


def _plist(path):
    require(path.stat().st_size <= MAX_ENVELOPE, "Plist size limit exceeded")
    try:
        value = plistlib.loads(path.read_bytes())
    except (ValueError, plistlib.InvalidFileException, OverflowError, RecursionError):
        raise ArchiveError("Malformed bundle plist") from None
    require(type(value) is dict, "Expected plist dictionary")
    return value


def _bundle_records(root, manifest, policy, *, signed=False, ipa=False):
    layout = [
        (
            identifier,
            path.replace(APP_PATH, "Payload/Clarify.app") if ipa else path,
            executable,
            extension,
        )
        for identifier, path, executable, extension in BUNDLE_LAYOUT
    ]
    by_path = {record["path"]: record for record in manifest}
    directories = set()
    for record in manifest:
        parts = record["path"].split("/")
        for index, part in enumerate(parts):
            if part.lower().endswith((".app", ".appex")):
                directories.add("/".join(parts[: index + 1]))
            require(
                not part.lower().endswith((".xcodeproj", ".xcworkspace"))
                and part != "Pods",
                "Candidate build inputs are forbidden",
            )
        if record["kind"] == "file":
            require(
                parts[-1]
                not in {
                    "Podfile",
                    "Podfile.lock",
                    "Gemfile",
                    "Gemfile.lock",
                    "Makefile",
                }
                and not parts[-1].lower().endswith((".sh", ".py", ".rb", ".command")),
                "Candidate build scripts are forbidden",
            )
    require(
        directories == {item[1] for item in layout},
        "Unexpected app or extension layout",
    )
    app_parent = "Payload" if ipa else ARCHIVE_ROOT + "/Products/Applications"
    children = {
        record["path"][len(app_parent) + 1 :].split("/")[0]
        for record in manifest
        if record["path"].startswith(app_parent + "/")
    }
    require(children == {"Clarify.app"}, "Expected exactly one application")
    bundles, primary_paths = [], set()
    for identifier, path, executable, extension in layout:
        info_path, executable_path = path + "/Info.plist", path + "/" + executable
        require(
            info_path in by_path
            and executable_path in by_path
            and by_path[info_path]["kind"]
            == by_path[executable_path]["kind"]
            == "file",
            "Missing bundle files",
        )
        require(
            by_path[executable_path]["mode"] & 0o111,
            "Bundle executable lacks execute mode",
        )
        info = _plist(root / info_path)
        require(
            info.get("CFBundleIdentifier") == identifier
            and info.get("CFBundleExecutable") == executable,
            "Wrong bundle identity or executable",
        )
        require(
            info.get("CFBundleShortVersionString") == policy.context["version"]
            and info.get("CFBundleVersion") == policy.context["build"],
            "Wrong bundle version/build",
        )
        require(
            info.get("CFBundlePackageType")
            == ("APPL" if extension is None else "XPC!"),
            "Wrong bundle package type",
        )
        if extension:
            require(
                type(info.get("NSExtension")) is dict
                and info["NSExtension"].get("NSExtensionPointIdentifier") == extension,
                "Wrong extension type",
            )
        else:
            require(
                info.get("ClarifyCloudURL") == policy.cloud_url,
                "Wrong MAIN cloud endpoint",
            )
        header = inspect_macho(
            _macho_prefix(root / executable_path), primary=True, signed=signed
        )
        subset = [
            {**record, "path": record["path"][len(path) + 1 :]}
            for record in manifest
            if record["path"].startswith(path + "/")
        ]
        bundles.append(
            {
                "id": identifier,
                "path": path,
                "sha256": digest(canonical(subset)),
                "info_plist_sha256": by_path[info_path]["sha256"],
                "executable": executable,
                "executable_sha256": by_path[executable_path]["sha256"],
                "executable_bytes": by_path[executable_path]["bytes"],
                "architectures": header["architectures"],
                "platform": header["platform"],
                "embedded_entitlements": None,
            }
        )
        primary_paths.add(executable_path)
    license_path = (
        LICENSE_PATH.replace(APP_PATH, "Payload/Clarify.app") if ipa else LICENSE_PATH
    )
    require(
        license_path in by_path
        and by_path[license_path]["sha256"] == policy.license_sha256,
        "Missing or changed keyboard license",
    )
    for required in policy.required_resources:
        path = required.replace(APP_PATH, "Payload/Clarify.app") if ipa else required
        require(
            path in by_path
            and by_path[path]["kind"] == "file"
            and by_path[path]["bytes"] > 0,
            "Missing essential app resource",
        )
    code = []
    framework_roots = set()
    for record in manifest:
        parts = record["path"].split("/")
        for index, part in enumerate(parts):
            if part.endswith(".framework"):
                framework_roots.add("/".join(parts[: index + 1]))
    framework_executables = set()
    for framework_path in framework_roots:
        info_path = framework_path + "/Info.plist"
        require(
            info_path in by_path and by_path[info_path]["kind"] == "file",
            "Missing framework Info.plist",
        )
        info = _plist(root / info_path)
        executable = info.get("CFBundleExecutable")
        require(
            type(executable) is str
            and matches(executable, r"[A-Za-z0-9_.-]{1,200}")
            and executable not in {".", ".."},
            "Invalid framework executable",
        )
        executable_path = framework_path + "/" + executable
        require(
            executable_path in by_path
            and by_path[executable_path]["kind"] == "file"
            and by_path[executable_path]["mode"] & 0o111,
            "Missing framework executable",
        )
        framework_executables.add(executable_path)
    magics = {
        b"\xcf\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xce",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
        b"\xca\xfe\xba\xbf",
        b"\xbf\xba\xfe\xca",
    }
    for record in manifest:
        if record["kind"] != "file":
            continue
        path = record["path"]
        with (root / path).open("rb") as incoming:
            prefix = incoming.read(4)
        require(prefix[:2] != b"#!", "Executable scripts are forbidden")
        framework = next(
            (part[:-10] for part in path.split("/") if part.endswith(".framework")),
            None,
        )
        expected_code = (
            path in primary_paths
            or path.endswith(".dylib")
            or path in framework_executables
            or framework == path.split("/")[-1]
        )
        require(not expected_code or prefix in magics, "Missing Mach-O code object")
        if prefix not in magics:
            continue
        debug = any(part.endswith(".dSYM") for part in path.split("/"))
        inspected = inspect_macho(
            _macho_prefix(root / path),
            primary=path in primary_paths,
            debug=debug,
            signed=signed,
        )
        kind = (
            "dsym"
            if debug
            else "primary"
            if path in primary_paths
            else "framework"
            if framework
            else "dylib"
            if path.endswith(".dylib")
            else "macho"
        )
        code.append(
            {"path": path, "kind": kind, "sha256": record["sha256"], **inspected}
        )
    return bundles, code


def _inspect_data(
    archive_path, policy, *, envelope=None, limits=LIMITS, extraction=None
):
    policy.validate()
    archive_path = absolute_path(archive_path)
    identity = file_digest(archive_path, limits.zip_bytes)
    manifest = zip_manifest(archive_path, limits=limits)
    require(
        manifest
        and all(
            record["path"] == ARCHIVE_ROOT
            or record["path"].startswith(ARCHIVE_ROOT + "/")
            for record in manifest
        ),
        "Unexpected archive root",
    )

    def inspect_at(root):
        _extract(archive_path, root, manifest, limits)
        require(
            (root / ARCHIVE_ROOT / "Info.plist").is_file(), "Missing archive Info.plist"
        )
        info = _plist(root / ARCHIVE_ROOT / "Info.plist")
        properties = info.get("ApplicationProperties")
        require(
            info.get("ArchiveVersion") == 2
            and type(properties) is dict
            and properties.get("ApplicationPath") == "Applications/Clarify.app",
            "Invalid Xcode archive metadata",
        )
        for key, expected in (
            ("CFBundleIdentifier", BUNDLE),
            ("CFBundleShortVersionString", policy.context["version"]),
            ("CFBundleVersion", policy.context["build"]),
        ):
            require(
                key not in properties or properties[key] == expected,
                "Wrong archive application metadata",
            )
        return _bundle_records(root, manifest, policy)

    if extraction is None:
        with tempfile.TemporaryDirectory(
            prefix="clarify-archive-inspect-"
        ) as temporary:
            bundles, code = inspect_at(Path(temporary) / "data")
    else:
        bundles, code = inspect_at(extraction)
    result = {
        **decode(canonical(policy.context)),
        "archive": {
            "filename": ARCHIVE_NAME,
            "root": ARCHIVE_ROOT,
            **identity,
            "manifest_sha256": digest(canonical(manifest)),
        },
        "bundles": bundles,
        "code_objects": code,
    }
    require(
        file_digest(archive_path, limits.zip_bytes) == identity,
        "Archive changed during inspection",
    )
    if envelope is not None:
        require(
            canonical(result) == canonical(envelope),
            "Envelope differs from inspected archive or MAIN policy",
        )
    require(len(canonical(result)) <= MAX_ENVELOPE, "Envelope size limit exceeded")
    return result


def inspect(archive_path, envelope_data, policy, *, limits=LIMITS):
    """Inspect all archive data. This API alone does not authenticate provenance."""
    return _inspect_data(
        archive_path, policy, envelope=load_envelope(envelope_data), limits=limits
    )


def _source_mode(path):
    return stat.S_IMODE(_node(path).st_mode)


def _verify_frozen(root, manifest):
    expected = {}
    for record in manifest:
        parts = record["path"].split("/")
        for index in range(1, len(parts)):
            expected.setdefault("/".join(parts[:index]), {"kind": "directory"})
        expected[record["path"]] = record
    found = set()
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            info = _node(path)
            require(relative in expected, "Frozen archive inventory changed")
            record = expected[relative]
            found.add(relative)
            require(
                stat.S_ISDIR(info.st_mode) == (record["kind"] == "directory"),
                "Frozen archive node changed",
            )
            require(
                "mode" not in record
                or stat.S_IMODE(info.st_mode) == record["mode"]
                or os.name == "nt",
                "Frozen archive mode changed",
            )
            if record["kind"] == "file":
                require(
                    file_digest(path)
                    == {"bytes": record["bytes"], "sha256": record["sha256"]},
                    "Frozen archive bytes changed",
                )
    require(found == set(expected), "Frozen archive inventory changed")


def pack(archive_path, output_dir, policy, *, limits=LIMITS):
    """Preserve the complete Xcode archive in a deterministic inner ZIP."""
    policy.validate()
    source, output = absolute_path(archive_path), absolute_path(output_dir)
    require(
        source.is_dir()
        and source.name == ARCHIVE_ROOT
        and output.is_dir()
        and not output.is_relative_to(source)
        and not any(output.iterdir()),
        "Pack needs a complete archive and fresh output directory",
    )
    records = []
    for directory, directories, files in os.walk(source, followlinks=False):
        for name in [*directories, *files]:
            path = Path(directory) / name
            info = _node(path)
            relative = ARCHIVE_ROOT + "/" + path.relative_to(source).as_posix()
            records.append(
                {
                    "path": relative,
                    "kind": "directory" if stat.S_ISDIR(info.st_mode) else "file",
                    "mode": _source_mode(path),
                    "bytes": info.st_size if stat.S_ISREG(info.st_mode) else 0,
                }
            )
    records.append(
        {
            "path": ARCHIVE_ROOT,
            "kind": "directory",
            "mode": _source_mode(source),
            "bytes": 0,
        }
    )
    require(
        len(records) <= limits.entries
        and all(record["bytes"] <= limits.file_bytes for record in records)
        and sum(record["bytes"] for record in records) <= limits.expanded_bytes,
        "Pack size limit exceeded",
    )
    _path_inventory(records, limits)
    target = output / ARCHIVE_NAME
    try:
        with zipfile.ZipFile(
            target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for record in sorted(records, key=lambda record: record["path"]):
                name = record["path"] + ("/" if record["kind"] == "directory" else "")
                item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                item.create_system = 3
                item.compress_type = zipfile.ZIP_DEFLATED
                item.external_attr = (
                    (stat.S_IFDIR if record["kind"] == "directory" else stat.S_IFREG)
                    | record["mode"]
                ) << 16
                if record["kind"] == "directory":
                    item.external_attr |= 0x10
                    archive.writestr(item, b"")
                else:
                    path = source.parent / record["path"]
                    before = file_digest(path, limits.file_bytes)
                    with (
                        path.open("rb") as incoming,
                        archive.open(item, "w", force_zip64=True) as outgoing,
                    ):
                        shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                    require(
                        file_digest(path, limits.file_bytes) == before
                        and before["bytes"] == record["bytes"],
                        "Archive source changed during pack",
                    )
        result = _inspect_data(target, policy, limits=limits)
        (output / ENVELOPE_NAME).write_bytes(canonical(result))
        return result
    except BaseException:
        target.unlink(missing_ok=True)
        (output / ENVELOPE_NAME).unlink(missing_ok=True)
        raise


def parse_artifact_record(log, *, source_sha, run_id, run_attempt):
    if type(log) is str:
        try:
            log = log.encode("utf-8")
        except UnicodeError:
            raise ArchiveError("Malformed trusted job log") from None
    require(
        type(log) is bytes and len(log) <= MAX_LOG,
        "Trusted job log size limit exceeded",
    )
    try:
        lines = log.decode("utf-8").splitlines()
    except UnicodeError:
        raise ArchiveError("Malformed trusted job log") from None
    records = []
    for line in lines:
        line = re.sub(
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z ",
            "",
            line,
            count=1,
        )
        if line.startswith(RECORD_PREFIX):
            records.append(decode(line[len(RECORD_PREFIX) :].encode("utf-8")))
        else:
            require(RECORD_PREFIX not in line, "Unknown trusted job log format")
    require(len(records) == 1, "Missing or duplicate archive recorder output")
    record = records[0]
    exact(
        record,
        {"artifact_id", "artifact_name", "artifact_digest", "run_id", "run_attempt"},
        "artifact recorder",
    )
    require(
        positive(record["artifact_id"])
        and positive(record["run_id"])
        and type(record["run_attempt"]) is int
        and record["run_attempt"] == run_attempt
        and record["run_id"] == run_id
        and record["artifact_name"] == "clarify-ios-qa-unsigned-" + source_sha
        and matches(record["artifact_digest"], r"sha256:[0-9a-f]{64}"),
        "Wrong archive recorder identity",
    )
    return record


def format_artifact_record(
    *, artifact_id, artifact_digest, source_sha, run_id, run_attempt
):
    record = {
        "artifact_id": artifact_id,
        "artifact_name": "clarify-ios-qa-unsigned-" + source_sha,
        "artifact_digest": "sha256:" + artifact_digest,
        "run_id": run_id,
        "run_attempt": run_attempt,
    }
    line = RECORD_PREFIX + canonical(record).decode("ascii")
    parse_artifact_record(
        line, source_sha=source_sha, run_id=run_id, run_attempt=run_attempt
    )
    return line


class ArchiveAPI(Protocol):
    """Authenticated transport seam, supplied by the MAIN caller.

    jobs() binds the exact-attempt endpoint into {run_id, run_attempt, jobs}.
    job_log() returns ONLY the authenticated final job's log, never a step or
    candidate log. download_artifact() must enforce max_bytes while streaming.
    control() returns raw Git blob bytes, not a claimed hash or verification flag.
    workflow_document() is a trusted, deterministic YAML parser over those exact
    authenticated bytes. It must reject duplicate YAML keys and unsafe tags.
    """

    def main(self) -> dict: ...
    def pull_request(self, number: int) -> dict: ...
    def commit(self, sha: str) -> dict: ...
    def control(self, sha: str, path: str) -> bytes: ...
    def workflow_document(self, data: bytes) -> dict: ...
    def run(self, run_id: int, attempt: int) -> dict: ...
    def jobs(self, run_id: int, attempt: int) -> dict: ...
    def artifact(self, artifact_id: int) -> dict: ...
    def job_log(self, job_id: int) -> bytes: ...
    def download_artifact(
        self, artifact_id: int, destination: Path, *, max_bytes: int
    ) -> None: ...


def _successful_job(jobs, name, steps, run_id, trusted_sha):
    found = [job for job in jobs if job.get("name") == name]
    require(len(found) == 1, "Missing or duplicate producer/final job")
    job = found[0]
    require(
        positive(job.get("id"))
        and job.get("run_id") == run_id
        and job.get("head_sha") == trusted_sha
        and job.get("status") == "completed"
        and job.get("conclusion") == "success",
        "Unsuccessful producer/final job",
    )
    for name in steps:
        found = [step for step in job.get("steps", []) if step.get("name") == name]
        require(
            len(found) == 1
            and found[0].get("status") == "completed"
            and found[0].get("conclusion") == "success",
            "Missing or unsuccessful producer/final step",
        )
    return job


def authenticate(api, policy, artifact_id, destination):
    """Verify current Git/PR, exact MAIN run/attempt/jobs, recorder and API digest.

    Returns facts plus a downloaded outer ZIP. The API has no producer-job field;
    the verified final-job recorder binds that gap. No network implementation is
    provided here. The upload action/overwrite=false semantics are reviewed MAIN
    workflow policy, whose actual bytes are authenticated below.
    """
    policy.validate()
    context = policy.context
    require(positive(artifact_id), "Invalid API artifact id")
    require(
        api.main().get("sha") == context["base_sha"] == context["trusted_sha"],
        "MAIN/base/trusted changed",
    )
    pr = api.pull_request(context["pr"])
    require(
        pr.get("number") == context["pr"]
        and pr.get("state") == "open"
        and pr.get("draft") is False
        and pr.get("head", {}).get("sha") == context["source_sha"]
        and pr.get("base", {}).get("sha") == context["base_sha"]
        and pr.get("base", {}).get("ref") == "main"
        and all(
            pr.get(part, {}).get("repo", {}).get("full_name") == REPOSITORY
            for part in ("head", "base")
        ),
        "Current PR/source/base differs",
    )
    for sha, tree in (
        (context["source_sha"], context["source_tree"]),
        (context["base_sha"], context["base_tree"]),
    ):
        commit = api.commit(sha)
        require(
            commit.get("sha") == sha and commit.get("tree", {}).get("sha") == tree,
            "Git tree binding differs",
        )
    workflow_bytes = None
    for path, expected in context["controls"].items():
        data = api.control(context["trusted_sha"], path)
        require(
            type(data) is bytes
            and len(data) <= 8 * 1024**2
            and git_blob(data) == expected,
            "MAIN control bytes differ",
        )
        if path == WORKFLOW:
            workflow_bytes = data
    workflow = api.workflow_document(workflow_bytes)
    require(
        type(workflow) is dict and type(workflow.get("jobs")) is dict,
        "Invalid authenticated workflow document",
    )
    producer_definition = workflow["jobs"].get(context["producer"]["job_key"], {})
    require(
        producer_definition.get("name") == policy.producer_job_name
        and type(producer_definition.get("steps")) is list,
        "MAIN producer job key/name differs",
    )
    uploaders = [
        step
        for step in producer_definition["steps"]
        if type(step) is dict
        and str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    require(len(uploaders) == 1, "Missing or ambiguous MAIN archive uploader")
    uploader = uploaders[0]
    options = uploader.get("with", {})
    require(
        uploader.get("name") == policy.uploader_step
        and uploader.get("uses") == policy.upload_action
        and type(options) is dict
        and options.get("overwrite") is False
        and type(options.get("name")) is str
        and options["name"].startswith("clarify-ios-qa-unsigned-"),
        "Unsafe MAIN uploader pin/name/overwrite policy",
    )
    finals = [
        job
        for job in workflow["jobs"].values()
        if type(job) is dict and job.get("name") == policy.final_job_name
    ]
    require(
        len(finals) == 1 and type(finals[0].get("steps")) is list,
        "Missing or duplicate MAIN final definition",
    )
    recorders = [
        step
        for step in finals[0]["steps"]
        if type(step) is dict and step.get("name") == policy.recorder_step
    ]
    require(
        len(recorders) == 1 and type(recorders[0].get("run")) is str,
        "Missing or duplicate MAIN recorder definition",
    )
    producer = context["producer"]
    run_id, attempt = producer["run_id"], producer["run_attempt"]
    run = api.run(run_id, attempt)
    require(
        run.get("id") == run_id
        and run.get("run_attempt") == attempt
        and run.get("workflow_id") == context["workflow"]["id"]
        and run.get("path") == WORKFLOW
        and run.get("head_sha") == context["trusted_sha"]
        and run.get("head_branch") == "main"
        and run.get("event") == "workflow_dispatch"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("repository", {}).get("full_name") == REPOSITORY,
        "MAIN producer run/attempt/workflow differs",
    )
    response = api.jobs(run_id, attempt)
    require(
        response.get("run_id") == run_id
        and response.get("run_attempt") == attempt
        and type(response.get("jobs")) is list,
        "Missing exact-attempt producer jobs",
    )
    jobs = response["jobs"]
    producer_job = _successful_job(
        jobs,
        policy.producer_job_name,
        policy.producer_steps,
        run_id,
        context["trusted_sha"],
    )
    final_job = _successful_job(
        jobs, policy.final_job_name, policy.final_steps, run_id, context["trusted_sha"]
    )
    require(producer_job["id"] != final_job["id"], "Producer and final job collide")
    record = parse_artifact_record(
        api.job_log(final_job["id"]),
        source_sha=context["source_sha"],
        run_id=run_id,
        run_attempt=attempt,
    )
    require(record["artifact_id"] == artifact_id, "Recorder/API artifact id differs")
    artifact = api.artifact(artifact_id)
    require(
        artifact.get("id") == artifact_id
        and artifact.get("name") == record["artifact_name"]
        and artifact.get("digest") == record["artifact_digest"]
        and artifact.get("expired") is False
        and positive(artifact.get("size_in_bytes"))
        and artifact["size_in_bytes"] <= LIMITS.zip_bytes
        and artifact.get("workflow_run", {}).get("id") == run_id
        and artifact.get("workflow_run", {}).get("head_sha") == context["trusted_sha"],
        "API artifact binding differs",
    )
    destination = absolute_path(destination, exists=False)
    require(not destination.exists(), "Artifact destination must be fresh")
    api.download_artifact(artifact_id, destination, max_bytes=LIMITS.zip_bytes)
    downloaded = file_digest(destination, LIMITS.zip_bytes)
    require(
        downloaded
        == {
            "bytes": artifact["size_in_bytes"],
            "sha256": record["artifact_digest"][7:],
        },
        "Outer GitHub artifact digest/size differs",
    )
    return {
        "id": artifact_id,
        "name": record["artifact_name"],
        **downloaded,
        "run_id": run_id,
        "run_attempt": attempt,
        "producer_job_id": producer_job["id"],
        "recorder_job_id": final_job["id"],
        "proof_channel": LOG_TRUST_MODEL,
    }


def _system_runner(command, *, cwd, env):
    options = (
        {"timeout": 1800} if tuple(command[:2]) == ("/usr/bin/xcrun", "altool") else {}
    )
    return subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, check=False, **options
    )


def _execute(runner, command, workspace, env, error):
    try:
        command = tuple(map(str, command))
        # Raw credential variables are needed only by the existing installer.
        command_env = (
            env
            if command[-1] == "install"
            else {
                key: value
                for key, value in env.items()
                if not key.startswith("CLARIFY_IOS_")
            }
        )
        result = runner(command, cwd=workspace, env=command_env)
        require(type(result.returncode) is int and result.returncode == 0, error)
        return result
    except BaseException as failure:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            raise
        # Never include subprocess arguments, stdout, stderr, or underlying errors.
        raise ArchiveError(error) from None


def _export_options(path):
    value = _plist(absolute_path(path))
    exact(
        value,
        {
            "method",
            "destination",
            "teamID",
            "signingStyle",
            "signingCertificate",
            "provisioningProfiles",
            "manageAppVersionAndBuildNumber",
            "uploadSymbols",
        },
        "export options",
    )
    require(
        value["method"] == "app-store-connect"
        and value["destination"] == "export"
        and value["teamID"] == TEAM
        and value["signingStyle"] == "manual"
        and value["signingCertificate"] == "Apple Distribution"
        and value["manageAppVersionAndBuildNumber"] is False
        and value["uploadSymbols"] is True,
        "Unsafe export options",
    )
    profiles = value["provisioningProfiles"]
    require(
        type(profiles) is dict
        and set(profiles) == {item[0] for item in BUNDLE_LAYOUT}
        and all(
            matches(profile, r"[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}")
            for profile in profiles.values()
        )
        and len(set(profiles.values())) == 3,
        "Expected three existing manual profiles",
    )
    return digest(path.read_bytes())


def _signed_entitlements(value, identifier):
    allowed = {
        "application-identifier",
        "com.apple.developer.team-identifier",
        "get-task-allow",
        "com.apple.security.application-groups",
        "keychain-access-groups",
        "beta-reports-active",
    }
    require(
        type(value) is dict
        and set(value) <= allowed
        and value.get("application-identifier") == TEAM + "." + identifier
        and value.get("com.apple.developer.team-identifier") == TEAM
        and value.get("get-task-allow", False) is False,
        "Signed entitlement identity/policy differs",
    )
    if identifier == BUNDLE + ".activity":
        require(
            "com.apple.security.application-groups" not in value,
            "Activity app group must be absent",
        )
    else:
        require(
            value.get("com.apple.security.application-groups") == ["group." + BUNDLE],
            "Signed app group differs",
        )
    require(
        "keychain-access-groups" not in value
        or value["keychain-access-groups"] == [TEAM + "." + identifier],
        "Signed keychain group differs",
    )
    require(
        "beta-reports-active" not in value
        or type(value["beta-reports-active"]) is bool,
        "Invalid beta entitlement",
    )


def _inspect_export(ipa, workspace, policy, runner, env):
    identity = file_digest(ipa, LIMITS.zip_bytes)
    manifest = zip_manifest(ipa)
    require(
        all(
            record["path"] == "Payload"
            or record["path"].startswith("Payload/")
            or record["path"] == "SwiftSupport"
            or record["path"].startswith("SwiftSupport/")
            or record["path"] == "Symbols"
            or record["path"].startswith("Symbols/")
            for record in manifest
        ),
        "Unexpected exported IPA root",
    )
    root = workspace / "signed-inspection"
    _extract(ipa, root, manifest)
    bundles, code = _bundle_records(root, manifest, policy, signed=True, ipa=True)
    for binding in bundles:
        bundle = root / binding["path"]
        require(
            (bundle / "embedded.mobileprovision").is_file(),
            "Missing exported distribution profile",
        )
        _execute(
            runner,
            ("/usr/bin/codesign", "--verify", "--deep", "--strict", bundle),
            workspace,
            env,
            "Export signature inspection failed",
        )
        result = _execute(
            runner,
            ("/usr/bin/codesign", "-d", "--entitlements", ":-", bundle),
            workspace,
            env,
            "Export entitlement inspection failed",
        )
        try:
            require(
                type(result.stdout) is bytes and len(result.stdout) <= MAX_ENVELOPE,
                "Export entitlement inspection failed",
            )
            entitlements = plistlib.loads(result.stdout)
        except (ValueError, plistlib.InvalidFileException, RecursionError):
            raise ArchiveError("Export entitlement inspection failed") from None
        _signed_entitlements(entitlements, binding["id"])
        binding["embedded_entitlements"] = entitlements
    require(
        file_digest(ipa, LIMITS.zip_bytes) == identity,
        "IPA changed during signature inspection",
    )
    return {**identity, "bundles": bundles, "code_objects": code}


def sign_export(
    *, api, policy, artifact_id, runner_temp, trusted_root, runner=_system_runner
):
    """Authenticate and freeze data BEFORE install; try export with no fallback.

    No upload or native-acceptance claim is made. The caller owns the returned
    private workspace and must remove it after consuming its review evidence.
    Failure removes only that new workspace. Existing helper install/clean are
    the only credential operations. Both streams are captured and never logged.
    """
    policy.validate()
    require(
        runner is not _system_runner or sys.platform == "darwin",
        "Native export requires a new trusted macOS runner",
    )
    # Freeze policy before API callbacks or a later credential boundary.
    policy = ArchivePolicy(
        **{**policy.__dict__, "context": decode(canonical(policy.context))}
    )
    temporary, trusted = absolute_path(runner_temp), absolute_path(trusted_root)
    require(
        temporary.is_dir() and trusted.is_dir(),
        "Expected runner and trusted directories",
    )
    helper = absolute_path(trusted / SIGNING_HELPER)
    module = absolute_path(trusted / MODULE)
    for path, name in ((helper, SIGNING_HELPER), (module, MODULE)):
        require(
            path.stat().st_size <= 8 * 1024**2
            and git_blob(path.read_bytes()) == policy.context["controls"][name],
            "Local MAIN helper/module bytes differ",
        )
    require(
        not (temporary / "clarify-signing").exists()
        and not (temporary / "clarify-upload").exists(),
        "Signing runner is not fresh",
    )
    workspace = Path(tempfile.mkdtemp(prefix="clarify-device-archive-", dir=temporary))
    workspace.chmod(0o700)
    installed = False
    succeeded = False
    # Only fixed system tools are resolved after credentials enter; no PATH tool.
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "HOME",
            "USER",
            "LOGNAME",
            "TMPDIR",
            "DEVELOPER_DIR",
            "SDKROOT",
            "CLARIFY_IOS_CERTIFICATE_BASE64",
            "CLARIFY_IOS_CERTIFICATE_PASSWORD",
            "CLARIFY_IOS_PROFILES_GZIP_BASE64",
        }
    }
    env.update(
        RUNNER_TEMP=str(temporary),
        PATH="/usr/bin:/bin:/usr/sbin:/sbin",
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    python = Path(sys.executable).absolute()
    try:
        outer = workspace / "github-artifact.zip"
        proof = authenticate(api, policy, artifact_id, outer)
        outer_manifest = zip_manifest(outer, _transport=True)
        require(
            {record["path"] for record in outer_manifest}
            == {ARCHIVE_NAME, ENVELOPE_NAME}
            and all(record["kind"] == "file" for record in outer_manifest),
            "Unexpected GitHub artifact members",
        )
        _extract(outer, workspace / "input", outer_manifest, transport=True)
        archive = workspace / "input" / ARCHIVE_NAME
        envelope_path = workspace / "input" / ENVELOPE_NAME
        require(
            envelope_path.stat().st_size <= MAX_ENVELOPE, "Envelope size limit exceeded"
        )
        envelope_bytes = envelope_path.read_bytes()
        envelope = load_envelope(envelope_bytes)
        inspected = _inspect_data(
            archive, policy, envelope=envelope, extraction=workspace / "frozen"
        )
        require(
            proof["sha256"] != inspected["archive"]["sha256"],
            "Outer and inner hashes must be distinct",
        )
        frozen_manifest = zip_manifest(archive)
        # Check the actual extracted data, including modes, against the ZIP before
        # installing keys. Native POSIX modes are required for the real runner.
        _verify_frozen(workspace / "frozen", frozen_manifest)
        require(
            envelope_path.read_bytes() == envelope_bytes
            and file_digest(archive, LIMITS.zip_bytes)
            == {key: inspected["archive"][key] for key in ("bytes", "sha256")}
            and file_digest(outer, LIMITS.zip_bytes)
            == {key: proof[key] for key in ("bytes", "sha256")},
            "Archive snapshot changed before install",
        )
        for path, name in ((helper, SIGNING_HELPER), (module, MODULE)):
            require(
                git_blob(path.read_bytes()) == policy.context["controls"][name],
                "MAIN helper changed before install",
            )
        output = workspace / "output"
        output.mkdir(mode=0o700)
        installed = True  # Also clean partial material if install itself fails.
        _execute(
            runner,
            (python, "-I", helper, "install"),
            workspace,
            env,
            "Existing signing credential installation failed",
        )
        options = temporary / "clarify-signing/ExportOptions.plist"
        options_hash = _export_options(options)
        _execute(
            runner,
            (
                "/usr/bin/xcodebuild",
                "-exportArchive",
                "-archivePath",
                workspace / "frozen" / ARCHIVE_ROOT,
                "-exportPath",
                output,
                "-exportOptionsPlist",
                options,
            ),
            workspace,
            env,
            "Unsigned archive export unsupported or failed",
        )
        require(
            digest(options.read_bytes()) == options_hash,
            "Export options changed during export",
        )
        outputs = list(output.iterdir())
        ipas = [path for path in outputs if path.suffix == ".ipa"]
        require(
            len(ipas) == 1 and ipas[0].name == "Clarify.ipa",
            "Expected one exported Clarify IPA",
        )
        for path in outputs:
            _node(path)
        exported = _inspect_export(ipas[0], workspace, policy, runner, env)
        require(
            exported["sha256"] not in {proof["sha256"], inspected["archive"]["sha256"]},
            "IPA and archive hashes must be distinct",
        )
        receipt = {
            "schema": 1,
            "status": "compatibilidade_nativa_não_verificada",
            "delivery_eligible": False,
            "workflowArtifactProvenanceVerified": False,
            "artifact": proof,
            "archive": inspected["archive"],
            "ipa": exported,
            "entitlements_policy": ENTITLEMENTS_POLICY,
        }
        (workspace / "archive-receipt.json").write_bytes(canonical(receipt))
        succeeded = True
        return {"workspace": workspace, "ipa_path": ipas[0], "receipt": receipt}
    finally:
        try:
            if installed:
                _execute(
                    runner,
                    (python, "-I", helper, "clean"),
                    workspace,
                    env,
                    "Signing credential cleanup failed",
                )
        except BaseException:
            succeeded = False
            raise
        finally:
            if not succeeded:
                shutil.rmtree(workspace)


def _qa_paths(temporary):
    root = temporary / "clarify-ios-qa"
    return {
        "context_path": root / "context.json",
        "ipa_path": root / "output/Clarify.ipa",
        "verification_path": root / "output/verification.json",
        "receipt_path": root / "output/upload-receipt.json",
    }


def _qa_verifier(trusted, policy):
    """Load only the reviewed MAIN bytes; do not create a helper bytecode cache."""
    policy.validate()
    verifier_bytes = None
    for name in (SIGNING_HELPER, QA_VERIFIER, QA_PUBLISHER):
        path = absolute_path(trusted / name)
        file_digest(path, 8 * 1024**2)
        data = path.read_bytes()
        require(
            git_blob(data) == policy.context["controls"].get(name),
            "Local MAIN QA helper bytes differ",
        )
        if name == QA_VERIFIER:
            verifier_bytes = data
    spec = importlib.util.spec_from_file_location(
        "clarify_trusted_qa", trusted / QA_VERIFIER
    )
    helper = importlib.util.module_from_spec(spec)
    exec(compile(verifier_bytes, str(trusted / QA_VERIFIER), "exec"), helper.__dict__)
    return helper


def _check_qa_prepared(prepared, policy, temporary, helper):
    paths = _qa_paths(temporary)
    exact(prepared, {"context", *paths}, "prepared QA")
    require(
        all(prepared[key] == path for key, path in paths.items()), "QA paths differ"
    )
    context_path = absolute_path(paths["context_path"])
    file_digest(context_path, 8192)
    data = context_path.read_bytes()
    context = decode(data, maximum=8192)
    require(data == canonical(context), "QA context must be canonical")
    try:
        helper.validate_qa_context(context)
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ArchiveError("Invalid R6 QA context") from None
    require(
        canonical(context) == canonical(prepared["context"])
        and all(
            context[key] == policy.context[key]
            for key in context
            if key in policy.context
        )
        and all(
            context["artifact"][key] == policy.context["producer"][key]
            for key in ("run_id", "run_attempt")
        ),
        "QA policy/context differs",
    )
    for path, expected in (
        (context_path.parent / "input" / ARCHIVE_NAME, context["artifact"]),
        (paths["ipa_path"], context["ipa"]),
    ):
        require(
            file_digest(absolute_path(path), LIMITS.zip_bytes)
            == {key: expected[key] for key in ("sha256", "bytes")},
            "Staged QA digest/size differs",
        )
    sidecar = absolute_path(paths["verification_path"])
    file_digest(sidecar, MAX_ENVELOPE)
    verification = decode(sidecar.read_bytes())
    expected = {
        **context["ipa"],
        "qa": context,
        "appId": APP_ID,
        "team": TEAM,
        "bundles": [
            {
                "bundleId": item["id"],
                "version": context["version"],
                "build": context["build"],
            }
            for item in sorted(context["bundles"], key=lambda item: item["path"])
        ],
        "artifactDigestVerified": True,
        "ipaDigestVerified": True,
        "bundleDigestsVerified": True,
        "workflowArtifactProvenanceVerified": False,
    }
    require(
        canonical(verification) == canonical(expected), "R6 QA verification differs"
    )
    return context


def prepare_qa_context(
    result,
    policy,
    *,
    runner_temp,
    trusted_root,
    run_id,
    run_attempt,
    runner=_system_runner,
):
    """Stage a real sign_export result and run the existing trusted R6 verifier.

    The returned paths belong to the caller. This operation does not upload or
    establish native compatibility, provenance, or publication authorization.
    """
    require(
        runner is not _system_runner or sys.platform == "darwin",
        "QA verification requires trusted macOS",
    )
    policy = ArchivePolicy(
        **{**policy.__dict__, "context": decode(canonical(policy.context))}
    )
    temporary, trusted = absolute_path(runner_temp), absolute_path(trusted_root)
    require(
        temporary.is_dir() and trusted.is_dir(),
        "Expected runner and trusted directories",
    )
    helper = _qa_verifier(trusted, policy)
    require(
        positive(run_id) and positive(run_attempt) and run_attempt <= 100,
        "Invalid QA upload run",
    )
    exact(result, {"workspace", "ipa_path", "receipt"}, "export result")
    workspace = absolute_path(result["workspace"])
    require(
        workspace.parent == temporary
        and workspace.name.startswith("clarify-device-archive-"),
        "Unexpected export workspace",
    )
    ipa = absolute_path(result["ipa_path"])
    require(ipa == workspace / "output/Clarify.ipa", "Unexpected export IPA path")
    receipt = decode(canonical(result["receipt"]))
    require(
        receipt.get("delivery_eligible") is False
        and receipt.get("workflowArtifactProvenanceVerified") is False,
        "Expected an unapproved export receipt",
    )
    archive = absolute_path(workspace / "input" / ARCHIVE_NAME)
    for path, expected in ((archive, receipt["archive"]), (ipa, receipt["ipa"])):
        require(
            file_digest(path, LIMITS.zip_bytes)
            == {key: expected[key] for key in ("bytes", "sha256")},
            "Export digest/size differs",
        )
    # R6 uses files only, NFC paths and insertion-ordered path/bytes/sha256
    # records. The archive module's manifest digest has a different contract.
    bundles = []
    for identifier, archive_path, executable, _ in BUNDLE_LAYOUT:
        relative = archive_path.replace(APP_PATH, "Payload/Clarify.app")
        bundle = absolute_path(workspace / "signed-inspection" / relative)
        for path in bundle.rglob("*"):
            _node(path)
        binary = file_digest(absolute_path(bundle / executable))
        bundles.append(
            {
                "id": identifier,
                "path": relative,
                "executable": executable,
                "sha256": helper.bundle_digest(bundle),
                "executable_sha256": binary["sha256"],
                "executable_bytes": binary["bytes"],
            }
        )
    context = {
        key: policy.context[key]
        for key in (
            "schema",
            "repository",
            "pr",
            "source_sha",
            "source_tree",
            "base_sha",
            "base_tree",
            "trusted_sha",
            "workflow",
            "version",
            "build",
            "tag",
        )
    }
    context.update(
        run_id=run_id,
        run_attempt=run_attempt,
        artifact={
            **{
                key: receipt["artifact"][key]
                for key in ("id", "name", "run_id", "run_attempt")
            },
            **{key: receipt["archive"][key] for key in ("sha256", "bytes")},
        },
        ipa={key: receipt["ipa"][key] for key in ("sha256", "bytes")},
        bundles=bundles,
    )
    try:
        helper.validate_qa_context(context)
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ArchiveError("Invalid R6 QA context") from None
    data = canonical(context)
    require(len(data) <= 8192, "QA context size limit exceeded")
    paths = _qa_paths(temporary)
    root = absolute_path(paths["context_path"].parent, exists=False)
    require(not root.exists(), "QA stage must be fresh")
    root.mkdir(mode=0o700)
    try:
        (root / "input").mkdir(mode=0o700)
        (root / "output").mkdir(mode=0o700)
        shutil.copyfile(archive, root / "input" / ARCHIVE_NAME)
        shutil.copyfile(ipa, paths["ipa_path"])
        for path in (root / "input" / ARCHIVE_NAME, paths["ipa_path"]):
            path.chmod(0o600)
        paths["context_path"].write_bytes(data)
        paths["context_path"].chmod(0o600)
        env = {
            key: value
            for key, value in os.environ.items()
            if key in {"HOME", "USER", "LOGNAME", "TMPDIR", "DEVELOPER_DIR", "SDKROOT"}
        }
        env.update(
            RUNNER_TEMP=str(temporary),
            PATH="/usr/bin:/bin:/usr/sbin:/sbin",
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
            GITHUB_REPOSITORY=REPOSITORY,
            GITHUB_EVENT_NAME="workflow_dispatch",
            GITHUB_REF="refs/heads/main",
            GITHUB_SHA=context["trusted_sha"],
            QA_WORKFLOW_SHA=context["trusted_sha"],
            QA_WORKFLOW_ID=str(context["workflow"]["id"]),
            QA_WORKFLOW_REF=REPOSITORY + "/" + WORKFLOW + "@refs/heads/main",
            GITHUB_RUN_ID=str(run_id),
            GITHUB_RUN_ATTEMPT=str(run_attempt),
        )
        _execute(
            runner,
            (
                Path(sys.executable).absolute(),
                "-I",
                trusted / QA_VERIFIER,
                paths["ipa_path"],
                "--qa-context",
                paths["context_path"],
            ),
            trusted / "mobile",
            env,
            "R6 QA verification failed",
        )
        prepared = {"context": context, **paths}
        _check_qa_prepared(prepared, policy, temporary, helper)
        return prepared
    except BaseException:
        shutil.rmtree(root)
        raise


def upload_qa_context(
    prepared, policy, *, runner_temp, trusted_root, runner=_system_runner
):
    """Upload once after the trusted caller's immediate authorization checks.

    The caller owns validation/proof/history and fresh Apple inventory gates.
    This receipt records this attempt only; confirmation is not availability.
    """
    require(
        runner is not _system_runner or sys.platform == "darwin",
        "QA upload requires trusted macOS",
    )
    policy = ArchivePolicy(
        **{**policy.__dict__, "context": decode(canonical(policy.context))}
    )
    temporary, trusted = absolute_path(runner_temp), absolute_path(trusted_root)
    require(
        temporary.is_dir() and trusted.is_dir(),
        "Expected runner and trusted directories",
    )
    helper = _qa_verifier(trusted, policy)
    context = _check_qa_prepared(prepared, policy, temporary, helper)
    require(
        all(
            os.environ.get("GITHUB_" + key.upper()) == str(context[key])
            for key in ("run_id", "run_attempt")
        ),
        "QA upload run differs",
    )
    receipt_path = absolute_path(_qa_paths(temporary)["receipt_path"], exists=False)
    require(not receipt_path.exists(), "QA upload receipt already exists; do not retry")
    key_id = os.environ.get("CLARIFY_ASC_KEY_ID", "")
    issuer = os.environ.get("CLARIFY_ASC_ISSUER_ID", "")
    key = os.environ.get("CLARIFY_ASC_KEY_P8", "")
    require(
        matches(key_id, r"[A-Z0-9]{10}")
        and matches(issuer, r"[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}")
        and len(key) <= 16384
        and key.startswith("-----BEGIN PRIVATE KEY-----\n")
        and key.rstrip().endswith("-----END PRIVATE KEY-----"),
        "Invalid App Store Connect credentials",
    )
    upload = absolute_path(temporary / "clarify-upload", exists=False)
    require(not upload.exists(), "QA upload key directory must be fresh")
    upload.mkdir(mode=0o700)
    try:
        keys = upload / "private_keys"
        keys.mkdir(mode=0o700)
        key_path = keys / ("AuthKey_" + key_id + ".p8")
        with key_path.open("xb") as outgoing:
            key_path.chmod(0o600)
            outgoing.write(key.encode("utf-8"))
        env = {
            name: value
            for name, value in os.environ.items()
            if name in {"HOME", "USER", "LOGNAME", "TMPDIR", "DEVELOPER_DIR", "SDKROOT"}
        }
        env.update(
            RUNNER_TEMP=str(temporary),
            PATH="/usr/bin:/bin:/usr/sbin:/sbin",
            API_PRIVATE_KEYS_DIR=str(keys),
        )
        receipt = {
            "schema": 1,
            "status": "started",
            "qa": context,
            "delivery_eligible": False,
            "workflowArtifactProvenanceVerified": False,
        }
        # Exclusive creation is the once-only boundary, including concurrent calls.
        with receipt_path.open("xb") as outgoing:
            receipt_path.chmod(0o600)
            outgoing.write(canonical(receipt))
        try:
            _execute(
                runner,
                (
                    "/usr/bin/xcrun",
                    "altool",
                    "--upload-app",
                    "--type",
                    "ios",
                    "--file",
                    prepared["ipa_path"],
                    "--apiKey",
                    key_id,
                    "--apiIssuer",
                    issuer,
                ),
                trusted / "mobile",
                env,
                "QA upload outcome is uncertain; do not retry",
            )
        except BaseException:
            receipt["status"] = "uncertain"
            absolute_path(receipt_path).write_bytes(canonical(receipt))
            raise ArchiveError("QA upload outcome is uncertain; do not retry") from None
        receipt["status"] = "confirmed"
        absolute_path(receipt_path).write_bytes(canonical(receipt))
        return receipt
    finally:
        shutil.rmtree(upload)


def _cli_policy(path):
    data = decode(absolute_path(path).read_bytes())
    exact(data, ArchivePolicy.__dataclass_fields__, "CLI policy")
    for field in ("producer_steps", "final_steps", "required_resources"):
        require(type(data[field]) is list, "Invalid CLI policy list")
        data[field] = tuple(data[field])
    return ArchivePolicy(**data).validate()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("pack", "inspect"):
        command = commands.add_parser(name)
        command.add_argument("--archive", required=True)
        command.add_argument(
            "--policy",
            required=True,
            help="Expected data prepared by reviewed MAIN; never artifact policy",
        )
        command.add_argument(
            "--output" if name == "pack" else "--envelope", required=True
        )
    commands.add_parser(
        "sign-export",
        help="Requires caller-owned authenticated API transport; CLI blocks",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "sign-export":
            raise ArchiveError(
                "sign-export requires the MAIN caller's authenticated API and a new trusted runner; delivery remains blocked"
            )
        policy = _cli_policy(args.policy)
        result = (
            pack(args.archive, args.output, policy)
            if args.command == "pack"
            else inspect(
                args.archive, absolute_path(args.envelope).read_bytes(), policy
            )
        )
        print(
            canonical(
                {
                    "archive": result["archive"],
                    "delivery_eligible": False,
                    "workflowArtifactProvenanceVerified": False,
                }
            ).decode("ascii")
        )
        return 0
    except (ArchiveError, OSError, zipfile.BadZipFile):
        print(
            "Archive operation blocked; native compatibility and delivery remain unverified.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
