"""Record the macOS Python runtime notices and the bundled PortAudio library."""

from __future__ import annotations

import argparse
from ast import literal_eval
from importlib.metadata import distribution, distributions
import json
from pathlib import Path
import platform
import sysconfig

from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]


def frozen_distribution_names():
    analysis = ROOT / "build/macos/Clarify/Analysis-00.toc"
    site = Path(sysconfig.get_path("purelib")).resolve()
    owners = {
        item.locate_file(file).resolve(): canonicalize_name(item.metadata["Name"])
        for item in distributions()
        for file in item.files or ()
    }
    found = set()
    for group in literal_eval(analysis.read_text(encoding="utf-8")):
        if not isinstance(group, list):
            continue
        for row in group:
            if (
                not isinstance(row, tuple)
                or len(row) != 3
                or not isinstance(row[1], str)
            ):
                continue
            source = Path(row[1]).resolve()
            if source.is_relative_to(site):
                if source not in owners:
                    raise ValueError(
                        f"Frozen Python file has no installed distribution: {source.name}"
                    )
                found.add(owners[source])
    return found


def add_component(document, name, version, ref, license_expression):
    document["components"].append(
        {
            "type": "library",
            "name": name,
            "version": version,
            "bom-ref": ref,
            "purl": ref,
            "licenses": [{"expression": license_expression}],
        }
    )
    document["dependencies"].append({"ref": ref, "dependsOn": []})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bom", type=Path, required=True)
    args = parser.parse_args()

    lock = ROOT / "requirements-lock-runtime-macos.txt"
    pins = {
        canonicalize_name(name): pin
        for line in lock.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith((" ", "#"))
        for name, pin in [line.split("==", 1)]
    }
    frozen = frozen_distribution_names()
    packager = {"pyinstaller", "pyinstaller-hooks-contrib"}
    unknown = frozen - pins.keys() - packager
    if unknown:
        raise ValueError(
            "Frozen packages absent from the macOS inventory: "
            + ", ".join(sorted(unknown))
        )
    document = json.loads(args.bom.read_text(encoding="utf-8"))
    notices = ["Clarify for macOS — Python runtime license texts"]
    python_version = platform.python_version()
    python_license = (Path(sysconfig.get_path("stdlib")) / "LICENSE.txt").read_text(
        encoding="utf-8"
    )
    notices.append(f"\nCPython {python_version}\n\n{python_license.strip()}")
    add_component(
        document,
        "CPython",
        python_version,
        f"pkg:generic/cpython@{python_version}",
        "PSF-2.0",
    )

    for name in sorted(pins.keys() | packager):
        installed = distribution(name)
        if name in pins and installed.version != pins[name]:
            raise ValueError(f"{name} does not match the macOS runtime lock")
        if name in packager:
            license_expression = (
                "GPL-2.0-or-later WITH Bootloader-exception"
                if name == "pyinstaller"
                else "Apache-2.0"
            )
            add_component(
                document,
                name,
                installed.version,
                f"pkg:pypi/{name}@{installed.version}",
                license_expression,
            )
        for file in installed.files or ():
            if not file.parts[0].endswith(".dist-info"):
                continue
            if "licenses" in file.parts[1:-1] or file.name.lower().startswith(
                ("license", "copying", "notice")
            ):
                text = installed.locate_file(file).read_text(encoding="utf-8-sig")
                notices.append(
                    f"\n{name} {installed.version} / {file.name}\n\n{text.strip()}"
                )

    # The sounddevice wheel bundles PortAudio without a separate Python pin.
    import sounddevice

    _, runtime = sounddevice.get_portaudio_version()
    if not runtime.startswith("PortAudio V19.7.0"):
        raise ValueError("Review the changed PortAudio runtime before packaging")
    source = "https://github.com/PortAudio/portaudio/blob/v19.7.0/LICENSE.txt"
    license_text = (ROOT / "licenses/portaudio-MIT.txt").read_text(encoding="utf-8")
    notices.append(f"\n{runtime}\n{source}\n\n{license_text.strip()}")
    (args.output_dir / "Clarify-macos-NOTICES.txt").write_text(
        "\n".join(notices) + "\n", encoding="utf-8"
    )

    ref = "pkg:generic/portaudio@19.7.0"
    add_component(document, "PortAudio", "19.7.0", ref, "MIT")
    document["components"][-1]["externalReferences"] = [
        {"type": "license", "url": source}
    ]
    sounddevice_ref = next(
        item["bom-ref"]
        for item in document["components"]
        if item["name"] == "sounddevice"
    )
    edge = next(
        (edge for edge in document["dependencies"] if edge["ref"] == sounddevice_ref),
        None,
    )
    if edge is None:
        document["dependencies"].append({"ref": sounddevice_ref, "dependsOn": [ref]})
    else:
        edge.setdefault("dependsOn", []).append(ref)
    args.bom.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
