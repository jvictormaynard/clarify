"""Prepare reviewed client releases and promote only their exact green source.

This module uses the GitHub API, not downloaded workflow artifacts. It does not
execute version files, accept arbitrary repositories, or accept arbitrary refs.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

REPOSITORY = "jvictormaynard/clarify"
INTENT = ".github/release-intent.json"
CI_PATH = ".github/workflows/ci.yml"
WORKFLOWS = {"desktop": "community-release.yml", "mobile": "ios-testflight.yml"}
ASSETS = {
    "Clarify.exe",
    "Clarify.exe.sha256",
    "Clarify.sbom.json",
    "Clarify-qt-sources.zip",
    "Clarify-windows-x64.zip",
    "sox-14.4.2-source.tar.gz",
    "Clarify-portable-update.json",
    "Clarify-portable-update.json.sig",
}
COMMON_CHECKS = {"CI required"}
COMPONENT_CHECKS = {
    "desktop": {
        "Tests (ubuntu-latest)",
        "Tests (windows-latest)",
        "Package Windows executable",
    },
    "mobile": {"Mobile checks", "iOS validation / Native tests and unsigned build"},
}


class ReleaseError(ValueError):
    """An unverified release must have no publication effects."""


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def exact_keys(value, keys):
    require(
        isinstance(value, dict) and set(value) == set(keys),
        "Invalid release intent fields",
    )


def version(value):
    require(
        isinstance(value, str)
        and re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value),
        "Use stable X.Y.Z without leading zeros",
    )
    parts = tuple(map(int, value.split(".")))
    require(
        all(part <= 65535 for part in parts), "Version exceeds Windows version limits"
    )
    return parts


def sha(value):
    require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value),
        "Expected an exact commit SHA",
    )
    return value


def build_number(value):
    require(
        isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,8}", value),
        "Use a positive decimal mobile build number",
    )
    return int(value)


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON fields are not allowed")
        result[key] = value
    return result


def decode(data):
    return json.loads(data, object_pairs_hook=object_pairs)


def validate_intent(intent):
    exact_keys(
        intent, {"schema", "component", "version", "base_sha", "notes", "evidence"}
    )
    require(
        type(intent["schema"]) is int and intent["schema"] == 1,
        "Unsupported release intent schema",
    )
    require(intent["component"] in WORKFLOWS, "Unknown release component")
    version(intent["version"])
    sha(intent["base_sha"])
    require(
        isinstance(intent["notes"], str) and 1 <= len(intent["notes"].strip()) <= 12000,
        "Release notes are required (maximum 12000 characters)",
    )
    evidence = intent["evidence"]
    if intent["component"] == "desktop":
        exact_keys(evidence, {"tested_sha", "windows_accepted", "report_url"})
        require(
            evidence["tested_sha"] == intent["base_sha"]
            and evidence["windows_accepted"] is True,
            "Windows manual acceptance must cover the prepared base SHA",
        )
    else:
        exact_keys(
            evidence,
            {
                "build",
                "highest_build",
                "pending_builds_checked",
                "checked_at",
                "report_url",
            },
        )
        require(
            evidence["pending_builds_checked"] is True,
            "Check App Store Connect builds and pending submissions before reserving a build",
        )
        require(
            build_number(evidence["build"]) > build_number(evidence["highest_build"]),
            "Mobile build is already reserved or uploaded",
        )
        try:
            checked = datetime.strptime(
                evidence["checked_at"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError) as error:
            raise ReleaseError("Use a UTC App Store Connect check timestamp") from error
        require(checked.year >= 2026, "Invalid App Store Connect check timestamp")
    require(
        isinstance(evidence["report_url"], str)
        and re.fullmatch(
            r"https://github\.com/jvictormaynard/clarify/(?:issues|pull|actions/runs)/[1-9][0-9]*(?:#[A-Za-z0-9_-]+)?",
            evidence["report_url"],
        ),
        "Evidence must link to a canonical GitHub report or workflow run",
    )
    return intent


def release_tag(intent):
    if intent["component"] == "desktop":
        return "v" + intent["version"]
    return "ios/v" + intent["version"] + "-build" + intent["evidence"]["build"]


def preparation_branch(intent):
    return "release-preparation/" + release_tag(intent)


def preparation_title(intent):
    return "release: prepare " + intent["component"] + " " + release_tag(intent)


class GitHub:
    """Small stdlib transport. The injectable base URL is used only by tests."""

    def __init__(self, token, base_url="https://api.github.com"):
        require(bool(token), "A configured GitHub token is required")
        self.token = token
        self.base = base_url + "/repos/" + REPOSITORY

    def request(self, method, path, body=None, *, missing=False):
        require(
            path.startswith("/") and ".." not in path.split("/"), "Invalid API path"
        )
        request = Request(
            self.base + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                data = response.read()
                return decode(data) if data else None
        except HTTPError as error:
            if missing and error.code == 404:
                return None
            raise ReleaseError(f"GitHub {method} failed: HTTP {error.code}") from error

    def pages(self, path, key=None):
        rows = []
        separator = "&" if "?" in path else "?"
        for page in range(1, 11):
            result = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            items = result[key] if key else result
            require(isinstance(items, list), "Invalid paginated GitHub response")
            rows.extend(items)
            if len(items) < 100:
                return rows
        raise ReleaseError("GitHub pagination exceeded the release safety limit")

    def file(self, path, ref, *, missing=False):
        item = self.request(
            "GET", "/contents/" + path + "?ref=" + quote(ref, safe=""), missing=missing
        )
        if item is None:
            return None
        require(
            item.get("type") == "file" and item.get("encoding") == "base64",
            "Expected a source file",
        )
        return base64.b64decode(item["content"]).decode("utf-8")


def validate_run(api, run, expected_sha=None):
    require(
        run.get("repository", {}).get("full_name") == REPOSITORY
        and run.get("head_repository", {}).get("full_name") == REPOSITORY,
        "CI must run in the canonical repository",
    )
    require(
        run.get("event") == "push" and run.get("head_branch") == "main",
        "CI must be a main push run",
    )
    require(
        run.get("status") == "completed" and run.get("conclusion") == "success",
        "CI is not green",
    )
    require(
        run.get("path") in {CI_PATH, CI_PATH + "@main", CI_PATH + "@refs/heads/main"},
        "Unexpected CI workflow path",
    )
    workflow = api.request("GET", f"/actions/workflows/{int(run['workflow_id'])}")
    require(
        workflow.get("path") == CI_PATH and workflow.get("name") == "CI",
        "Unexpected CI workflow identity",
    )
    source = sha(run.get("head_sha"))
    require(
        expected_sha is None or source == expected_sha,
        "CI SHA does not match the release source",
    )
    return source


def intent_at(api, source):
    data = api.file(INTENT, source, missing=True)
    return None if data is None else validate_intent(decode(data))


def check_metadata(api, intent, source):
    target = intent["version"]
    base = intent["base_sha"]
    if intent["component"] == "desktop":

        def read_version(ref):
            text = api.file("version.py", ref)
            match = re.search(r'^__version__ = "([0-9.]+)"$', text, re.MULTILINE)
            require(
                match is not None,
                "Cannot read desktop version without executing source",
            )
            package = decode(api.file("package.json", ref))
            packaged = package["version"]
            require(
                packaged == match[1], "Desktop package and executable versions differ"
            )
            return match[1], text, package

        previous, base_module, base_package = read_version(base)
        current, current_module, current_package = read_version(source)
        require(current == target, "Desktop intent and packaged version differ")
        expected_module = re.sub(
            r'(?m)^__version__ = "[0-9.]+"$',
            '__version__ = "' + target + '"',
            base_module,
        )
        base_package["version"] = target
        require(
            current_module == expected_module and current_package == base_package,
            "Only desktop version values can change in release metadata",
        )
        changelog = api.file("CHANGELOG.md", source)
        require(
            re.search(
                r"^## \[" + re.escape(target) + r"\] - \d{4}-\d{2}-\d{2}$",
                changelog,
                re.MULTILINE,
            ),
            "Desktop changelog must contain the prepared release",
        )
        require(version(target) > version(previous), "Desktop version must increase")
    else:
        current_doc = decode(api.file("mobile/app.json", source))
        previous_doc = decode(api.file("mobile/app.json", base))
        current = current_doc["expo"]
        previous = previous_doc["expo"]
        require(
            current["version"] == target
            and current["ios"]["buildNumber"] == intent["evidence"]["build"],
            "Mobile intent and app identity differ",
        )
        require(
            version(target) >= version(previous["version"])
            and build_number(current["ios"]["buildNumber"])
            > build_number(previous["ios"]["buildNumber"]),
            "Mobile version cannot decrease and build must increase",
        )
        previous["version"] = target
        previous["ios"]["buildNumber"] = intent["evidence"]["build"]
        require(
            current_doc == previous_doc,
            "Only mobile version and build can change in release metadata",
        )


def dedicated_plan(api, source, intent):
    summaries = api.pages(f"/commits/{source}/pulls")
    candidates = []
    for summary in summaries:
        pr = api.request("GET", f"/pulls/{int(summary['number'])}")
        if pr.get("merged") and pr.get("merge_commit_sha") == source:
            candidates.append(pr)
    # A prior intent on a later ordinary code or documentation commit is inert.
    if not candidates or not any(
        pr.get("head", {}).get("ref") == preparation_branch(intent) for pr in candidates
    ):
        return False
    require(
        len(candidates) == 1, "Release source must identify one merged preparation PR"
    )
    pr = candidates[0]
    require(
        pr.get("state") == "closed" and pr.get("title") == preparation_title(intent),
        "Unexpected preparation PR identity",
    )
    require(
        pr.get("base", {}).get("ref") == "main"
        and pr["base"].get("repo", {}).get("full_name") == REPOSITORY
        and pr["head"].get("repo", {}).get("full_name") == REPOSITORY,
        "Preparation PR must belong to canonical main",
    )
    merger = pr.get("merged_by", {}).get("login", "")
    require(
        bool(re.fullmatch(r"[A-Za-z0-9-]+", merger)),
        "Preparation PR needs a maintainer merge",
    )
    permission = api.request("GET", "/collaborators/" + merger + "/permission")
    require(
        permission.get("permission") in {"admin", "maintain", "write"},
        "Preparation PR must be approved by a maintainer merge",
    )
    files = api.pages(f"/pulls/{int(pr['number'])}/files")
    allowed = (
        {INTENT, "CHANGELOG.md", "version.py", "package.json"}
        if intent["component"] == "desktop"
        else {INTENT, "mobile/app.json"}
    )
    paths = {item["filename"] for item in files}
    require(
        INTENT in paths
        and paths <= allowed
        and all(item["status"] in {"added", "modified"} for item in files),
        "Preparation PR must contain only its release metadata",
    )
    comparison = api.request("GET", f"/compare/{intent['base_sha']}...{source}")
    require(
        comparison.get("status") == "ahead"
        and comparison.get("total_commits", 999) <= 10,
        "Prepared source does not follow the accepted base",
    )
    changes = comparison.get("files", [])
    require(
        {item["filename"] for item in changes} == paths
        and all(item["status"] in {"added", "modified"} for item in changes),
        "Source changed after acceptance; prepare and validate it again",
    )
    check_metadata(api, intent, source)
    return True


def check_jobs(api, run_id, component):
    jobs = api.pages(f"/actions/runs/{int(run_id)}/jobs?filter=latest", "jobs")
    required = COMMON_CHECKS | COMPONENT_CHECKS[component]
    for name in required:
        matches = [job for job in jobs if job.get("name") == name]
        require(
            len(matches) == 1
            and matches[0].get("conclusion") == "success"
            and matches[0].get("status") == "completed",
            "Required CI job is not green: " + name,
        )


def tag_source(api, tag):
    ref = api.request("GET", "/git/ref/tags/" + tag, missing=True)
    if ref is None:
        return None
    obj = ref["object"]
    for _ in range(5):
        if obj.get("type") == "commit":
            return sha(obj["sha"])
        require(obj.get("type") == "tag", "Unsupported release tag object")
        obj = api.request("GET", "/git/tags/" + sha(obj["sha"]))["object"]
    raise ReleaseError("Release tag nesting exceeds the safety limit")


def existing_publication(api, intent):
    if intent["component"] != "desktop":
        return False
    release = api.request("GET", "/releases/tags/" + release_tag(intent), missing=True)
    if release is None:
        return False
    assets = [asset["name"] for asset in release.get("assets", [])]
    require(
        not release.get("draft")
        and not release.get("prerelease")
        and len(assets) == len(ASSETS)
        and set(assets) == ASSETS,
        "Existing release is incomplete; inspect it without replacing assets",
    )
    return True


def require_new_desktop_release(api, intent):
    if intent["component"] != "desktop":
        return
    target = version(intent["version"])
    for release in api.pages("/releases"):
        tag = release.get("tag_name", "")
        if release.get("draft") or release.get("prerelease"):
            continue
        if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
            continue
        require(
            version(tag[1:]) < target,
            "Desktop release is superseded by an equal or newer published version",
        )


def mobile_upload_never_started(jobs):
    gates = [job for job in jobs if job.get("name") == "release_gate"]
    if len(gates) != 1:
        return False
    if gates[0].get("conclusion") == "skipped":
        # Tests/status/availability inputs cannot sign or upload.
        return True
    uploads = [job for job in jobs if job.get("name") == "Test, sign and upload iOS"]
    return (
        gates[0].get("status") == "completed"
        and gates[0].get("conclusion") in {"failure", "cancelled", "timed_out"}
        and len(uploads) == 1
        and uploads[0].get("status") == "completed"
        and uploads[0].get("conclusion") == "skipped"
    )


def publication_runs(api, intent, source):
    runs = []
    for run in api.pages(
        f"/actions/workflows/{WORKFLOWS[intent['component']]}/runs?head_sha={source}",
        "workflow_runs",
    ):
        if (
            run.get("event") not in {"push", "workflow_dispatch"}
            or run.get("head_sha") != source
            or run.get("head_branch") != release_tag(intent)
        ):
            continue
        if intent["component"] == "mobile":
            jobs = api.pages(
                f"/actions/runs/{int(run['id'])}/jobs?filter=latest", "jobs"
            )
            if mobile_upload_never_started(jobs):
                attempts = int(run.get("run_attempt", 1))
                require(1 <= attempts <= 100, "Publication retry limit exceeded")
                if all(
                    mobile_upload_never_started(
                        api.pages(
                            f"/actions/runs/{int(run['id'])}/attempts/{attempt}/jobs",
                            "jobs",
                        )
                    )
                    for attempt in range(1, attempts)
                ):
                    continue
        runs.append(run)
    return runs


def promote(api, event):
    require(
        event.get("repository", {}).get("full_name") == REPOSITORY,
        "Unexpected event repository",
    )
    supplied = event["workflow_run"]
    run = api.request("GET", f"/actions/runs/{int(supplied['id'])}")
    source = validate_run(api, run, supplied.get("head_sha"))
    require(
        api.request("GET", "/git/ref/heads/main")["object"]["sha"] == source,
        "CI source is stale against main",
    )
    intent = intent_at(api, source)
    if intent is None:
        return "no-intent"
    if not dedicated_plan(api, source, intent):
        return "no-preparation-pr"
    check_jobs(api, run["id"], intent["component"])
    tag = release_tag(intent)
    existing = tag_source(api, tag)
    require(
        existing is None or existing == source,
        "Existing tag points to another source; never move it",
    )
    if existing_publication(api, intent):
        require(existing == source, "Published release has no matching source tag")
        return "already-published"
    require_new_desktop_release(api, intent)
    if publication_runs(api, intent, source):
        require(existing == source, "Publication run has no matching source tag")
        return "already-dispatched"
    # Recheck immediately before mutation. A later main push cannot move this tag.
    require(
        api.request("GET", "/git/ref/heads/main")["object"]["sha"] == source,
        "Main advanced before promotion",
    )
    if existing is None:
        obj = api.request(
            "POST",
            "/git/tags",
            {
                "tag": tag,
                "message": "Clarify " + tag,
                "object": source,
                "type": "commit",
            },
        )
        api.request(
            "POST", "/git/refs", {"ref": "refs/tags/" + tag, "sha": sha(obj["sha"])}
        )
    # GITHUB_TOKEN-created tag pushes do not start workflows. Dispatch explicitly.
    api.request(
        "POST",
        f"/actions/workflows/{WORKFLOWS[intent['component']]}/dispatches",
        {
            "ref": tag,
            "inputs": {
                "source_sha": source,
                **({"tests_only": "false"} if intent["component"] == "mobile" else {}),
            },
        },
    )
    return "dispatched"


def verify_publication(api, component, source, tag, run_id, run_attempt=1):
    sha(source)
    intent = intent_at(api, source)
    require(
        intent is not None
        and intent["component"] == component
        and release_tag(intent) == tag,
        "Publication requires the reviewed release intent and exact tag",
    )
    require(
        tag_source(api, tag) == source,
        "Immutable tag does not match publication source",
    )
    require(
        dedicated_plan(api, source, intent),
        "Publication source has no dedicated merged preparation PR",
    )
    runs = api.pages(
        f"/actions/workflows/ci.yml/runs?head_sha={source}&event=push", "workflow_runs"
    )
    require(bool(runs), "No post-merge CI exists for the publication source")
    run = max(runs, key=lambda item: (item["id"], item.get("run_attempt", 1)))
    validate_run(api, run, source)
    check_jobs(api, run["id"], component)
    if existing_publication(api, intent):
        return "skip"
    require_new_desktop_release(api, intent)
    if component == "mobile":
        prior = [
            run
            for run in publication_runs(api, intent, source)
            if int(run["id"]) != int(run_id)
            # A first attempt still queued behind this serialized workflow has
            # never uploaded. A queued retry can have earlier upload history.
            and not (run.get("status") == "queued" and run.get("run_attempt") == 1)
        ]
        if prior:
            require(
                all(
                    run.get("status") == "completed"
                    and run.get("conclusion") == "success"
                    for run in prior
                ),
                "A prior upload run exists; inspect or rerun that run",
            )
            return "skip"
        require(1 <= int(run_attempt) <= 100, "Publication retry limit exceeded")
        uploaded = False
        for attempt in range(1, int(run_attempt)):
            jobs = api.pages(
                f"/actions/runs/{int(run_id)}/attempts/{attempt}/jobs", "jobs"
            )
            for job in jobs:
                for step in job.get("steps", []):
                    if step.get("name") == "Upload directly to App Store Connect":
                        outcome = step.get("conclusion")
                        require(
                            outcome in {"success", "skipped"},
                            "Prior upload outcome is ambiguous; inspect Apple and use availability_only",
                        )
                        uploaded = uploaded or outcome == "success"
        if uploaded:
            return "availability"
    return "publish"


def prepare(api, component, target, evidence, notes, now=None):
    require(component in WORKFLOWS, "Unknown release component")
    now = now or datetime.now(timezone.utc)
    source = sha(api.request("GET", "/git/ref/heads/main")["object"]["sha"])
    intent = validate_intent(
        {
            "schema": 1,
            "component": component,
            "version": target,
            "base_sha": source,
            "notes": notes,
            "evidence": evidence,
        }
    )
    if component == "mobile":
        checked = datetime.strptime(
            evidence["checked_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        require(
            0 <= (now - checked).total_seconds() <= 86400,
            "Repeat the App Store Connect check within 24 hours before preparation",
        )
    require(
        tag_source(api, release_tag(intent)) is None, "This release tag already exists"
    )
    branch = preparation_branch(intent)
    require(
        api.request("GET", "/git/ref/heads/" + branch, missing=True) is None,
        "Preparation branch exists; review that PR",
    )
    changes = {}
    if component == "desktop":
        module = api.file("version.py", source)
        match = re.search(r'^__version__ = "([0-9.]+)"$', module, re.MULTILINE)
        require(
            match is not None and version(target) > version(match[1]),
            "Desktop version must increase",
        )
        package = decode(api.file("package.json", source))
        require(
            package["version"] == match[1], "Desktop versions differ before preparation"
        )
        package["version"] = target
        changes["package.json"] = json.dumps(package, indent=2) + "\n"
        changes["version.py"] = (
            module[: match.start(1)] + target + module[match.end(1) :]
        )
        changelog = api.file("CHANGELOG.md", source)
        require(
            f"## [{target}]" not in changelog
            and changelog.count("## [Unreleased]") == 1,
            "Changelog release boundary is invalid",
        )
        changes["CHANGELOG.md"] = changelog.replace(
            "## [Unreleased]", f"## [Unreleased]\n\n## [{target}] - {now:%Y-%m-%d}", 1
        )
        comparison = re.search(
            r"^\[Unreleased\]: (https://github.com/jvictormaynard/clarify/compare/)(v[0-9.]+)\.\.\.HEAD$",
            changelog,
            re.MULTILINE,
        )
        require(comparison is not None, "Changelog comparison link is missing")
        changes["CHANGELOG.md"] = changes["CHANGELOG.md"].replace(
            comparison[0],
            f"[Unreleased]: {comparison[1]}v{target}...HEAD\n[{target}]: {comparison[1]}{comparison[2]}...v{target}",
        )
    else:
        app = decode(api.file("mobile/app.json", source))
        require(
            version(target) >= version(app["expo"]["version"]),
            "Mobile version cannot decrease",
        )
        require(
            build_number(evidence["build"])
            > build_number(app["expo"]["ios"]["buildNumber"]),
            "Mobile build must increase",
        )
        app["expo"]["version"] = target
        app["expo"]["ios"]["buildNumber"] = evidence["build"]
        changes["mobile/app.json"] = (
            json.dumps(app, indent=2, ensure_ascii=False) + "\n"
        )
    changes[INTENT] = json.dumps(intent, indent=2, ensure_ascii=False) + "\n"
    require(
        api.request("GET", "/git/ref/heads/main")["object"]["sha"] == source,
        "Main advanced; prepare again",
    )
    commit = api.request("GET", "/git/commits/" + source)
    tree = api.request(
        "POST",
        "/git/trees",
        {
            "base_tree": commit["tree"]["sha"],
            "tree": [
                {"path": path, "mode": "100644", "type": "blob", "content": content}
                for path, content in changes.items()
            ],
        },
    )
    commit = api.request(
        "POST",
        "/git/commits",
        {
            "message": preparation_title(intent),
            "tree": tree["sha"],
            "parents": [source],
        },
    )
    api.request(
        "POST", "/git/refs", {"ref": "refs/heads/" + branch, "sha": commit["sha"]}
    )
    pr = api.request(
        "POST",
        "/pulls",
        {
            "head": branch,
            "base": "main",
            "title": preparation_title(intent),
            "body": "Review the release notes, evidence and exact source before merging. Maintainer merge authorizes publication after green main CI.\n\n"
            + notes
            + "\n\nEvidence: "
            + evidence["report_url"],
            "draft": True,
        },
    )
    return pr["html_url"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "promote", "verify"])
    parser.add_argument("--component", choices=list(WORKFLOWS))
    parser.add_argument("--version")
    parser.add_argument("--build", default="")
    parser.add_argument("--source-sha")
    parser.add_argument("--tag")
    args = parser.parse_args()
    try:
        require(
            os.environ.get("GITHUB_REPOSITORY") == REPOSITORY,
            "Use the canonical repository",
        )
        api = GitHub(os.environ.get("GH_TOKEN", ""))
        if args.command == "prepare":
            require(
                os.environ.get("GITHUB_REF") == "refs/heads/main",
                "Run preparation from main",
            )
            evidence = decode(os.environ.get("RELEASE_EVIDENCE", "{}"))
            require(
                (args.component == "mobile" and evidence.get("build") == args.build)
                or (args.component == "desktop" and not args.build),
                "Build input must match the mobile reservation evidence",
            )
            result = prepare(
                api,
                args.component,
                args.version,
                evidence,
                os.environ.get("RELEASE_NOTES", ""),
            )
        elif args.command == "promote":
            require(
                os.environ.get("CLARIFY_RELEASE_PROMOTION_ENABLED") == "true",
                "Release promotion is disabled",
            )
            require(
                os.environ.get("GITHUB_EVENT_NAME") == "workflow_run",
                "Use a completed CI event",
            )
            result = promote(
                api,
                decode(
                    Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
                ),
            )
        else:
            require(
                os.environ.get("GITHUB_REF") == "refs/tags/" + (args.tag or ""),
                "Publication must dispatch an immutable tag",
            )
            require(
                os.environ.get("GITHUB_SHA") == args.source_sha,
                "Workflow source SHA differs from release source",
            )
            result = verify_publication(
                api,
                args.component,
                args.source_sha,
                args.tag,
                os.environ["GITHUB_RUN_ID"],
                int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")),
            )
        print(result)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write("result=" + result + "\n")
    except (ReleaseError, KeyError, TypeError, ValueError) as error:
        # Source documents and HTTP bodies may contain credentials. Do not echo them.
        print(
            "Release gate failed. Check source, intent, CI, token permissions and evidence.",
            file=sys.stderr,
        )
        if isinstance(error, ReleaseError):
            print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
