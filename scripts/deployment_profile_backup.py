"""Private, verified offline profile copies for deploy.ps1 only.

The caller must stop ALL profile writers and prevent new writers until restart.
Repeated inventory/hash checks detect changes; they are not a filesystem snapshot
or an application lock. Files are copied as opaque bytes, never parsed or logged.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile


class BackupError(Exception):
    """The deployment must stop without replacing or launching the app."""


def _plain_stat(path: Path) -> os.stat_result:
    value = path.lstat()
    if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
        raise BackupError("Links and reparse points are not supported.")
    if not (stat.S_ISREG(value.st_mode) or stat.S_ISDIR(value.st_mode)):
        raise BackupError("Unsupported profile entry.")
    return value


def _local_directory(path: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise BackupError("Use an explicit absolute directory.")
    for part in reversed((path, *path.parents)):
        if not stat.S_ISDIR(_plain_stat(part).st_mode):
            raise BackupError("A directory is required.")
    if os.name == "nt" and ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) != 3:
        raise BackupError("A fixed local Windows drive is required.")
    return path.resolve(strict=True)


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_mode,
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _digest(path: Path) -> str:
    before = _plain_stat(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        if _identity(os.fstat(stream.fileno())) != _identity(before):
            raise BackupError("Profile changed during backup.")
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if _identity(os.fstat(stream.fileno())) != _identity(before):
            raise BackupError("Profile changed during backup.")
    if _identity(_plain_stat(path)) != _identity(before):
        raise BackupError("Profile changed during backup.")
    return digest


def _inventory(root: Path) -> dict:
    entries = {}

    def visit(path: Path) -> None:
        value = _plain_stat(path)
        relative = path.relative_to(root).as_posix()
        directory = stat.S_ISDIR(value.st_mode)
        entries[relative] = (_identity(value), None if directory else _digest(path))
        if directory:
            for child in sorted(path.iterdir()):
                visit(child)
        if _identity(_plain_stat(path)) != _identity(value):
            raise BackupError("Profile changed during backup.")

    visit(root)
    return entries


def _make_private(directory: Path) -> None:
    if os.name == "nt":
        # Set a protected DACL on the empty directory before copying any bytes.
        result = subprocess.run(
            ["whoami.exe", "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
        )
        sid = next(csv.reader(result.stdout.strip().splitlines()))[1]
        if not sid.startswith("S-1-"):
            raise BackupError("Cannot identify the backup owner.")
        # Set an exact protected DACL rather than adding a grant to potentially
        # broad inherited/default permissions. Children inherit only this user.
        from ctypes import wintypes

        security = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        volume = kernel.GetVolumeInformationW
        volume.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        volume.restype = wintypes.BOOL
        filesystem_flags = wintypes.DWORD()
        if (
            not volume(
                str(directory.anchor),
                None,
                0,
                None,
                None,
                ctypes.byref(filesystem_flags),
                None,
                0,
            )
            or not filesystem_flags.value & 8
        ):
            raise BackupError(
                "The backup volume must support persistent access controls."
            )
        convert = security.ConvertStringSecurityDescriptorToSecurityDescriptorW
        convert.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        ]
        convert.restype = wintypes.BOOL
        apply = security.SetFileSecurityW
        apply.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        apply.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        descriptor = ctypes.c_void_p()
        if not convert(f"D:P(A;OICI;FA;;;{sid})", 1, ctypes.byref(descriptor), None):
            raise BackupError("Cannot construct private backup permissions.")
        try:
            if not apply(str(directory), 0x80000004, descriptor):
                raise BackupError("Cannot restrict backup access.")
        finally:
            kernel.LocalFree(descriptor)
    else:
        directory.chmod(0o700)
        if stat.S_IMODE(directory.stat().st_mode) != 0o700:
            raise BackupError("Cannot restrict backup access.")


def create_backup(profile: Path, backup_root: Path, *, exclusive_access: bool) -> Path:
    """Copy all regular files, including hidden files and every audio artifact.

    backup_root must already exist outside the profile. A unique private attempt
    directory is retained on failure, without a completion manifest. No existing
    backup is reused, replaced or pruned. Original retention policy is unchanged.
    """
    if not exclusive_access:
        raise BackupError("Confirm that all profile writers are stopped.")
    profile = _local_directory(Path(profile))
    backup_root = _local_directory(Path(backup_root))
    if profile.is_relative_to(backup_root) or backup_root.is_relative_to(profile):
        raise BackupError("Profile and backup directories must be separate trees.")
    before = _inventory(profile)
    attempt = Path(tempfile.mkdtemp(prefix="clarify-profile-", dir=backup_root))
    _make_private(attempt)
    target = attempt / "profile"
    target.mkdir(mode=0o700)
    for relative, (identity, _) in before.items():
        if relative == ".":
            continue
        source = profile / relative
        destination = target / relative
        if stat.S_ISDIR(identity[0]):
            destination.mkdir(mode=0o700)
        else:
            # Exclusive creation prevents overwrite. Do not copy source ACLs.
            descriptor = os.open(
                destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "wb") as output:
                if _identity(_plain_stat(source)) != identity:
                    raise BackupError("Profile changed during backup.")
                flags = (
                    os.O_RDONLY
                    | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                with os.fdopen(os.open(source, flags), "rb") as input_file:
                    if _identity(os.fstat(input_file.fileno())) != identity:
                        raise BackupError("Profile changed during backup.")
                    shutil.copyfileobj(input_file, output)
                    if _identity(os.fstat(input_file.fileno())) != identity:
                        raise BackupError("Profile changed during backup.")
                output.flush()
                os.fsync(output.fileno())
            os.utime(destination, ns=(identity[4], identity[4]))
    copied = _inventory(target)
    if set(copied) != set(before) or any(
        copied[name][1] != expected[1]
        or stat.S_IFMT(copied[name][0][0]) != stat.S_IFMT(expected[0][0])
        for name, expected in before.items()
    ):
        raise BackupError("Backup verification failed.")
    if _inventory(profile) != before:
        raise BackupError("Profile changed during backup.")
    # The completion marker is written only after both copies pass verification.
    with (attempt / "manifest.pending").open("x", encoding="utf-8") as stream:
        json.dump(
            {
                "schema": 1,
                "complete": True,
                "files": {
                    name: {
                        "sha256": digest,
                        "size": identity[3],
                        "mtime_ns": identity[4],
                    }
                    for name, (identity, digest) in before.items()
                    if digest is not None
                },
            },
            stream,
            sort_keys=True,
        )
        stream.flush()
        os.fsync(stream.fileno())
    # Publish without replacing an existing marker. Failed writes remain pending.
    os.link(attempt / "manifest.pending", attempt / "manifest.json")
    (attempt / "manifest.pending").unlink()
    return attempt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--exclusive-access", action="store_true")
    arguments = parser.parse_args()
    try:
        backup = create_backup(
            arguments.profile,
            arguments.backup_root,
            exclusive_access=arguments.exclusive_access,
        )
    except (OSError, ValueError, BackupError, subprocess.SubprocessError):
        # Do not expose file names, contents or subprocess output on failure.
        print("Profile backup failed. Deployment must stop.")
        return 1
    print(f"Verified private profile backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
