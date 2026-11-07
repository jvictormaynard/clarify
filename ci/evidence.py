"""Read-only authentication of bounded, same-source PR validation evidence."""

from datetime import datetime, timezone
import hashlib
from http.client import HTTPException
import io
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile
import zlib

from ci import impact
from ci.tasks import JOBS

REPOSITORY = "jvictormaynard/clarify"
WORKFLOW = ".github/workflows/ci.yml"
LIMIT = 256 * 1024
MAX_AGE = 24 * 60 * 60


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    """Never forward the API token to an artifact storage origin."""

    def __init__(self):
        self.opener = build_opener(NoRedirect())

    def read(self, url, *, authenticated=True):
        from urllib.error import HTTPError

        headers = {"Accept": "application/vnd.github+json"}
        if authenticated:
            if not url.startswith(f"https://api.github.com/repos/{REPOSITORY}/"):
                raise ValueError("Foreign API origin")
            headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
        request = Request(url, headers=headers)
        try:
            response = self.opener.open(request, timeout=20)
        except HTTPError as error:
            if not authenticated or error.code != 302:
                raise
            target = error.headers.get("Location", "")
            parsed = urlsplit(target)
            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
                or not parsed.hostname
                or not parsed.hostname.endswith(
                    (".blob.core.windows.net", ".actions.githubusercontent.com")
                )
            ):
                raise ValueError("Untrusted artifact redirect") from error
            return self.read(target, authenticated=False)
        with response:
            data = response.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("Oversized API response or evidence archive")
        return data

    def get(self, path):
        return json.loads(
            self.read(f"https://api.github.com/repos/{REPOSITORY}/{path}"),
            object_pairs_hook=impact.json_object,
        )

    def archive(self, artifact_id):
        return self.read(
            f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip"
        )


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], timeout=30, text=True
    ).strip()


def source(repo, sha):
    if not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{40}", sha):
        raise ValueError("Expected exact source SHA")
    return {
        "sha": sha,
        "tree": git(repo, "rev-parse", sha + "^{tree}"),
        "parents": git(repo, "show", "-s", "--format=%P", sha).split(),
    }


def control_change(paths):
    return any(
        path.startswith(("ci/", ".github/", "scripts/", "tests/policy/"))
        or path in impact.FULL_INPUTS | impact.SHARED_INPUTS
        or path
        in {
            "package.json",
            "package-lock.json",
            "requirements.txt",
            "requirements-dev.txt",
            "requirements-lock-linux.txt",
            "requirements-lock-windows.txt",
        }
        for path in paths
    )


def emit(repo, env, event, needs, destination):
    impact.validate_ci_results(needs)
    if env["GITHUB_EVENT_NAME"] != "pull_request":
        raise ValueError("Only PR runs emit reusable evidence")
    checked = source(repo, env["GITHUB_SHA"])
    pr = event["pull_request"]
    if checked["parents"] != [pr["base"]["sha"], pr["head"]["sha"]]:
        raise ValueError("PR checkout is not the event synthetic merge")
    proof = {
        "schema": 1,
        "repository": env["GITHUB_REPOSITORY"],
        "workflow": WORKFLOW,
        "run_id": int(env["GITHUB_RUN_ID"]),
        "attempt": int(env["GITHUB_RUN_ATTEMPT"]),
        "source": checked,
        "pr": {
            "number": event["number"],
            "base": pr["base"]["sha"],
            "head": pr["head"]["sha"],
        },
        "needs": needs,
    }
    Path(destination).write_text(json.dumps(proof), encoding="utf-8")


def unpack(data, digest):
    if len(data) > LIMIT or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Invalid evidence archive metadata")
    if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Evidence archive digest mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if (
            len(entries) != 1
            or entries[0].filename != "proof.json"
            or entries[0].file_size > LIMIT
        ):
            raise ValueError("Invalid evidence archive inventory")
        proof = json.loads(
            archive.read(entries[0]), object_pairs_hook=impact.json_object
        )
    if (
        not isinstance(proof, dict)
        or set(proof)
        != {
            "schema",
            "repository",
            "workflow",
            "run_id",
            "attempt",
            "source",
            "pr",
            "needs",
        }
        or type(proof["schema"]) is not int
        or proof["schema"] != 1
    ):
        raise ValueError("Unknown evidence manifest")
    return proof


def complete(run):
    if (
        run["repository"]["full_name"] != REPOSITORY
        or run["head_repository"]["full_name"] != REPOSITORY
        or run["path"] != WORKFLOW
        or run["name"] != "CI"
        or run["event"] != "pull_request"
        or run["status"] != "completed"
        or run["conclusion"] != "success"
    ):
        raise ValueError("Producer is not successful canonical PR CI")


