"""Build Settings dependency evidence from installed, locked npm/Cargo inputs.

No provider or user profile is read. Cargo build-only crates are retained with
excluded scope: this is a source dependency inventory, not a binary link map.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tomllib
from pathlib import Path
from urllib.parse import quote


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


def dependency_notices(desktop: Path, ref: str, root: Path, explicit=None):
    try:
        return license_texts(root, explicit)
    except MissingLicenseError:
        manifest = json.loads((desktop / "licenses/manifest.json").read_text())
        if ref not in manifest:
            raise ValueError(f"Review missing license text: {ref}")
        result = []
        for entry in manifest[ref]:
            path = desktop / "licenses" / entry["file"]
            if not path.resolve().is_relative_to((desktop / "licenses").resolve()):
                raise ValueError("Vendored notice escapes license directory")
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError("Vendored notice checksum mismatch")
            result.append((entry["source"], path.read_text(encoding="utf-8")))
        if not result:
            raise ValueError("Empty vendored notice entry")
        return result


def inventory(desktop: Path, npm: dict, cargo: dict) -> tuple[dict, str]:
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
        texts = dependency_notices(desktop, component["purl"], directory)
        notices.append((component["purl"], texts))
        components.append(component)
    for edge in npm["dependencies"]:
        dependencies.append(
            {
                "ref": refs[edge["ref"]],
                "dependsOn": sorted(refs[r] for r in edge.get("dependsOn", [])),
            }
        )

    packages = {p["id"]: p for p in cargo["packages"]}
    nodes = {p["id"]: p for p in cargo["resolve"]["nodes"]}
    cargo_root = cargo["resolve"]["root"]
    cargo_refs = {
        key: f"pkg:cargo/{quote(p['name'])}@{p['version']}"
        for key, p in packages.items()
    }
    cargo_refs[cargo_root] = root_ref
    runtime = {cargo_root}
    pending = [cargo_root]
    while pending:
        for edge in nodes[pending.pop()]["deps"]:
            package = packages[edge["pkg"]]
            normal = any(kind["kind"] is None for kind in edge["dep_kinds"])
            proc_macro = any(
                "proc-macro" in target["kind"] for target in package["targets"]
            )
            if normal and not proc_macro and edge["pkg"] not in runtime:
                runtime.add(edge["pkg"])
                pending.append(edge["pkg"])
    # Only resolved nodes are relevant to the selected Windows target.
    for key, node in nodes.items():
        package = packages[key]
        if key != cargo_root:
            if not package.get("source", "").startswith("registry+"):
                raise ValueError(
                    "Review non-registry Cargo dependencies before distribution"
                )
            expression = package.get("license")
            if not expression:
                raise ValueError(f"Missing Cargo license expression: {package['name']}")
            expression = expression.replace("MIT/Apache-2.0", "MIT OR Apache-2.0")
            texts = dependency_notices(
                desktop,
                cargo_refs[key],
                Path(package["manifest_path"]).parent,
                package.get("license_file"),
            )
            source_url = f"https://crates.io/api/v1/crates/{package['name']}/{package['version']}/download"
            texts = [("Corresponding crate source", source_url), *texts]
            notices.append((cargo_refs[key], texts))
            components.append(
                {
                    "type": "library",
                    "name": package["name"],
                    "version": package["version"],
                    "bom-ref": cargo_refs[key],
                    "purl": cargo_refs[key],
                    "scope": "required" if key in runtime else "excluded",
                    "licenses": [{"expression": expression}],
                    "externalReferences": [{"type": "distribution", "url": source_url}],
                    "properties": [
                        {
                            "name": "clarify:dependency-evidence",
                            "value": "resolved Windows source graph; not a binary link map",
                        }
                    ],
                }
            )
        dependencies.append(
            {
                "ref": cargo_refs[key],
                "dependsOn": sorted({cargo_refs[e["pkg"]] for e in node["deps"]}),
            }
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
                "version": packages[cargo_root]["version"],
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
    text += "Generated from locked npm production dependencies and the resolved Windows Cargo graph.\n"
    text += "Build-only crates are included for attribution; inclusion does not prove binary linkage.\n"
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop", type=Path)
    parser.add_argument("--output-dir", type=Path)
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
        [*npm_command, "sbom", "--omit=dev", "--sbom-format", "cyclonedx"], desktop
    )
    cargo = command_json(
        [
            "cargo",
            "metadata",
            "--format-version",
            "1",
            "--locked",
            "--filter-platform",
            "x86_64-pc-windows-msvc",
            "--manifest-path",
            "src-tauri/Cargo.toml",
            "--features",
            "custom-protocol",
        ],
        desktop,
    )
    bom, notices = inventory(desktop, npm, cargo)
    executable = args.output_dir / "clarify-settings.exe"
    bom["metadata"]["component"]["hashes"] = [
        {
            "alg": "SHA-256",
            "content": hashlib.sha256(executable.read_bytes()).hexdigest(),
        }
    ]
    bom["metadata"]["properties"] = [
        {
            "name": f"clarify:input-sha256:{name}",
            "value": hashlib.sha256((desktop / name).read_bytes()).hexdigest(),
        }
        for name in ("package-lock.json", "src-tauri/Cargo.lock", "rust-toolchain.toml")
    ]
    toolchain = tomllib.loads((desktop / "rust-toolchain.toml").read_text())
    bom["metadata"]["properties"].append(
        {"name": "clarify:rust-toolchain", "value": toolchain["toolchain"]["channel"]}
    )
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
