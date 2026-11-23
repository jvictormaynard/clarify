"""Read one canonical CI run and its current attempt without fetching logs."""

from datetime import datetime, timezone

from ci import evidence

# These labels describe named work, not the reason for a failure. Mixed steps
# and arbitrary shell commands remain unclassified.
NATIVE_TESTS = {
    "Test Swift contracts",
    "Test native keyboard and library integration",
    "Test installed keyboard typing and activation",
    "Test the containing app on an isolated simulator service",
    "Smoke-test packaged QML entrypoint",
    "Smoke-test release Electron package",
}
BUILDS = {
    "Compile app and extensions without signing or upload",
    "Build portable executable",
    "Build baseline and current installers",
    "Build installer baseline only when required",
    "Type-check and build frontend",
    "Build Electron shell and dependency inventory",
}


def phases(name):
    if name in NATIVE_TESTS:
        return ["native", "test"]
    if name in BUILDS:
        return ["build"]
    if name == "Set up job" or name.startswith(
        ("Set up ", "Install ", "Run actions/setup-", "Run actions/checkout@")
    ):
        return ["setup"]
    if name.startswith(("Test ", "Smoke-test ")):
        return ["test"]
    return []


def timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.year <= 1970:
        return None
    return parsed


def seconds(start, end):
    if start is None or end is None or end < start:
        return None
    return (end - start).total_seconds()


def timing(item, now, *, job=False):
    status, conclusion = item.get("status"), item.get("conclusion")
    # Skipped jobs can contain placeholder timestamps. They did not execute.
    started = (
        timestamp(item.get("started_at"))
        if status in {"in_progress", "completed"} and conclusion != "skipped"
        else None
    )
    completed = timestamp(item.get("completed_at"))
    running = status == "in_progress"
    result = {
        "execution_duration_seconds": seconds(started, completed)
        if status == "completed"
        else None,
        "execution_elapsed_seconds": seconds(started, now) if running else None,
    }
    if job:
        created = timestamp(item.get("created_at"))
        result.update(
            queue_delay_seconds=seconds(created, started),
            queue_elapsed_seconds=seconds(created, now)
            if status in {"queued", "waiting", "pending", "requested"}
            and started is None
            else None,
        )
    return result


def describe_job(job, now):
    steps = [
        {
            "number": step["number"],
            "name": step["name"],
            "status": step["status"],
            "conclusion": step.get("conclusion"),
            "phases": phases(step["name"]),
            **timing(step, now),
        }
        for step in sorted(job.get("steps", []), key=lambda step: step["number"])
    ]
    return {
        "id": job["id"],
        "name": job["name"],
        "status": job["status"],
        "conclusion": job.get("conclusion"),
        **timing(job, now, job=True),
        "first_failed_step": next(
            (step for step in steps if step["conclusion"] in {"failure", "timed_out"}),
            None,
        ),
        "steps": steps,
    }


def inspect_run(run_id, api=None, now=None):
    """Take a bounded snapshot. Never retry a changed attempt or fetch log bodies."""
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("Run ID must be a positive integer")
    api = api if api is not None else evidence.GitHub()
    now = now if now is not None else datetime.now(timezone.utc)

    def get(path):
        try:
            return api.get(path)
        except Exception:
            # Transport exceptions can contain URLs, headers or response bodies.
            raise ValueError("Cannot read CI run metadata") from None

    def check_run(run):
        if (
            run["id"] != run_id
            or run["repository"]["full_name"] != evidence.REPOSITORY
            or run["path"] != evidence.WORKFLOW
            or run["name"] != "CI"
            or type(run["run_attempt"]) is not int
            or run["run_attempt"] <= 0
        ):
            raise ValueError("Expected the exact canonical CI run")

    try:
        run = get(f"actions/runs/{run_id}")
        check_run(run)
        attempt = run["run_attempt"]
        jobs = []
        total = None
        # Small pages stay within the existing transport's response byte limit.
        for page in range(1, 21):
            payload = get(
                f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=20&page={page}"
            )
            count = payload["total_count"]
            if type(count) is not int or count < 0 or count > 400:
                raise ValueError("CI job count exceeds the diagnostic limit")
            if total is not None and count != total:
                raise ValueError("CI jobs changed during inspection; inspect again")
            total = count
            batch = payload["jobs"]
            jobs.extend(batch)
            if len(jobs) >= total:
                break
            if len(batch) != 20:
                raise ValueError("Incomplete CI job metadata; inspect again")
        if len(jobs) != total or len({job["id"] for job in jobs}) != total:
            raise ValueError("Incomplete or duplicate CI job metadata")
        for job in jobs:
            if job["run_id"] != run_id or job["run_attempt"] != attempt:
                raise ValueError("CI jobs do not match the current attempt")
        current = get(f"actions/runs/{run_id}")
        check_run(current)
        if current["run_attempt"] != attempt or current["head_sha"] != run["head_sha"]:
            raise ValueError("CI attempt changed during inspection; inspect again")
        return {
            "schema": 1,
            "scope": "read-only CI snapshot",
            "repository": evidence.REPOSITORY,
            "workflow": evidence.WORKFLOW,
            "run_id": run_id,
            "run_attempt": attempt,
            "head_sha": run["head_sha"],
            "source_repository": (run.get("head_repository") or {}).get("full_name"),
            "observed_at": now.isoformat(),
            "status": current["status"],
            "conclusion": current.get("conclusion"),
            "timing_note": "Null means unavailable. Job times are not summed wall time. "
            "Queue delay measures job creation to start and can include dependency "
            "or approval waits; it does not isolate runner capacity. "
            "Running elapsed times are not completed durations. Phase labels use "
            "step names only and do not identify a failure cause.",
            "jobs": [describe_job(job, now) for job in jobs],
        }
    except (KeyError, TypeError, AttributeError):
        raise ValueError("Incomplete CI run metadata") from None
