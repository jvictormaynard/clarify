"""Tiny frozen Windows fixture. No profile, Qt UI, audio, or global hotkeys."""

import json
import os
from pathlib import Path
import sys
import time

from fixture_version import VERSION
from portable_update_windows import (
    acknowledge_portable_update,
    prepare_portable_update,
    run_portable_update_helper,
)
from portable_updates import (
    MANIFEST_ASSET,
    SIGNATURE_ASSET,
    load_policy,
    verify_manifest,
)


def main():
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--apply-portable-update":
        return run_portable_update_helper(Path(args[1]), VERSION)
    marker = Path(os.environ["CLARIFY_FIXTURE_MARKERS"])
    if len(args) == 2 and args[0] == "--fixture-start":
        directory = Path(args[1])
        release = verify_manifest(
            (directory / MANIFEST_ASSET).read_bytes(),
            (directory / SIGNATURE_ASSET).read_bytes(),
            load_policy(),
            VERSION,
        )
        try:
            prepared = prepare_portable_update(
                release, directory / "Clarify.exe", VERSION
            )
            deadline = time.monotonic() + 30
            while not prepared.armed():
                if prepared.process.poll() is not None or time.monotonic() > deadline:
                    prepared.cancel()
                    raise RuntimeError("Helper did not arm")
                time.sleep(0.05)
        except Exception:
            (marker / "rejected.json").write_text(json.dumps({"version": VERSION}))
            return 3
        (marker / "parent-exit.json").write_text(json.dumps({"version": VERSION}))
        if os.environ.get("CLARIFY_FIXTURE_CANCEL_RETRY") == "1":
            prepared.cancel()
            prepared = prepare_portable_update(
                release, directory / "Clarify.exe", VERSION
            )
            deadline = time.monotonic() + 30
            while not prepared.armed():
                if prepared.process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Retry helper did not arm")
                time.sleep(0.05)
        (marker / "apply-directory.json").write_text(
            json.dumps({"path": str(prepared.directory)})
        )
        return 0
    if VERSION == "0.5.1" and os.environ.get("CLARIFY_FIXTURE_STARTUP_FAILURE") == "1":
        return 31
    acknowledge_portable_update(VERSION)
    (marker / ("started-" + VERSION + ".json")).write_text(
        json.dumps({"version": VERSION, "pid": os.getpid()})
    )
    deadline = time.monotonic() + 60
    while not (marker / "stop").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
