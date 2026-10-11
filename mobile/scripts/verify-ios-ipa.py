"""Check the exported artifact before an upload to App Store Connect."""

import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import zipfile

TEAM = "8K353P3496"
BUNDLE = "com.jvictormaynard.clarify"
config = json.loads(Path("app.json").read_text())["expo"]
ipa = Path(sys.argv[1]).resolve()
verified = []
with tempfile.TemporaryDirectory(prefix="clarify-ipa-") as directory:
    with zipfile.ZipFile(ipa) as archive:
        archive.extractall(directory)
    apps = list((Path(directory) / "Payload").glob("*.app"))
    if len(apps) != 1:
        raise ValueError("Expected one container app")
    app = apps[0]
    bundles = [app, *sorted((app / "PlugIns").glob("*.appex"))]
    expected = {BUNDLE, BUNDLE + ".keyboard", BUNDLE + ".activity"}
    if len(bundles) != 3:
        raise ValueError("Expected app, keyboard and activity")
    for path in bundles:
        info = plistlib.loads((path / "Info.plist").read_bytes())
        identifier = info["CFBundleIdentifier"]
        if identifier not in expected:
            raise ValueError("Unexpected bundle identifier")
        expected.remove(identifier)
        if (
            info["CFBundleShortVersionString"] != config["version"]
            or info["CFBundleVersion"] != config["ios"]["buildNumber"]
        ):
            raise ValueError("Artifact version does not match source")
        subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(path)], check=True
        )
        signed = subprocess.run(
            ["codesign", "-d", "--entitlements", ":-", str(path)],
            check=True,
            capture_output=True,
        )
        entitlements = plistlib.loads(signed.stdout)
        if entitlements.get(
            "com.apple.developer.team-identifier"
        ) != TEAM or entitlements.get("get-task-allow", False):
            raise ValueError("Expected non-debug Apple distribution signature")
        if entitlements.get("application-identifier") != TEAM + "." + identifier:
            raise ValueError("Unexpected signed application identifier")
        if (
            identifier != BUNDLE + ".activity"
            and "group." + BUNDLE
            not in entitlements.get("com.apple.security.application-groups", [])
        ):
            raise ValueError("Shared app group missing from signature")
        if not (path / "embedded.mobileprovision").is_file():
            raise ValueError("Missing distribution profile")
        verified.append(
            {
                "bundleId": identifier,
                "version": info["CFBundleShortVersionString"],
                "build": info["CFBundleVersion"],
            }
        )
    license_path = app / "PlugIns/ClarifyKeyboard.appex/KeyboardHostBundleID.LICENSE"
    if (
        license_path.read_bytes()
        != Path("third-party/KeyboardHostBundleID/LICENSE").read_bytes()
    ):
        raise ValueError("Bundled third-party license differs from source")
digest = hashlib.sha256(ipa.read_bytes()).hexdigest()
ipa.with_suffix(".ipa.sha256").write_text(digest + "  " + ipa.name + "\n")
result = {"sha256": digest, "bytes": ipa.stat().st_size, "bundles": verified}
ipa.with_name("verification.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
