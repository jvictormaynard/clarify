"""Check that the portable executable contains the exact Settings build."""

import argparse
import hashlib
import json
from pathlib import Path


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
    print("Packaged Settings payload matches the build input.")


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
