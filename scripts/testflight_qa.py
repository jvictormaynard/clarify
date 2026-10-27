"""MAIN-owned internal QA validation, unsigned archive and isolated export proof.

Run as a module from an immutable, trusted main checkout. Candidate code runs
only in the secret-free producer. The finalizer and signer consume data only.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

from scripts.delivery_policy import affected_components
from scripts import qa_device_archive as device_archive
from scripts import trusted_ci
from scripts.release_delivery import (
    CI_PATH,
    REPOSITORY,
    GitHub,
    ReleaseError,
    build_number,
    decode,
    exact_keys,
    require,
    sha,
    tag_source,
    version,
)

ROOT = Path(__file__).resolve().parents[1]
QA_PATH = ".github/workflows/ios-qa.yml"
STABLE_PATH = ".github/workflows/ios-testflight.yml"
BUNDLE = "com.jvictormaynard.clarify"
APP_ID = "6820869157"
VALIDATION_TRUST_MODEL = "reviewed-source-internal-qa-v1"
VALIDATION_ARTIFACT_PREFIX = "CLARIFY_QA_VALIDATION_ARTIFACT "
VALIDATION_TRANSPORT = "trusted-final-job-log-v1"
FINAL_JOB_NAME = "Finalize trusted validation"
FINAL_STEPS = (
    "Upload trusted validation manifest",
    "Record trusted validation artifact",
)
ARCHIVE_JOB_NAME = "Unsigned Device Release archive"
ARCHIVE_FINAL_JOB_NAME = "Finalize trusted Device archive"
ARCHIVE_SIGN_JOB_NAME = "Experimental trusted export proof"
ARCHIVE_UPLOAD_STEP = "Upload unsigned Device archive"
ARCHIVE_RECORD_STEP = "Record trusted Device archive"
ARCHIVE_STEPS = (
    "Authenticate validation and produce unsigned Device Release archive",
    ARCHIVE_UPLOAD_STEP,
)
ARCHIVE_FINAL_STEPS = (ARCHIVE_RECORD_STEP,)
ARCHIVE_JOB_NAMES = {ARCHIVE_JOB_NAME, ARCHIVE_FINAL_JOB_NAME, ARCHIVE_SIGN_JOB_NAME}
UPLOAD_ACTION = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
DEVELOPER_DIR = "/Applications/Xcode_26.6.app/Contents/Developer"
ARCHIVE_LOCKS = {
    "desktop/package.json",
    "desktop/package-lock.json",
    "mobile/package.json",
    "mobile/package-lock.json",
}
VALIDATION_WORKFLOWS = {
    CI_PATH,
    ".github/workflows/ios-validation.yml",
    ".github/workflows/server-validation.yml",
    ".github/workflows/dependency-audit.yml",
}
VALIDATION_KEYS = (
    "selection",
    "repository",
    "python_linux",
    "python_windows",
    "settings",
    "package_windows",
    "installer_windows",
    "server",
    "mobile",
    "ios_native",
    "ios_build",
    "ios_aggregate",
    "audit_python_linux",
    "audit_python_windows",
    "audit_settings",
    "ci_required",
)
VALIDATION_MINIMUM = {
    "selection",
    "repository",
    "mobile",
    "ios_native",
    "ios_build",
    "ios_aggregate",
    "ci_required",
}
VALIDATION_COMPONENT_KEYS = {
    "desktop": {"python_linux", "python_windows"},
    "settings": {"settings"},
    "package": {"package_windows"},
    "installer": {"installer_windows"},
    "server": {"server"},
    "mobile": {"mobile"},
    "ios": {"ios_native", "ios_build", "ios_aggregate"},
    "audit": {"audit_python_linux", "audit_python_windows", "audit_settings"},
}
POLICY_PATHS = (
    CI_PATH,
    ".github/workflows/ios-validation.yml",
    ".github/workflows/server-validation.yml",
    ".github/workflows/dependency-audit.yml",
    "scripts/delivery_policy.py",
    "scripts/release_delivery.py",
)
NATIVE_JOB = "iOS validation / Native tests and unsigned build"
NATIVE_STEPS = {
    "iOS validation / Native keyboard and library tests": {
        "Run npm run test:native",
        "Test native keyboard and library integration",
    },
    "iOS validation / Unsigned app and extensions build": {
        "Compile app and extensions without signing or upload",
    },
    NATIVE_JOB: {"Require native tests and unsigned compilation"},
}
COMPONENT_JOBS = {
    "desktop": {"Tests (ubuntu-latest)", "Tests (windows-latest)"},
    "settings": {"Settings web and bridge"},
    "package": {"Package Windows executable"},
    "installer": {"Windows installer lifecycle"},
    "server": {"Server validation / Server tests and container"},
    "mobile": {"Mobile checks"},
    "ios": set(NATIVE_STEPS),
    "audit": {
        "Dependency audits / Python audit (ubuntu-latest)",
        "Dependency audits / Python audit (windows-latest)",
        "Dependency audits / Settings dependency audit",
    },
}
CORE_JOBS = {"Select component validation", "Repository checks", "CI required"}
BLOCKER = (
    "Packaging, upload and availability are disabled. Trusted signing/IPA/source "
    "receipts and an identity-parameterized internal availability helper are required."
)
# These main-owned workflows do not publish to Apple. Historical definitions,
# including local reusable workflows/actions, must match before using that fact.
NON_APPLE_WORKFLOWS = {
    ".github/workflows/ci.yml",
    ".github/workflows/community-release.yml",
    ".github/workflows/dependency-audit.yml",
    ".github/workflows/ios-audio-contracts.yml",
    ".github/workflows/ios-validation.yml",
    ".github/workflows/release-preparation.yml",
    ".github/workflows/release-promotion.yml",
    ".github/workflows/release.yml",
    ".github/workflows/server-validation.yml",
    ".github/workflows/shared-account.yml",
}
STABLE_APPLE_HELPERS = (
    "mobile/scripts/verify-ios-ipa.py",
    "mobile/scripts/ios-signing.py",
    "mobile/scripts/ios-signing.rb",
    "mobile/scripts/publish-testflight.cjs",
    "scripts/release_delivery.py",
)


def positive(value, label):
    require(type(value) is int and 1 <= value <= 2**63 - 1, "Invalid " + label)
    return value


def check_validation_trust_model(data):
    require(
        isinstance(data, dict)
        and type(data.get("schema")) is int
        and data["schema"] == 1
        and data.get("trust_model") == VALIDATION_TRUST_MODEL,
        "Unsupported validation trust model",
    )


def inspect_unsigned_device_executable(prefix):
    """Inspect bounded Mach-O header/load-command data without running it.

    The caller supplies the 32-byte header and its declared load commands.
    This checks the three primary executables only. It does not establish
    source provenance, Release configuration, a complete valid image or export
    compatibility. Frameworks and archive contents need separate inspection.
    """
    require(
        isinstance(prefix, bytes) and 32 <= len(prefix) <= 32 + 16 * 1024**2,
        "Invalid or oversized executable header",
    )
    magic, cpu, subtype, kind, count, size, _, reserved = struct.unpack_from(
        "<8I", prefix
    )
    require(
        magic == 0xFEEDFACF
        and cpu == 0x0100000C
        and subtype == 0
        and kind == 2
        and reserved == 0,
        "Expected a thin ARM64 executable",
    )
    require(
        1 <= count <= 4096 and size <= 16 * 1024**2 and 32 + size <= len(prefix),
        "Invalid or truncated executable load commands",
    )
    offset, platforms = 32, []
    for _ in range(count):
        require(offset + 8 <= 32 + size, "Truncated executable command")
        command, length = struct.unpack_from("<2I", prefix, offset)
        require(
            length >= 8 and length % 8 == 0 and offset + length <= 32 + size,
            "Invalid executable command length",
        )
        require(
            command not in {0x1D, 0x24, 0x25, 0x2F, 0x30},
            "Signed or ambiguous executable metadata",
        )
        if command == 0x32:  # LC_BUILD_VERSION in Apple's mach-o/loader.h.
            require(length >= 24, "Truncated platform command")
            _, _, platform, _, _, tools = struct.unpack_from("<6I", prefix, offset)
            require(
                tools <= 1024 and length == 24 + tools * 8,
                "Invalid platform command tools",
            )
            platforms.append(platform)
        offset += length
    require(offset == 32 + size, "Executable command size differs from header")
    require(platforms == [2], "Expected one iOS device platform declaration")
    return dict(architecture="arm64", platform="ios-device", embedded_entitlements=None)


def validation_manifest(plan, contract, jobs, *, workflow, run_id, run_attempt):
    """Build data from a locally recalculated MAIN plan and exact-attempt API jobs.

    The caller must authenticate the checkout, run, workflow and API transport.
    ``plan`` and ``contract`` must come from trusted_ci in that checkout. This
    function does not load a candidate report, approve the final job or publish.
    """
    exact_keys(
        plan,
        {
            "schema",
            "kind",
            "trust_model",
            "source_sha",
            "source_tree",
            "base_sha",
            "base_tree",
            "trusted_sha",
            "components",
            "selected_keys",
            "checks",
            "controls",
        },
    )
    check_validation_trust_model(plan)
    require(plan["kind"] == "clarify-trusted-ci-plan", "Unexpected trusted plan kind")
    for key in ("source_sha", "source_tree", "base_sha", "base_tree", "trusted_sha"):
        sha(plan[key])
    require(
        plan["base_sha"] == plan["trusted_sha"] != plan["source_sha"],
        "Unexpected validation composition",
    )
    for value in (run_id, run_attempt):
        require(
            type(value) is int and 1 <= value <= 2**53 - 1, "Invalid validation run"
        )
    require(run_attempt <= 100, "Invalid validation attempt")
    exact_keys(workflow, {"id", "path", "blob_sha"})
    require(
        type(workflow["id"]) is int
        and 1 <= workflow["id"] <= 2**53 - 1
        and workflow["path"] == QA_PATH,
        "Unexpected validation workflow",
    )
    sha(workflow["blob_sha"])

    exact_keys(contract, VALIDATION_KEYS)
    names = []
    for check in contract.values():
        exact_keys(check, {"job_name", "required_steps"})
        require(
            isinstance(check["job_name"], str)
            and check["job_name"].startswith("Trusted validation / ")
            and isinstance(check["required_steps"], list)
            and check["required_steps"]
            and all(isinstance(name, str) and name for name in check["required_steps"])
            and len(set(check["required_steps"])) == len(check["required_steps"]),
            "Invalid trusted check contract",
        )
        names.append(check["job_name"])
    require(len(set(names)) == len(names), "Duplicate trusted job contract")
    exact_keys(plan["components"], VALIDATION_COMPONENT_KEYS)
    require(
        all(type(flag) is bool for flag in plan["components"].values())
        and plan["components"]["mobile"]
        and plan["components"]["ios"],
        "QA requires mobile and native validation",
    )
    selected = set(VALIDATION_MINIMUM)
    for key, flag in plan["components"].items():
        if flag:
            selected.update(VALIDATION_COMPONENT_KEYS[key])
    ordered = [key for key in VALIDATION_KEYS if key in selected]
    require(
        plan["selected_keys"] == ordered
        and plan["checks"] == {key: contract[key] for key in ordered},
        "Trusted validation selection or controls differ",
    )
    controls = plan["controls"]
    require(
        isinstance(controls, dict) and 1 <= len(controls) <= 4096,
        "Missing or oversized trusted control inventory",
    )
    aliases = set()
    for path, blob in controls.items():
        require(
            isinstance(path, str)
            and len(path) <= 512
            and re.fullmatch(r"[A-Za-z0-9_.+@/-]+", path)
            and not path.startswith("/")
            and not any(part in {"", ".", ".."} for part in path.split("/"))
            and path.casefold() not in aliases,
            "Invalid trusted control path",
        )
        aliases.add(path.casefold())
        sha(blob)

    require(
        isinstance(jobs, list) and len(jobs) <= len(VALIDATION_KEYS),
        "Invalid validation executor jobs",
    )
    by_name, identifiers = {}, set()
    selected_names = {contract[key]["job_name"] for key in ordered}
    for job in jobs:
        require(isinstance(job, dict), "Invalid validation job")
        identifier = job.get("id")
        require(
            type(identifier) is int
            and 1 <= identifier <= 2**53 - 1
            and identifier not in identifiers,
            "Invalid or duplicate API job ID",
        )
        identifiers.add(identifier)
        name = job.get("name")
        require(
            isinstance(name, str) and name in names and name not in by_name,
            "Unknown or duplicate validation job",
        )
        require(
            job.get("run_id") == run_id
            and type(job.get("run_id")) is int
            and job.get("head_sha") == plan["trusted_sha"]
            and job.get("status") == "completed"
            and job.get("conclusion")
            == ("success" if name in selected_names else "skipped"),
            "Validation job is not the required successful execution",
        )
        if "run_attempt" in job:
            require(
                type(job["run_attempt"]) is int and job["run_attempt"] == run_attempt,
                "Validation job belongs to another attempt",
            )
        by_name[name] = job

    checks = {}
    for key in ordered:
        expected = contract[key]
        require(expected["job_name"] in by_name, "Mandatory validation job is missing")
        job = by_name[expected["job_name"]]
        steps = job.get("steps")
        require(
            isinstance(steps, list) and 1 <= len(steps) <= 256,
            "Missing or oversized validation steps",
        )
        numbers = [step.get("number") for step in steps if isinstance(step, dict)]
        require(
            len(numbers) == len(steps)
            and all(type(number) is int and number >= 1 for number in numbers)
            and numbers == sorted(set(numbers)),
            "Unknown validation step ordering",
        )
        required_steps, positions = [], []
        for name in expected["required_steps"]:
            matches = [
                (index, step)
                for index, step in enumerate(steps)
                if step.get("name") == name
            ]
            require(len(matches) == 1, "Missing or duplicate mandatory validation step")
            position, step = matches[0]
            require(
                step.get("status") == "completed"
                and step.get("conclusion") == "success",
                "Mandatory validation step is unsuccessful",
            )
            positions.append(position)
            required_steps.append(
                {
                    field: step[field]
                    for field in ("name", "number", "status", "conclusion")
                }
            )
        require(
            positions == sorted(positions), "Mandatory validation steps changed order"
        )
        checks[key] = dict(
            job_id=job["id"],
            job_name=job["name"],
            status="completed",
            conclusion="success",
            steps=required_steps,
        )
    return dict(
        schema=1,
        trust_model=VALIDATION_TRUST_MODEL,
        repository=REPOSITORY,
        pr=179,
        **{
            key: plan[key]
            for key in (
                "source_sha",
                "source_tree",
                "base_sha",
                "base_tree",
                "trusted_sha",
            )
        },
        workflow=deepcopy(workflow),
        run_id=run_id,
        run_attempt=run_attempt,
        controls=deepcopy(controls),
        checks=checks,
    )


def _validation_artifact_record(data, *, run_id, run_attempt):
    exact_keys(
        data,
        {"artifact_id", "artifact_name", "artifact_digest", "run_id", "run_attempt"},
    )
    for value in (
        run_id,
        run_attempt,
        data["artifact_id"],
        data["run_id"],
        data["run_attempt"],
    ):
        require(
            type(value) is int and 1 <= value <= 2**53 - 1, "Invalid artifact identity"
        )
    require(1 <= run_attempt <= 100, "Invalid validation attempt")
    require(
        data["run_id"] == run_id
        and data["run_attempt"] == run_attempt
        and data["artifact_name"] == f"clarify-qa-validation-{run_id}-{run_attempt}",
        "Validation artifact belongs to another execution",
    )
    require(
        isinstance(data["artifact_digest"], str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", data["artifact_digest"]) is not None,
        "Invalid validation artifact digest",
    )
    return data


def format_validation_artifact_record(
    *, artifact_id, artifact_digest, run_id, run_attempt
):
    require(
        isinstance(artifact_digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", artifact_digest) is not None,
        "Invalid upload artifact digest",
    )
    record = _validation_artifact_record(
        dict(
            artifact_id=artifact_id,
            artifact_name=f"clarify-qa-validation-{run_id}-{run_attempt}",
            artifact_digest="sha256:" + artifact_digest,
            run_id=run_id,
            run_attempt=run_attempt,
        ),
        run_id=run_id,
        run_attempt=run_attempt,
    )
    return VALIDATION_ARTIFACT_PREFIX + json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        ensure_ascii=True,
    )


def parse_validation_artifact_record(log, *, run_id, run_attempt):
    require(isinstance(log, str), "Missing validation artifact log")
    try:
        encoded = log.encode("utf-8")
    except UnicodeError:
        raise ReleaseError("Malformed validation artifact log") from None
    require(len(encoded) <= 1024 * 1024, "Validation artifact log is too large")
    records = []
    for raw_line in log.splitlines():
        line = re.sub(
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z ",
            "",
            raw_line,
            count=1,
        )
        if line.startswith(VALIDATION_ARTIFACT_PREFIX):
            try:
                records.append(decode(line[len(VALIDATION_ARTIFACT_PREFIX) :]))
            except (ReleaseError, ValueError, RecursionError):
                raise ReleaseError("Malformed validation artifact record") from None
        else:
            require(
                VALIDATION_ARTIFACT_PREFIX not in line, "Unknown validation log format"
            )
    require(len(records) == 1, "Missing or ambiguous validation artifact record")
    return _validation_artifact_record(
        records[0], run_id=run_id, run_attempt=run_attempt
    )


def canonical_validation_json(value):
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


class ValidationGitHub(GitHub):
    """Reuse MAIN JSON transport; bound binary responses without credential redirects."""

    def binary(self, path, *, limit):
        require(
            re.fullmatch(
                r"/actions/(?:jobs/[1-9][0-9]*/logs|artifacts/[1-9][0-9]*/zip)", path
            )
            is not None,
            "Unknown validation binary endpoint",
        )
        url = self.base + path
        require(
            url.startswith("https://api.github.com/repos/" + REPOSITORY + "/"),
            "Unknown validation API origin",
        )
        opener = build_opener(_NoRedirect())
        for redirect in range(4):
            parts = urlsplit(url)
            require(
                parts.scheme == "https"
                and bool(parts.hostname)
                and parts.username is None
                and parts.password is None
                and parts.port in {None, 443}
                and not parts.fragment,
                "Unsafe validation download redirect",
            )
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if redirect == 0:
                headers["Authorization"] = "Bearer " + self.token
            try:
                with opener.open(Request(url, headers=headers), timeout=30) as response:
                    require(
                        response.status == 200, "Validation download is unavailable"
                    )
                    data = response.read(limit + 1)
                    require(len(data) <= limit, "Validation download exceeds its limit")
                    return data
            except HTTPError as error:
                if error.code in {301, 302, 303, 307, 308} and redirect < 3:
                    locations = error.headers.get_all("Location", [])
                    require(
                        len(locations) == 1 and bool(locations[0]),
                        "Ambiguous validation download redirect",
                    )
                    url = urljoin(url, locations[0])
                    error.close()
                    continue
                raise ReleaseError("Validation download is unavailable") from None
            except (URLError, OSError, ValueError):
                raise ReleaseError("Validation download is unavailable") from None
        raise ReleaseError("Validation download redirect limit exceeded")


def safe_workflow_document(data, *, trusted_repo=ROOT, node=None, yaml_module=None):
    """Parse authenticated MAIN bytes with its locked Node YAML dependency."""
    require(type(data) is bytes and len(data) <= 256 * 1024, "Workflow size limit")
    node = node or shutil.which("node")
    require(node is not None, "Pinned Node is required for trusted YAML parsing")
    yaml_module = yaml_module or Path(trusted_repo) / "desktop/node_modules/yaml"
    program = r"""
