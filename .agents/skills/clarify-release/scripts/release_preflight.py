#!/usr/bin/env python3
"""Read-only preflight checks for a Clarify release candidate."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path


REQUIRED_FILES = (
    "CHANGELOG.md",
    "README.md",
    "docs/README.pt-BR.md",
    "docs/architecture.md",
    "docs/development.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "package.json",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-lock-linux.txt",
    "requirements-lock-windows.txt",
    "requirements-lock-runtime-windows.txt",
    "scripts/check_runtime_lock.py",
    "scripts/format_staged.py",
    "scripts/install_bootstrap_tools.py",
    "scripts/add_sbom_component.py",
    "scripts/sox-runtime-manifest.json",
    "version.py",
    "scripts/build.ps1",
    "scripts/build-settings.ps1",
    "scripts/check_settings_payload.py",
    "scripts/qt_distribution.py",
    "scripts/qt_sources.json",
    "docs/qt-distribution.md",
    "scripts/settings_inventory.py",
    "desktop/licenses/manifest.json",
    "desktop/package-lock.json",
    "desktop/src-tauri/Cargo.lock",
    ".github/actions/settings-build/action.yml",
    "docs/release-readiness.md",
    "scripts/build-installer.ps1",
    "scripts/test-installer.ps1",
    "scripts/create_release_manifest.py",
    "scripts/verify-signature.ps1",
    "distribution/update-policy.json",
    "distribution/portable-update-policy.json",
    "portable_updates.py",
    "portable_update_windows.py",
    "scripts/create_portable_update_manifest.py",
    "scripts/test_portable_update.py",
    "scripts/portable_crypto_inventory.py",
    "docs/windows-distribution.md",
    ".githooks/pre-commit",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "scripts/release_candidate.py",
    "tests/policy/test_release_candidate.py",
)

STABLE_REQUIRED_ASSETS = (
    "Clarify-portable-update.json",
    "Clarify-portable-update.json.sig",
    "Clarify-qt-sources.zip",
    "Clarify.exe",
    "Clarify.exe.sha256",
    "Clarify.sbom.json",
    "Clarify-windows-x64.zip",
    "sox-14.4.2-source.tar.gz",
)


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ("git", "-C", str(repo), *args),
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def parse_version(raw: str) -> tuple[str, tuple[int, int, int]]:
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", raw)
    if not match:
        raise ValueError("version must be SemVer X.Y.Z, optionally prefixed by v")
    number = ".".join(match.groups())
    return number, tuple(int(part) for part in match.groups())


def version_consistency_failures(repo: Path, expected: str) -> list[str]:
    """Require release metadata and the packaged module to agree exactly."""
    failures: list[str] = []
    version_source = (repo / "version.py").read_text(encoding="utf-8")
    version_match = re.search(
        r"^__version__\s*=\s*\"([0-9]+\.[0-9]+\.[0-9]+)\"$",
        version_source,
        re.MULTILINE,
    )
    if not version_match or version_match.group(1) != expected:
        failures.append("version.py does not match the proposed release version")

    try:
        package = json.loads((repo / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        failures.append("package.json is not valid JSON")
    else:
        package_version = package.get("version") if isinstance(package, dict) else None
        if package_version != expected:
            failures.append("package.json does not match the proposed release version")
    return failures


def version_tags(repo: Path) -> list[tuple[tuple[int, int, int], str]]:
    tags = git(repo, "tag", "--list", "v*").splitlines()
    parsed = []
    for tag in tags:
        try:
            _, parts = parse_version(tag)
        except ValueError:
            continue
        parsed.append((parts, tag))
    return sorted(parsed)


def workflow_failures(workflow: str) -> list[str]:
    """Check the one portable publisher. This is not native/package acceptance."""
    failures = []
    for required in (
        "workflow_dispatch:",
        "options: [build-candidate, publish-candidate]",
        "default: build-candidate",
        "options: [preview, stable]",
        "preview-build",
        "portable-updates",
        "environment: desktop-publication",
        "vars.CLARIFY_RELEASE_PUBLICATION_ENABLED == 'true'",
        "scripts/release_candidate.py publish",
        "scripts/release_candidate.py seal",
        "--artifact-id",
        "--artifact-digest",
        "attestations: read",
        "requirements-lock-windows.txt",
        "requirements-lock-runtime-windows.txt",
        "cyclonedx-py requirements requirements-lock-runtime-windows.txt",
        "attest-build-provenance@",
    ):
        if required not in workflow:
            failures.append("portable release workflow is missing: " + required)
    for forbidden in (
        "azure/login@",
        "azure/artifact-signing-action@",
        "build-installer.ps1",
        "create_release_manifest.py",
        "release-manifest.cab",
        "  push:",
        "  schedule:",
        "gh release create",
        "--clobber",
    ):
        if forbidden in workflow:
            failures.append(
                "portable release workflow must not reference: " + forbidden
            )
    build = workflow.split("  build_candidate:", 1)[-1].split(
        "  publish_candidate:", 1
    )[0]
    publish = workflow.split("  publish_candidate:", 1)[-1]
    if "contents: write" in build:
        failures.append("candidate build must have no release-write permission")
    if any(
        token in publish
        for token in (
            "pip install",
            "npm ci",
            "build.ps1",
            "CLARIFY_UPDATE_SIGNING_KEY",
        )
    ):
        failures.append(
            "publication must reuse candidate bytes without installation, packaging or signing"
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=("stable", "preview"), default="stable")
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()

    repo = args.repo.resolve()
    version, version_parts = parse_version(args.version)
    tag = f"v{version}"
    failures: list[str] = []

    if not (repo / ".git").exists():
        failures.append(f"not a Git repository: {repo}")

    required_files = list(REQUIRED_FILES)
    missing = [path for path in required_files if not (repo / path).is_file()]
    if missing:
        failures.append("missing required files: " + ", ".join(missing))

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    failures.extend(version_consistency_failures(repo, version))

    tags = version_tags(repo)
    previous = [item for item in tags if item[0] < version_parts]
    previous_tag = previous[-1][1] if previous else None
    owner_url = "https://github.com/jvictormaynard/clarify"
    if args.channel == "stable":
        if tag in {existing_tag for _, existing_tag in tags}:
            failures.append(f"tag already exists: {tag}")
        if previous_tag is None:
            failures.append("no previous SemVer tag found")
        changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
        heading_pattern = rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$"
        if not re.search(heading_pattern, changelog, re.MULTILINE):
            failures.append(f"CHANGELOG.md has no dated [{version}] section")
        if f"[Unreleased]: {owner_url}/compare/{tag}...HEAD" not in changelog:
            failures.append("Unreleased comparison does not start at the new tag")
        if (
            previous_tag
            and f"[{version}]: {owner_url}/compare/{previous_tag}...{tag}"
            not in changelog
        ):
            failures.append("version comparison link is missing or incorrect")

    release_workflow = (repo / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )
    failures.extend(workflow_failures(release_workflow))

    readme = (repo / "README.md").read_text(encoding="utf-8")
    readme_pt = (repo / "docs/README.pt-BR.md").read_text(encoding="utf-8")
    latest_url = f"{owner_url}/releases/latest"
    if latest_url not in readme or latest_url not in readme_pt:
        failures.append("English and Portuguese READMEs must link to releases/latest")

    if args.require_clean and git(repo, "status", "--porcelain"):
        failures.append("worktree is not clean")

    current_branch = git(repo, "branch", "--show-current")
    head = git(repo, "rev-parse", "--short=12", "HEAD")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print(f"OK: Clarify {tag} {args.channel} release preflight passed")
    print(f"Repository: {repo}")
    print(f"Branch: {current_branch}")
    print(f"HEAD: {head}")
    print(f"Previous tag: {previous_tag}")
    print(f"Checked on: {date.today().isoformat()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
