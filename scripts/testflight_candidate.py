"""Verify an explicitly requested internal TestFlight build from an open PR.

Stable publication still uses release_delivery and its merged preparation gate.
This read-only gate accepts only a canonical, current, ready PR and a distinct
immutable candidate tag. It never creates a tag, merges a PR or uploads a build.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
import re
import sys

from scripts.release_delivery import (
    CI_PATH,
    REPOSITORY,
    GitHub,
    ReleaseError,
    build_number,
    check_jobs,
    decode,
    mobile_upload_never_started,
    require,
    sha,
    tag_source,
    validate_intent,
    version,
)


def _upload_state(api, run_id, attempt):
    jobs = api.pages(f"/actions/runs/{int(run_id)}/attempts/{attempt}/jobs", "jobs")
    if mobile_upload_never_started(jobs):
        return False
    upload_jobs = [
        job for job in jobs if job.get("name") == "Test, sign and upload iOS"
    ]
    require(len(upload_jobs) == 1, "Upload job history is missing or ambiguous")
    steps = [
        step
        for step in upload_jobs[0].get("steps", [])
        if step.get("name") == "Upload directly to App Store Connect"
    ]
    require(len(steps) == 1, "Upload step history is missing or ambiguous")
    outcome = steps[0].get("conclusion")
    require(
        outcome in {"success", "skipped"},
        "Prior upload outcome is ambiguous; inspect Apple and use availability_only",
    )
    return outcome == "success"


def _check_pr(api, number, source):
    pr = api.request("GET", f"/pulls/{number}")
    require(
        pr.get("number") == number
        and pr.get("state") == "open"
        and pr.get("draft") is False
        and pr.get("merged") is False
        and pr.get("mergeable") is True,
        "Candidate requires an open, ready, conflict-free pull request",
    )
    require(
        pr.get("head", {}).get("sha") == source
        and pr["head"].get("repo", {}).get("full_name") == REPOSITORY
        and pr.get("base", {}).get("ref") == "main"
        and pr["base"].get("repo", {}).get("full_name") == REPOSITORY,
        "Candidate must match the canonical pull request's current head",
    )
    return pr


def _check_ci(api, source, number, base):
    runs = api.pages(
        f"/actions/workflows/ci.yml/runs?head_sha={source}&event=pull_request",
        "workflow_runs",
    )
    require(bool(runs), "Candidate has no pull request CI")
    run = max(
        runs, key=lambda value: (int(value["id"]), int(value.get("run_attempt", 1)))
    )
    require(
        run.get("repository", {}).get("full_name") == REPOSITORY
        and run.get("head_repository", {}).get("full_name") == REPOSITORY
        and run.get("event") == "pull_request"
        and run.get("head_sha") == source
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("path") == CI_PATH,
        "Candidate CI must be completed and green for the exact canonical source",
    )
    refs = run.get("pull_requests", [])
    require(
        any(
            ref.get("number") == number
            and ref.get("head", {}).get("sha") == source
            and ref.get("base", {}).get("sha") == base
            for ref in refs
        ),
        "Candidate CI did not validate this pull request against current main",
    )
    workflow = api.request("GET", f"/actions/workflows/{int(run['workflow_id'])}")
    require(
        workflow.get("path") == CI_PATH and workflow.get("name") == "CI",
        "Unexpected candidate CI workflow identity",
    )
    check_jobs(api, run["id"], "mobile")


def verify_candidate(api, *, source, tag, pr_number, actor, run_id, run_attempt=1):
    sha(source)
    require(
        isinstance(pr_number, int) and 0 < pr_number < 10**9, "Invalid candidate PR"
    )
    require(
        isinstance(actor, str) and bool(re.fullmatch(r"[A-Za-z0-9-]+", actor)),
        "Candidate requires an identified maintainer",
    )
    require(1 <= int(run_attempt) <= 100, "Candidate retry limit exceeded")
    permission = api.request("GET", f"/collaborators/{actor}/permission")
    require(
        permission.get("permission") in {"admin", "maintain", "write"},
        "Only a repository maintainer can authorize an internal candidate",
    )
    _check_pr(api, pr_number, source)
    main = sha(api.request("GET", "/git/ref/heads/main")["object"]["sha"])
    comparison = api.request("GET", f"/compare/{main}...{source}")
    require(
        comparison.get("status") == "ahead"
        and comparison.get("merge_base_commit", {}).get("sha") == main,
        "Candidate must contain current main",
    )
    current = decode(api.file("mobile/app.json", source))["expo"]
    previous = decode(api.file("mobile/app.json", main))["expo"]
    target = current["version"]
    build = current["ios"]["buildNumber"]
    require(
        version(target) >= version(previous["version"])
        and build_number(build) > build_number(previous["ios"]["buildNumber"]),
        "Candidate identity must use an increased mobile build",
    )
    reservation = validate_intent(
        decode(api.file(".github/testflight-candidate.json", source))
    )
    require(
        reservation["component"] == "mobile"
        and reservation["base_sha"] == main
        and reservation["version"] == target
        and reservation["evidence"]["build"] == build,
        "Candidate build reservation must match its source and current main",
    )
    checked = datetime.strptime(
        reservation["evidence"]["checked_at"], "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc)
    require(
        0 <= (datetime.now(timezone.utc) - checked).total_seconds() <= 86400,
        "Refresh the candidate's Apple build and reservation check",
    )
    require(
        tag == f"ios/pr-{pr_number}/v{target}-build{build}",
        "Candidate requires its own PR-specific immutable tag",
    )
    require(tag_source(api, tag) == source, "Candidate tag does not match source")
    _check_ci(api, source, pr_number, main)
    uploaded = False
    runs = api.pages(
        f"/actions/workflows/ios-testflight.yml/runs?head_sha={source}", "workflow_runs"
    )
    for run in runs:
        if int(run["id"]) == int(run_id):
            continue
        if run.get("event") != "workflow_dispatch" or run.get("head_sha") != source:
            continue
        if run.get("status") == "queued" and int(run.get("run_attempt", 1)) == 1:
            continue
        require(
            run.get("status") == "completed", "Another candidate publication is active"
        )
        for attempt in range(1, int(run.get("run_attempt", 1)) + 1):
            uploaded = _upload_state(api, run["id"], attempt) or uploaded
    for attempt in range(1, int(run_attempt)):
        uploaded = _upload_state(api, run_id, attempt) or uploaded
    # Recheck both mutable references immediately before the caller can sign.
    _check_pr(api, pr_number, source)
    require(
        api.request("GET", "/git/ref/heads/main")["object"]["sha"] == main,
        "Main changed during candidate validation",
    )
    return "availability" if uploaded else "publish"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--pr", required=True, type=int)
    args = parser.parse_args()
    try:
        require(
            os.environ.get("GITHUB_REPOSITORY") == REPOSITORY,
            "Use the canonical repository",
        )
        require(
            os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch",
            "Internal candidates require an explicit manual dispatch",
        )
        require(
            os.environ.get("GITHUB_REF") == "refs/tags/" + args.tag
            and os.environ.get("GITHUB_SHA") == args.source_sha,
            "Candidate workflow must run its immutable source tag",
        )
        result = verify_candidate(
            GitHub(os.environ.get("GH_TOKEN", "")),
            source=args.source_sha,
            tag=args.tag,
            pr_number=args.pr,
            actor=os.environ.get("GITHUB_TRIGGERING_ACTOR")
            or os.environ.get("GITHUB_ACTOR", ""),
            run_id=int(os.environ["GITHUB_RUN_ID"]),
            run_attempt=int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")),
        )
        print(result)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write("result=" + result + "\n")
    except (ReleaseError, KeyError, TypeError, ValueError) as error:
        print("Internal candidate gate failed.", file=sys.stderr)
        if isinstance(error, ReleaseError):
            print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
