"""Plan and execute bounded validation without publication or hidden skipped gates."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from ci import evidence, impact
from ci.tasks import JOBS, ROOT, commands
from scripts.run_tests import isolated_environment

TEMP_PATH = "{validation-temp}"


def git(repo, *arguments):
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout


def build_plan(repo, base="origin/main", full=False, quick=False):
    repo = Path(repo).resolve()
    try:
        head = git(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        base_sha = (
            git(repo, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}")
            .decode()
            .strip()
        )
        merge_base = git(repo, "merge-base", base_sha, head).decode().strip()
        paths = set(impact.changed_paths(repo, merge_base, head))
        for args in (
            ("diff", "--cached", "--no-renames", "--name-only", "-z", head, "--"),
            ("diff", "--no-renames", "--name-only", "-z", "--"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        ):
            paths.update(os.fsdecode(p) for p in git(repo, *args).split(b"\0") if p)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(
            "Cannot resolve the validation range or working tree"
        ) from error
    try:
        full = full or impact.git_links(repo, (merge_base, head), paths, index=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Cannot inspect validation input modes") from error
    if full:
        jobs = set(JOBS)
    elif impact.RELEASE_INTENT in paths or "version.py" in paths:
        try:
            jobs = impact.select_candidate(paths, repo)
        except (OSError, ValueError, subprocess.SubprocessError):
            jobs = set(JOBS)
    else:
        jobs = impact.select_jobs(paths, repo=repo)
    checks = [
        {
            "id": "diff",
            "component": "policy",
            "argv": ["git", "diff", "--check", head, "--"],
            "cwd": str(repo),
        },
        {
            "id": "staged-diff",
            "component": "policy",
            "argv": ["git", "diff", "--cached", "--check", head, "--"],
            "cwd": str(repo),
        },
    ]
    if quick:
        from ci.quick import checks as quick_checks

        checks.extend(quick_checks(repo, paths, jobs))
    else:
        checks.extend(commands("policy", repo))
        checks.extend(
            check for job in JOBS if job in jobs for check in commands(job, repo)
        )
    for platform in ("Windows" if os.name != "nt" else "Linux",):
        if not quick and jobs & {"python", "qt"}:
            checks.append(
                {
                    "id": "python-other-platform",
                    "component": "python",
                    "reason": f"The CI matrix also requires {platform}.",
                }
            )
    return {
        "schema": 2,
        "repo": str(repo),
        "base_ref": base,
        "base": base_sha,
        "merge_base": merge_base,
        "head": head,
        "paths": sorted(paths),
        "full": full,
        "mode": "quick" if quick else ("full" if full else "affected"),
        "ci_required": ["policy", *sorted(jobs)],
        "reasons": impact.explain(paths, jobs, repo),
        "components": {job: job in jobs for job in JOBS},
        "checks": checks,
    }


def stop_process(process):
    """Stop descendants as well as the command when its time limit expires."""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        if process.poll() is None:
            process.kill()
    else:
        # Let wrapper signal handlers close their owned child groups first.
        # A direct SIGKILL would bypass those handlers on POSIX.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        else:
            time.sleep(2)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


def run_plan(plan, timeout=3600, check_timeout=1800):
    deadline = time.monotonic() + timeout
    results = []
    cancelled = False
    # Browser downloads belong to the tool cache, outside the isolated app profile.
    browser_cache = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if browser_cache is None:
        if sys.platform == "win32":
            cache = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        elif sys.platform == "darwin":
            cache = Path.home() / "Library/Caches"
        else:
            cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        browser_cache = str(cache / "ms-playwright")
    with isolated_environment() as temporary:
        environment = dict(os.environ)
        environment.update(
            CLARIFY_TEST_PYTHON=sys.executable,
            CLARIFY_TEST_FIXTURE=str(ROOT / "tests/web_settings_fixture.py"),
            CLARIFY_TEST_BROWSER="chromium",
            PLAYWRIGHT_BROWSERS_PATH=browser_cache,
            EXPO_NO_DOTENV="1",
            EXPO_NO_TELEMETRY="1",
            CI="1",
        )
        # Each nested test runner owns its own report; never inherit an outer path.
        environment.pop("CLARIFY_TEST_DURATIONS_JSON", None)
        environment.pop("CLARIFY_TEST_DURATIONS_UNIT", None)
        for check in plan["checks"]:
            result = {"id": check["id"], "component": check["component"]}
            results.append(result)
            reason = check.get("reason")
            remaining = deadline - time.monotonic()
            if cancelled or remaining <= 0:
                reason = (
                    reason
                    or "The validation run was cancelled or its total time limit expired."
                )
            if not reason and check["component"] in {
                "settings_unit",
                "settings_browser",
                "desktop_shell",
                "mobile",
            }:
                if any(
                    p.name != ".env.example" for p in Path(check["cwd"]).glob(".env*")
                ):
                    reason = "Local dotenv files prevent isolated frontend validation."
            if reason:
                result.update(status="unexecuted", reason=reason)
                continue
            started = time.monotonic()
            process = None
            try:
                argv = [
                    str(arg).replace(TEMP_PATH, str(temporary)) for arg in check["argv"]
                ]
                print(f"Running {check['id']}", file=sys.stderr, flush=True)
                check_env = dict(environment)
                duration_dir = None
                if plan.get("task"):
                    duration_dir = os.environ.get("CLARIFY_CI_DURATIONS_DIR")
                    if not duration_dir and os.environ.get("GITHUB_ACTIONS") == "true":
                        duration_dir = str(
                            Path(os.environ["RUNNER_TEMP"]) / "durations"
                        )
                if duration_dir and "scripts/run_tests.py" in argv:
                    check_env["CLARIFY_TEST_DURATIONS_JSON"] = str(
                        Path(duration_dir) / (check["id"] + ".json")
                    )
                    check_env["CLARIFY_TEST_DURATIONS_UNIT"] = "test"
                if (
                    plan.get("task") == "qt"
                    and os.environ.get("GITHUB_ACTIONS") == "true"
                ):
                    check_env["CLARIFY_TEST_ARTIFACTS_DIR"] = str(
                        Path(os.environ["RUNNER_TEMP"]) / "qt-artifacts"
                    )
                process = subprocess.Popen(
                    argv,
                    cwd=check["cwd"],
                    env=check_env,
                    # Unittest -b replaces sys.stderr with a buffer without fileno.
                    stdout=sys.__stderr__,
                    stderr=sys.__stderr__,
                    start_new_session=os.name != "nt",
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    if os.name == "nt"
                    else 0,
                )
                code = process.wait(timeout=min(check_timeout, remaining))
                result.update(
                    status="passed" if code == 0 else "failed", returncode=code
                )
            except OSError as error:
                result.update(status="unexecuted", reason=str(error))
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                if process is not None:
                    try:
                        stop_process(process)
                    except (OSError, subprocess.SubprocessError) as cleanup_error:
                        result["reason"] = f"Process cleanup failed: {cleanup_error}"
                cancelled = isinstance(error, KeyboardInterrupt)
                result.update(status="cancelled" if cancelled else "timed_out")
            result["duration_seconds"] = time.monotonic() - started
    states = {result["status"] for result in results}
    status = (
        "failed"
        if states & {"failed", "cancelled", "timed_out"}
        else ("incomplete" if "unexecuted" in states else "passed")
    )
    report = {"schema": 1, "status": status, "plan": plan, "results": results}
    if plan.get("mode") == "quick":
        report.update(
            scope="quick", ci_status="unverified", ci_required=plan["ci_required"]
        )
    return report


def positive_seconds(value):
    import math

    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError(
            "Time limits must be finite and greater than zero"
        )
    return seconds


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--github-plan", action="store_true")
    mode.add_argument("--check-results", action="store_true")
    mode.add_argument("--emit-proof", metavar="PATH")
    mode.add_argument("--task", choices=("policy", *JOBS))
    mode.add_argument("--list-tasks", action="store_true")
    mode.add_argument(
        "--quick",
        action="store_true",
        help="Run bounded local checks; CI obligations remain open",
    )
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--shard")
    parser.add_argument("--timeout", type=positive_seconds)
    parser.add_argument("--check-timeout", type=positive_seconds)
    args = parser.parse_args(arguments)
    if args.quick and args.full:
        parser.error("--quick cannot be combined with --full")
    if args.shard and args.task != "python":
        parser.error("--shard requires --task python")
    try:
        if args.list_tasks:
            print(json.dumps(["policy", *JOBS]))
            return 0
        if args.check_results or args.emit_proof:
            needs = json.loads(
                os.environ["CI_NEEDS"], object_pairs_hook=impact.json_object
            )
            event = json.loads(
                Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
            )
            head = git(ROOT, "rev-parse", "HEAD").decode().strip()
            if head != os.environ["GITHUB_SHA"]:
                raise ValueError("The checked-out source does not match the CI event")
            if args.emit_proof:
                evidence.emit(ROOT, os.environ, event, needs, args.emit_proof)
            else:
                expected = impact.event_jobs(
                    ROOT, os.environ["GITHUB_EVENT_NAME"], event, head
                )
                evidence.validate(ROOT, head, expected, needs, os.environ)
            print("All selected CI jobs passed")
            return 0
        if args.github_plan:
            event = json.loads(
                Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
            )
            head = git(ROOT, "rev-parse", "HEAD").decode().strip()
            if head != os.environ["GITHUB_SHA"]:
                raise ValueError("The checked-out source does not match the CI event")
            selection = impact.event_selection(
                ROOT, os.environ["GITHUB_EVENT_NAME"], event, head
            )
            jobs = set(selection["jobs"])
            jobs, reuse = evidence.plan(ROOT, head, jobs, os.environ)
            runners = impact.runner_profile(
                os.environ.get("CI_RUNNER_PROVIDER", "github"),
                event.get("repository", {}).get("owner", {}).get("type", "User"),
            )
            outputs = {
                **{job: str(job in jobs).lower() for job in JOBS},
                **runners,
                "reuse": reuse,
            }
            with Path(os.environ["GITHUB_OUTPUT"]).open(
                "a", encoding="utf-8"
            ) as output:
                output.writelines(f"{key}={value}\n" for key, value in outputs.items())
            if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
                lines = [
                    "## Validation plan",
                    "",
                    selection["reason"],
                    "",
                    "| Task | Decision | Changed inputs |",
                    "| --- | --- | --- |",
                ]
                for job in JOBS:
                    decision = (
                        "run"
                        if job in jobs
                        else (
                            "verified PR coverage"
                            if job in selection["jobs"]
                            else "not affected"
                        )
                    )
                    inputs = [
                        p.replace("|", "\\|").replace("`", "")
                        for p in selection["reasons"].get(job, [])
                    ]
                    label = ", ".join(inputs[:3]) + (
                        f" (+{len(inputs) - 3})" if len(inputs) > 3 else ""
                    )
                    lines.append(f"| {job} | {decision} | {label} |")
                with Path(summary).open("a", encoding="utf-8") as stream:
                    stream.write("\n".join(lines) + "\n")
            print(
                json.dumps(
                    {
                        "head": head,
                        "jobs": sorted(jobs),
                        "runners": runners,
                        "reuse": reuse,
                        "selection": selection,
                    }
                )
            )
            return 0
        if args.task:
            checks = commands(args.task)
            if args.shard:
                for check in checks:
                    check["argv"].extend(["--shard", args.shard])
            plan = {"schema": 2, "task": args.task, "checks": checks}
        else:
            plan = build_plan(ROOT, base=args.base, full=args.full, quick=args.quick)
        if args.plan:
            print(json.dumps(plan, indent=2))
            return 0
        report = run_plan(
            plan,
            timeout=args.timeout or (300 if args.quick else 3600),
            check_timeout=args.check_timeout or (120 if args.quick else 1800),
        )
        if args.quick:
            print(
                json.dumps(
                    {
                        "scope": "quick",
                        "status": report["status"],
                        "ci_status": "unverified",
                        "checks": report["results"],
                        "ci_required": plan["ci_required"],
                    },
                    indent=2,
                )
            )
        else:
            print(json.dumps(report, indent=2))
        return {"passed": 0, "failed": 1, "incomplete": 2}[report["status"]]
    except (KeyError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1
