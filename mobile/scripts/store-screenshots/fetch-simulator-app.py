"""Read a previous capture artifact; never build, sign or upload an app."""

import argparse
import json
import subprocess
import time
from pathlib import Path

REPO = "jvictormaynard/clarify"
SOURCE = "542b8a742634183bf7fb857305674968e96f559b"


def read(arguments):
    response = subprocess.run(["gh", *arguments], capture_output=True, text=True)
    if response.returncode:
        raise RuntimeError("Read-only GitHub request failed")
    return json.loads(response.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.run.isascii() or not args.run.isdigit():
        raise RuntimeError("Expected numeric previous run ID")
    args.output.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic() + 15 * 60
    while time.monotonic() < deadline:
        run = read(["api", f"repos/{REPO}/actions/runs/{args.run}"])
        if (
            run["name"] != "iOS store screenshots"
            or run["head_branch"] != "codex/ios-store-screenshots-20261016"
        ):
            raise RuntimeError("Unexpected simulator capture workflow")
        artifacts = read(["api", f"repos/{REPO}/actions/runs/{args.run}/artifacts"])[
            "artifacts"
        ]
        matches = [
            item
            for item in artifacts
            if item["name"].startswith("clarify-store-screenshots-" + SOURCE + "-")
            and not item["expired"]
        ]
        if len(matches) == 1:
            artifact = matches[0]
            if artifact["size_in_bytes"] > 512 * 1024 * 1024:
                raise RuntimeError(
                    "Previous simulator artifact exceeds the capture download limit"
                )
            response = subprocess.run(
                [
                    "gh",
                    "run",
                    "download",
                    args.run,
                    "--repo",
                    REPO,
                    "--name",
                    artifact["name"],
                    "--dir",
                    str(args.output),
                ],
                capture_output=True,
            )
            if response.returncode:
                raise RuntimeError("Simulator app artifact download failed")
            print(
                json.dumps(
                    {
                        "reusedRun": args.run,
                        "artifactId": artifact["id"],
                        "artifactName": artifact["name"],
                    }
                )
            )
            return
        if run["status"] == "completed":
            raise RuntimeError(
                "Previous capture completed without one reusable simulator artifact"
            )
        print(
            "Waiting for the first capture run to preserve its compiled simulator app",
            flush=True,
        )
        time.sleep(45)
    raise RuntimeError(
        "Previous simulator artifact did not become available within 15 minutes"
    )


if __name__ == "__main__":
    main()
