"""Component commands shared by local validation and GitHub Actions.

Install the locked dependencies before execution. Commands never publish.
Workflow steps own tool installation, services, artifact transfer and permissions.
"""

import os
from pathlib import Path
import shutil
import sys

JOBS = (
    "static",
    "python",
    "qt",
    "settings_unit",
    "settings_browser",
    "package",
    "installer",
    "server",
    "mobile",
    "ios",
    "audit",
)
STANDARD = set(JOBS) - {"installer"}
ROOT = Path(__file__).resolve().parents[1]


def commands(task, repo=ROOT):
    repo = Path(repo).resolve()
    python = sys.executable
    checks = []

    def run(name, argv, directory="."):
        checks.append(
            {"id": name, "component": task, "argv": argv, "cwd": str(repo / directory)}
        )

    def gate(name, reason):
        checks.append({"id": name, "component": task, "reason": reason})

    def tests(*suites):
        run(
            task + "-tests",
            [
                python,
                "scripts/run_tests.py",
                *[arg for suite in suites for arg in ("--suite", suite)],
                "-v",
            ],
        )

    def npm(script, directory):
        # npm.cmd cannot be executed directly by CreateProcess on Windows.
        # Use the installed npm CLI through Node; all arguments are fixed here.
        node = shutil.which("node") or "node"
        npm_bin = shutil.which("npm")
        cli = (
            Path(npm_bin).resolve().parent / "node_modules/npm/bin/npm-cli.js"
            if npm_bin
            else Path("missing")
        )
        argv = (
            [node, str(cli), "run", script] if cli.is_file() else ["npm", "run", script]
        )
        if os.name == "nt" and not cli.is_file():
            gate(f"{directory}-{script}", "Node and its npm CLI must be installed.")
        else:
            run(f"{directory}-{script}", argv, directory)

    if task == "policy":
        run("skills", [python, "scripts/check_agent_skills.py"])
        run("workflow-contracts", ["node", "--test", "ci/tests/workflows.test.mjs"])
        tests("policy")
    elif task == "static":
        run("lint", [python, "-m", "ruff", "check", "."])
        run("format", [python, "-m", "ruff", "format", "--check", "."])
        run("types", [python, "-m", "mypy"])
        run(
            "compile",
            [
                python,
                "-m",
                "compileall",
                "-q",
                "ci",
                "scripts",
                "clarify",
                "tests",
                *sorted(p.name for p in repo.glob("*.py")),
            ],
        )
    elif task == "python":
        tests("unit", "contract", "integration")
    elif task == "qt":
        # Retained prototype adapters include real Qt subprocesses.
        tests("qt", "compatibility")
        if os.name == "nt":
            run(
                "windows-tests",
                [python, "scripts/run_tests.py", "--suite", "windows", "-v"],
            )
    elif task == "settings_unit":
        npm("typecheck", "desktop")
        npm("test:unit", "desktop")
    elif task == "settings_browser":
        if sys.platform not in {"win32", "linux"}:
            gate(
                "browser-process-owner",
                "Browser process supervision requires Linux or Windows.",
            )
            return checks
        npm("build", "desktop")
        npm("test:boot", "desktop")
        npm("test:browser", "desktop")
    elif task == "mobile":
        npm("check", "mobile")
        run(
            "mobile-bundle",
            [
                "node",
                "node_modules/expo/bin/cli",
                "export",
                "--platform",
                "ios",
                "--max-workers",
                "2",
                "--output-dir",
                "{validation-temp}/mobile-export",
            ],
            "mobile",
        )
    elif task == "server":
        run("server-prompts", [python, "mobile/scripts/sync-prompts.py", "--check"])
        gate(
            "server-database-container",
            "Run server-validation.yml with disposable PostgreSQL and Docker.",
        )
    elif task == "ios":
        gate(
            "ios-native",
            "Run ios-validation.yml on macOS with Xcode and the required simulator.",
        )
    elif task == "package":
        gate(
            "windows-package",
            "Run the Windows package job: native Settings, EXE, payload, startup, recovery and inventory.",
        )
    elif task == "installer":
        gate(
            "installer",
            "Run installer lifecycle checks on a disposable GitHub-hosted Windows runner.",
        )
    elif task == "audit":
        gate(
            "audits",
            "Run dependency-audit.yml with network vulnerability databases on both platforms.",
        )
    else:
        raise ValueError(f"Unknown validation task: {task}")
    return checks
