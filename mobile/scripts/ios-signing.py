"""Install existing distribution credentials in an ephemeral macOS keychain."""

import base64
import datetime
import gzip
import json
import os
from pathlib import Path
import plistlib
import secrets
import shutil
import subprocess
import sys

TEAM = "8K353P3496"
BUNDLE = "com.jvictormaynard.clarify"
BUNDLES = {BUNDLE, BUNDLE + ".keyboard", BUNDLE + ".activity"}
ROOT = Path(os.environ["RUNNER_TEMP"]) / "clarify-signing"
KEYCHAIN = ROOT / "signing.keychain-db"


def run(*args):
    result = subprocess.run(args, capture_output=True)
    if result.returncode:
        # Credential-bearing arguments must never appear in an exception or log.
        raise RuntimeError(f"{args[0]} failed with exit code {result.returncode}")
    return result.stdout


def clean():
    manifest = ROOT / "installed-profiles.json"
    if manifest.exists():
        for name in json.loads(manifest.read_text()):
            Path(name).unlink(missing_ok=True)
    if KEYCHAIN.exists():
        subprocess.run(
            ["security", "delete-keychain", str(KEYCHAIN)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    shutil.rmtree(ROOT, ignore_errors=True)
    shutil.rmtree(
        Path(os.environ["RUNNER_TEMP"]) / "clarify-upload", ignore_errors=True
    )


def install():
    ROOT.mkdir(mode=0o700)
    p12 = ROOT / "certificate.p12"
    p12.write_bytes(
        base64.b64decode(os.environ["CLARIFY_IOS_CERTIFICATE_BASE64"], validate=True)
    )
    p12.chmod(0o600)
    password = secrets.token_urlsafe(32)
    run("security", "create-keychain", "-p", password, str(KEYCHAIN))
    run("security", "set-keychain-settings", "-lut", "21600", str(KEYCHAIN))
    run("security", "unlock-keychain", "-p", password, str(KEYCHAIN))
    run(
        "security",
        "import",
        str(p12),
        "-P",
        os.environ["CLARIFY_IOS_CERTIFICATE_PASSWORD"],
        "-A",
        "-t",
        "cert",
        "-f",
        "pkcs12",
        "-k",
        str(KEYCHAIN),
    )
    run(
        "security",
        "set-key-partition-list",
        "-S",
        "apple-tool:,apple:,codesign:",
        "-s",
        "-k",
        password,
        str(KEYCHAIN),
    )
    run(
        "security",
        "list-keychains",
        "-d",
        "user",
        "-s",
        str(KEYCHAIN),
        str(Path.home() / "Library/Keychains/login.keychain-db"),
    )
    raw = gzip.decompress(
        base64.b64decode(os.environ["CLARIFY_IOS_PROFILES_GZIP_BASE64"], validate=True)
    )
    profiles = json.loads(raw)
    if set(profiles) != BUNDLES:
        raise ValueError("Expected app, keyboard and activity profiles")
    installed = []
    manifest = ROOT / "installed-profiles.json"
    mapping = {}
    for bundle, encoded in profiles.items():
        path = ROOT / (bundle + ".mobileprovision")
        path.write_bytes(base64.b64decode(encoded, validate=True))
        path.chmod(0o600)
        profile = plistlib.loads(run("security", "cms", "-D", "-i", str(path)))
        entitlements = profile["Entitlements"]
        if (
            profile["TeamIdentifier"] != [TEAM]
            or entitlements["application-identifier"] != TEAM + "." + bundle
        ):
            raise ValueError("Unexpected team or application in profile")
        if profile["ExpirationDate"] <= datetime.datetime.now(
            datetime.timezone.utc
        ).replace(tzinfo=None):
            raise ValueError("Expired profile")
        if (
            entitlements.get("get-task-allow", False)
            or "ProvisionedDevices" in profile
            or profile.get("ProvisionsAllDevices")
        ):
            raise ValueError("Expected App Store distribution profile")
        if bundle != BUNDLE + ".activity" and "group." + BUNDLE not in entitlements.get(
            "com.apple.security.application-groups", []
        ):
            raise ValueError("Missing shared app group")
        mapping[bundle] = profile["UUID"]
        for directory in [
            "Library/MobileDevice/Provisioning Profiles",
            "Library/Developer/Xcode/UserData/Provisioning Profiles",
        ]:
            destination = (
                Path.home() / directory / (profile["UUID"] + ".mobileprovision")
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            installed.append(str(destination))
            manifest.write_text(json.dumps(installed))
    (ROOT / "profiles.json").write_text(json.dumps(mapping))
    options = {
        "method": "app-store-connect",
        "destination": "export",
        "teamID": TEAM,
        "signingStyle": "manual",
        "signingCertificate": "Apple Distribution",
        "provisioningProfiles": mapping,
        "manageAppVersionAndBuildNumber": False,
        "uploadSymbols": True,
    }
    (ROOT / "ExportOptions.plist").write_bytes(plistlib.dumps(options))
    p12.unlink()
    print("Installed existing distribution identity and three validated profiles.")


if __name__ == "__main__":
    if sys.argv[1:] == ["install"]:
        try:
            install()
        except Exception:
            clean()
            raise
    elif sys.argv[1:] == ["clean"]:
        clean()
    else:
        raise SystemExit("Use install or clean")
