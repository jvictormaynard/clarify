"""Record the macOS Python runtime notices and the bundled PortAudio library."""

from __future__ import annotations

import argparse
from importlib.metadata import distribution
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bom", type=Path, required=True)
    args = parser.parse_args()

    lock = ROOT / "requirements-lock-runtime-macos.txt"
    notices = ["Clarify for macOS — Python runtime license texts"]
    for line in lock.read_text(encoding="utf-8").splitlines():
        if line.startswith((" ", "#")) or not line:
            continue
        name, pin = line.split("==", 1)
        installed = distribution(name)
        if installed.version != pin:
            raise ValueError(f"{name} does not match the macOS runtime lock")
        for file in installed.files or ():
            if not file.parts[0].endswith(".dist-info"):
                continue
            if "licenses" in file.parts[1:-1] or file.name.lower().startswith(
                ("license", "copying", "notice")
            ):
                text = installed.locate_file(file).read_text(encoding="utf-8-sig")
                notices.append(f"\n{name} {pin} / {file.name}\n\n{text.strip()}")

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

    document = json.loads(args.bom.read_text(encoding="utf-8"))
    ref = "pkg:generic/portaudio@19.7.0"
    document["components"].append(
        {
            "type": "library",
            "name": "PortAudio",
            "version": "19.7.0",
            "bom-ref": ref,
            "purl": ref,
            "licenses": [{"license": {"id": "MIT"}}],
            "externalReferences": [{"type": "license", "url": source}],
        }
    )
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
    document["dependencies"].append({"ref": ref, "dependsOn": []})
    args.bom.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
