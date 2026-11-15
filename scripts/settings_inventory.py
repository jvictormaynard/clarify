"""Build desktop dependency evidence from locked npm and Electron inputs.

No provider credentials or user profiles are read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

try:
    from .desktop_payload import MANIFEST, manifest_bytes, payload_manifest
except ImportError:
    from desktop_payload import MANIFEST, manifest_bytes, payload_manifest


def command_json(args: list[str], cwd: Path) -> dict:
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=300,
    )
    return json.loads(result.stdout)


class MissingLicenseError(ValueError):
    pass


def license_texts(root: Path, explicit: str | None = None) -> list[tuple[str, str]]:
    root = root.resolve()
    candidates = []
    if explicit:
        candidates.append(root / explicit)
    candidates.extend(
        p
        for p in root.iterdir()
        if p.is_file()
        and p.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE"))
    )
    for folder in ("licenses", "LICENSES"):
        directory = root / folder
        if directory.is_dir():
            candidates.extend(p for p in directory.rglob("*") if p.is_file())
    result = []
    for path in sorted(set(candidates)):
        if not path.resolve().is_relative_to(root):
            raise ValueError("License path escapes dependency directory")
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError("Missing or oversized license file")
        text = path.read_text(encoding="utf-8-sig")
        if text.strip():
            result.append((path.relative_to(root).as_posix(), text))
    if not result:
        raise MissingLicenseError(f"No license text for dependency {root.name}")
    return result


def vendored_notices(desktop: Path, entries: list[dict]) -> list[tuple[str, str]]:
    result = []
    for entry in entries:
        path = desktop / "licenses" / entry["file"]
        if not path.resolve().is_relative_to((desktop / "licenses").resolve()):
            raise ValueError("Vendored notice escapes license directory")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Vendored notice checksum mismatch")
        result.append((entry["source"], path.read_text(encoding="utf-8")))
    if not result or any(not content.strip() for _, content in result):
        raise ValueError("Empty vendored notice entry")
    return result


def inventory(desktop: Path, npm: dict) -> tuple[dict, str]:
    components, dependencies, notices = [], [], []
    npm_components = [npm["metadata"]["component"], *npm.get("components", [])]
    refs = {c["bom-ref"]: c["purl"] for c in npm_components}
    root_ref = "pkg:generic/clarify-settings"
    refs[npm_components[0]["bom-ref"]] = root_ref
    for component in npm_components[1:]:
        component = dict(component)
        component["bom-ref"] = component["purl"]
        relative = next(
            p["value"]
            for p in component["properties"]
            if p["name"] == "cdx:npm:package:path"
        )
        directory = (desktop / relative).resolve()
        if not directory.is_relative_to((desktop / "node_modules").resolve()):
            raise ValueError("npm dependency path escapes node_modules")
        texts = license_texts(directory)
        notices.append((component["purl"], texts))
        components.append(component)
    for edge in npm["dependencies"]:
        dependencies.append(
            {
                "ref": refs[edge["ref"]],
                "dependsOn": sorted(refs[r] for r in edge.get("dependsOn", [])),
            }
        )

    source_manifest = desktop / "licenses/source-components.json"
    if source_manifest.is_file():
        for entry in json.loads(source_manifest.read_text(encoding="utf-8")):
            ref = entry["purl"]
            notices.append((ref, vendored_notices(desktop, [entry])))
            components.append(
                {
                    "type": "library",
                    "name": entry["name"],
                    "version": entry["version"],
                    "bom-ref": ref,
                    "purl": ref,
                    "scope": "required",
                    "licenses": [{"expression": entry["license"]}],
                    "externalReferences": [{"type": "license", "url": entry["source"]}],
                }
            )
            dependencies.extend(
                [
                    {"ref": root_ref, "dependsOn": [ref]},
                    {"ref": ref, "dependsOn": []},
                ]
            )

    merged = {}
    for edge in dependencies:
        merged.setdefault(edge["ref"], set()).update(edge["dependsOn"])
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "Clarify Settings",
                "bom-ref": root_ref,
                "version": npm_components[0]["version"],
            },
            "lifecycles": [{"phase": "build"}],
        },
        "components": sorted(components, key=lambda c: c["bom-ref"]),
        "dependencies": [
            {"ref": key, "dependsOn": sorted(value)}
            for key, value in sorted(merged.items())
        ],
    }
    text = "Clarify Settings — third-party license texts\n\n"
    text += "Generated from locked npm production dependencies and vendored source notices.\n"
    for ref, files in sorted(notices):
        text += f"\n{'=' * 72}\n{ref}\n"
        for name, content in files:
            text += f"\n--- {name} ---\n{content.rstrip()}\n"
    return bom, text


def merge_bom(base: dict, settings: dict) -> dict:
    """Merge without losing the Python/SoX graph or creating dangling refs."""
    components = {c["bom-ref"]: c for c in base.get("components", [])}
    additions = [settings["metadata"]["component"], *settings["components"]]
    for component in additions:
        components[component["bom-ref"]] = component
    edges = {}
    for edge in [*base.get("dependencies", []), *settings["dependencies"]]:
        edges.setdefault(edge["ref"], set()).update(edge.get("dependsOn", []))
    root = base.get("metadata", {}).get("component", {}).get("bom-ref")
    if root:
        edges.setdefault(root, set()).add(settings["metadata"]["component"]["bom-ref"])
    base["components"] = sorted(components.values(), key=lambda c: c["bom-ref"])
    base["dependencies"] = [
        {"ref": key, "dependsOn": sorted(value)} for key, value in sorted(edges.items())
    ]
    return base


def electron_inventory(desktop: Path, npm: dict, shell: Path) -> tuple[dict, str]:
    package = json.loads((desktop / "package.json").read_text(encoding="utf-8"))
    installed = json.loads(
        (desktop / "node_modules/electron/package.json").read_text(encoding="utf-8")
    )
    version = installed["version"]
    if package["devDependencies"]["electron"] != version:
        raise ValueError("Installed Electron differs from the pinned runtime")
    bom, notices = inventory(desktop, npm)
    bom["metadata"]["component"]["name"] = "Clarify Desktop"
    ref = "pkg:github/electron/electron@" + version
    bom["components"].append(
        {
            "type": "framework",
            "name": "electron",
            "version": version,
            "bom-ref": ref,
            "purl": ref,
            "scope": "required",
            "licenses": [{"expression": "MIT"}],
            "externalReferences": [
                {
                    "type": "distribution",
                    "url": f"https://github.com/electron/electron/releases/tag/v{version}",
                }
            ],
        }
    )
    bom["dependencies"].append({"ref": ref, "dependsOn": []})
    root_edge = next(
        edge
        for edge in bom["dependencies"]
        if edge["ref"] == bom["metadata"]["component"]["bom-ref"]
    )
    root_edge["dependsOn"] = sorted(set(root_edge["dependsOn"]) | {ref})
    environment = {
        key: value for key, value in os.environ.items() if key != "NODE_OPTIONS"
    }
    environment["ELECTRON_RUN_AS_NODE"] = "1"
    runtime = subprocess.run(
        [str(shell / "Clarify Desktop.exe"), "-p", "JSON.stringify(process.versions)"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    versions = json.loads(runtime.stdout)
    if versions["electron"] != version:
        raise ValueError("Packaged Electron differs from the pinned runtime")
    runtime_refs = []
    for name, key in (("chromium", "chrome"), ("nodejs", "node"), ("v8", "v8")):
        runtime_ref = f"pkg:generic/{name}@{versions[key]}"
        runtime_refs.append(runtime_ref)
        bom["components"].append(
            {
                "type": "framework",
                "name": name,
                "version": versions[key],
                "bom-ref": runtime_ref,
                "purl": runtime_ref,
                "scope": "required",
            }
        )
        bom["dependencies"].append({"ref": runtime_ref, "dependsOn": []})
    next(edge for edge in bom["dependencies"] if edge["ref"] == ref)["dependsOn"] = (
        runtime_refs
    )
    for name in ("LICENSE", "LICENSES.chromium.html"):
        content = (shell / name).read_text(encoding="utf-8")
        if not content.strip():
            raise ValueError("Missing Electron runtime license text")
        notices += f"\n{'=' * 72}\n{ref}/{name}\n{content}\n"
    return bom, notices


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--electron-shell", type=Path)
    parser.add_argument("--merge-bom", type=Path)
    parser.add_argument("--settings-bom", type=Path)
    args = parser.parse_args()
    if args.merge_bom:
        result = merge_bom(
            json.loads(args.merge_bom.read_text(encoding="utf-8-sig")),
            json.loads(args.settings_bom.read_text(encoding="utf-8")),
        )
        args.merge_bom.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return
    desktop = args.desktop.resolve()
    node = shutil.which("node")
    npm_cli = Path(node).parent / "node_modules/npm/bin/npm-cli.js"
    npm_command = [node, str(npm_cli)] if npm_cli.is_file() else [shutil.which("npm")]
    npm = command_json(
        # Each application owns its inventory, independent of other workspaces.
        [
            *npm_command,
            "sbom",
            "--workspaces=false",
            "--omit=dev",
            "--sbom-format",
            "cyclonedx",
        ],
        desktop,
    )
    if not args.electron_shell:
        parser.error(
            "--electron-shell is required when generating the desktop inventory"
        )
    shell = args.electron_shell.resolve(strict=True)
    manifest = manifest_bytes(payload_manifest(shell))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / MANIFEST).write_bytes(manifest)
    bom, notices = electron_inventory(desktop, npm, shell)
    bom["metadata"]["component"]["hashes"] = [
        {"alg": "SHA-256", "content": hashlib.sha256(manifest).hexdigest()}
    ]
    bom["metadata"]["properties"] = [
        {
            "name": "clarify:input-sha256:package-lock.json",
            "value": hashlib.sha256(
                (desktop / "package-lock.json").read_bytes()
            ).hexdigest(),
        }
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "Clarify-settings.sbom.json").write_text(
        json.dumps(bom, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "Clarify-settings-NOTICES.txt").write_text(
        notices, encoding="utf-8"
    )
    print(
        f"Settings inventory: {len(bom['components'])} components with license texts."
    )


if __name__ == "__main__":
    main()