def authenticate(repo, head, api=None, reference=None, now=None):
    """Return selected successful coverage and immutable producer identity, or raise."""
    api = api or GitHub()
    actual = source(repo, head)
    if len(actual["parents"]) != 2:
        raise ValueError("Main source is not a two-parent merge")
    base, pr_head = actual["parents"]
    if control_change(impact.changed_paths(repo, base, head)):
        raise ValueError("CI control changes require fresh validation")
    remote = api.get(f"git/commits/{head}")
    if (
        remote["sha"] != head
        or remote["tree"]["sha"] != actual["tree"]
        or [p["sha"] for p in remote["parents"]] != actual["parents"]
    ):
        raise ValueError("Main Git source mismatch")
    prs = api.get(f"commits/{head}/pulls?per_page=100")
    if len(prs) != 1:
        raise ValueError("Expected one integrated PR")
    pr = prs[0]
    if (
        pr["merged_at"] is None
        or pr["merge_commit_sha"] != head
        or pr["base"]["ref"] != "main"
        or pr["base"]["repo"]["full_name"] != REPOSITORY
        or pr["head"]["repo"]["full_name"] != REPOSITORY
        or pr["head"]["repo"]["fork"]
        or pr["head"]["sha"] != pr_head
    ):
        raise ValueError("Foreign or unrelated PR")
    listing = api.get(
        f"actions/workflows/ci.yml/runs?event=pull_request&head_sha={pr_head}&per_page=100"
    )
    runs = listing["workflow_runs"]
    if not runs or listing["total_count"] > 100:
        raise ValueError("Missing or excessive producer runs")
    run = max(runs, key=lambda item: item["id"])
    run = api.get(f"actions/runs/{run['id']}")
    complete(run)
    if run["head_sha"] != pr_head:
        raise ValueError("Producer head mismatch")
    age = (
        (now or datetime.now(timezone.utc))
        - datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
    ).total_seconds()
    if not 0 <= age <= MAX_AGE:
        raise ValueError("Expired producer evidence")
    run_id, attempt = run["id"], run["run_attempt"]
    jobs = api.get(f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
    required = [j for j in jobs["jobs"] if j["name"] == "CI required"]
    if (
        jobs["total_count"] > 100
        or len(required) != 1
        or required[0]["status"] != "completed"
        or required[0]["conclusion"] != "success"
    ):
        raise ValueError("Producer aggregate did not succeed")
    artifacts = api.get(f"actions/runs/{run_id}/artifacts?per_page=100")
    matches = [
        a for a in artifacts["artifacts"] if a["name"] == f"ci-proof-{run_id}-{attempt}"
    ]
    if artifacts["total_count"] > 100 or len(matches) != 1:
        raise ValueError("Missing or ambiguous producer artifact")
    artifact = matches[0]
    if artifact["expired"] or not 0 < artifact["size_in_bytes"] <= LIMIT:
        raise ValueError("Unavailable or oversized artifact")
    identity = {
        "run_id": run_id,
        "attempt": attempt,
        "artifact_id": artifact["id"],
        "digest": artifact["digest"],
    }
    if reference is not None and identity != reference:
        raise ValueError("Producer evidence identity changed")
    proof = unpack(api.archive(artifact["id"]), artifact["digest"])
    if (
        proof["repository"] != REPOSITORY
        or proof["workflow"] != WORKFLOW
        or proof["run_id"] != run_id
        or proof["attempt"] != attempt
        or proof["pr"] != {"number": pr["number"], "base": base, "head": pr_head}
        or set(proof["source"]) != {"sha", "tree", "parents"}
        or proof["source"]["tree"] != actual["tree"]
        or proof["source"]["parents"] != actual["parents"]
    ):
        raise ValueError("Evidence does not bind the integrated source")
    tested = proof["source"]["sha"]
    if not isinstance(tested, str) or not re.fullmatch("[0-9a-f]{40}", tested):
        raise ValueError("Invalid tested merge SHA")
    tested_commit = api.get(f"git/commits/{tested}")
    if (
        tested_commit["sha"] != tested
        or tested_commit["tree"]["sha"] != actual["tree"]
        or [p["sha"] for p in tested_commit["parents"]] != actual["parents"]
    ):
        raise ValueError("Synthetic source mismatch")
    impact.validate_ci_results(proof["needs"])
    # These consumers need jobs/artifacts in the main run itself.
    coverage = {
        j
        for j in JOBS
        if proof["needs"]["plan"]["outputs"][j] == "true"
        and proof["needs"][j]["result"] == "success"
    } - {"mobile", "ios", "installer"}
    current = api.get(f"actions/runs/{run_id}")
    complete(current)
    if current["run_attempt"] != attempt or current["head_sha"] != pr_head:
        raise ValueError("Producer attempt changed during verification")
    return coverage, identity


def eligible(env):
    return (
        env.get("GITHUB_EVENT_NAME") == "push"
        and env.get("GITHUB_REF") == "refs/heads/main"
        and env.get("GITHUB_REPOSITORY") == REPOSITORY
    )


def plan(repo, head, jobs, env, api=None):
    if eligible(env):
        try:
            coverage, identity = authenticate(repo, head, api)
            remaining = set(jobs) - coverage
            if "installer" in remaining:
                remaining.add("package")
            return remaining, json.dumps(identity, separators=(",", ":"))
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            subprocess.SubprocessError,
            zipfile.BadZipFile,
            RuntimeError,
            EOFError,
            AttributeError,
            HTTPException,
            zlib.error,
        ):
            pass  # Missing or uncertain proof means ordinary main CI.
    return set(jobs), ""


def validate(repo, head, expected, needs, env, api=None):
    impact.validate_ci_results(needs)
    flags = needs["plan"]["outputs"]
    reference = flags.get("reuse", "")
    if reference:
        if not eligible(env):
            raise ValueError("Reuse is only permitted on canonical main pushes")
        identity = json.loads(reference, object_pairs_hook=impact.json_object)
        if not isinstance(identity, dict) or set(identity) != {
            "run_id",
            "attempt",
            "artifact_id",
            "digest",
        }:
            raise ValueError("Invalid reuse identity")
        coverage, _ = authenticate(repo, head, api, identity)
        expected = set(expected) - coverage
        if "installer" in expected:
            expected.add("package")
    if {j for j in JOBS if flags[j] == "true"} != set(expected):
        raise ValueError("CI selection differs from authenticated expected plan")
