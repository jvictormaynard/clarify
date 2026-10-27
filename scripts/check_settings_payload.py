"""Check that the portable executable contains the exact Settings build."""

import argparse
import hashlib
import json
from pathlib import Path

try:
    from .qt_package_policy import unexpected_qt_payload
except ImportError:
    from qt_package_policy import unexpected_qt_payload


def verify_payload(executable: Path, settings: Path) -> None:
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    try:
        embedded = archive.extract("clarify-settings.exe")
    except KeyError as error:
        raise ValueError("The portable build has no Settings executable") from error
    expected = hashlib.sha256(settings.read_bytes()).digest()
    if not embedded or hashlib.sha256(embedded).digest() != expected:
        raise ValueError(
            "The packaged Settings executable differs from the build input"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("settings", type=Path)
    args = parser.parse_args()
    verify_payload(args.executable, args.settings)
    verify_inventory(args.executable, args.settings)
    verify_qt_notices(args.executable, args.settings.parent)
    verify_qt_payload(args.executable)
    verify_update_payload(args.executable, args.settings.parent)
    verify_localization_payload(args.executable)
    verify_computer_payload(args.executable)
    print("Packaged Settings payload matches the build input.")


def verify_computer_payload(executable: Path) -> None:
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    names = [name for name in archive.toc if name.lower().endswith(".pyz")]
    if len(names) != 1:
        raise ValueError("The portable build has no unique Python module archive")
    modules = archive.open_embedded_archive(names[0]).toc
    required = {"computer_host", "computer_processing", "qrcode", "qrcode.image.svg"}
    if required - modules.keys():
        raise ValueError("The portable build is missing computer connection modules")
    name = "licenses/qrcode-BSD.txt"
    matches = [entry for entry in archive.toc if entry.replace("\\", "/") == name]
    expected = (Path(__file__).resolve().parents[1] / name).read_bytes()
    if len(matches) != 1 or archive.extract(matches[0]) != expected:
        raise ValueError("Packaged QR notices differ from the source notice")


def verify_qt_notices(executable: Path, inputs: Path) -> None:
    from PyInstaller.archive.readers import CArchiveReader

    name = "Clarify-qt-NOTICES.txt"
    expected = (inputs / name).read_bytes()
    if not expected or CArchiveReader(str(executable)).extract(name) != expected:
        raise ValueError("Packaged Qt notices differ from the build input")


def verify_update_payload(executable: Path, inputs: Path) -> None:
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    policy = "distribution/portable-update-policy.json"
    expected = (Path(__file__).resolve().parents[1] / policy).read_bytes()
    matches = [name for name in archive.toc if name.replace("\\", "/") == policy]
    if len(matches) != 1 or archive.extract(matches[0]) != expected:
        raise ValueError("Packaged portable update key differs from the source policy")
    name = "Clarify-crypto-NOTICES.txt"
    if archive.extract(name) != (inputs / name).read_bytes():
        raise ValueError("Packaged crypto notices differ from the build input")


def verify_qt_payload(executable: Path) -> None:
    from PyInstaller.archive.readers import CArchiveReader

    unexpected = unexpected_qt_payload(CArchiveReader(str(executable)).toc)
    if unexpected:
        raise ValueError("Unreviewed Qt payload: " + ", ".join(unexpected[:12]))


def verify_localization_payload(executable: Path) -> None:
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    name = "shared/ui_strings.json"
    matches = [entry for entry in archive.toc if entry.replace("\\", "/") == name]
    expected = (Path(__file__).resolve().parents[1] / name).read_bytes()
    if len(matches) != 1 or archive.extract(matches[0]) != expected:
        raise ValueError("Packaged UI translations differ from the source catalog")


def verify_inventory(executable: Path, settings: Path) -> None:
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    for name in ("Clarify-settings.sbom.json", "Clarify-settings-NOTICES.txt"):
        expected = (settings.parent / name).read_bytes()
        if not expected or archive.extract(name) != expected:
            raise ValueError(f"Packaged inventory mismatch: {name}")
    bom = json.loads(
        (settings.parent / "Clarify-settings.sbom.json").read_text(encoding="utf-8")
    )
    expected_hash = hashlib.sha256(settings.read_bytes()).hexdigest()
    if {"alg": "SHA-256", "content": expected_hash} not in bom["metadata"]["component"][
        "hashes"
    ]:
        raise ValueError("Settings inventory describes a different executable")


if __name__ == "__main__":
    main()
