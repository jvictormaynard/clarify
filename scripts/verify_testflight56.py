"""One-time internal build 56 exception authorized by the maintainer.

Keep the existing upload-history and signed-IPA guards. Reuse actual successful
mobile/native checks; do not claim that the complete CI run passed.
"""
from datetime import datetime, timezone
import release_delivery as release

PRODUCT_SOURCE = "70a4d7850cf1ad52875886f1abb59889e6c1ad8f"
CI_RUN = 41610351151
TAG = "ios/v0.13.0-build56"
EXCEPTION_FILES = {".github/workflows/ios-testflight.yml", "scripts/verify_testflight56.py"}


def verify_internal_source(api, component, source, tag, *, reuse_proof=None):
    release.require(component == "mobile" and tag == TAG, "Exception is only for internal build 56")
    release.require(datetime.now(timezone.utc) < datetime(2026, 11, 4, 8, 24, tzinfo=timezone.utc), "Repeat Apple inventory before delivery")
    release.require(release.tag_source(api, tag) == source, "Immutable tag mismatch")
    release.require(api.request("GET", "/git/ref/heads/main")["object"]["sha"] == PRODUCT_SOURCE, "Main changed; review source again")
    comparison = api.request("GET", f"/compare/{PRODUCT_SOURCE}...{source}")
    files = comparison.get("files", [])
    release.require(comparison.get("status") == "ahead" and comparison.get("total_commits") == 1
                    and {item["filename"] for item in files} == EXCEPTION_FILES
                    and all(item["status"] in {"added", "modified"} for item in files), "Product source differs from reviewed build 56")
    intent = release.intent_at(api, PRODUCT_SOURCE)
    release.require(intent is not None and release.release_tag(intent) == TAG
                    and release.dedicated_plan(api, PRODUCT_SOURCE, intent), "Missing merged build 56 preparation")
    release.require(release.intent_at(api, source) == intent, "Release intent changed")
    run = api.request("GET", f"/actions/runs/{CI_RUN}")
    release.require(run["head_sha"] == PRODUCT_SOURCE and run["event"] == "push"
                    and run["head_branch"] == "main" and run["repository"]["full_name"] == release.REPOSITORY
                    and run["head_repository"]["full_name"] == release.REPOSITORY
                    and run["path"] == release.CI_PATH, "Unexpected CI source")
    workflow = api.request("GET", f"/actions/workflows/{run['workflow_id']}")
    release.require(workflow["path"] == release.CI_PATH and workflow["name"] == "CI", "Unexpected CI workflow")
    attempt = int(run["run_attempt"])
    jobs = api.pages(f"/actions/runs/{CI_RUN}/attempts/{attempt}/jobs", "jobs")
    required = {
        "Mobile checks": ["Check Expo configuration"],
        "ios validation / Native keyboard and library tests": [
            "Test Swift contracts", "Test native keyboard and library integration",
            "Test installed keyboard typing and activation"],
        "ios validation / Unsigned app and extensions build": [],
    }
    evidence = []
    for name, steps in required.items():
        matches = [job for job in jobs if job["name"] == name]
        release.require(len(matches) == 1 and matches[0]["status"] == "completed"
                        and matches[0]["conclusion"] == "success", "Missing successful native/mobile check: " + name)
        job = matches[0]
        for step in steps:
            found = [entry for entry in job["steps"] if entry["name"] == step]
            release.require(len(found) == 1 and found[0]["status"] == "completed"
                            and found[0]["conclusion"] == "success", "Missing successful step: " + step)
        evidence.append({"job_id": job["id"], "name": name, "steps": steps})
    current = api.request("GET", f"/actions/runs/{CI_RUN}")
    release.require(current["run_attempt"] == attempt and current["head_sha"] == PRODUCT_SOURCE, "CI attempt changed")
    if reuse_proof is not None:
        reuse_proof.update(source=source, product_source=PRODUCT_SOURCE, run_id=CI_RUN,
                           attempt=attempt, workflow=release.CI_PATH, jobs=evidence,
                           full_ci_status=current["status"], full_ci_conclusion=current["conclusion"],
                           exception="Maintainer authorized one-time internal TestFlight upload without waiting for unrelated suites or full app UI acceptance",
                           excluded_checks=[job["name"] for job in jobs if job["name"] not in required],
                           internalManualReturn=True, appStoreAcceptance=False)
    return intent


release.verify_source = verify_internal_source
if __name__ == "__main__":
    raise SystemExit(release.main())
