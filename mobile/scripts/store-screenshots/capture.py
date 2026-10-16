"""Capture the unchanged release app on disposable iPhone simulators.

No signing, provider processing, login or App Store Connect calls occur here.
Demo history and vocabulary are stored in each simulator's real local database.
"""

import argparse
import hashlib
import json
import plistlib
import shutil
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

SOURCE = "542b8a742634183bf7fb857305674968e96f559b"
BUNDLE = "com.jvictormaynard.clarify"
LANGUAGES = ("pt", "en", "es")
EXAMPLES = {
    "pt": [
        "Vamos marcar a reunião para quinta-feira às 10h.",
        "A ideia é simples: falar naturalmente e transformar a voz em um texto claro.",
        "Revisei o documento e organizei os próximos passos para a equipe.",
    ],
    "en": [
        "Let's schedule the meeting for Thursday at 10 AM.",
        "The idea is simple: speak naturally and turn your voice into clear text.",
        "I reviewed the document and organized the next steps for the team.",
    ],
    "es": [
        "Programemos la reunión para el jueves a las 10.",
        "La idea es sencilla: hablar con naturalidad y convertir la voz en un texto claro.",
        "Revisé el documento y organicé los próximos pasos para el equipo.",
    ],
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_demo(container, language):
    database = container / "Library/Application Support/Clarify/library.sqlite"
    if not database.is_file():
        raise RuntimeError("The real app did not create its local library")
    today = datetime.now(timezone.utc).replace(
        hour=9, minute=35, second=0, microsecond=0
    )
    dates = (
        today,
        today - timedelta(minutes=15),
        today - timedelta(days=1) + timedelta(hours=7, minutes=35),
    )
    with sqlite3.connect(database) as connection:
        if connection.execute("PRAGMA user_version").fetchone()[0] != 3:
            raise RuntimeError("Unexpected release library schema")
        if connection.execute("SELECT COUNT(*) FROM history").fetchone()[0]:
            raise RuntimeError(
                "A disposable screenshot profile must start with empty history"
            )
        for index, (text, created) in enumerate(zip(EXAMPLES[language], dates)):
            identifier = f"store-demo-{language}-{index}"
            payload = {
                "id": identifier,
                "createdAt": created.timestamp(),
                "transcript": text,
                "text": text,
                "rewritten": True,
                "sourceDevice": "mobile",
            }
            connection.execute(
                "INSERT INTO history(operation_id,owner,created_at,payload) VALUES(?,?,?,?)",
                (
                    identifier,
                    "",
                    created.timestamp(),
                    json.dumps(payload, ensure_ascii=False).encode(),
                ),
            )
        vocabulary = [
            {"term": term, "pronunciation": "", "aliases": [], "enabled": True}
            for term in ("Clarify", "Open source", "API")
        ]
        connection.execute(
            "INSERT INTO vocabulary(id,payload) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (json.dumps(vocabulary).encode(),),
        )


def png_dimensions(path):
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise RuntimeError("The native attachment is not a PNG")
    return struct.unpack(">II", data[16:24])


def validate_simulator_archive(path):
    if path.stat().st_size > 512 * 1024 * 1024:
        raise RuntimeError("Simulator app archive exceeds the capture size limit")
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if (
            len(members) > 10000
            or sum(item.file_size for item in members) > 1024 * 1024 * 1024
        ):
            raise RuntimeError("Simulator app archive exceeds the extraction limits")
        names = set()
        for member in members:
            parts = PurePosixPath(member.filename)
            if (
                parts.is_absolute()
                or ".." in parts.parts
                or not parts.parts
                or parts.parts[0] not in {"Clarify.app", "__MACOSX"}
                or "\\" in member.filename
            ):
                raise RuntimeError("Unsafe simulator app archive path")
            normalized = str(parts)
            if normalized in names:
                raise RuntimeError("Duplicate simulator app archive path")
            names.add(normalized)
            kind = stat.S_IFMT(member.external_attr >> 16)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise RuntimeError(
                    "Simulator app archive contains a link or special file"
                )
            if (
                member.flag_bits & 1
                or member.file_size > 256 * 1024 * 1024
                or member.file_size > max(1, member.compress_size) * 1000
            ):
                raise RuntimeError(
                    "Unsafe simulator app archive entry size or encoding"
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--existing-simulator", type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise RuntimeError("Real iOS simulator capture requires macOS")
    root = args.app_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise RuntimeError(
            "Preserve existing output; choose a new empty capture directory"
        )
    helper = Path(__file__).resolve().parent
    log_path = output / "capture.log"

    def run(command, *, cwd=None, capture=False, check=True):
        with log_path.open("a") as log:
            log.write("\nCOMMAND " + repr(command) + "\n")
            log.flush()
            result = subprocess.run(
                command,
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE if capture else log,
                stderr=log,
            )
        if check and result.returncode:
            raise RuntimeError(
                f"{command[0]} failed ({result.returncode}); see capture.log"
            )
        return result.stdout.strip() if capture else result.returncode

    if run(["git", "-C", str(root), "rev-parse", "HEAD"], capture=True) != SOURCE:
        raise RuntimeError("The app checkout must match the published build29 source")
    if run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
        capture=True,
    ):
        raise RuntimeError("Tracked app source changed before capture")
    config = json.loads((root / "app.json").read_text())["expo"]
    if (
        config["version"],
        config["ios"]["buildNumber"],
        config["ios"]["bundleIdentifier"],
    ) != ("0.8.0", "29", BUNDLE):
        raise RuntimeError("Unexpected release version or bundle")
    if "ClarifyKeyboardDiagnostic" in config["ios"]["infoPlist"]:
        raise RuntimeError("The temporary diagnostic screen must remain hidden")
    height_hash = digest(root / "native/keyboard/KeyboardHeightSync.m")
    if (
        height_hash
        != "b1a475f5fa841e2272e9bc0e8b65dc6783fcd20f6cfc55893861a41a8736de04"
    ):
        raise RuntimeError("The accepted keyboard correction source changed")

    types = json.loads(
        run(["xcrun", "simctl", "list", "devicetypes", "--json"], capture=True)
    )["devicetypes"]
    device_type = next(
        (item for item in types if item["name"] == "iPhone 17 Pro"), None
    )
    runtimes = json.loads(
        run(["xcrun", "simctl", "list", "runtimes", "--json"], capture=True)
    )["runtimes"]
    runtime = next(
        (
            item
            for item in runtimes
            if item.get("isAvailable") and item["name"] == "iOS 26.5"
        ),
        None,
    )
    if not device_type or not runtime:
        raise RuntimeError("Expected iPhone 17 Pro and iOS 26.5 simulator")
    manifest = {
        "appSourceSHA": SOURCE,
        "helperSourceSHA": run(
            ["git", "-C", str(helper), "rev-parse", "HEAD"], capture=True
        ),
        "version": "0.8.0",
        "build": "29",
        "bundleId": BUNDLE,
        "device": device_type["name"],
        "runtime": runtime["name"],
        "keyboardHeightSyncSourceSHA256": height_hash,
        "credentialsUsed": False,
        "providerRequests": False,
        "microphoneActivated": False,
        "data": "Synthetic examples stored in the real local SQLite library of fresh disposable simulator profiles. Guest Account screen. No fake account or API key.",
        "ui": "Unmodified release source; native XCUIScreen attachments. Dark appearance and standard simulator status-bar override; no image edits or overlays.",
        "onboarding": "Captured before seeding. Ready screens use the standard clarify.onboarding.completed launch default; no setup code is modified.",
        "captures": [],
    }
    created_devices = []
    try:
        with tempfile.TemporaryDirectory(prefix="clarify-store-capture-") as temporary:
            temporary = Path(temporary)
            if args.existing_simulator:
                previous = args.existing_simulator.resolve()
                evidence = json.loads((previous / "capture-manifest.json").read_text())
                archive = previous / "simulator-app.zip"
                if (
                    evidence.get("appSourceSHA"),
                    evidence.get("version"),
                    evidence.get("build"),
                ) != (SOURCE, "0.8.0", "29"):
                    raise RuntimeError("Previous simulator app provenance differs")
                validate_simulator_archive(archive)
                if evidence.get("simulatorAppArchiveSHA256") != digest(archive):
                    raise RuntimeError("Previous simulator app checksum differs")
                unpacked = temporary / "ReusedApp"
                unpacked.mkdir()
                run(["ditto", "-x", "-k", str(archive), str(unpacked)])
                app = unpacked / "Clarify.app"
                shutil.copyfile(archive, output / "simulator-app.zip")
                manifest["reusedSimulatorAppArchiveSHA256"] = digest(archive)
                print(
                    "Reusing the byte-identical build29 simulator app; no app compilation",
                    flush=True,
                )
            else:
                derived = temporary / "AppDerivedData"
                print(
                    "Building the unchanged build29 container for iOS Simulator",
                    flush=True,
                )
                run(
                    [
                        "xcodebuild",
                        "build",
                        "-workspace",
                        str(root / "ios/Clarify.xcworkspace"),
                        "-scheme",
                        "Clarify",
                        "-configuration",
                        "Release",
                        "-destination",
                        "generic/platform=iOS Simulator",
                        "-derivedDataPath",
                        str(derived),
                        "CODE_SIGNING_ALLOWED=NO",
                        "CODE_SIGNING_REQUIRED=NO",
                    ],
                    cwd=root,
                )
                app = derived / "Build/Products/Release-iphonesimulator/Clarify.app"
            info = plistlib.loads((app / "Info.plist").read_bytes())
            if (
                info["CFBundleShortVersionString"],
                str(info["CFBundleVersion"]),
                info["CFBundleIdentifier"],
            ) != ("0.8.0", "29", BUNDLE):
                raise RuntimeError("Built simulator app identity differs")
            if not (app / "main.jsbundle").is_file():
                raise RuntimeError(
                    "Release simulator app is missing its bundled JavaScript"
                )
            if not args.existing_simulator:
                run(
                    [
                        "ditto",
                        "-c",
                        "-k",
                        "--sequesterRsrc",
                        "--keepParent",
                        str(app),
                        str(output / "simulator-app.zip"),
                    ]
                )
            manifest["simulatorAppArchiveSHA256"] = digest(output / "simulator-app.zip")
            fixture = temporary / "Runner"
            run(
                [
                    "ruby",
                    str(helper / "project.rb"),
                    str(fixture),
                    str(helper / "StoreScreenshots.swift"),
                ]
            )
            runner_derived = temporary / "RunnerDerivedData"

            for language in LANGUAGES:
                print(
                    f"Capturing real {language} onboarding, Home, Dictionary and Account",
                    flush=True,
                )
                device = run(
                    [
                        "xcrun",
                        "simctl",
                        "create",
                        f"Clarify Store {language}",
                        device_type["identifier"],
                        runtime["identifier"],
                    ],
                    capture=True,
                )
                created_devices.append(device)
                run(["xcrun", "simctl", "bootstatus", device, "-b"])
                run(["xcrun", "simctl", "ui", device, "appearance", "dark"])
                run(
                    [
                        "xcrun",
                        "simctl",
                        "status_bar",
                        device,
                        "override",
                        "--time",
                        "9:41",
                        "--dataNetwork",
                        "wifi",
                        "--wifiMode",
                        "active",
                        "--wifiBars",
                        "3",
                        "--batteryState",
                        "charged",
                        "--batteryLevel",
                        "100",
                    ]
                )
                run(["xcrun", "simctl", "install", device, str(app)])
                for phase in ("Onboarding", "Screens"):
                    if phase == "Screens":
                        run(
                            ["xcrun", "simctl", "terminate", device, BUNDLE],
                            check=False,
                        )
                        container = Path(
                            run(
                                [
                                    "xcrun",
                                    "simctl",
                                    "get_app_container",
                                    device,
                                    BUNDLE,
                                    "data",
                                ],
                                capture=True,
                            )
                        )
                        seed_demo(container, language)
                    result_path = output / f"{language}-{phase.lower()}.xcresult"
                    test = f"StoreScreenshots/StoreScreenshots/test{phase}{language.upper()}"
                    run(
                        [
                            "xcodebuild",
                            "test",
                            "-project",
                            str(fixture / "StoreScreenshots.xcodeproj"),
                            "-scheme",
                            "StoreScreenshots",
                            "-configuration",
                            "Release",
                            "-destination",
                            f"platform=iOS Simulator,id={device}",
                            "-derivedDataPath",
                            str(runner_derived),
                            "-parallel-testing-enabled",
                            "NO",
                            "-collect-test-diagnostics",
                            "never",
                            "-test-timeouts-enabled",
                            "YES",
                            "-maximum-test-execution-time-allowance",
                            "180",
                            "-only-testing:" + test,
                            "-resultBundlePath",
                            str(result_path),
                            "CODE_SIGNING_ALLOWED=NO",
                            "CODE_SIGNING_REQUIRED=NO",
                        ]
                    )
                    attachments = output / f"{language}-{phase.lower()}-attachments"
                    run(
                        [
                            "xcrun",
                            "xcresulttool",
                            "export",
                            "attachments",
                            "--path",
                            str(result_path),
                            "--output-path",
                            str(attachments),
                        ]
                    )
                    exported = json.loads((attachments / "manifest.json").read_text())
                    screens = (
                        ("01-onboarding",)
                        if phase == "Onboarding"
                        else ("02-home", "03-dictionary", "04-account")
                    )
                    for screen in screens:
                        prefix = f"{language}-{screen}"
                        matches = [
                            item
                            for test_case in exported
                            for item in test_case.get("attachments", [])
                            if item.get("suggestedHumanReadableName", "").startswith(
                                prefix + "_"
                            )
                        ]
                        if len(matches) != 1:
                            raise RuntimeError(
                                f"Expected exactly one native screenshot for {prefix}"
                            )
                        filename = matches[0]["exportedFileName"]
                        if Path(filename).name != filename:
                            raise RuntimeError("Unsafe attachment path")
                        source = attachments / filename
                        width, height = png_dimensions(source)
                        if (width, height) != (1206, 2622):
                            raise RuntimeError(
                                f"Unexpected native medium Dynamic Island screenshot dimensions: {width}x{height}"
                            )
                        target = output / "screenshots" / language / (screen + ".png")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)
                        manifest["captures"].append(
                            {
                                "file": str(target.relative_to(output)),
                                "width": width,
                                "height": height,
                                "sha256": digest(target),
                                "nativeAttachmentName": matches[0][
                                    "suggestedHumanReadableName"
                                ],
                            }
                        )
                run(["xcrun", "simctl", "shutdown", device])
            if run(
                [
                    "git",
                    "-C",
                    str(root),
                    "status",
                    "--porcelain",
                    "--untracked-files=no",
                ],
                capture=True,
            ):
                raise RuntimeError("Tracked app source changed during capture")
            if len(manifest["captures"]) != 12:
                raise RuntimeError("Incomplete three-language screenshot set")
            manifest["trackedAppSourceUnchanged"] = True
            manifest["capturedAt"] = datetime.now(timezone.utc).isoformat()
            manifest["result"] = "PASS"
    finally:
        for device in created_devices:
            run(["xcrun", "simctl", "shutdown", device], check=False)
            run(["xcrun", "simctl", "delete", device], check=False)
        (output / "capture-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2)
        )
    print(
        json.dumps(
            {
                "result": "PASS",
                "screenshots": len(manifest["captures"]),
                "output": str(output),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
