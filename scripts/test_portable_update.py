"""Exercise the production Windows replacement helper with two frozen fixtures.

The generated key is for these temporary fixtures only. All binaries, profiles,
receipts and process launches remain in an isolated temporary directory.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from portable_updates import PortableUpdatePolicy, file_sha256  # noqa: E402
from scripts.create_portable_update_manifest import create_manifest  # noqa: E402


def wait_until(predicate, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("Frozen update fixture timed out")


def build_fixture(root, version, public_key):
    stage = root / ("fixture-" + version)
    stage.mkdir()
    for module in ("portable_updates.py", "portable_update_windows.py"):
        shutil.copyfile(REPO / module, stage / module)
    shutil.copyfile(REPO / "tests" / "portable_update_fixture.py", stage / "entry.py")
    (stage / "fixture_version.py").write_text(
        f"VERSION = {version!r}\n", encoding="utf-8"
    )
    policy = stage / "distribution"
    policy.mkdir()
    (policy / "portable-update-policy.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repository": "jvictormaynard/clarify",
                "channel": "stable",
                "algorithm": "Ed25519",
                "public_key": base64.b64encode(public_key).decode("ascii"),
                "maximum_download_bytes": 268435456,
            }
        ),
        encoding="utf-8",
    )
    with (stage / "build.log").open("w", encoding="utf-8") as log:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--onefile",
                "--windowed",
                "--name",
                "ClarifyFixture",
                "--add-data",
                "distribution;distribution",
                "entry.py",
            ],
            cwd=stage,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=180,
        )
    print("Built isolated Windows fixture", version, flush=True)
    return stage / "dist" / "ClarifyFixture.exe"


def scenario(
    root,
    old_binary,
    new_binary,
    key,
    name,
    startup_failure=False,
    tamper=False,
    cancel_retry=False,
):
    case = root / name
    install = case / "install"
    cache = case / "local-appdata" / "Clarify" / "updates" / ("update-" + name)
    markers = case / "markers"
    for directory in (install, cache, markers):
        directory.mkdir(parents=True)
    target = install / "Clarify.exe"
    shutil.copyfile(old_binary, target)
    shutil.copyfile(new_binary, cache / "Clarify.exe")
    policy = PortableUpdatePolicy(key.public_key().public_bytes_raw())
    create_manifest(cache, "0.5.1", "a" * 40, key.private_bytes_raw(), policy)
    if tamper:
        with (cache / "Clarify.exe").open("ab") as stream:
            stream.write(b"corruption")
    environment = os.environ.copy()
    environment.update(
        LOCALAPPDATA=str(case / "local-appdata"),
        CLARIFY_FIXTURE_MARKERS=str(markers),
        CLARIFY_FIXTURE_STARTUP_FAILURE="1" if startup_failure else "0",
        CLARIFY_FIXTURE_CANCEL_RETRY="1" if cancel_retry else "0",
        PYINSTALLER_RESET_ENVIRONMENT="1",
    )
    process = subprocess.Popen(
        [str(target), "--fixture-start", str(cache)],
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
    try:
        if tamper:
            wait_until(lambda: (markers / "rejected.json").is_file())
            assert file_sha256(target) == file_sha256(old_binary), (
                "Tampered update changed the installed binary"
            )
            assert not (cache / "armed.json").exists(), "Tampered update armed a helper"
        else:
            wait_until(lambda: (markers / "apply-directory.json").is_file())
            original_cache = cache
            cache = Path(
                json.loads((markers / "apply-directory.json").read_text("utf-8"))[
                    "path"
                ]
            )
            if cancel_retry:
                assert cache != original_cache, (
                    "Retry reused a cancelled helper's state"
                )
            wait_until(lambda: (cache / "result.json").is_file())
            result = json.loads((cache / "result.json").read_text("utf-8"))
            expected = "failed" if startup_failure else "success"
            assert result["status"] == expected, result
            version = "0.5.0" if startup_failure else "0.5.1"
            wait_until(lambda: (markers / ("started-" + version + ".json")).is_file())
            assert file_sha256(target) == file_sha256(
                old_binary if startup_failure else new_binary
            )
            if startup_failure:
                failure = json.loads(
                    (cache.parent / "failed-version.json").read_text("utf-8")
                )
                assert failure["version"] == "0.5.1", failure
            else:
                backups = list(install.glob("Clarify.exe.previous-*"))
                assert len(backups) == 1 and file_sha256(backups[0]) == file_sha256(
                    old_binary
                )
                assert (cache / "ready.json").is_file()
        print("PASS frozen Windows update:", name, flush=True)
    finally:
        (markers / "stop").touch()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=15,
            )
        # Give only our detached helper/new child time to close their file handles.
        time.sleep(2)


def main():
    if sys.platform != "win32":
        raise SystemExit("Frozen portable update acceptance requires Windows.")
    # Keep failed evidence for inspection. Remove no user-owned directories.
    root = Path(tempfile.mkdtemp(prefix="clarify-portable-acceptance-"))
    print("Isolated update evidence:", root, flush=True)
    key = Ed25519PrivateKey.generate()
    old_binary = build_fixture(root, "0.5.0", key.public_key().public_bytes_raw())
    new_binary = build_fixture(root, "0.5.1", key.public_key().public_bytes_raw())
    scenario(root, old_binary, new_binary, key, "success")
    scenario(root, old_binary, new_binary, key, "cancel-and-retry", cancel_retry=True)
    scenario(root, old_binary, new_binary, key, "startup-failure", startup_failure=True)
    scenario(root, old_binary, new_binary, key, "tampered-binary", tamper=True)
    print("All frozen Windows portable update checks passed.", flush=True)


if __name__ == "__main__":
    main()
