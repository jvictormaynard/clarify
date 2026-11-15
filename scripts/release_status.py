"""Read-only release observations. This report does not authorize publication."""

from datetime import datetime, timezone
from urllib.parse import quote
import re

from scripts import release_delivery as release


class ReadOnlyGitHub(release.GitHub):
    """Keep all reused release verifiers on the GET transport boundary."""

    def request(self, method, path, body=None, *, missing=False):
        release.require(method == "GET" and body is None, "Status permits GET only")
        return super().request(method, path, missing=missing)


def component_tag(component, tag):
    pattern = (
        r"v(\d+\.\d+\.\d+)"
        if component == "desktop"
        else r"ios/v(\d+\.\d+\.\d+)-build([1-9][0-9]{0,8})"
    )
    match = re.fullmatch(pattern, tag or "")
    release.require(match is not None, "Tag does not identify the selected component")
    return release.version(match[1]) + (
        () if component == "desktop" else (int(match[2]),)
    )


def verified(check):
    try:
        result = check()
        return {"state": "verified" if result is not False else "missing"}
    except (ValueError, KeyError, TypeError, OSError):
        # Do not echo source documents, HTTP bodies or private URLs.
        return {
            "state": "unverified",
            "reason": "Existing verifier did not confirm this gate",
        }


def run_record(run):
    return {
        "run_id": run["id"],
        "attempt": run.get("run_attempt", 1),
        "status": run.get("status", "unknown"),
        "conclusion": run.get("conclusion"),
    }


def included_changes(api, component, source, target_tag, previous_tag):
    published = [
        row
        for row in api.pages("/releases")
        if not row.get("draft")
        and not row.get("prerelease")
        and row.get("published_at")
    ]
    target = component_tag(component, target_tag)
    eligible = []
    for row in published:
        try:
            order = component_tag(component, row.get("tag_name"))
        except release.ReleaseError:
            continue
        if order < target:
            eligible.append((order, row["tag_name"]))
    if previous_tag:
        release.require(
            previous_tag in [tag for _, tag in eligible],
            "Previous tag must be an earlier published release of this component",
        )
    elif eligible:
        previous_tag = max(eligible)[1]
    else:
        return {
            "state": "unknown",
            "reason": "No previous published component tag is observable on GitHub",
        }
    base = release.tag_source(api, previous_tag)
    release.require(base is not None, "Previous published tag has no source")
    path = f"/compare/{base}...{source}"
    comparison = api.request("GET", path)
    release.require(
        comparison.get("status") in {"ahead", "identical"}
        and comparison.get("merge_base_commit", {}).get("sha") == base,
        "Previous published source is not an ancestor of the selected source",
    )
    commits = api.pages(path, "commits")
    release.require(
        len(commits) == comparison.get("total_commits"),
        "Included-change range is incomplete",
    )
    return {
        "state": "observed",
        "previous_tag": previous_tag,
        "previous_source_sha": base,
        "source_sha": source,
        "scope": "All repository commits in this component release range; shared changes are included",
        "compare_url": f"https://github.com/{release.REPOSITORY}/compare/{quote(previous_tag, safe='')}...{source}",
        "commits": [
            {
                "sha": release.sha(row["sha"]),
                "subject": row["commit"]["message"].splitlines()[0],
            }
            for row in commits
        ],
    }


def candidates(api, component, source, tag, target_version):
    runs = api.pages(
        f"/actions/workflows/{release.WORKFLOWS[component]}/runs?head_sha={source}",
        "workflow_runs",
    )
    records = []
    for run in runs:
        if run.get("head_sha") != source or run.get("head_branch") != tag:
            continue
        record = run_record(run)
        record["artifacts"] = []
        run_id, attempt = int(run["id"]), int(run.get("run_attempt", 1))
        name = (
            f"desktop-candidate-{run_id}-{attempt}"
            if component == "desktop"
            else f"clarify-testflight-candidate-{run_id}-{attempt}"
        )
        for artifact in api.pages(f"/actions/runs/{run_id}/artifacts", "artifacts"):
            if artifact.get("name") != name:
                continue
            item = {
                key: artifact.get(key) for key in ("id", "name", "digest", "expired")
            }
            item["producer"] = {"state": "unverified"}
            if component == "desktop":
                from scripts import release_candidate

                expected = release_candidate.identity(
                    source,
                    "refs/tags/" + tag,
                    run_id,
                    attempt,
                    "stable",
                    target_version,
                )
                item["producer"] = verified(
                    lambda: release_candidate.authenticate(
                        api, expected, artifact["id"], artifact.get("digest")
                    )
                )
            record["artifacts"].append(item)
        records.append(record)
    return records


