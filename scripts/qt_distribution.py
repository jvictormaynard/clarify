"""Prepare pinned upstream Qt sources and notices, without extracting source trees."""

import argparse
import hashlib
import json
import posixpath
import tarfile
import zipfile
from importlib.metadata import version
from pathlib import Path, PurePosixPath

import requests

ROOT = Path(__file__).resolve().parents[1]


def source_url(name, qt_version):
    filename = f"{name}-everywhere-src-{qt_version}.tar.xz"
    if name == "pyside-setup":
        return f"https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{qt_version}-src/{filename}"
    minor = ".".join(qt_version.split(".")[:2])
    return f"https://download.qt.io/official_releases/qt/{minor}/{qt_version}/submodules/{filename}"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download_verified(url, target, expected):
    if target.exists():
        if digest(target) != expected:
            raise ValueError(f"Cached source checksum mismatch: {target.name}")
        return
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=(15, 60)) as response:
            response.raise_for_status()
            with temporary.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    output.write(chunk)
        if digest(temporary) != expected:
            raise ValueError(f"Source checksum mismatch: {target.name}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def notice_entries(archive_path):
    """Collect conservative source-tree attribution, including unlinked components."""
    with tarfile.open(archive_path, "r:xz") as archive:
        files = {item.name: item for item in archive if item.isfile()}
        selected = set()
        for name, item in files.items():
            path = PurePosixPath(name)
            basename = path.name.lower()
            if "LICENSES" in path.parts or basename.startswith(
                ("license", "copying", "copyright", "notice")
            ):
                selected.add(name)
            if basename == "qt_attribution.json":
                selected.add(name)
                entries = json.loads(archive.extractfile(item).read(), strict=False)
                if isinstance(entries, dict):
                    entries = [entries]
                for entry in entries:
                    refs = entry.get("LicenseFile", [])
                    if isinstance(refs, str):
                        refs = [refs]
                    for ref in refs:
                        resolved = posixpath.normpath(
                            posixpath.join(str(path.parent), ref)
                        )
                        if resolved not in files:
                            raise ValueError(
                                f"Missing attribution license: {name}: {ref}"
                            )
                        selected.add(resolved)
        if not any(name.endswith("/LICENSES/LGPL-3.0-only.txt") for name in selected):
            raise ValueError(f"No LGPL text found in {archive_path.name}")
        for name in sorted(selected):
            data = archive.extractfile(files[name]).read()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("latin-1")
            yield name, text


def prepare(output, cache):
    manifest = json.loads((ROOT / "scripts/qt_sources.json").read_text())
    qt_version = manifest["version"]
    for package in ("PySide6-Essentials", "shiboken6"):
        if version(package) != qt_version:
            raise ValueError(f"Review Qt sources before changing {package}")
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    guide = (ROOT / "docs/qt-distribution.md").read_text(encoding="utf-8")
    notices = [
        guide,
        "\nSOURCE-TREE NOTICES\nIncludes build tools and unlinked code for conservative attribution.\n",
    ]
    with zipfile.ZipFile(
        output / "Clarify-qt-sources.zip", "w", compression=zipfile.ZIP_STORED
    ) as bundle:
        bundle.writestr("qt-distribution.md", guide)
        bundle.writestr("qt_sources.json", json.dumps(manifest, indent=2))
        for entry in manifest["archives"]:
            url = source_url(entry["name"], qt_version)
            path = cache / url.rsplit("/", 1)[1]
            download_verified(url, path, entry["sha256"])
            bundle.write(path, path.name)
            notices.append(f"\nSOURCE: {url}\nSHA-256: {entry['sha256']}\n")
            for name, text in notice_entries(path):
                notices.append(f"\n--- {name} ---\n{text}\n")
            print(f"Qt source verified: {entry['name']}", flush=True)
    (output / "Clarify-qt-NOTICES.txt").write_text("\n".join(notices), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "build/qt-sources")
    args = parser.parse_args()
    prepare(args.output_dir, args.cache_dir)
