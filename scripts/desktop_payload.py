"""Bind every file in the unpacked Electron application to the portable build."""

import hashlib
import json
from pathlib import Path


MANIFEST = "Clarify-desktop-payload.json"
REQUIRED = {
    "Clarify Desktop.exe",
    "LICENSE",
    "LICENSES.chromium.html",
    "resources/app/package.json",
    "resources/app/electron/main.cjs",
    "resources/app/dist/index.html",
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_manifest(directory: Path) -> dict:
    if directory.is_symlink() or directory.is_junction():
        raise ValueError("Desktop payload cannot be a linked directory")
    root = directory.resolve(strict=True)
    files, names = [], set()
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Desktop payload contains a linked entry")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if not path.resolve().is_relative_to(root) or relative.casefold() in names:
            raise ValueError("Desktop payload path escapes or duplicates an entry")
        names.add(relative.casefold())
        files.append(
            {"path": relative, "size": path.stat().st_size, "sha256": file_hash(path)}
        )
    if REQUIRED - {entry["path"] for entry in files}:
        raise ValueError(
            "Desktop payload is missing runtime, renderer, or license files"
        )
    return {"schema": 1, "files": files}


def manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")


def verify_desktop_payload(archive, directory: Path) -> None:
    expected = payload_manifest(directory)
    if archive.extract(MANIFEST) != manifest_bytes(expected):
        raise ValueError("Packaged desktop manifest differs from the build input")
    names = [
        (name.replace("\\", "/"), name)
        for name in archive.toc
        if name.replace("\\", "/").casefold().startswith("desktop-shell/")
    ]
    if len({name.casefold() for name, _ in names}) != len(names):
        raise ValueError("Packaged desktop inventory contains duplicate Windows paths")
    entries = dict(names)
    expected_names = {"desktop-shell/" + entry["path"] for entry in expected["files"]}
    if set(entries) != expected_names:
        raise ValueError("Packaged desktop file inventory differs from the build input")
    for entry in expected["files"]:
        content = archive.extract(entries["desktop-shell/" + entry["path"]])
        if (
            len(content) != entry["size"]
            or hashlib.sha256(content).hexdigest() != entry["sha256"]
        ):
            raise ValueError(
                "Packaged desktop file differs from the build input: " + entry["path"]
            )
