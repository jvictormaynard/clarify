"""Preserve verified crypto attribution and record the wheel's bundled OpenSSL."""

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inventory(output, bom=None):
    manifest = json.loads((ROOT / "licenses/portable-crypto.json").read_text("utf-8"))
    if version("cryptography") != manifest["cryptography_version"]:
        raise ValueError("Cryptography attribution does not match the installed pin")
    from cryptography.hazmat.bindings.openssl.binding import Binding

    binding = Binding()
    openssl = binding.ffi.string(binding.lib.OpenSSL_version(0)).decode("ascii")
    if not openssl.startswith("OpenSSL " + manifest["openssl_version"] + " "):
        raise ValueError("Review the changed OpenSSL component before packaging")
    notices = [
        f"Cryptography {manifest['cryptography_version']} (Apache-2.0 OR BSD-3-Clause)\n{openssl} (Apache-2.0)\n"
    ]
    for license in manifest["licenses"]:
        path = ROOT / "licenses" / license["file"]
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != license["sha256"]:
            raise ValueError("Crypto attribution checksum changed")
        notices.extend(
            ["\nSource: " + license["source"] + "\n", content.decode("utf-8")]
        )
    output.mkdir(parents=True, exist_ok=True)
    (output / "Clarify-crypto-NOTICES.txt").write_text(
        "\n".join(notices), encoding="utf-8"
    )
    if bom is not None:
        document = json.loads(bom.read_text("utf-8"))
        reference = "pkg:generic/openssl@" + manifest["openssl_version"]
        if any(
            component.get("bom-ref") == reference
            for component in document["components"]
        ):
            raise ValueError("OpenSSL is already present in the BOM")
        document["components"].append(
            {
                "type": "library",
                "name": "OpenSSL",
                "version": manifest["openssl_version"],
                "bom-ref": reference,
                "purl": reference,
                "licenses": [{"license": {"id": "Apache-2.0"}}],
                "description": "Statically linked into the pinned cryptography Windows wheel.",
                "externalReferences": [
                    {
                        "type": "website",
                        "url": "https://github.com/openssl/openssl/tree/openssl-"
                        + manifest["openssl_version"],
                    }
                ],
            }
        )
        bom.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bom", type=Path)
    arguments = parser.parse_args()
    inventory(arguments.output_dir, arguments.bom)
    print("Crypto licenses and bundled OpenSSL verified.")


if __name__ == "__main__":
    main()