const fs = require('node:fs');
const YAML = require(process.argv[1]);
try {
  const doc = YAML.parseDocument(fs.readFileSync(0, 'utf8'), {uniqueKeys: true});
  if (doc.errors.length || doc.warnings.length || !YAML.isMap(doc.contents)) throw 0;
  let count = 0;
  YAML.visit(doc, (key, value, path) => {
    if (++count > 20000 || path.length > 64 || YAML.isAlias(value) ||
        value?.tag || value?.anchor) throw 0;
    if (YAML.isPair(value) && (!YAML.isScalar(value.key) ||
        typeof value.key.value !== 'string' ||
        ['__proto__', 'prototype', 'constructor'].includes(value.key.value))) throw 0;
  });
  const result = JSON.stringify(doc.toJS({maxAliasCount: 0}));
  if (Buffer.byteLength(result) > 1024 * 1024) throw 0;
  process.stdout.write(result);
} catch { process.exitCode = 1; }
"""
    result = subprocess.run(
        [str(node), "-e", program, str(yaml_module)],
        input=data,
        cwd=trusted_repo,
        capture_output=True,
        timeout=30,
        check=False,
        env={
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "SystemRoot", "SYSTEMROOT", "TEMP", "TMP"}
        },
    )
    require(
        result.returncode == 0 and len(result.stdout) <= 1024 * 1024,
        "Unsafe or unavailable MAIN workflow YAML",
    )
    document = decode(result.stdout)
    require(type(document) is dict, "Invalid MAIN workflow document")
    return document


def archive_controls(trusted_repo, trusted_sha):
    tree = trusted_ci.git_tree(trusted_repo, trusted_sha)
    require(ARCHIVE_LOCKS <= tree.keys(), "Missing MAIN archive dependency locks")
    paths = set(trusted_ci.control_inventory(trusted_repo, trusted_sha)) | ARCHIVE_LOCKS
    paths.update(p for p in tree if p.endswith("/.npmrc") or p == ".npmrc")
    require(
        {
            QA_PATH,
            device_archive.MODULE,
            device_archive.SIGNING_HELPER,
            "scripts/testflight_qa.py",
            "scripts/release_delivery.py",
            "scripts/delivery_policy.py",
            "scripts/trusted_ci.py",
            "mobile/app.json",
            "mobile/third-party/KeyboardHostBundleID/LICENSE",
        }
        <= paths,
        "Missing MAIN archive controls",
    )
    return {p: tree[p]["blob"] for p in sorted(paths)}


class ArchiveGitHub(ValidationGitHub):
    """Bounded API and streaming transport; MAIN controls come from local Git."""

    def __init__(self, token, *, trusted_repo=ROOT):
        super().__init__(token)
        self.trusted_repo = Path(trusted_repo)
        self._controls = {}
        self._final_jobs = set()

    def request(self, method, path, body=None, *, missing=False):
        require(
            method == "GET"
            and body is None
            and type(path) is str
            and path.startswith("/")
            and ".." not in path.split("/")
            and self.base == "https://api.github.com/repos/" + REPOSITORY,
            "Unknown archive API request",
        )
        try:
            request = Request(
                self.base + path,
                headers={
                    "Authorization": "Bearer " + self.token,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            with build_opener(_NoRedirect()).open(request, timeout=30) as response:
                require(response.status == 200, "Archive API unavailable")
                data = response.read(12 * 1024**2 + 1)
                require(len(data) <= 12 * 1024**2, "Archive API size limit")
                return decode(data)
        except HTTPError as error:
            if missing and error.code == 404:
                return None
            raise ReleaseError("Archive API unavailable") from None
        except (URLError, OSError):
            raise ReleaseError("Archive API unavailable") from None

    def main(self):
        return {"sha": self.request("GET", "/git/ref/heads/main")["object"]["sha"]}

    def pull_request(self, number):
        require(type(number) is int and number == 179, "Unknown archive PR")
        return self.request("GET", "/pulls/179")

    def commit(self, revision):
        return self.request("GET", "/git/commits/" + sha(revision))

    def control(self, revision, path):
        sha(revision)
        if revision not in self._controls:
            require(
                trusted_ci.git(self.trusted_repo, "rev-parse", "HEAD").decode().strip()
                == revision,
                "Archive controls require the MAIN checkout",
            )
            tree_sha = (
                trusted_ci.git(self.trusted_repo, "rev-parse", revision + "^{tree}")
                .decode()
                .strip()
            )
            commit = self.commit(revision)
            require(
                commit.get("sha") == revision
                and commit.get("tree", {}).get("sha") == tree_sha,
                "Archive MAIN commit/tree differs",
            )
            inventory = archive_controls(self.trusted_repo, revision)
            tree = trusted_ci.git_tree(self.trusted_repo, revision)
            blobs = trusted_ci.git_blobs(
                self.trusted_repo, {p: tree[p] for p in inventory}
            )
            values = {}
            for name, blob in inventory.items():
                data = blobs[blob]
                file = device_archive.absolute_path(self.trusted_repo / name)
                require(
                    device_archive.git_blob(data) == blob and file.read_bytes() == data,
                    "Local MAIN archive control differs",
                )
                values[name] = data
            self._controls[revision] = values
        require(path in self._controls[revision], "Unknown MAIN archive control")
        return self._controls[revision][path]

    def workflow_document(self, data):
        return safe_workflow_document(data, trusted_repo=self.trusted_repo)

    def run(self, run_id, attempt):
        positive(run_id, "archive run")
        require(type(attempt) is int and 1 <= attempt <= 100, "Invalid archive attempt")
        return self.request("GET", f"/actions/runs/{run_id}/attempts/{attempt}")

    def jobs(self, run_id, attempt):
        positive(run_id, "archive run")
        require(type(attempt) is int and 1 <= attempt <= 100, "Invalid archive attempt")
        jobs = self.pages(f"/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
        require(
            type(jobs) is list
            and 1 <= len(jobs) <= 23
            and all(
                type(j) is dict and type(j.get("id")) is int and j["id"] > 0
                for j in jobs
            )
            and len({j["id"] for j in jobs}) == len(jobs)
            and len({j.get("name") for j in jobs}) == len(jobs),
            "Invalid archive exact-attempt jobs",
        )
        inactive = {c["job_name"] for c in trusted_ci.CHECKS.values()} | {
            FINAL_JOB_NAME,
            "Internal QA preflight",
            "Trusted validation",
            "Authenticate trusted validation dispatch",
            ARCHIVE_SIGN_JOB_NAME,
        }
        require(
            all(
                j.get("name") in {ARCHIVE_JOB_NAME, ARCHIVE_FINAL_JOB_NAME}
                or (
                    j.get("name") in inactive
                    and j.get("status") == "completed"
                    and j.get("conclusion") == "skipped"
                )
                for j in jobs
            ),
            "Unexpected active or unknown archive job",
        )
        self._final_jobs = {
            j["id"]
            for j in jobs
            if j.get("name") == ARCHIVE_FINAL_JOB_NAME
            and j.get("run_id") == run_id
            and j.get("status") == "completed"
            and j.get("conclusion") == "success"
        }
        return dict(run_id=run_id, run_attempt=attempt, jobs=jobs)

    def artifact(self, artifact_id):
        return self.request(
            "GET", f"/actions/artifacts/{positive(artifact_id, 'artifact')}"
        )

    def job_log(self, job_id):
        require(
            job_id in self._final_jobs,
            "Only the authenticated final job log is allowed",
        )
        return self.binary(
            f"/actions/jobs/{positive(job_id, 'job')}/logs", limit=1024**2
        )

    def download_artifact(self, artifact_id, destination, *, max_bytes):
        positive(artifact_id, "artifact")
        require(
            type(max_bytes) is int and 0 < max_bytes <= 2 * 1024**3,
            "Invalid archive download bound",
        )
        target = device_archive.absolute_path(destination, exists=False)
        require(not target.exists(), "Archive download destination must be fresh")
        url = self.base + f"/actions/artifacts/{artifact_id}/zip"
        require(
            self.base == "https://api.github.com/repos/" + REPOSITORY,
            "Unknown archive API origin",
        )
        opener = build_opener(_NoRedirect())
        created = False
        try:
            for redirect in range(4):
                parts = urlsplit(url)
                require(
                    parts.scheme == "https"
                    and bool(parts.hostname)
                    and parts.username is None
                    and parts.password is None
                    and parts.port in {None, 443}
                    and not parts.fragment,
                    "Unsafe archive download redirect",
                )
                headers = {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                if redirect == 0:
                    headers["Authorization"] = "Bearer " + self.token
                try:
                    with opener.open(
                        Request(url, headers=headers), timeout=30
                    ) as response:
                        require(response.status == 200, "Archive download unavailable")
                        with target.open("xb") as output:
                            created = True
                            total = 0
                            while True:
                                chunk = response.read(
                                    min(1024**2, max_bytes - total + 1)
                                )
                                if not chunk:
                                    break
                                total += len(chunk)
                                require(
                                    total <= max_bytes, "Archive download size limit"
                                )
                                output.write(chunk)
                        return
                except HTTPError as error:
                    if error.code in {301, 302, 303, 307, 308} and redirect < 3:
                        locations = error.headers.get_all("Location", [])
                        require(
                            len(locations) == 1 and bool(locations[0]),
                            "Ambiguous archive redirect",
                        )
                        url = urljoin(url, locations[0])
                        error.close()
                        continue
                    raise ReleaseError("Archive download unavailable") from None
            raise ReleaseError("Archive download redirect limit")
        except BaseException:
            if created:
                target.unlink(missing_ok=True)
            raise


def _validation_origin(api, inputs, context, trusted_repo):
    exact_keys(inputs, {"source_sha", "base_sha", "trusted_sha"})
    for value in inputs.values():
        sha(value)
    # This context is built from the fresh job's runtime and dispatch event, never a report.
    trusted = validate_context(context | {"mode": "preflight"})
    require(context["mode"] == "validate", BLOCKER)
    require(
        inputs["trusted_sha"] == inputs["base_sha"] == trusted != inputs["source_sha"],
        "Unexpected trusted validation composition",
    )
    trusted_repo = Path(trusted_repo)
    require(
        trusted_ci.git(trusted_repo, "rev-parse", "HEAD").decode().strip() == trusted,
        "Verifier checkout differs from trusted MAIN",
    )
    for actor in {context["actor"], context["triggering_actor"]}:
        require(
            isinstance(actor, str) and re.fullmatch(r"[A-Za-z0-9-]{1,100}", actor),
            "Missing maintainer identity",
        )
        permission = api.request("GET", f"/collaborators/{actor}/permission")
        require(
            (permission.get("role_name"), permission.get("permission"))
            in {("admin", "admin"), ("maintain", "write")},
            "Only a maintainer can dispatch or rerun QA",
        )
    _validation_current_source(api, inputs)
    comparison = api.request("GET", f"/compare/{trusted}...{inputs['source_sha']}")
    require(
        comparison.get("status") == "ahead"
        and comparison.get("merge_base_commit", {}).get("sha") == trusted,
        "Candidate does not incorporate exact current main",
    )
    # Identity is read as data. Validation does not reserve or require a new Apple build.
    app_identity(api, inputs["source_sha"])
    relay = decode(api.file("shared/computer_connect.json", inputs["source_sha"]))
    exact_keys(relay, {"schema_version", "relay_host", "relay_port"})
    require(
        type(relay["schema_version"]) is int
        and relay["schema_version"] == 1
        and relay["relay_host"] is None
        and type(relay["relay_port"]) is int
        and 1 <= relay["relay_port"] <= 65535,
        "Relay configuration must remain null",
    )
    plan = trusted_ci.build_plan(
        trusted_repo, trusted_repo, trusted, inputs["base_sha"], inputs["source_sha"]
    )
    require(
        trusted_ci.TRUST_MODEL == VALIDATION_TRUST_MODEL
        and tuple(trusted_ci.CHECKS) == VALIDATION_KEYS,
        "Unknown trusted CI contract",
    )
    tree = trusted_ci.git_tree(trusted_repo, trusted)
    inventory = trusted_ci.control_inventory(trusted_repo, trusted)
    require(inventory == plan["controls"], "Trusted control inventory differs")
    required = VALIDATION_WORKFLOWS | {
        QA_PATH,
        ".github/actions/settings-build/action.yml",
        "pyproject.toml",
        "scripts/testflight_qa.py",
        "scripts/trusted_ci.py",
        "scripts/release_delivery.py",
        "scripts/delivery_policy.py",
    }
    require(required <= inventory.keys(), "Missing trusted control inputs")
    blobs = trusted_ci.git_blobs(trusted_repo, {p: tree[p] for p in inventory})
    for path, blob in inventory.items():
        file = trusted_repo / path
        require(
            not any(
                p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                for p in (file, *file.parents)
            ),
            "Linked trusted control input",
        )
        require(
            file.is_file() and file.read_bytes() == blobs[blob],
            "Executed trusted control differs from its Git blob",
        )
    for revision, expected in {
        trusted: plan["base_tree"],
        inputs["source_sha"]: plan["source_tree"],
    }.items():
        commit = api.request("GET", "/git/commits/" + revision)
        require(
            commit.get("sha") == revision
            and commit.get("tree", {}).get("sha") == expected,
            "API source or trusted Git tree differs",
        )
    run_id, attempt = context["run_id"], context["run_attempt"]
    run = api.request("GET", f"/actions/runs/{run_id}/attempts/{attempt}")
    require(
        type(run.get("id")) is int
        and run["id"] == run_id
        and type(run.get("run_attempt")) is int
        and run["run_attempt"] == attempt
        and run.get("repository", {}).get("full_name") == REPOSITORY
        and run.get("head_repository", {}).get("full_name") == REPOSITORY
        and run.get("event") == "workflow_dispatch"
        and run.get("head_branch") == "main"
        and run.get("head_sha") == trusted
        and run.get("workflow_sha", trusted) == trusted
        and run.get("path")
        in {QA_PATH, QA_PATH + "@refs/heads/main", QA_PATH + "@main"},
        "Validation run is not the exact trusted MAIN attempt",
    )
    workflow_id = run.get("workflow_id")
    require(
        type(workflow_id) is int and 1 <= workflow_id <= 2**53 - 1,
        "Invalid validation workflow ID",
    )
    workflow = api.request("GET", f"/actions/workflows/{workflow_id}")
    require(
        workflow.get("id") == workflow_id and workflow.get("path") == QA_PATH,
        "Unexpected validation workflow identity",
    )
    return plan, run, dict(id=workflow_id, path=QA_PATH, blob_sha=inventory[QA_PATH])


def _validation_current_source(api, inputs):
    require(
        api.request("GET", "/git/ref/heads/main").get("object", {}).get("sha")
        == inputs["trusted_sha"],
        "Main advanced; recompose and run new validation",
    )
    check_pr(api, inputs)


def _validation_graph(run, plan):
    references = run.get("referenced_workflows")
    require(
        isinstance(references, list) and 1 <= len(references) <= 4,
        "Missing or oversized executed reusable workflow graph",
    )
    observed = set()
    for item in references:
        require(isinstance(item, dict), "Invalid executed reusable workflow")
        path = item.get("path", "")
        allowed = {
            f"{REPOSITORY}/{p}@{ref}": p
            for p in VALIDATION_WORKFLOWS
            for ref in ("main", "refs/heads/main", plan["trusted_sha"])
        }
        require(
            path in allowed
            and allowed[path] not in observed
            and item.get("sha") == plan["trusted_sha"]
            and item.get("ref", "refs/heads/main")
            in {"refs/heads/main", plan["trusted_sha"]},
            "Executed reusable workflow differs from trusted MAIN allowlist",
        )
        observed.add(allowed[path])
    required = {CI_PATH, ".github/workflows/ios-validation.yml"}
    if plan["components"]["server"]:
        required.add(".github/workflows/server-validation.yml")
    if plan["components"]["audit"]:
        required.add(".github/workflows/dependency-audit.yml")
    require(required <= observed, "Missing executed trusted reusable workflow")


def _validation_api_manifest(api, inputs, context, trusted_repo, *, completed):
    plan, run, workflow = _validation_origin(api, inputs, context, trusted_repo)
    _validation_graph(
        run, plan
    )  # Authenticate execution before interpreting omissions/skips.
    if completed:
        require(
            run.get("status") == "completed" and run.get("conclusion") == "success",
            "Validation run is not successfully completed",
        )
    else:
        require(
            (run.get("status"), run.get("conclusion"))
            in {("in_progress", None), ("completed", "success")},
            "Validation run cannot finalize",
        )
    jobs = api.pages(
        f"/actions/runs/{context['run_id']}/attempts/{context['run_attempt']}/jobs",
        "jobs",
    )
    require(
        isinstance(jobs, list) and 1 <= len(jobs) <= 23, "Invalid exact-attempt jobs"
    )
    require(
        all(
            isinstance(j, dict)
            and type(j.get("id")) is int
            and 1 <= j["id"] <= 2**53 - 1
            for j in jobs
        ),
        "Invalid exact-attempt job ID",
    )
    require(
        len({j["id"] for j in jobs}) == len(jobs)
        and len({j.get("name") for j in jobs}) == len(jobs),
        "Duplicate exact-attempt job",
    )
    names = {c["job_name"] for c in trusted_ci.CHECKS.values()}
    # Caller-only jobs never supply a product result.
    require(
        all(
            isinstance(j, dict)
            and j.get("name")
            in names
            | ARCHIVE_JOB_NAMES
            | {
                FINAL_JOB_NAME,
                "Internal QA preflight",
                "Authenticate trusted validation dispatch",
            }
            for j in jobs
        ),
        "Unexpected exact-attempt job",
    )
    require(
        all(
            j.get("status") == "completed" and j.get("conclusion") == "skipped"
            for j in jobs
            if j.get("name") in ARCHIVE_JOB_NAMES
        ),
        "Archive jobs must be skipped in a validation run",
    )
    final = [j for j in jobs if j.get("name") == FINAL_JOB_NAME]
    require(len(final) == 1, "Missing or duplicate final trusted job")
    manifest = validation_manifest(
        plan,
        trusted_ci.CHECKS,
        [j for j in jobs if j["name"] in names],
        workflow=workflow,
        run_id=context["run_id"],
        run_attempt=context["run_attempt"],
    )
    if completed:
        _successful_final(final[0], context, plan["trusted_sha"])
    _validation_current_source(api, inputs)
    return manifest, final[0], plan


def _successful_final(job, context, trusted):
    require(
        type(job.get("id")) is int
        and 1 <= job["id"] <= 2**53 - 1
        and type(job.get("run_id")) is int
        and job["run_id"] == context["run_id"]
        and job.get("head_sha") == trusted
        and job.get("status") == "completed"
        and job.get("conclusion") == "success"
        and (
            "run_attempt" not in job
            or (
                type(job["run_attempt"]) is int
                and job["run_attempt"] == context["run_attempt"]
            )
        ),
        "Final trusted job is not the exact successful execution",
    )
    steps = job.get("steps")
    require(
        isinstance(steps, list)
        and 2 <= len(steps) <= 256
        and all(
            isinstance(s, dict) and type(s.get("number")) is int and s["number"] >= 1
            for s in steps
        ),
        "Invalid final job steps",
    )
    numbers = [s["number"] for s in steps]
    require(numbers == sorted(set(numbers)), "Ambiguous final step ordering")
    positions = []
    for name in FINAL_STEPS:
        matches = [i for i, s in enumerate(steps) if s.get("name") == name]
        require(len(matches) == 1, "Missing or duplicate final required step")
        position = matches[0]
        require(
            steps[position].get("status") == "completed"
            and steps[position].get("conclusion") == "success",
            "Final required step is unsuccessful",
        )
        positions.append(position)
    require(positions == sorted(positions), "Final upload must precede its record")


def finalize_validation(api, inputs, context, *, trusted_repo=ROOT, outputs=None):
    manifest, _, plan = _validation_api_manifest(
        api, inputs, context, trusted_repo, completed=False
    )
    if outputs is not None:
        expected = dict(
            selected_keys=trusted_ci.canonical_json(plan["selected_keys"]),
            source_tree=plan["source_tree"],
            base_tree=plan["base_tree"],
            plan_digest=trusted_ci.digest(plan),
            controls_digest=trusted_ci.digest(plan["controls"]),
        )
        require(
            outputs == expected, "Reusable outputs differ from recomputed MAIN plan"
        )
    return manifest


def consume_validation(api, inputs, context, *, trusted_repo=ROOT):
    """Model A consistency only. No Apple action can use this as publication authority."""
    expected, final, _ = _validation_api_manifest(
        api, inputs, context, trusted_repo, completed=True
    )
    # Transport is MAIN literal policy. Step numbers identify order only.
    require(
        VALIDATION_TRANSPORT == "trusted-final-job-log-v1",
        "Unknown validation transport",
    )
    raw = api.binary(f"/actions/jobs/{final['id']}/logs", limit=1024 * 1024)
    require(
        isinstance(raw, bytes) and len(raw) <= 1024 * 1024,
        "Invalid final trusted job log",
    )
    try:
        log = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise ReleaseError("Malformed final trusted job log") from None
    record = parse_validation_artifact_record(
        log, run_id=context["run_id"], run_attempt=context["run_attempt"]
    )
    artifact = api.request("GET", f"/actions/artifacts/{record['artifact_id']}")
    require(
        type(artifact.get("id")) is int
        and artifact["id"] == record["artifact_id"]
        and artifact.get("name") == record["artifact_name"]
        and artifact.get("digest") == record["artifact_digest"]
        and artifact.get("expired") is False
        and type(artifact.get("workflow_run", {}).get("id")) is int
        and artifact["workflow_run"]["id"] == context["run_id"]
        and artifact["workflow_run"].get("head_sha") == inputs["trusted_sha"],
        "Validation artifact differs from final uploader record",
    )
    archive = api.binary(
        f"/actions/artifacts/{record['artifact_id']}/zip", limit=1024 * 1024
    )
    require(
        isinstance(archive, bytes)
        and len(archive) <= 1024 * 1024
        and "sha256:" + hashlib.sha256(archive).hexdigest()
        == record["artifact_digest"],
        "Validation artifact download digest differs",
    )
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            entries = zipped.infolist()
            require(
                len(entries) == 1 and entries[0].filename == "validation.json",
                "Validation artifact must contain only validation.json",
            )
            entry = entries[0]
            kind = stat.S_IFMT(entry.external_attr >> 16)
            require(
                kind in {0, stat.S_IFREG}
                and entry.orig_filename == entry.filename
                and not entry.is_dir()
                and not entry.flag_bits & 1
                and 0 < entry.file_size < 256 * 1024
                and entry.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                and entry.file_size <= max(1, entry.compress_size) * 1000,
                "Unsafe validation artifact ZIP entry",
            )
            with zipped.open(entry) as stream:
                data = stream.read(256 * 1024)
            require(len(data) == entry.file_size, "Validation artifact size differs")
            manifest = decode(data.decode("utf-8", errors="strict"))
    except ReleaseError:
        raise
    except (
        zipfile.BadZipFile,
        RuntimeError,
        UnicodeError,
        EOFError,
        ValueError,
        RecursionError,
    ):
        raise ReleaseError("Malformed validation artifact ZIP") from None
    check_validation_trust_model(manifest)
    require(
        manifest == expected and data == canonical_validation_json(expected),
        "Validation artifact differs from authenticated MAIN/API observations",
    )
    _validation_current_source(api, inputs)
    return manifest


def validate_metadata(data, now):
    exact_keys(
        data,
        {
            "schema",
            "pr",
            "source_sha",
            "base_sha",
            "app_id",
            "bundle_id",
            "version",
            "build",
            "tag",
            "relay_host",
            "reservation",
        },
    )
    require(type(data["schema"]) is int and data["schema"] == 1, "Unknown QA schema")
    require(type(data["pr"]) is int and data["pr"] == 179, "Only PR 179 is in scope")
    sha(data["source_sha"])
    sha(data["base_sha"])
    version(data["version"])
    build_number(data["build"])
    require(
        data["bundle_id"] == BUNDLE and data["app_id"] == APP_ID,
        "Unexpected Apple application identity",
    )
    require(
        data["tag"] == f"ios/pr-179/v{data['version']}-build{data['build']}",
        "Use the immutable PR 179 QA tag",
    )
    require(data["relay_host"] is None, "Relay must remain null; WAN is not delivered")
    evidence = data["reservation"]
    exact_keys(
        evidence,
        {"highest_build", "pending_builds_checked", "checked_at", "report_url"},
    )
    build_number(evidence["highest_build"])
    require(
        evidence["pending_builds_checked"] is True,
        "Check existing builds, reservations and pending uploads for this identity",
    )
    try:
        checked = datetime.strptime(
            evidence["checked_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as error:
        raise ReleaseError("Use an exact UTC reservation timestamp") from error
    require(
        0 <= (now - checked).total_seconds() <= 86400, "Reservation evidence is stale"
    )
    require(
        isinstance(evidence["report_url"], str)
        and re.fullmatch(
            r"https://github\.com/jvictormaynard/clarify/(?:issues|pull|actions/runs)/[1-9][0-9]*(?:#[A-Za-z0-9_-]+)?",
            evidence["report_url"],
        ),
        "Use a canonical reservation report",
    )
    return data


def validate_context(ctx):
    require(
        ctx["repository"] == REPOSITORY
        and ctx["event"] == "workflow_dispatch"
        and ctx["ref"] == "refs/heads/main"
        and ctx["workflow_ref"] == f"{REPOSITORY}/{QA_PATH}@refs/heads/main",
        "QA requires a manual dispatch of the trusted main workflow",
    )
    trusted = sha(ctx["workflow_sha"])
    require(
        ctx["sha"] == trusted == ctx["checkout_sha"],
        "Workflow and verifier must use the same immutable trusted main SHA",
    )
    positive(ctx["run_id"], "workflow run")
    require(
        type(ctx["run_attempt"]) is int and 1 <= ctx["run_attempt"] <= 100,
        "Invalid workflow attempt",
    )
    require(ctx["mode"] == "preflight", BLOCKER)
    return trusted


def app_identity(api, source):
    app = decode(api.file("mobile/app.json", sha(source)))["expo"]
    require(app["ios"]["bundleIdentifier"] == BUNDLE, "Unknown application bundle")
    version(app["version"])
    build_number(app["ios"]["buildNumber"])
    return BUNDLE, app["version"], app["ios"]["buildNumber"]


def check_pr(api, data):
    pr = api.request("GET", "/pulls/179")
    require(
        pr.get("number") == 179
        and pr.get("state") == "open"
        and pr.get("draft") is False
        and pr.get("merged") is False
        and pr.get("mergeable") is True,
        "PR 179 must be open, ready, unmerged and conflict-free",
    )
    require(
        pr.get("head", {}).get("repo", {}).get("full_name") == REPOSITORY
        and pr.get("base", {}).get("repo", {}).get("full_name") == REPOSITORY
        and pr["base"].get("ref") == "main"
        and pr["base"].get("sha") == data["base_sha"]
        and pr["head"].get("sha") == data["source_sha"]
        and pr["head"].get("ref") != "codex/ios-testflight",
        "PR source and current main must match the exact candidate composition",
    )


def check_policy(api, data):
    # Read routing policy from the trusted checkout only. Never import PR code.
    for path in POLICY_PATHS:
        trusted = (ROOT / path).read_text(encoding="utf-8")
        require(
            api.file(path, data["base_sha"]) == trusted,
            "Trusted CI policy differs from the immutable checkout",
        )
        require(
            api.file(path, data["source_sha"]) == trusted,
            "PR changes CI policy; omitted checks cannot authorize QA",
        )
    files = api.pages("/pulls/179/files")
    require(bool(files) and len(files) < 3000, "Missing or truncated PR change range")
    paths = []
    for item in files:
        path = item["filename"]
        require(
            isinstance(path, str)
            and path
            and not path.startswith("/")
            and ".." not in path.split("/")
            and "\\" not in path,
            "Unknown candidate source path",
        )
        for name in (path, item.get("previous_filename", path)):
            require(
                not name.startswith((".github/workflows/", ".github/actions/")),
                "Restore all candidate workflow/action files to exact main policy",
            )
        paths.append(path)
    return affected_components(paths)


def check_ci(api, source, base, *, pull_request, selected):
    events = ("pull_request",) if pull_request else ("push", "workflow_dispatch")
    runs = []
    for event in events:
        runs.extend(
            api.pages(
                f"/actions/workflows/ci.yml/runs?head_sha={source}&event={event}",
                "workflow_runs",
            )
        )
    require(bool(runs), "Missing CI for the exact source")
    run = max(runs, key=lambda row: (positive(row["id"], "CI run"), row["run_attempt"]))
    require(
        run.get("repository", {}).get("full_name") == REPOSITORY
        and run.get("head_repository", {}).get("full_name") == REPOSITORY
        and run.get("head_sha") == source
        and run.get("event") in events
        and run.get("path") == CI_PATH
        and run.get("status") == "completed"
        and run.get("conclusion") == "success",
        "Exact source CI is not green",
    )
    workflow = api.request(
        "GET", f"/actions/workflows/{positive(run['workflow_id'], 'CI workflow')}"
    )
    require(
        workflow.get("path") == CI_PATH and workflow.get("name") == "CI",
        "Unexpected CI workflow identity",
    )
    if pull_request:
        require(
            any(
                pr.get("number") == 179
                and pr.get("head", {}).get("sha") == source
                and pr.get("base", {}).get("sha") == base
                for pr in run.get("pull_requests", [])
            ),
            "CI used another HEAD/base composition; recompose and run new CI",
        )
    else:
        require(run.get("head_branch") == "main", "Base CI is not trusted main")
    attempt = positive(run["run_attempt"], "CI attempt")
    require(attempt <= 100, "CI attempt limit exceeded")
    jobs = api.pages(f"/actions/runs/{run['id']}/attempts/{attempt}/jobs", "jobs")
    required = CORE_JOBS | COMPONENT_JOBS["mobile"] | COMPONENT_JOBS["ios"]
    for component, needed in selected.items():
        if needed:
            required |= COMPONENT_JOBS[component]
    known = CORE_JOBS.union(*COMPONENT_JOBS.values())
    names = [job.get("name") for job in jobs]
    require(
        len(names) == len(set(names)) and set(names) <= known,
        "Duplicate or unknown CI job identity",
    )
    for job in jobs:
        require(
            job.get("status") == "completed"
            and job.get("head_sha") == source
            and job.get("conclusion")
            in ({"success"} if job["name"] in required else {"success", "skipped"}),
            "CI job is incomplete or unsuccessful",
        )
        if job["name"] in NATIVE_STEPS:
            for name in NATIVE_STEPS[job["name"]]:
                steps = [
                    step for step in job.get("steps", []) if step.get("name") == name
                ]
                require(
                    len(steps) == 1
                    and steps[0].get("status") == "completed"
                    and steps[0].get("conclusion") == "success",
                    "Mandatory native step is missing or unsuccessful",
                )
    require(required <= set(names), "Mandatory CI job is missing")
    return run["id"]


def upload_state(jobs):
    uploads = [job for job in jobs if job.get("name") == "Test, sign and upload iOS"]
    require(len(uploads) == 1, "Unknown or missing historical upload job")
    job = uploads[0]
    require(job.get("status") == "completed", "Historical upload job is incomplete")
    if job.get("status") == "completed" and job.get("conclusion") == "skipped":
        return False
    steps = [
        step
        for step in job.get("steps", [])
        if step.get("name") == "Upload directly to App Store Connect"
    ]
    require(
        len(steps) == 1
        and steps[0].get("status") == "completed"
        and steps[0].get("conclusion") in {"skipped", "success"},
        "Attempted upload is ambiguous; inspect Apple, never resend blindly",
    )
    return steps[0]["conclusion"] == "success"


def check_history(api, data, ctx):
    trusted_paths = NON_APPLE_WORKFLOWS | {STABLE_PATH, QA_PATH}
    workflows = api.pages("/actions/workflows", "workflows")
    require(
        {STABLE_PATH, QA_PATH} <= {row.get("path") for row in workflows}
        and all(row.get("path") in trusted_paths for row in workflows),
        "Unknown workflow inventory; audit its upload history",
    )
    authenticated = set()

    def authenticate(path, source, *, apple=False):
        key = path, source
        if key in authenticated:
            return
        text = (ROOT / path).read_text(encoding="utf-8")
        require(
            api.file(path, source) == text,
            "Unknown historical upload implementation; inspect Apple"
            if apple
            else "Unknown historical workflow implementation; inspect Apple",
        )
        authenticated.add(key)
        for local in re.findall(
            r"(?m)^\s*(?:-\s*)?uses:\s+(\./[A-Za-z0-9/_.-]+)\s*(?:#.*)?$", text
        ):
            child = local[2:]
            if child.startswith("trusted/.github/actions/"):
                child = child[len("trusted/") :]
            require(
                ".." not in child.split("/")
                and child.startswith((".github/workflows/", ".github/actions/")),
                "Unknown historical local action",
            )
            if not child.endswith((".yml", ".yaml")):
                child += "/action.yml"
            authenticate(child, source, apple=apple)

    uploaded = False
    seen = set()
    # Repository-wide history includes old upload behavior at paths that are
    # harmless today. Current names or keyword searches cannot establish that.
    history = api.pages("/actions/runs", "workflow_runs")
    require(
        bool(history), "Missing historical inventory; audited reconciliation required"
    )
    for run in history:
        identifier = positive(run["id"], "historical run")
        path = run.get("path")
        require(
            identifier not in seen
            and path in trusted_paths
            and run.get("repository", {}).get("full_name") == REPOSITORY,
            "Unknown historical workflow identity",
        )
        seen.add(identifier)
        source = sha(run["head_sha"])
        authenticate(path, source, apple=path == STABLE_PATH)
        if path in NON_APPLE_WORKFLOWS:
            continue
        if path == STABLE_PATH:
            for helper in STABLE_APPLE_HELPERS:
                authenticate(helper, source, apple=True)
        attempts = positive(run["run_attempt"], "historical attempt")
        require(attempts <= 100, "History attempt limit exceeded")
        current = identifier == ctx["run_id"]
        require(
            not current or path == QA_PATH, "Current run has another workflow identity"
        )
        require(
            not current or attempts == ctx["run_attempt"],
            "Current attempt differs from API",
        )
        if not current and run.get("status") == "queued" and attempts == 1:
            continue
        require(
            current or run.get("status") == "completed",
            "Another publication run is active",
        )
        limit = ctx["run_attempt"] - 1 if current else attempts
        for attempt in range(1, limit + 1):
            jobs = api.pages(
                f"/actions/runs/{identifier}/attempts/{attempt}/jobs", "jobs"
            )
            if path == QA_PATH:
                require(
                    len(jobs) == 1 and jobs[0].get("name") == "Internal QA preflight",
                    "Unknown historical QA job",
                )
                continue
            if upload_state(jobs):
                identity = app_identity(api, source)
                if identity == (data["bundle_id"], data["version"], data["build"]):
                    require(
                        source == data["source_sha"],
                        "Apple identity was uploaded from another SHA",
                    )
                    uploaded = True
    if ctx["run_attempt"] > 1:
        require(ctx["run_id"] in seen, "Current run history is missing")
    return uploaded


def evaluate(api, candidate, context, *, now):
    trusted = validate_context(context)
    data = validate_metadata(candidate, now)
    for actor in {context["actor"], context["triggering_actor"]}:
        require(
            isinstance(actor, str) and re.fullmatch(r"[A-Za-z0-9-]{1,100}", actor),
            "Missing maintainer identity",
        )
        permission = api.request("GET", f"/collaborators/{actor}/permission")
        require(
            (permission.get("role_name"), permission.get("permission"))
            in {("admin", "admin"), ("maintain", "write")},
            "Only a maintainer can dispatch or rerun QA",
        )
    main = sha(api.request("GET", "/git/ref/heads/main")["object"]["sha"])
    require(
        main == trusted == data["base_sha"], "Main advanced; recompose and run new CI"
    )
    check_pr(api, data)
    comparison = api.request("GET", f"/compare/{main}...{data['source_sha']}")
    require(
        comparison.get("status") == "ahead"
        and comparison.get("merge_base_commit", {}).get("sha") == main,
        "Candidate does not incorporate exact current main",
    )
    identity = app_identity(api, data["source_sha"])
    require(
        identity == (data["bundle_id"], data["version"], data["build"]),
        "Reservation identity differs from candidate data",
    )
    previous = app_identity(api, main)
    require(
        version(data["version"]) >= version(previous[1])
        and build_number(data["build"]) > build_number(previous[2]),
        "Candidate build must exceed the current main build",
    )
    relay = decode(api.file("shared/computer_connect.json", data["source_sha"]))
    exact_keys(relay, {"schema_version", "relay_host", "relay_port"})
    require(
        type(relay["schema_version"]) is int
        and relay["schema_version"] == 1
        and relay["relay_host"] is None
        and type(relay["relay_port"]) is int
        and 1 <= relay["relay_port"] <= 65535,
        "Relay configuration must remain null",
    )
    require(
        tag_source(api, data["tag"]) == data["source_sha"],
        "QA tag differs from exact source",
    )
    selected = check_policy(api, data)
    source_run = check_ci(
        api, data["source_sha"], main, pull_request=True, selected=selected
    )
    base_run = check_ci(api, main, main, pull_request=False, selected={})
    uploaded = check_history(api, data, context)
    if not uploaded:
        require(
            build_number(data["build"])
            > build_number(data["reservation"]["highest_build"]),
            "A new upload requires a build above all used or reserved builds",
        )
    # Repeat the mutable checks at the end. This is a preflight boundary only;
    # a future upload must repeat this entire gate immediately before upload.
    check_pr(api, data)
    require(
        api.request("GET", "/git/ref/heads/main")["object"]["sha"] == main,
        "Main changed during preflight",
    )
    require(
        tag_source(api, data["tag"]) == data["source_sha"],
        "QA tag changed during preflight",
    )
    validate_metadata(data, now)
    return dict(
        schema=1,
        decision="availability-required" if uploaded else "eligible-preflight",
        source_sha=data["source_sha"],
        base_sha=main,
        trusted_sha=trusted,
        pr=179,
        app_id=APP_ID,
        bundle_id=BUNDLE,
        version=data["version"],
        build=data["build"],
        tag=data["tag"],
        source_ci_run=source_run,
        base_ci_run=base_run,
        packaging_proven=False,
        upload_enabled=False,
        relay_host=None,
        wan_delivered=False,
    )


def archive_identity(api, candidate, inputs):
    """The archive uses an existing root-selected identity and immutable tag."""
    exact_keys(
        candidate,
        {
            "schema",
            "pr",
            "source_sha",
            "base_sha",
            "app_id",
            "bundle_id",
            "version",
            "build",
            "tag",
            "relay_host",
        },
    )
    require(
        type(candidate["schema"]) is int
        and candidate["schema"] == 1
        and type(candidate["pr"]) is int
        and candidate["pr"] == 179,
        "Unknown archive candidate schema/PR",
    )
    require(
        candidate["source_sha"] == inputs["source_sha"]
        and candidate["base_sha"] == inputs["base_sha"],
        "Archive candidate differs from runtime composition",
    )
    version(candidate["version"])
    build_number(candidate["build"])
    require(
        candidate["app_id"] == APP_ID
        and candidate["bundle_id"] == BUNDLE
        and candidate["relay_host"] is None
        and candidate["tag"]
        == (f"ios/pr-179/v{candidate['version']}-build{candidate['build']}"),
        "Unknown archive identity/tag",
    )
    require(
        app_identity(api, inputs["source_sha"])
        == (BUNDLE, candidate["version"], candidate["build"]),
        "Archive identity differs from exact source data",
    )
    require(
        tag_source(api, candidate["tag"]) == inputs["source_sha"],
        "Archive tag must resolve to the exact reviewed source",
    )
    return candidate


def observe_archive_toolchain():
    require(
        sys.platform == "darwin" and os.environ.get("DEVELOPER_DIR") == DEVELOPER_DIR,
        "Device archive requires the fixed MAIN Xcode toolchain",
    )
    outputs = []
    for command in (
        ("/usr/bin/xcodebuild", "-version"),
        ("/usr/bin/xcrun", "--sdk", "iphoneos", "--show-sdk-version"),
    ):
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=30,
            env={
                "DEVELOPER_DIR": DEVELOPER_DIR,
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            },
        )
        require(
            result.returncode == 0 and len(result.stdout) <= 4096,
            "MAIN toolchain observation failed",
        )
        outputs.append(result.stdout.decode("ascii", errors="strict").strip())
    match = re.fullmatch(r"Xcode 26\.6\nBuild version ([A-Za-z0-9.]{1,40})", outputs[0])
    require(
        match is not None and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", outputs[1]),
        "Unexpected MAIN Xcode/SDK observation",
    )
    return dict(xcode_build=match[1], sdk_version=outputs[1])


def archive_policy(api, inputs, context, toolchain, *, trusted_repo=ROOT):
    composition = {k: inputs[k] for k in ("source_sha", "base_sha", "trusted_sha")}
    plan, _, workflow = _validation_origin(
        api, composition, context | {"mode": "validate"}, trusted_repo
    )
    candidate = archive_identity(api, inputs["candidate"], composition)
    consume_validation(
        api,
        composition,
        context
        | dict(
            mode="validate",
            run_id=inputs["validation_run_id"],
            run_attempt=inputs["validation_run_attempt"],
        ),
        trusted_repo=trusted_repo,
    )
    controls = archive_controls(trusted_repo, inputs["trusted_sha"])
    # Resolve the complete MAIN byte inventory once; the API adapter caches it.
    for path, blob in controls.items():
        require(
            device_archive.git_blob(api.control(inputs["trusted_sha"], path)) == blob,
            "Archive MAIN control bytes differ",
        )
    main_app = decode(api.control(inputs["trusted_sha"], "mobile/app.json"))["expo"]
    license_bytes = api.control(
        inputs["trusted_sha"], "mobile/third-party/KeyboardHostBundleID/LICENSE"
    )
    result = device_archive.ArchivePolicy(
        context={
            **candidate,
            **{k: plan[k] for k in ("source_tree", "base_tree")},
            "kind": "clarify-ios-qa-unsigned-archive",
            "trust_model": VALIDATION_TRUST_MODEL,
            "repository": REPOSITORY,
            "trusted_sha": inputs["trusted_sha"],
            "workflow": workflow,
            "producer": dict(
                run_id=inputs["producer_run_id"],
                run_attempt=inputs["producer_run_attempt"],
                job_key="archive",
            ),
            "controls": controls,
            "recipe": dict(
                id="device-release-v1",
                configuration="Release",
                sdk="iphoneos",
                destination="generic/platform=iOS",
                architectures=["arm64"],
                code_signing_allowed=False,
                **toolchain,
            ),
            "entitlements_policy": deepcopy(device_archive.ENTITLEMENTS_POLICY),
        },
        cloud_url=main_app["ios"]["infoPlist"]["ClarifyCloudURL"],
        license_sha256=hashlib.sha256(license_bytes).hexdigest(),
        producer_job_name=ARCHIVE_JOB_NAME,
        producer_steps=ARCHIVE_STEPS,
        final_job_name=ARCHIVE_FINAL_JOB_NAME,
        final_steps=ARCHIVE_FINAL_STEPS,
        uploader_step=ARCHIVE_UPLOAD_STEP,
        recorder_step=ARCHIVE_RECORD_STEP,
        upload_action=UPLOAD_ACTION,
    )
    result.validate()
    _validation_current_source(api, composition)
    return result


def produce_archive(job, policy, output_dir):
    output_dir = device_archive.absolute_path(output_dir, exists=False)
    output_dir.mkdir(mode=0o700)
    job.authenticate()
    job.prepare()
    archive_path = job.metadata / device_archive.ARCHIVE_ROOT
    try:
        job.run_recipe("ios-project")
        job.run_recipe("ios-pods")
        job.command(
            [
                "/usr/bin/xcodebuild",
                "-workspace",
                "ios/Clarify.xcworkspace",
                "-scheme",
                "Clarify",
                "-configuration",
                "Release",
                "-sdk",
                "iphoneos",
                "-destination",
                "generic/platform=iOS",
                "-archivePath",
                archive_path,
                "-derivedDataPath",
                job.metadata / "UnsignedDeviceRelease",
                "ARCHS=arm64",
                "CODE_SIGNING_ALLOWED=NO",
                "archive",
            ],
            cwd=job.execution / "mobile",
            extra_env={"DEVELOPER_DIR": DEVELOPER_DIR},
        )
    finally:
        try:
            job.verify_source()
        finally:
            job.verify_controls()
    return device_archive.pack(archive_path, output_dir, policy)


def record_archive(api, policy, artifact_id, artifact_digest):
    """Record cross-checked uploader outputs on a fresh MAIN-only runner."""
    policy.validate()
    context = policy.context
    producer = context["producer"]
    run_id, attempt = producer["run_id"], producer["run_attempt"]
    line = device_archive.format_artifact_record(
        artifact_id=artifact_id,
        artifact_digest=artifact_digest,
        source_sha=context["source_sha"],
        run_id=run_id,
        run_attempt=attempt,
    )
    run = api.run(run_id, attempt)
    require(
        run.get("id") == run_id
        and run.get("run_attempt") == attempt
        and run.get("workflow_id") == context["workflow"]["id"]
        and run.get("path") == QA_PATH
        and run.get("head_sha") == context["trusted_sha"]
        and run.get("head_branch") == "main"
        and run.get("event") == "workflow_dispatch"
        and run.get("repository", {}).get("full_name") == REPOSITORY
        and (run.get("status"), run.get("conclusion"))
        in {("in_progress", None), ("completed", "success")},
        "Archive producer run differs",
    )
    response = api.jobs(run_id, attempt)
    require(
        response.get("run_id") == run_id
        and response.get("run_attempt") == attempt
        and type(response.get("jobs")) is list
        and 1 <= len(response["jobs"]) <= 23,
        "Archive exact-attempt jobs differ",
    )
    job = device_archive._successful_job(
        response["jobs"],
        policy.producer_job_name,
        policy.producer_steps,
        run_id,
        context["trusted_sha"],
    )
    final = [j for j in response["jobs"] if j.get("name") == policy.final_job_name]
    require(
        len(final) == 1
        and type(final[0].get("id")) is int
        and final[0]["id"] > 0
        and final[0]["id"] != job["id"]
        and final[0].get("run_id") == run_id
        and final[0].get("head_sha") == context["trusted_sha"]
        and (final[0].get("status"), final[0].get("conclusion"))
        in {("in_progress", None), ("completed", "success")},
        "Archive final job differs",
    )
    artifact = api.artifact(artifact_id)
    require(
        artifact.get("id") == artifact_id
        and artifact.get("name") == "clarify-ios-qa-unsigned-" + context["source_sha"]
        and artifact.get("digest") == "sha256:" + artifact_digest
        and artifact.get("expired") is False
        and type(artifact.get("size_in_bytes")) is int
        and 0 < artifact["size_in_bytes"] <= device_archive.LIMITS.zip_bytes
        and artifact.get("workflow_run", {}).get("id") == run_id
        and artifact.get("workflow_run", {}).get("head_sha") == context["trusted_sha"],
        "Archive API artifact differs from uploader outputs",
    )
    return line


def _runtime_archive_inputs(context, command):
    event_path = Path(os.environ["GITHUB_EVENT_PATH"])
    require(event_path.stat().st_size <= 64 * 1024, "Dispatch event is too large")
    event = decode(event_path.read_text(encoding="utf-8"))
    inputs = event.get("inputs")
    allowed = {
        "mode",
        "candidate",
        "source_sha",
        "base_sha",
        "trusted_sha",
        "validation_run_id",
        "validation_run_attempt",
        "producer_run_id",
        "producer_run_attempt",
        "archive_artifact_id",
    }
    expected_mode = "sign-export-proof" if command == "sign-export-proof" else "archive"
    require(
        type(inputs) is dict
        and inputs.keys() <= allowed
        and inputs.get("mode") == expected_mode,
        "Unexpected archive dispatch mode",
    )
    validate_context(context | {"mode": "preflight"})
    result = {k: sha(inputs.get(k)) for k in ("source_sha", "base_sha", "trusted_sha")}
    require(
        result["base_sha"] == result["trusted_sha"] == context["workflow_sha"],
        "Archive dispatch differs from MAIN runtime",
    )
    raw = inputs.get("candidate")
    require(
        type(raw) is str and len(raw.encode("utf-8")) <= 8192,
        "Invalid archive candidate data",
    )
    result["candidate"] = decode(raw)
    keys = ["validation_run_id", "validation_run_attempt"]
    if expected_mode == "sign-export-proof":
        keys += ["producer_run_id", "producer_run_attempt", "archive_artifact_id"]
    else:
        require(
            all(
                inputs.get(k, "") == ""
                for k in (
                    "producer_run_id",
                    "producer_run_attempt",
                    "archive_artifact_id",
                )
            ),
            "Archive producer must use its current runtime identity",
        )
        result.update(
            producer_run_id=context["run_id"],
            producer_run_attempt=context["run_attempt"],
        )
    for key in keys:
        value = inputs.get(key)
        require(
            type(value) is str and re.fullmatch(r"[1-9][0-9]{0,15}", value),
            "Invalid archive run/attempt/artifact input",
        )
        result[key] = positive(int(value), key)
        require(
            result[key] <= (100 if key.endswith("attempt") else 2**53 - 1),
            "Archive run/attempt/artifact input exceeds its bound",
        )
    require(
        result["validation_run_id"]
        not in {context["run_id"], result["producer_run_id"]},
        "Archive requires a separate completed validation run",
    )
    if expected_mode == "sign-export-proof":
        require(
            result["producer_run_id"] != context["run_id"],
            "Export proof requires a later separate dispatch",
        )
    context["mode"] = expected_mode
    return result


def run_archive_command(command, inputs, context):
    api = ArchiveGitHub(os.environ.get("GH_TOKEN", ""))
    policy = archive_policy(api, inputs, context, observe_archive_toolchain())
    if command == "archive":
        env = dict(
            os.environ,
            QA_SOURCE_SHA=inputs["source_sha"],
            QA_BASE_SHA=inputs["base_sha"],
            QA_TRUSTED_SHA=inputs["trusted_sha"],
            QA_WORKFLOW_SHA=context["workflow_sha"],
            QA_COMPONENT_KEY="ios_build",
            QA_TRUSTED_MODE="true",
        )
        produce_archive(
            trusted_ci.Job(env), policy, ROOT.parent / "unsigned-device-archive"
        )
        _validation_current_source(api, inputs)
    elif command == "archive-record":
        identifier = os.environ["QA_UPLOAD_ARTIFACT_ID"]
        require(
            re.fullmatch(r"[1-9][0-9]{0,15}", identifier), "Invalid archive uploader ID"
        )
        line = record_archive(
            api, policy, int(identifier), os.environ["QA_UPLOAD_ARTIFACT_DIGEST"]
        )
        _validation_current_source(api, inputs)
        print(line)
    else:
        result = device_archive.sign_export(
            api=api,
            policy=policy,
            artifact_id=inputs["archive_artifact_id"],
            runner_temp=Path(os.environ["RUNNER_TEMP"]),
            trusted_root=ROOT,
        )
        try:
            require(
                result["receipt"]["delivery_eligible"] is False,
                "Experimental export cannot authorize delivery",
            )
            output = device_archive.absolute_path(
                ROOT.parent / "archive-proof", exists=False
            )
            output.mkdir()
            (output / "archive-receipt.json").write_bytes(
                device_archive.canonical(result["receipt"])
            )
            print('{"delivery_eligible":false,"upload_enabled":false}')
        finally:
            shutil.rmtree(result["workspace"])


def _runtime_validation_inputs(context):
    event_path = Path(os.environ["GITHUB_EVENT_PATH"])
    require(event_path.stat().st_size <= 64 * 1024, "Dispatch event is too large")
    event = decode(event_path.read_text(encoding="utf-8"))
    inputs = event.get("inputs")
    require(
        isinstance(inputs, dict) and inputs.get("mode") == "validate",
        "Validation requires the fresh runtime dispatch inputs",
    )
    result = {key: inputs.get(key) for key in ("source_sha", "base_sha", "trusted_sha")}
    for value in result.values():
        sha(value)
    require(
        result["base_sha"] == result["trusted_sha"] == context["workflow_sha"],
        "Dispatch composition differs from trusted MAIN runtime",
    )
    context["mode"] = "validate"
    return result


def main(argv=None):
    try:
        arguments = sys.argv[1:] if argv is None else argv
        require(
            arguments
            in (
                [],
                ["validate"],
                ["finalize"],
                ["record"],
                ["archive"],
                ["archive-record"],
                ["sign-export-proof"],
            ),
            "Unknown QA command",
        )
        command = arguments[0] if arguments else "preflight"
        checkout = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        ctx = {
            "repository": os.environ["GITHUB_REPOSITORY"],
            "event": os.environ["GITHUB_EVENT_NAME"],
            "ref": os.environ["GITHUB_REF"],
            "workflow_ref": os.environ[
                "QA_WORKFLOW_REF" if command == "preflight" else "GITHUB_WORKFLOW_REF"
            ],
            "workflow_sha": os.environ[
                "QA_WORKFLOW_SHA" if command == "preflight" else "GITHUB_WORKFLOW_SHA"
            ],
            "sha": os.environ["GITHUB_SHA"],
            "checkout_sha": checkout,
            "actor": os.environ["GITHUB_ACTOR"],
            "triggering_actor": os.environ["GITHUB_TRIGGERING_ACTOR"],
            "run_id": int(os.environ["GITHUB_RUN_ID"]),
            "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
            "mode": os.environ.get("QA_MODE", "preflight"),
        }
        if command in {"archive", "archive-record", "sign-export-proof"}:
            inputs = _runtime_archive_inputs(ctx, command)
            run_archive_command(command, inputs, ctx)
            return 0
        if command != "preflight":
            if command == "record":
                validate_context(ctx | {"mode": "preflight"})
                identifier = os.environ["QA_UPLOAD_ARTIFACT_ID"]
                require(
                    re.fullmatch(r"[1-9][0-9]{0,15}", identifier) is not None,
                    "Invalid upload artifact ID",
                )
                print(
                    format_validation_artifact_record(
                        artifact_id=int(identifier),
                        artifact_digest=os.environ["QA_UPLOAD_ARTIFACT_DIGEST"],
                        run_id=ctx["run_id"],
                        run_attempt=ctx["run_attempt"],
                    )
                )
                return 0
            inputs = _runtime_validation_inputs(ctx)
            api = ValidationGitHub(os.environ.get("GH_TOKEN", ""))
            if command == "validate":
                _validation_origin(api, inputs, ctx, ROOT)
                _validation_current_source(api, inputs)
                print('{"apple_enabled":false,"validation_enabled":true}')
                return 0
            outputs = {
                key: os.environ["QA_" + key.upper()]
                for key in (
                    "selected_keys",
                    "source_tree",
                    "base_tree",
                    "plan_digest",
                    "controls_digest",
                )
            }
            result = finalize_validation(api, inputs, ctx, outputs=outputs)
            output = ROOT.parent / "validation" / "validation.json"
            output.parent.mkdir(exist_ok=True)
            require(
                not output.is_symlink() and not output.parent.is_symlink(),
                "Linked validation output is forbidden",
            )
            output.write_bytes(canonical_validation_json(result))
            return 0
        raw = os.environ["QA_CANDIDATE"]
        require(len(raw.encode("utf-8")) <= 8192, "Candidate metadata is too large")
        result = evaluate(
            GitHub(os.environ.get("GH_TOKEN", "")),
            decode(raw),
            ctx,
            now=datetime.now(timezone.utc),
        )
        # Fixed fields only: no arbitrary metadata, tokens, paths or API responses.
        print(json.dumps(result, sort_keys=True))
        return 0
    except ReleaseError as error:
        # ReleaseError messages use fixed policy text and sanitized HTTP status;
        # candidate JSON and remote response bodies are never included.
        print(f"Internal QA preflight blocked: {error}", file=sys.stderr)
        return 1
    except (
        KeyError,
        TypeError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
        RecursionError,
    ):
        print(
            "Internal QA preflight blocked. Check identity, exact CI, history and helper limits.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
