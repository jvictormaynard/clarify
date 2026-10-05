"""Sign immutable portable release metadata with the protected CI environment key."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from portable_updates import (  # noqa: E402
    MANIFEST_ASSET,
    SIGNATURE_ASSET,
    PortableUpdateError,
    file_sha256,
    load_policy,
    verify_binary,
    verify_manifest,
    version_tuple,
)


def create_manifest(
    directory: Path, version: str, source_sha: str, key_bytes: bytes, policy
):
    """Refuse a wrong key or binary before creating any publishable metadata."""
    version_tuple(version)
    if not isinstance(source_sha, str) or not re.fullmatch(r"[a-f0-9]{40}", source_sha):
        raise PortableUpdateError("A release must identify its exact source commit.")
    key = Ed25519PrivateKey.from_private_bytes(key_bytes)
    if key.public_key().public_bytes_raw() != policy.public_key:
        raise PortableUpdateError(
            "The signing key does not match the packaged public key."
        )
    binary = directory / "Clarify.exe"
    document = {
        "schema_version": 1,
        "repository": policy.repository,
        "channel": "stable",
        "version": version,
        "tag": "v" + version,
        "source_sha": source_sha,
        "asset": "Clarify.exe",
        "url": f"https://github.com/{policy.repository}/releases/download/v{version}/Clarify.exe",
        "sha256": file_sha256(binary),
        "size": binary.stat().st_size,
    }
    data = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    signature = key.sign(data)
    release = verify_manifest(data, signature, policy, "0.0.0", "v" + version)
    verify_binary(binary, release)
    (directory / MANIFEST_ASSET).write_bytes(data)
    (directory / SIGNATURE_ASSET).write_bytes(signature)
    return release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=REPO / "dist")
    parser.add_argument("--source-sha", required=True)
    arguments = parser.parse_args()
    from version import __version__

    key = os.environ.pop("CLARIFY_UPDATE_SIGNING_KEY", "")
    try:
        release = create_manifest(
            arguments.dist,
            __version__,
            arguments.source_sha,
            base64.b64decode(key, validate=True),
            load_policy(),
        )
    except (OSError, ValueError, PortableUpdateError) as error:
        # Never print secret values or an exception containing decoded key bytes.
        raise SystemExit(
            "Unable to sign portable release metadata. Check the protected environment and packaged policy."
        ) from error
    print(
        f"Authenticated portable manifest: {release.tag}, source {release.source_sha}, SHA-256 {release.sha256}"
    )


if __name__ == "__main__":
    main()
