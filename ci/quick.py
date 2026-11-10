"""Bounded local feedback. Complete affected validation remains a CI obligation."""

from pathlib import Path
import sys

from ci.tasks import commands


def checks(repo, paths, jobs):
    repo = Path(repo)
    paths = set(paths)
    result = []

    def run(name, argv, cwd=repo):
        result.append({"id": name, "component": "quick", "argv": argv, "cwd": str(cwd)})

    python = sorted(p for p in paths if p.endswith(".py") and (repo / p).is_file())
    if python:
        run(
            "changed-python-lint",
            [sys.executable, "-m", "ruff", "check", "--force-exclude", "--", *python],
        )
        run(
            "changed-python-format",
            [
                sys.executable,
                "-m",
                "ruff",
                "format",
                "--check",
                "--force-exclude",
                "--",
                *python,
            ],
        )
    if paths & {"desktop_state.py", "windows_hotkeys.py", "pyproject.toml"}:
        run("types", [sys.executable, "-m", "mypy"])

    tests = {
        p
        for p in paths
        if p.startswith(("tests/unit/", "tests/policy/"))
        and Path(p).name.startswith("test_")
        and p.endswith(".py")
        and (repo / p).is_file()
    }
    # Test ownership stays with the existing suites; do not import tests to discover them.
    stems = {Path(p).stem for p in python if not p.startswith("tests/")}
    for suite in ("unit", "policy"):
        for stem in stems:
            path = f"tests/{suite}/test_{stem}.py"
            if (repo / path).is_file():
                tests.add(path)
    controls = {
        "ci/impact.py": ("test_delivery_policy", "test_ci_evidence"),
        "ci/evidence.py": ("test_ci_evidence",),
        "ci/tasks.py": ("test_delivery_policy", "test_validate"),
        "ci/cli.py": ("test_validate",),
        "ci/quick.py": ("test_validate",),
        "scripts/ci.py": ("test_validate",),
    }
    for path in paths:
        for name in controls.get(path, ()):
            candidate = f"tests/policy/{name}.py"
            if (repo / candidate).is_file():
                tests.add(candidate)
    if tests:
        run(
            "focused-python-tests",
            [
                sys.executable,
                "scripts/run_tests.py",
                *[
                    str(Path(p).with_suffix("")).replace("\\", ".").replace("/", ".")
                    for p in sorted(tests)
                ],
                "-v",
            ],
        )

    if any(
        p == "AGENTS.md" or p.startswith((".agents/", "docs/agents/")) for p in paths
    ):
        run("skills", [sys.executable, "scripts/check_agent_skills.py"])
    if any(
        p.startswith(("ci/", ".github/workflows/", ".github/actions/")) for p in paths
    ):
        run("workflow-contracts", ["node", "--test", "ci/tests/workflows.test.mjs"])

    if "settings_unit" in jobs and any(p.startswith("desktop/") for p in paths):
        result.extend(commands("settings_unit", repo))
    if "desktop_shell" in jobs and any(
        p.startswith(("desktop/electron/", "desktop/electron-tests/")) for p in paths
    ):
        # Host unit tests need Node, not a running Electron application.
        run(
            "electron-host-units",
            ["node", "--test", "scripts/electron.test.cjs"],
            repo / "desktop",
        )
    if "mobile" in jobs and any(
        p.startswith(("mobile/", "shared/"))
        and Path(p).suffix in {".ts", ".tsx", ".js", ".jsx", ".json"}
        for p in paths
    ):
        # Reuse the portable npm invocation; do not run the export/native pipeline.
        for check in commands("settings_unit", repo):
            if check["id"] == "desktop-typecheck":
                result.append(
                    {
                        **check,
                        "id": "mobile-typecheck",
                        "component": "quick",
                        "cwd": str(repo / "mobile"),
                    }
                )
    return result
