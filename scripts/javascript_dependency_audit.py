#!/usr/bin/env python3
"""Apply expiring, version-scoped policy to npm audit's advisory graph."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LEVELS = {"info": 0, "low": 1, "moderate": 2, "high": 3, "critical": 4}


def evaluate(payload, lock, policy, component, now):
    """Return unapproved high findings and the exceptions actually applied."""
    if policy.get("policy_version") != 1:
        raise ValueError("Unsupported audit policy version")
    if payload.get("auditReportVersion") != 2 or "error" in payload:
        raise ValueError("npm audit failed or returned an unsupported report")
    findings = payload.get("vulnerabilities")
    if not isinstance(findings, dict):
        raise ValueError("npm audit report lacks vulnerability entries")
    exceptions = policy.get("javascript_exceptions", {})
    if not isinstance(exceptions, dict):
        raise ValueError("Invalid JavaScript exceptions")
    roots, edges, approved, applied = {}, {}, set(), set()
    for name, finding in findings.items():
        if (
            finding.get("severity") not in LEVELS
            or not isinstance(finding.get("via"), list)
            or not finding["via"]
        ):
            raise ValueError(f"Invalid advisory entry: {name}")
        roots[name], edges[name] = set(), set()
        for advisory in finding["via"]:
            if isinstance(advisory, str):
                if advisory not in findings:
                    raise ValueError(f"Missing advisory dependency: {advisory}")
                edges[name].add(advisory)
                continue
            if not isinstance(advisory, dict) or advisory.get("severity") not in LEVELS:
                raise ValueError(f"Invalid advisory for {name}")
            url = advisory.get("url")
            if not isinstance(url, str) or not url:
                raise ValueError(f"Missing advisory URL for {name}")
            if LEVELS[advisory["severity"]] < LEVELS["high"]:
                continue
            identity = (name, url)
            roots[name].add(identity)
            exception = exceptions.get(url, {})
            versions = exception.get("versions", {}).get(component)
            if not versions:
                continue
            expiry = datetime.fromisoformat(
                exception["expires_utc"].replace("Z", "+00:00")
            )
            if (
                expiry.tzinfo is None
                or not exception.get("rationale")
                or not exception.get("approved_by")
            ):
                raise ValueError("Exception requires expiry, rationale and approver")
            if now >= expiry or exception.get("package") != name:
                continue
            nodes = finding.get("nodes")
            if not isinstance(nodes, list) or not nodes:
                raise ValueError(f"Missing installed paths for {name}")
            packages = lock["packages"]
            if all(
                node in packages and packages[node].get("version") in versions
                for node in nodes
            ):
                approved.add(identity)
                applied.add(url)
    # Union to a fixed point: npm's parent graph can contain cycles (Expo/Metro).
    while True:
        changed = False
        for name, dependencies in edges.items():
            combined = roots[name].union(*(roots[dep] for dep in dependencies))
            if combined != roots[name]:
                roots[name] = combined
                changed = True
        if not changed:
            break
    blocked = []
    for name, finding in findings.items():
        if LEVELS[finding["severity"]] >= LEVELS["high"]:
            if not roots[name] or roots[name] - approved:
                blocked.append(name)
    return sorted(blocked), sorted(applied)


def _npm_command():
    npm = shutil.which("npm")
    if not npm:
        raise ValueError("npm is unavailable")
    # Match the CI runner: Windows cannot execute npm.cmd via CreateProcess.
    cli = Path(npm).resolve().parent / "node_modules/npm/bin/npm-cli.js"
    if cli.is_file():
        node = shutil.which("node")
        if not node:
            raise ValueError("Node is unavailable")
        return [node, str(cli)]
    if sys.platform == "win32":
        raise ValueError("Node and its npm CLI must be installed")
    return [npm]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--component", choices=("ci", "desktop", "mobile"), required=True
    )
    args = parser.parse_args()
    try:
        result = subprocess.run(
            [*_npm_command(), "audit", "--include=dev", "--audit-level=high", "--json"],
            cwd=ROOT / args.component,
            capture_output=True,
            text=True,
            timeout=300,
        )
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode not in (0, 1):
            return result.returncode
        payload = json.loads(result.stdout)
        blocked, applied = evaluate(
            payload,
            json.loads(
                (ROOT / args.component / "package-lock.json").read_text(
                    encoding="utf-8"
                )
            ),
            json.loads((ROOT / "dependency-audit.json").read_text(encoding="utf-8")),
            args.component,
            datetime.now(timezone.utc),
        )
        # A failure without any advisory entries is a registry/tool error.
        if result.returncode and not payload["vulnerabilities"]:
            raise ValueError("npm audit failed without advisory entries")
        for url in applied:
            print(f"Applied approved temporary exception: {url}")
        if blocked:
            print(
                f"Unapproved high/critical findings: {', '.join(blocked)}",
                file=sys.stderr,
            )
            return 1
        print("No unapproved high/critical JavaScript findings.")
        return 0
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"JavaScript audit failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
