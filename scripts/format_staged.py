#!/usr/bin/env python3
"""Format staged Python files before a commit without staging unrelated edits."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=REPO_ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


def staged_python_files() -> list[str]:
    result = run_git(
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
    )
    return [
        os.fsdecode(path)
        for path in result.stdout.encode().split(b"\0")
        if path.endswith(b".py")
    ]


def unstaged_files(paths: list[str]) -> list[str]:
    if not paths:
        return []
    result = run_git("diff", "--name-only", "--", *paths)
    return result.stdout.splitlines()


def ruff_command() -> list[str] | None:
    for executable in ("ruff", "ruff.exe"):
        resolved = shutil.which(executable)
        if resolved:
            return [resolved]

    candidates = (
        REPO_ROOT / ".venv" / "bin" / "ruff",
        REPO_ROOT / ".venv" / "Scripts" / "ruff.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return [str(candidate)]

    for python_executable in (sys.executable, "python3", "python"):
        probe = subprocess.run(
            (python_executable, "-m", "ruff", "--version"),
            cwd=REPO_ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode == 0:
            return [python_executable, "-m", "ruff"]
    return None


def main() -> int:
    paths = staged_python_files()
    if not paths:
        return 0

    conflicting = unstaged_files(paths)
    if conflicting:
        print(
            "Clarify pre-commit: stage the complete file before formatting "
            "it automatically:",
            file=sys.stderr,
        )
        for path in conflicting:
            print(f"  {path}", file=sys.stderr)
        return 1

    command = ruff_command()
    if command is None:
        print(
            "Clarify pre-commit: Ruff was not found. Run npm run setup "
            "or install the locked development dependencies.",
            file=sys.stderr,
        )
        return 1

    result = subprocess.run(
        (*command, "format", "--force-exclude", "--", *paths),
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        return result.returncode

    run_git("add", "--", *paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