def report(api, component, source, *, tag=None, previous_tag=None):
    release.require(component in release.WORKFLOWS, "Select desktop or mobile")
    source = release.sha(source)
    if component == "desktop":
        module = api.file("version.py", source)
        match = re.search(r'^__version__ = "([0-9.]+)"$', module, re.MULTILINE)
        release.require(match is not None, "Cannot read desktop version")
        target_version = match[1]
        release.require(
            release.decode(api.file("package.json", source))["version"]
            == target_version,
            "Desktop versions differ",
        )
        expected_tag = "v" + target_version
        build = None
    else:
        app = release.decode(api.file("mobile/app.json", source))["expo"]
        target_version, build = app["version"], app["ios"]["buildNumber"]
        release.build_number(build)
        expected_tag = "ios/v" + target_version + "-build" + build
    release.version(target_version)
    release.require(
        tag is None or tag == expected_tag, "Tag differs from selected source metadata"
    )
    tag = expected_tag
    tag_sha = release.tag_source(api, tag)
    release.require(
        tag_sha is None or tag_sha == source, "Tag points to another source"
    )
    result = {
        "schema": 1,
        "repository": release.REPOSITORY,
        "component": component,
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_sha": source,
        "version": target_version,
        "build": build,
        "tag": tag,
        "tag_state": "matching" if tag_sha else "missing",
        "main_source": verified(lambda: release.require_main_source(api, source)),
        "preparation": {"state": "missing"},
    }
    intent = release.intent_at(api, source)
    if intent is not None:
        if intent["component"] == component and release.release_tag(intent) == tag:
            result["preparation"] = verified(
                lambda: release.dedicated_plan(api, source, intent)
            )
        else:
            result["preparation"] = {
                "state": "unverified",
                "reason": "Intent identifies another component or version",
            }
    runs = api.pages(
        f"/actions/workflows/ci.yml/runs?head_sha={source}&event=push", "workflow_runs"
    )
    runs = [run for run in runs if run.get("head_sha") == source]
    ci = {
        "state": "missing",
        "coverage": "unverified",
        "required_coverage": sorted(release.release_jobs(component)),
    }
    if runs:
        run = max(
            runs, key=lambda row: (int(row["id"]), int(row.get("run_attempt", 1)))
        )
        ci.update(run_record(run))
        ci["state"] = "observed"

        def check_ci():
            release.validate_run(api, run, source)
            release.check_jobs(api, run, component)

        ci["coverage"] = verified(check_ci)["state"]
    result["ci"] = ci
    result["included_changes"] = included_changes(
        api, component, source, tag, previous_tag
    )
    result["candidates"] = candidates(api, component, source, tag, target_version)
    result["acceptance"] = {
        "state": "unknown",
        "reason": "Candidate acceptance was not authenticated by this report",
    }
    publication = api.request("GET", "/releases/tags/" + tag, missing=True)
    result["publication"] = {
        "state": "observed"
        if publication
        else "unknown"
        if component == "mobile"
        else "missing",
        "reason": "GitHub metadata does not prove candidate bytes, native acceptance or Apple availability",
    }
    if publication:
        result["publication"].update(
            {
                key: publication.get(key)
                for key in ("draft", "prerelease", "published_at")
            }
        )
    if (
        result["main_source"]["state"] != "verified"
        or result["preparation"]["state"] != "verified"
    ):
        action = "Review exact source and release preparation evidence"
    elif ci["coverage"] != "verified":
        action = "Inspect or complete exact-source component CI coverage"
    elif not result["candidates"]:
        action = "Request candidate creation through the existing release workflow"
    elif any(run["status"] != "completed" for run in result["candidates"]):
        action = "Wait for the observed candidate workflow to finish, then repeat this report"
    elif any(run["conclusion"] != "success" for run in result["candidates"]):
        action = "Inspect the failed candidate workflow before any retry or publication"
    elif component == "desktop":
        action = "Authenticate candidate bytes, Windows acceptance and publication through the existing candidate verifier"
    else:
        action = "Reconcile TestFlight candidate and Apple availability through the existing App Store handoff"
    result["next_action"] = action
    return result


def human_report(result):
    lines = [
        f"{result['component']} {result['version']} ({result['tag']})",
        "Source: " + result["source_sha"],
        f"Preparation: {result['preparation']['state']}; tag: {result['tag_state']}",
        f"CI: {result['ci'].get('status', result['ci']['state'])}; coverage: {result['ci']['coverage']}",
        f"Candidate runs: {len(result['candidates'])}; acceptance: {result['acceptance']['state']}",
        f"Publication: {result['publication']['state']} (unverified)",
    ]
    for run in result["candidates"]:
        lines.append(
            f"  Run {run['run_id']} attempt {run['attempt']}: {run['status']} / {run['conclusion']}"
        )
        for artifact in run["artifacts"]:
            lines.append(
                f"    Artifact {artifact['id']}: {artifact['digest']}; producer {artifact['producer']['state']}; payload unverified"
            )
    changes = result["included_changes"]
    if changes["state"] == "observed":
        lines.append("Included changes since " + changes["previous_tag"] + ":")
        lines.extend(
            "  " + row["sha"][:12] + " " + row["subject"] for row in changes["commits"]
        )
    else:
        lines.append("Included changes: unknown. " + changes["reason"])
    lines.append("Next: " + result["next_action"])
    return "\n".join(lines)
