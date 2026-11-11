"""Lexical Windows executable identities for safe foreground target capture."""

from __future__ import annotations

import ntpath

_RESERVED_DOS_NAMES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "123456789¹²³"
}


def windows_executable_key(executable: str | None) -> str | None:
    """Return a lexical Windows key without inspecting the filesystem.

    Relative paths, device namespaces, streams, and ambiguous path components
    have no identity. Unicode normalization and case folding beyond Windows
    ``normcase`` would merge distinct executable paths, so neither is used.
    """

    if not isinstance(executable, str) or not 0 < len(executable) <= 32767:
        return None
    candidate = executable.replace("/", "\\")
    if any(ord(char) < 32 or char in '<>"|?*' for char in candidate):
        return None
    drive, tail = ntpath.splitdrive(candidate)
    if drive.startswith("\\\\"):
        drive_parts = drive[2:].split("\\")
        if len(drive_parts) != 2 or not all(drive_parts) or ":" in drive:
            return None
    elif not (
        len(drive) == 2
        and drive[0] in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        and drive[1] == ":"
    ):
        return None
    if not tail.startswith("\\") or ":" in tail:
        return None
    components = candidate.split("\\")
    if any(
        part in {".", ".."} or part.endswith((" ", ".")) for part in components if part
    ):
        return None
    if any(
        part.split(".", 1)[0].rstrip(" ").upper() in _RESERVED_DOS_NAMES
        for part in tail.split("\\")
    ):
        return None
    if ntpath.splitext(tail)[1].lower() != ".exe":
        return None
    return ntpath.normcase(ntpath.normpath(candidate))
