"""Plan and execute bounded validation without publication or hidden skipped gates."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from ci import impact
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


def build_plan(repo, base="origin/main", full=False):
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
    jobs = impact.select_jobs(paths, repo=repo) if not full else set(JOBS)
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
        *commands("policy", repo),
        *[check for job in JOBS if job in jobs for check in commands(job, repo)],
    ]
    for platform in ("Windows" if os.name != "nt" else "Linux",):
        if jobs & {"python", "qt"}:
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
    return {"schema": 1, "status": status, "plan": plan, "results": results}


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
    mode.add_argument("--task", choices=("policy", *JOBS))
    mode.add_argument("--list-tasks", action="store_true")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--shard")
    parser.add_argument("--timeout", type=positive_seconds, default=3600)
    parser.add_argument("--check-timeout", type=positive_seconds, default=1800)
    args = parser.parse_args(arguments)
    if args.shard and args.task != "python":
        parser.error("--shard requires --task python")
    try:
        if args.list_tasks:
            print(json.dumps(["policy", *JOBS]))
            return 0
        if args.check_results:
            impact.validate_ci_results(
                json.loads(os.environ["CI_NEEDS"], object_pairs_hook=impact.json_object)
            )
            print("All selected CI jobs passed")
            return 0
        if args.github_plan:
            event = json.loads(
                Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
            )
            head = git(ROOT, "rev-parse", "HEAD").decode().strip()
            if head != os.environ["GITHUB_SHA"]:
                raise ValueError("The checked-out source does not match the CI event")
            jobs = impact.event_jobs(ROOT, os.environ["GITHUB_EVENT_NAME"], event, head)
            runners = impact.runner_profile(
                os.environ.get("CI_RUNNER_PROVIDER", "github"),
                event.get("repository", {}).get("owner", {}).get("type", "User"),
            )
            outputs = {**{job: str(job in jobs).lower() for job in JOBS}, **runners}
            with Path(os.environ["GITHUB_OUTPUT"]).open(
                "a", encoding="utf-8"
            ) as output:
                output.writelines(f"{key}={value}\n" for key, value in outputs.items())
            print(json.dumps({"head": head, "jobs": sorted(jobs), "runners": runners}))
            return 0
        if args.task:
            checks = commands(args.task)
            if args.shard:
                for check in checks:
                    check["argv"].extend(["--shard", args.shard])
            plan = {"schema": 2, "task": args.task, "checks": checks}
        else:
            plan = build_plan(ROOT, base=args.base, full=args.full)
        if args.plan:
            print(json.dumps(plan, indent=2))
            return 0
        report = run_plan(plan, timeout=args.timeout, check_timeout=args.check_timeout)
        print(json.dumps(report, indent=2))
        return {"passed": 0, "failed": 1, "incomplete": 2}[report["status"]]
    except (KeyError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1
