"""Verify the signed app, both extensions, identity, license and IPA digest."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import plistlib
import stat
import subprocess
import sys
import tempfile
import unicodedata
import zipfile

TEAM = "8K353P3496"
BUNDLE = "com.jvictormaynard.clarify"
BUNDLES = {BUNDLE, BUNDLE + ".keyboard", BUNDLE + ".activity"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_zip(archive):
    """Reject links, duplicate extraction targets, escapes and oversized input."""
    items = archive.infolist()
    require(len(items) <= 50000, "IPA contains too many entries")
    names = set()
    total = 0
    for item in items:
        name = item.orig_filename
        parts = PurePosixPath(name).parts
        require(
            name
            and (not name.startswith("/"))
            and ("\\" not in name)
            and (":" not in name)
            and ("\x00" not in name)
            and (".." not in parts)
            and all(
                (
                    part and part != "." and (not part.endswith((" ", ".")))
                    for part in name.rstrip("/").split("/")
                )
            ),
            "Unsafe IPA extraction path",
        )
        canonical = unicodedata.normalize("NFC", name.rstrip("/")).casefold()
        require(canonical not in names, "Duplicate IPA extraction target")
        names.add(canonical)
        mode = stat.S_IFMT(item.external_attr >> 16)
        require(
            mode in (0, stat.S_IFREG, stat.S_IFDIR) and (not item.flag_bits & 1),
            "IPA contains a link, special node or encrypted entry",
        )
        total += item.file_size
        require(
            item.file_size <= 512 * 1024**2 and total <= 2 * 1024**3,
            "IPA extraction exceeds the size limit",
        )


def verify_ipa(ipa_value=None):
    config = json.loads(Path("app.json").read_text())["expo"]
    ipa = Path(sys.argv[1] if ipa_value is None else ipa_value).resolve()
    license_source = Path("third-party/KeyboardHostBundleID/LICENSE")
    verified = []
    with tempfile.TemporaryDirectory(prefix="clarify-ipa-") as directory:
        extracted = Path(directory)
        with zipfile.ZipFile(ipa) as archive:
            check_zip(archive)
            archive.extractall(extracted)
        apps = list((extracted / "Payload").glob("*.app"))
        require(len(apps) == 1, "Expected one container app")
        app = apps[0]
        bundles = [app, *sorted((app / "PlugIns").glob("*.appex"))]
        expected = set(BUNDLES)
        require(len(bundles) == 3, "Expected app, keyboard and activity")
        discovered = {
            path
            for path in extracted.rglob("*")
            if path.suffix.lower() in {".app", ".appex"}
        }
        require(discovered == set(bundles), "Unexpected nested app or extension")
        for path in bundles:
            info = plistlib.loads((path / "Info.plist").read_bytes())
            identifier = info["CFBundleIdentifier"]
            require(identifier in expected, "Unexpected bundle identifier")
            if identifier == BUNDLE:
                endpoint = config["ios"]["infoPlist"]["ClarifyCloudURL"]
                require(
                    endpoint.startswith("https://")
                    and info.get("ClarifyCloudURL") == endpoint,
                    "Artifact must use the declared production endpoint",
                )
            expected.remove(identifier)
            require(
                info["CFBundleShortVersionString"] == config["version"]
                and info["CFBundleVersion"] == config["ios"]["buildNumber"],
                "Artifact version does not match source",
            )
            subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", str(path)],
                check=True,
            )
            signed = subprocess.run(
                ["codesign", "-d", "--entitlements", ":-", str(path)],
                check=True,
                capture_output=True,
            )
            entitlements = plistlib.loads(signed.stdout)
            require(
                entitlements.get("com.apple.developer.team-identifier") == TEAM
                and (not entitlements.get("get-task-allow", False)),
                "Expected non-debug Apple distribution signature",
            )
            require(
                entitlements.get("application-identifier") == TEAM + "." + identifier,
                "Unexpected signed application identifier",
            )
            require(
                identifier == BUNDLE + ".activity"
                or "group." + BUNDLE
                in entitlements.get("com.apple.security.application-groups", []),
                "Shared app group missing from signature",
            )
            require(
                (path / "embedded.mobileprovision").is_file(),
                "Missing distribution profile",
            )
            verified.append(
                {
                    "bundleId": identifier,
                    "version": info["CFBundleShortVersionString"],
                    "build": info["CFBundleVersion"],
                }
            )
        license_path = (
            app / "PlugIns/ClarifyKeyboard.appex/KeyboardHostBundleID.LICENSE"
        )
        require(
            license_path.read_bytes() == license_source.read_bytes(),
            "Bundled third-party license differs from source",
        )
    digest = hashlib.sha256(ipa.read_bytes()).hexdigest()
    ipa.with_suffix(".ipa.sha256").write_text(digest + "  " + ipa.name + "\n")
    result = {"sha256": digest, "bytes": ipa.stat().st_size, "bundles": verified}
    ipa.with_name("verification.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    require(len(sys.argv) == 2, "Use verify-ios-ipa.py IPA")
    print(json.dumps(verify_ipa(sys.argv[1])))


if __name__ == "__main__":
    main()
