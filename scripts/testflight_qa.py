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
PUBLICATION_JOB_NAME = "Upload verified internal preview"
AVAILABILITY_JOB_NAME = "Complete internal preview availability"
PROOF_STEPS = (
    "Authenticate completed archive and run experimental export proof",
    "Retain experimental export receipt",
    "Record experimental export proof",
)
PUBLICATION_STEPS = (
    "Authenticate publication gates",
    "Export and verify internal preview",
    "Upload exactly once to Apple",
    "Retain internal publication receipts",
    "Record internal publication artifact",
)
PHASE_ARTIFACTS = {
    "proof": ("CLARIFY_QA_EXPORT_PROOF_ARTIFACT ", "clarify-ios-qa-export-proof"),
    "publication": ("CLARIFY_QA_PUBLICATION_ARTIFACT ", "clarify-ios-qa-publication"),
}
PUBLICATION_INPUTS = {
    "proof_run_id",
    "proof_run_attempt",
    "proof_artifact_id",
    "publication_run_id",
    "publication_run_attempt",
    "publication_artifact_id",
    "inventory_run_id",
    "inventory_run_attempt",
}
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


# PR 179 internal preview only. These are audited observations, not per-attempt
# provenance for deleted history and not authority for another reservation.
PREVIEW_HISTORY_BASELINE = {
    "run_id": 40551997834,
    "run_attempt": 1,
    "artifact_id": 12755640916,
    "source_sha": "7573268d54f28b4d5d45e5bc46527ee1df673885",
    "workflow_id": 380816838,
    "workflow_sha256": "d37f241c152e7de1a493eba41ffa1366e166296f208745add6125cc589cd36ad",
    "artifact_sha256": "c5b4b3fc7f5dfcf46118edf8dbbbdce05e108b9ac9220ca7dc1322752b0a2a45",
    "report_sha256": "9c5125eadfbe8071c83058454b2f965082e06237feae951b610f85203d155064",
    "finished_at": "2026-10-27T17:35:26.101Z",
    "history_boundary": "2026-10-27T17:35:29Z",
    "retained_runs": 2000,
    "apple_runs": 226,
    "app_config_sources": 185,
    "max_historical_app_build": 40,
    "snapshot_sha256": "a2bd411c6ba39027144ec1e899a5d5e0cdd28ce19526c06e16bdf419c8a4d11b",
    "identity_audit_sha256": "1bf6e9471d040279f21cf50da68425489e1512f322ba10ad40db7c4a61798ac9",
}
PREVIEW_PROTECTED_STABLE_SOURCE = "678772aadda5d5eec78bd8f2b818635a7657ba90"
PREVIEW_PUBLICATION_JOB = "Upload verified internal preview"
PREVIEW_PUBLICATION_STEPS = (
    "Authenticate publication gates",
    "Export and verify internal preview",
    "Upload exactly once to Apple",
    "Retain internal publication receipts",
    "Record internal publication artifact",
)
PREVIEW_AVAILABILITY_JOB = "Complete internal preview availability"
PREVIEW_INVENTORY_STEPS = (
    "Read complete App Store Connect reservation state (GET only)",
    "Preserve read-only Apple reservation evidence",
)
# The supplied MAIN 22a91ec has validation/archive/export proof, with no Apple
# uploader. Pin its executable controls to recognize earlier post-baseline QA.
PREVIEW_UNSIGNED_QA_CONTROLS = {
    QA_PATH: "124fad215b36786614003a4956ee1f36d9265ec60f7cdf96eb2bbdf9c619a6e5",
    "scripts/testflight_qa.py": "a2145d524c98ba93cb5d25ea3201e0fb3519253d9f253a7519d4ad6dd702f4cd",
    "scripts/qa_device_archive.py": "a56413bfcfabca692f38a3d8a5fd456ef6fa2932acda88738fb68bc6a0785873",
    "scripts/trusted_ci.py": "237b0a7f7ab0c139091f9d6ac6c7fb0b570858cbaed3820b185731f153d35aa9",
    "scripts/release_delivery.py": "2584beb28f7c542c804780768f75f5a5279d179cf0fcf813791bf958d5a4544a",
    "scripts/delivery_policy.py": "18c4aa0421c69ca360a70065f948af9c3832b9d46f7221d79eca444aba40248b",
    "mobile/scripts/ios-signing.py": "b62b76ffaaf3cd463327d4b6ad9bc7d66a154162afa97aa9058cab66d140c322",
}
# Finite reviewed control variants: MAIN1b before189, MAIN17b/22a after189,
# and the four normal-only PR179 CI blocks accepted in a51/7a/89.
PREVIEW_OLD_ADAPTER_SHA256 = (
    "e7a233fb13c1447eb49067529b1c3815b7ec00fbbc27e00be5f08e98d31c749f"
)
PREVIEW_FEATURE_CI_SHA256 = (
    "df7479fdb2829f33135747f99166dda621677cc6d9c0af2180a71e210f338844"
)
# Finite, reviewed build-41 controls. These authenticate historical execution;
# they never replace the controls selected for a new run.
PREVIEW_ARCHIVE41_CONTROLS = {
    QA_PATH: "d56839bda61d3dbf7410f24346c2ff8db586ee77b289c459941cd57822e12e65",
    "scripts/testflight_qa.py": "84e7e98d8e3838796888599ecf1c9a77eb262cfa383fec8ddcd887cb2474bab8",
    "scripts/qa_device_archive.py": "ddba5a71b72bc838d3483417023ad76717c9f2e3848406125fb18c7eadb9ef15",
}
PREVIEW_DIAGNOSTIC41 = {
    "run_id": 40611469556,
    "source_sha": "2c5d1eb7b40005d0b317e6abe12e385f573516c4",
    "workflow_sha256": "89404fbe3897e48cb7d1eee193610925b2bdebaa7df276d4809dbc2738b797e4",
    "job_id": 122563767007,
    "job_name": "Unsigned archive41 diagnostics",
}
PREVIEW_INSPECTION43 = {
    "run_id": 40643791484,
    "source_sha": "ef3b25f9e539a32a3f0e7b8c44ab50d3bdf69ab7",
    "workflow_sha256": "07be9cc1ff05635b7e97597e3005c801173188a0c62a0f390feb8144b1a2d780",
    "job_id": 122667791524,
    "job_name": "Secret-free archive43 pre-key inspection",
}
# Reviewed pre-197 MAIN CI bytes remain historical data, never current policy.
PREVIEW_PRIOR_MAIN_CI_SHA256 = (
    "0621fcb642bda323ca5a7fef37de9b1065ac51b4486e471b08120cf27cd6283d"
)
# The reviewed source6bd union keeps MAIN197 and the existing normal-only checks.
PREVIEW_RECOMPOSED_FEATURE_CI_SHA256 = (
    "f028b12b0964cdbe89a23432dd2a491a89b099c2dbe88b2036e243ceb6b408a5"
)
# Fixed historical MAIN inventories are data, never execution authority. They
# exclude controls added later and bind earlier runs to reviewed Git objects.
PREVIEW_HISTORICAL_CONTROL_ROOTS = {
    "264e41335e2edf4d36a9a5b2c711fe24a3a2633d": "264e41335e2edf4d36a9a5b2c711fe24a3a2633d",
    "d777ddde8a5f5dea0b035ee3a49aacb7e1654c79": "d777ddde8a5f5dea0b035ee3a49aacb7e1654c79",
    PREVIEW_DIAGNOSTIC41["source_sha"]: "d777ddde8a5f5dea0b035ee3a49aacb7e1654c79",
    "a740ac9c319fd2cca0630bfd8489fa438e969827": "a740ac9c319fd2cca0630bfd8489fa438e969827",
    "be4796c7c771af98a5782acb2eef9a5d4d50e3c4": "be4796c7c771af98a5782acb2eef9a5d4d50e3c4",
    PREVIEW_INSPECTION43["source_sha"]: "be4796c7c771af98a5782acb2eef9a5d4d50e3c4",
}
# Existing tags stay immutable. Build 44 still requires its own reservation,
# source/tag, validation, archive and native proof; this list reserves nothing.
PREVIEW_PUBLICATION_IDENTITIES = {
    ("0.12.0", str(n), f"ios/pr-179/v0.12.0-build{n}") for n in (41, 42, 43, 44)
}


def _preview_time(value):
    require(type(value) is str and value.endswith("Z"), "Missing UTC history time")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ReleaseError("Invalid UTC history time") from None
    require(result.utcoffset().total_seconds() == 0, "Invalid UTC history time")
    return result


def _preview_pages(api, path, key):
    """Check declared totals, including the 2,000 retained baseline runs."""
    rows, total = [], None
    for page in range(1, 102):
        result = api.request("GET", f"{path}?per_page=100&page={page}")
        count = result.get("total_count")
        items = result.get(key)
        require(
            type(count) is int
            and 0 <= count <= 10000
            and (total is None or count == total)
            and type(items) is list
            and len(items) <= 100,
            "Incomplete or changing preview history pagination",
        )
        total = count
        rows.extend(items)
        require(len(rows) <= total, "Preview history count differs")
        if len(items) < 100:
            require(len(rows) == total, "Missing preview history page")
            ids = [positive(row.get("id"), "history item") for row in rows]
            require(len(set(ids)) == len(ids), "Duplicate preview history item")
            return rows
    raise ReleaseError("Preview history pagination limit exceeded")


def _preview_inventory(api, run_id, attempt, *, now, baseline=False):
    """Authenticate the fixed GET-only producer before decoding its report."""
    fixed = PREVIEW_HISTORY_BASELINE
    positive(run_id, "inventory run")
    require(type(attempt) is int and 1 <= attempt <= 100, "Invalid inventory attempt")
    run = api.request("GET", f"/actions/runs/{run_id}/attempts/{attempt}")
    branch = "diagnostics/apple-next-build-check-20261026"
    require(
        run.get("id") == run_id
        and run.get("run_attempt") == attempt
        and run.get("repository", {}).get("full_name") == REPOSITORY
        and run.get("head_repository", {}).get("full_name") == REPOSITORY
        and run.get("workflow_id") == fixed["workflow_id"]
        and run.get("path") == STABLE_PATH
        and run.get("head_sha") == fixed["source_sha"]
        and run.get("head_branch") == branch
        and run.get("event") == "workflow_dispatch"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success",
        "Unauthenticated Apple inventory producer",
    )
    workflow = api.request("GET", f"/actions/workflows/{fixed['workflow_id']}")
    require(
        workflow.get("id") == fixed["workflow_id"]
        and workflow.get("path") == STABLE_PATH,
        "Apple inventory workflow identity differs",
    )
    data = api.file(STABLE_PATH, fixed["source_sha"]).encode("utf-8")
    require(
        hashlib.sha256(data).hexdigest() == fixed["workflow_sha256"],
        "Apple inventory Git workflow differs",
    )
    jobs = _preview_pages(
        api, f"/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs"
    )
    require(len(jobs) == 1, "Ambiguous Apple inventory job")
    job = jobs[0]
    require(
        job.get("name") == "apple_status"
        and job.get("run_id") == run_id
        and job.get("head_sha") == fixed["source_sha"]
        and job.get("status") == "completed"
        and job.get("conclusion") == "success",
        "Apple inventory job differs",
    )
    steps = job.get("steps", [])
    require(
        [s.get("name") for s in steps]
        == ["Set up job", *PREVIEW_INVENTORY_STEPS, "Complete job"]
        and all(
            s.get("status") == "completed" and s.get("conclusion") == "success"
            for s in steps
        ),
        "Apple inventory producer or uploader did not succeed",
    )
    artifacts = _preview_pages(api, f"/actions/runs/{run_id}/artifacts", "artifacts")
    require(len(artifacts) == 1, "Ambiguous Apple inventory artifact")
    artifact = artifacts[0]
    require(
        not baseline or artifact.get("id") == fixed["artifact_id"],
        "Audited Apple baseline artifact differs",
    )
    created = _preview_time(artifact.get("created_at"))
    require(
        artifact.get("name") == f"apple-next-build-check-{run_id}"
        and artifact.get("expired") is False
        and artifact.get("workflow_run", {}).get("id") == run_id
        and artifact["workflow_run"].get("head_sha") == fixed["source_sha"]
        and artifact["workflow_run"].get("head_branch") == branch
        and type(artifact.get("size_in_bytes")) is int
        and 0 < artifact["size_in_bytes"] <= 4 * 1024**2
        and _preview_time(steps[2].get("started_at"))
        <= created
        <= _preview_time(steps[2].get("completed_at")),
        "Apple inventory artifact producer/attempt differs",
    )
    raw = api.binary(f"/actions/artifacts/{artifact['id']}/zip", limit=4 * 1024**2)
    digest = hashlib.sha256(raw).hexdigest()
    require(
        len(raw) == artifact["size_in_bytes"]
        and artifact.get("digest") == "sha256:" + digest,
        "Apple inventory artifact digest differs",
    )
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(len(entries) == 1, "Apple inventory ZIP must contain one report")
            item = entries[0]
            mode = item.external_attr >> 16
            require(
                item.filename == "apple-reservation-report.json"
                and not item.flag_bits & 1
                and not item.is_dir()
                and stat.S_IFMT(mode) in {0, stat.S_IFREG}
                and item.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                and 0 < item.file_size <= 2 * 1024**2,
                "Unsafe Apple inventory report ZIP",
            )
            report_bytes = archive.read(item)
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
        raise ReleaseError("Invalid Apple inventory ZIP") from None
    report_digest = hashlib.sha256(report_bytes).hexdigest()
    if baseline:
        require(
            (run_id, attempt, artifact["id"], digest, report_digest)
            == (
                fixed["run_id"],
                fixed["run_attempt"],
                fixed["artifact_id"],
                fixed["artifact_sha256"],
                fixed["report_sha256"],
            ),
            "Audited Apple baseline differs",
        )
    report = decode(report_bytes)
    require(type(report) is dict, "Invalid Apple inventory report")
    require(
        report.get("app") == APP_ID
        and report.get("method") == "GET"
        and report.get("source_sha") == fixed["source_sha"]
        and report.get("source_ref") == "refs/heads/" + branch
        and report.get("run_id") == str(run_id)
        and report.get("errors") == []
        and report.get("apple_queries_complete") is True,
        "Incomplete or unbound Apple inventory report",
    )
    start, finish = (
        _preview_time(report.get("started_at")),
        _preview_time(report.get("finished_at")),
    )
    # GitHub step completion timestamps have whole-second precision. Preserve
    # exact report times for chronology and the 900-second freshness limit.
    require(
        _preview_time(steps[1].get("started_at")) <= start <= finish <= now
        and finish.replace(microsecond=0)
        <= _preview_time(steps[1].get("completed_at")).replace(microsecond=0)
        <= now
        and (baseline or 0 <= (now - start).total_seconds() <= 900),
        "Stale or future Apple inventory report",
    )
    if baseline:
        require(
            report["finished_at"] == fixed["finished_at"], "Apple baseline time differs"
        )
    collections, queries = report.get("collections"), report.get("queries")
    require(
        type(collections) is dict
        and {"builds", "uploads", "appStoreVersions", "reviewSubmissions", "groups"}
        <= collections.keys()
        and type(queries) is list
        and queries,
        "Missing Apple inventory collections",
    )
    for collection in collections.values():
        require(
            collection.get("complete") is True
            and type(collection.get("pages")) is int
            and collection["pages"] > 0
            and type(collection.get("data")) is list
            and type(collection.get("included")) is list
            and type(collection.get("totals")) is list
            and all(
                type(n) is int and n == len(collection["data"])
                for n in collection["totals"]
            ),
            "Incomplete Apple inventory collection",
        )
    for query in queries:
        url = urlsplit(query.get("url", ""))
        require(
            query.get("method") == "GET"
            and query.get("status") == 200
            and url.scheme == "https"
            and url.netloc == "api.appstoreconnect.apple.com"
            and url.path.startswith("/v1/")
            and start <= _preview_time(query.get("checked_at")) <= finish,
            "Invalid Apple inventory query",
        )
    binding = dict(
        run_id=run_id,
        run_attempt=attempt,
        artifact_id=artifact["id"],
        source_sha=fixed["source_sha"],
        workflow_sha256=fixed["workflow_sha256"],
        artifact_sha256=digest,
        report_sha256=report_digest,
        finished_at=report["finished_at"],
    )
    return report, binding


def _preview_history_graph(api, path, source, trusted, authenticated):
    """Compare MAIN workflow graphs, without treating CI product payloads as controls."""
    key = path, source
    if key in authenticated:
        return
    require(len(authenticated) < 1000, "Preview workflow graph limit")
    expected = api.control(trusted, path)
    observed = api.file(path, source).encode("utf-8")
    require(
        observed == expected
        or (
            path == CI_PATH
            and hashlib.sha256(observed).hexdigest()
            in {
                PREVIEW_FEATURE_CI_SHA256,
                PREVIEW_PRIOR_MAIN_CI_SHA256,
                PREVIEW_RECOMPOSED_FEATURE_CI_SHA256,
            }
        )
        or (
            path == QA_PATH
            and hashlib.sha256(observed).hexdigest()
            in {
                PREVIEW_ARCHIVE41_CONTROLS[QA_PATH],
                PREVIEW_DIAGNOSTIC41["workflow_sha256"],
                PREVIEW_INSPECTION43["workflow_sha256"],
            }
        ),
        "Unknown post-baseline workflow implementation",
    )
    authenticated.add(key)
    document = api.workflow_document(observed)
    require(type(document) is dict, "Missing MAIN workflow graph")
    pending = [document]
    local_uses = set()
    while pending:
        node = pending.pop()
        if type(node) is dict:
            local = node.get("uses")
            if type(local) is str and local.startswith("./"):
                local_uses.add(local)
            pending.extend(node.values())
        elif type(node) is list:
            pending.extend(node)
    for local in sorted(local_uses):
        child = local[2:]
        if child.startswith("trusted/.github/"):
            child = child[len("trusted/") :]
        require(
            ".." not in child.split("/")
            and child.startswith((".github/workflows/", ".github/actions/")),
            "Unknown local preview workflow control",
        )
        if not child.endswith((".yml", ".yaml")):
            child += "/action.yml"
        _preview_history_graph(api, child, source, trusted, authenticated)


def _preview_managed_dependabot(api, row):
    """Authenticate only GitHub's managed updater type; no YAML blob exists."""
    path = "dynamic/dependabot/dependabot-updates"
    identifier = positive(row.get("id"), "managed updater run")
    attempt = api.request("GET", f"/actions/runs/{identifier}/attempts/1")
    workflow = api.request("GET", "/actions/workflows/316003284")
    terminal = {"success", "failure", "cancelled", "timed_out"}
    for run in (row, attempt):
        require(
            run.get("id") == identifier
            and run.get("path") == path
            and run.get("workflow_id") == 316003284
            and run.get("event") == "dynamic"
            and run.get("head_branch") == "main"
            and run.get("run_attempt") == 1
            and run.get("status") == "completed"
            and run.get("conclusion") in terminal
            and run.get("head_sha") == row.get("head_sha"),
            "Unknown managed updater execution",
        )
        sha(run.get("head_sha"))
        for key in ("repository", "head_repository"):
            repo = run.get(key, {})
            require(
                repo.get("id") == 1135801455 and repo.get("full_name") == REPOSITORY,
                "Managed updater repository differs",
            )
        for key in ("actor", "triggering_actor"):
            actor = run.get(key, {})
            require(
                actor.get("id") == 49699333
                and actor.get("login") == "dependabot[bot]"
                and actor.get("type") == "Bot",
                "Managed updater actor differs",
            )
    require(
        workflow.get("id") == 316003284 and workflow.get("path") == path,
        "Managed updater workflow differs",
    )
    jobs = _preview_pages(api, f"/actions/runs/{identifier}/attempts/1/jobs", "jobs")
    require(len(jobs) == 1, "Managed updater job count differs")
    job = jobs[0]
    runner = positive(job.get("runner_id"), "managed updater runner")
    require(
        job.get("name") == "Dependabot"
        and job.get("run_id") == identifier
        and job.get("head_sha") == row["head_sha"]
        and job.get("run_attempt") == 1
        and job.get("status") == "completed"
        and job.get("conclusion") in terminal
        and job.get("labels") == ["ubuntu-latest"]
        and job.get("runner_group_name") == "GitHub Actions"
        and job.get("runner_name") == f"GitHub Actions {runner}",
        "Managed updater is not the expected hosted job",
    )
    steps = job.get("steps", [])
    require(
        [(item.get("name"), item.get("number")) for item in steps]
        == [
            ("Set up job", 1),
            ("Create job directory", 2),
            ("Run Dependabot", 3),
            ("Post Run Dependabot", 6),
            ("Complete job", 7),
        ]
        and all(
            item.get("status") == "completed" and item.get("conclusion") in terminal
            for item in steps
        ),
        "Managed updater step sequence differs",
    )


def reconcile_preview_history(
    api,
    policy,
    context,
    *,
    inventory_run_id,
    inventory_run_attempt,
    now,
    publication_receipt_reader=None,
):
    """Reconcile the audited build-41 reservation; never perform an Apple write.

    The caller owns receipt authentication. A receipt for this identity always
    selects availability, including an uncertain upload or another source SHA.
    """
    policy.validate()
    q = policy.context
    trusted = validate_context(context | {"mode": "preflight"})
    require(
        q["trusted_sha"] == trusted
        and q["pr"] == 179
        and set(PREVIEW_UNSIGNED_QA_CONTROLS) <= q["controls"].keys()
        and (q["app_id"], q["bundle_id"]) == (APP_ID, BUNDLE)
        and (q["version"], q["build"], q["tag"]) in PREVIEW_PUBLICATION_IDENTITIES
        and q["source_sha"] != PREVIEW_PROTECTED_STABLE_SOURCE
        and isinstance(now, datetime)
        and now.tzinfo is not None,
        "History reconciliation is limited to the internal PR 179 identities",
    )
    fixed = PREVIEW_HISTORY_BASELINE
    baseline, baseline_binding = _preview_inventory(
        api, fixed["run_id"], fixed["run_attempt"], now=now, baseline=True
    )
    require(
        inventory_run_id != fixed["run_id"], "A fresh Apple inventory run is required"
    )
    fresh, fresh_binding = _preview_inventory(
        api, inventory_run_id, inventory_run_attempt, now=now
    )
    runs = _preview_pages(api, "/actions/runs", "workflow_runs")
    require(len(runs) >= fixed["retained_runs"], "Retained baseline history is missing")
    seen, authenticated, receipts, checked = set(), set(), [], 0
    current_upload_active = False
    boundary = _preview_time(fixed["history_boundary"])
    for run in runs:
        identifier = positive(run.get("id"), "historical run")
        seen.add(identifier)
        require(
            run.get("repository", {}).get("full_name") == REPOSITORY,
            "Unknown historical repository",
        )
        created, updated = (
            _preview_time(run.get("created_at")),
            _preview_time(run.get("updated_at")),
        )
        # The active current job can update after the inventory check began.
        observed_now = (
            datetime.now(timezone.utc) if identifier == context["run_id"] else now
        )
        require(created <= updated <= observed_now, "Invalid historical run times")
        if (
            identifier <= fixed["run_id"]
            and created <= boundary
            and updated <= boundary
        ):
            # The audit records app identities <=40, not deleted upload attempts.
            continue
        path, source = run.get("path"), sha(run.get("head_sha"))
        attempts = positive(run.get("run_attempt"), "historical attempt")
        require(attempts <= 100, "Historical attempt limit")
        if path == STABLE_PATH and source == fixed["source_sha"]:
            if identifier not in {fixed["run_id"], inventory_run_id}:
                # Earlier successful reads from this same fixed GET-only
                # control are not additional publishers. Authenticate their
                # full producer/report at their recorded completion time.
                for attempt in range(1, attempts + 1):
                    _preview_inventory(api, identifier, attempt, now=updated)
            continue
        if path == "dynamic/dependabot/dependabot-updates":
            _preview_managed_dependabot(api, run)
            continue
        require(
            path in NON_APPLE_WORKFLOWS | {QA_PATH, STABLE_PATH},
            "Unknown post-baseline workflow",
        )
        unsigned_qa = (
            path == QA_PATH
            and hashlib.sha256(api.file(path, source).encode("utf-8")).hexdigest()
            == PREVIEW_UNSIGNED_QA_CONTROLS[QA_PATH]
        )
        workflow_digest = (
            hashlib.sha256(api.file(path, source).encode("utf-8")).hexdigest()
            if path == QA_PATH
            else None
        )
        diagnostic = workflow_digest == PREVIEW_DIAGNOSTIC41["workflow_sha256"]
        inspection43 = workflow_digest == PREVIEW_INSPECTION43["workflow_sha256"]
        archive41 = diagnostic or workflow_digest == PREVIEW_ARCHIVE41_CONTROLS[QA_PATH]
        historical_root = (
            PREVIEW_HISTORICAL_CONTROL_ROOTS.get(source) if path == QA_PATH else None
        )
        historical_controls = (
            archive_controls(ROOT, historical_root) if historical_root else None
        )
        if diagnostic:
            require(
                identifier == PREVIEW_DIAGNOSTIC41["run_id"]
                and source == PREVIEW_DIAGNOSTIC41["source_sha"]
                and attempts == 1
                and run.get("status") == "completed"
                and run.get("conclusion") == "failure"
                and run.get("head_branch") == "codex/ios-archive41-diagnostics-20261028"
                and run.get("workflow_id") == 398590797
                and run.get("event") == "workflow_dispatch",
                "Unknown archive diagnostic execution",
            )
        if inspection43:
            require(
                identifier == PREVIEW_INSPECTION43["run_id"]
                and source == PREVIEW_INSPECTION43["source_sha"]
                and attempts == 1
                and run.get("status") == "completed"
                and run.get("conclusion") == "success"
                and run.get("head_branch")
                == "codex/ios-archive43-prekey-diagnostic-20261028"
                and run.get("workflow_id") == 398590797
                and run.get("event") == "workflow_dispatch"
                and run.get("repository", {}).get("id") == 1135801455
                and run.get("head_repository", {}).get("id") == 1135801455
                and run.get("actor", {}).get("id") == 142351107
                and run.get("triggering_actor", {}).get("id") == 142351107,
                "Unknown pre-key inspection execution",
            )
        if unsigned_qa:
            require(
                all(
                    hashlib.sha256(api.file(p, source).encode("utf-8")).hexdigest()
                    in (
                        {digest, PREVIEW_OLD_ADAPTER_SHA256}
                        if p == "scripts/trusted_ci.py"
                        else {digest}
                    )
                    for p, digest in PREVIEW_UNSIGNED_QA_CONTROLS.items()
                ),
                "Unknown unsigned QA executable controls",
            )
            # Reusable validation graphs still use the current MAIN authority.
            _preview_history_graph(api, CI_PATH, source, trusted, authenticated)
        else:
            _preview_history_graph(
                api, path, source, historical_root or trusted, authenticated
            )
        if path in NON_APPLE_WORKFLOWS:
            continue
        # Apple-capable implementations must be authenticated even if skipped.
        for helper in (
            ()
            if unsigned_qa
            else STABLE_APPLE_HELPERS
            if path == STABLE_PATH
            else (
                p
                for p in (historical_controls or q["controls"])
                if p.startswith(("scripts/", "mobile/scripts/"))
            )
        ):
            observed = api.file(helper, source).encode("utf-8")
            if historical_controls is not None:
                require(
                    device_archive.git_blob(observed) == historical_controls[helper],
                    "Unknown historical MAIN Apple implementation",
                )
                continue
            require(
                (
                    hashlib.sha256(observed).hexdigest()
                    == PREVIEW_ARCHIVE41_CONTROLS[helper]
                )
                if archive41 and helper in PREVIEW_ARCHIVE41_CONTROLS
                else observed == api.control(trusted, helper),
                "Unknown post-baseline Apple implementation",
            )
        current = identifier == context["run_id"]
        require(
            not current
            or (
                path == QA_PATH
                and source == trusted
                and attempts == context["run_attempt"]
            ),
            "Current publication identity differs",
        )
        require(
            current or run.get("status") == "completed",
            "Another Apple-capable run is active",
        )
        for attempt in range(1, attempts + 1):
            jobs = _preview_pages(
                api, f"/actions/runs/{identifier}/attempts/{attempt}/jobs", "jobs"
            )
            require(jobs, "Missing historical attempt jobs")
            require(
                all(
                    j.get("run_id") == identifier and j.get("head_sha") == source
                    for j in jobs
                ),
                "Historical attempt job binding differs",
            )
            checked += 1
            qa_jobs = {
                "Internal QA preflight",
                "Authenticate trusted validation dispatch",
                "Trusted validation",
                FINAL_JOB_NAME,
                ARCHIVE_JOB_NAME,
                ARCHIVE_FINAL_JOB_NAME,
                ARCHIVE_SIGN_JOB_NAME,
                PREVIEW_PUBLICATION_JOB,
                PREVIEW_AVAILABILITY_JOB,
            }
            allowed = {c["job_name"] for c in trusted_ci.CHECKS.values()} | qa_jobs
            if path == QA_PATH:
                if diagnostic:
                    allowed.add(PREVIEW_DIAGNOSTIC41["job_name"])
                if inspection43:
                    allowed.add(PREVIEW_INSPECTION43["job_name"])
                require(
                    all(j.get("name") in allowed for j in jobs),
                    "Unknown historical QA job",
                )
            if diagnostic:
                diagnostic_jobs = [
                    j for j in jobs if j.get("name") == PREVIEW_DIAGNOSTIC41["job_name"]
                ]
                require(
                    len(jobs) == len(qa_jobs) + 1
                    and {j.get("name") for j in jobs}
                    == qa_jobs | {PREVIEW_DIAGNOSTIC41["job_name"]}
                    and len(diagnostic_jobs) == 1
                    and diagnostic_jobs[0].get("id") == PREVIEW_DIAGNOSTIC41["job_id"]
                    and diagnostic_jobs[0].get("status") == "completed"
                    and diagnostic_jobs[0].get("conclusion") == "failure"
                    and all(
                        j.get("status") == "completed"
                        and j.get("conclusion") == "skipped"
                        for j in jobs
                        if j is not diagnostic_jobs[0]
                    )
                    and all(
                        sum(
                            s.get("name") == name
                            and s.get("status") == "completed"
                            and s.get("conclusion") == result
                            for s in diagnostic_jobs[0].get("steps", [])
                        )
                        == 1
                        for name, result in (
                            ("Check out frozen MAIN recipes", "success"),
                            ("Check out immutable build41 source", "success"),
                            (
                                "Install frozen MAIN YAML parser without scripts",
                                "success",
                            ),
                            (
                                "Reproduce frozen archive recipe and retain failure details",
                                "failure",
                            ),
                            ("Retain inert archive diagnostic logs", "success"),
                        )
                    ),
                    "Archive diagnostic job or no-Apple boundary differs",
                )
                continue
            if inspection43:
                inspected = [
                    j for j in jobs if j.get("name") == PREVIEW_INSPECTION43["job_name"]
                ]
                require(
                    len(jobs) == len(qa_jobs) + 1
                    and {j.get("name") for j in jobs}
                    == qa_jobs | {PREVIEW_INSPECTION43["job_name"]}
                    and len(inspected) == 1
                    and inspected[0].get("id") == PREVIEW_INSPECTION43["job_id"]
                    and inspected[0].get("status") == "completed"
                    and inspected[0].get("conclusion") == "success"
                    and all(
                        j.get("status") == "completed"
                        and j.get("conclusion") == "skipped"
                        for j in jobs
                        if j is not inspected[0]
                    )
                    and all(
                        sum(
                            s.get("name") == name for s in inspected[0].get("steps", [])
                        )
                        == 1
                        and all(
                            s.get("status") == "completed"
                            and s.get("conclusion") == "success"
                            for s in inspected[0].get("steps", [])
                            if s.get("name") == name
                        )
                        for name in (
                            "Check out immutable MAIN inspection controls",
                            "Install frozen MAIN parser without scripts",
                            "Inspect existing archive and stop before credentials",
                            "Retain inert pre-key diagnostic",
                        )
                    ),
                    "Pre-key inspection or no-Apple boundary differs",
                )
                continue
            if unsigned_qa:
                require(
                    not current and all(j.get("status") == "completed" for j in jobs),
                    "Unsigned historical QA is still active",
                )
                require(
                    not any(
                        j.get("name")
                        in {PREVIEW_PUBLICATION_JOB, PREVIEW_AVAILABILITY_JOB}
                        for j in jobs
                    ),
                    "Unsigned QA contains a publication job",
                )
                continue
            publication = [j for j in jobs if j.get("name") == PREVIEW_PUBLICATION_JOB]
            if path == STABLE_PATH:
                require(
                    not upload_state(jobs),
                    "Legacy Apple upload requires manual reconciliation",
                )
                continue
            require(len(publication) == 1, "Missing or ambiguous QA publication job")
            job = publication[0]
            if current and attempt == context["run_attempt"]:
                require(
                    job.get("status") == "in_progress",
                    "Current publication job is not active",
                )
                upload = [
                    s
                    for s in job.get("steps", [])
                    if s.get("name") == PREVIEW_PUBLICATION_STEPS[2]
                ]
                require(
                    len(upload) == 1
                    and upload[0].get("status") in {"pending", "in_progress"}
                    and upload[0].get("conclusion") is None,
                    "Current upload has a terminal or ambiguous result",
                )
                current_upload_active = upload[0]["status"] == "in_progress"
                continue
            require(
                job.get("status") == "completed", "Historical publication is active"
            )
            if job.get("conclusion") == "skipped":
                continue
            upload = [
                s
                for s in job.get("steps", [])
                if s.get("name") == PREVIEW_PUBLICATION_STEPS[2]
            ]
            require(
                len(upload) == 1 and upload[0].get("status") == "completed",
                "Ambiguous historical upload",
            )
            if upload[0].get("conclusion") == "skipped":
                continue
            require(
                upload[0].get("conclusion") in {"success", "failure", "cancelled"}
                and all(
                    sum(
                        s.get("name") == name
                        and s.get("status") == "completed"
                        and s.get("conclusion") == "success"
                        for s in job.get("steps", [])
                    )
                    == 1
                    for name in PREVIEW_PUBLICATION_STEPS
                    if name != PREVIEW_PUBLICATION_STEPS[2]
                ),
                "Historical publication gates or receipt retention did not succeed",
            )
            require(
                callable(publication_receipt_reader),
                "Authenticated publication receipt is required",
            )
            receipt = publication_receipt_reader(identifier, attempt)
            require(
                type(receipt) is dict
                and receipt.get("state") in {"confirmed", "uncertain"},
                "Missing authenticated publication receipt",
            )
            original = receipt.get("qa")
            # The authenticated reader returns the R6 post-sign context, not
            # the different unsigned-archive envelope context.
            exact_keys(
                original,
                {
                    "schema",
                    "repository",
                    "pr",
                    "source_sha",
                    "source_tree",
                    "base_sha",
                    "base_tree",
                    "trusted_sha",
                    "workflow",
                    "version",
                    "build",
                    "tag",
                    "run_id",
                    "run_attempt",
                    "artifact",
                    "ipa",
                    "bundles",
                },
            )
            sha(original["source_sha"])
            require(
                all(
                    original[k] == q[k]
                    for k in (
                        "repository",
                        "pr",
                        "version",
                        "build",
                        "tag",
                    )
                )
                and original["source_sha"] != PREVIEW_PROTECTED_STABLE_SOURCE,
                "Historical receipt has another Apple identity",
            )
            artifact = receipt.get("receipt_artifact")
            exact_keys(
                artifact,
                {
                    "artifact_id",
                    "artifact_name",
                    "artifact_digest",
                    "run_id",
                    "run_attempt",
                },
            )
            positive(artifact["artifact_id"], "publication receipt artifact")
            require(
                artifact["run_id"] == identifier
                and artifact["run_attempt"] == attempt
                and type(artifact["artifact_name"]) is str
                and bool(artifact["artifact_name"])
                and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["artifact_digest"])
                is not None,
                "Publication receipt artifact binding differs",
            )
            receipts.append(
                dict(run_id=identifier, run_attempt=attempt, **deepcopy(receipt))
            )
    require(
        {fixed["run_id"], inventory_run_id, context["run_id"]} <= seen,
        "Baseline, fresh inventory or current publication run is missing",
    )
    require(len(receipts) <= 1, "Multiple uploads require manual reconciliation")
    require(
        not (current_upload_active and receipts),
        "An existing upload requires the separate availability job",
    )
    # Reviews and public-version state are outside this internal preview. Any
    # change to those audited collections needs explicit reconciliation.
    for name, collection in baseline["collections"].items():
        if name not in {"builds", "uploads"} and not name.startswith(
            ("groupBuilds:", "groupTesters:", "betaReviews:")
        ):
            require(
                name in fresh["collections"]
                and fresh["collections"][name]["data"] == collection["data"],
                "Apple review or public-version state changed",
            )
    observed = False
    resources = [
        item
        for c in fresh["collections"].values()
        for item in c["data"] + c["included"]
    ]
    resources.extend(
        v["build"]
        for v in fresh.get("appStoreVersionBuilds", [])
        if v.get("build") is not None
    )
    candidate_builds = {
        item["id"]
        for item in resources
        if item.get("type") == "builds"
        and item.get("attributes", {}).get("version") == q["build"]
    }
    versions = {
        item["id"]: item.get("attributes", {})
        for item in resources
        if item.get("type") == "preReleaseVersions"
    }
    for item in resources:
        attributes = item.get("attributes", {})
        if item.get("type") == "betaAppReviewSubmissions":
            linked = item.get("relationships", {}).get("build") or {}
            require(
                attributes.get("betaReviewState") in {"APPROVED", "REJECTED"}
                or (receipts and linked.get("id") in candidate_builds),
                "Another Apple beta review is pending",
            )
        if item.get("type") not in {"builds", "buildUploads"}:
            continue
        upload = item["type"] == "buildUploads"
        number = build_number(
            attributes.get("cfBundleVersion" if upload else "version")
        )
        require(
            number <= build_number(q["build"]),
            "Another Apple build identity was observed",
        )
        if number == build_number(q["build"]):
            require(
                receipts, "Apple candidate build has no authenticated upload source"
            )
            require(
                not upload or attributes.get("cfBundleShortVersionString") == "0.12.0",
                "Apple upload version differs",
            )
            if not upload and item.get("relationships", {}).get("preReleaseVersion"):
                linked = item["relationships"]["preReleaseVersion"]
                require(
                    versions.get(linked.get("id"), {}).get("version") == "0.12.0"
                    and versions[linked["id"]].get("platform") == "IOS",
                    "Apple build version differs",
                )
            observed = True
        else:
            require(
                attributes.get("state" if upload else "processingState")
                == ("COMPLETE" if upload else "VALID"),
                "Another Apple identity is pending",
            )
    return dict(
        decision="availability-required" if receipts else "publish",
        qa=deepcopy(q),
        baseline=baseline_binding,
        inventory=fresh_binding,
        existing_uploads=receipts,
        apple_candidate_build_observed=observed,
        history=dict(
            retained_runs=len(runs),
            checked_attempts=checked,
            deleted_attempts_proven=False,
        ),
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


def _validation_artifact_record(data, *, run_id, run_attempt, artifact_name=None):
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
        and data["artifact_name"]
        == (artifact_name or f"clarify-qa-validation-{run_id}-{run_attempt}"),
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
    # Historical classification also authenticates non-Apple MAIN workflows
    # and their local actions. These bytes are inspected, never executed here.
    paths.update(
        p for p in tree if p.startswith((".github/workflows/", ".github/actions/"))
    )
    require(
        {
            QA_PATH,
            device_archive.MODULE,
            device_archive.SIGNING_HELPER,
            device_archive.QA_VERIFIER,
            device_archive.QA_PUBLISHER,
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
            and 1 <= len(jobs) <= 32
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
            PUBLICATION_JOB_NAME,
            AVAILABILITY_JOB_NAME,
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
        isinstance(jobs, list) and 1 <= len(jobs) <= 32, "Invalid exact-attempt jobs"
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
            | {PUBLICATION_JOB_NAME, AVAILABILITY_JOB_NAME}
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
            if j.get("name")
            in ARCHIVE_JOB_NAMES | {PUBLICATION_JOB_NAME, AVAILABILITY_JOB_NAME}
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

    def phase(name, operation):
        record = {
            "schema": 1,
            "phase": name,
            "exit_code": None,
            "source_sha": policy.context.get("source_sha"),
            "trusted_sha": policy.context.get("trusted_sha"),
        }
        folder = job.metadata / "archive-phases"

        def save():
            try:
                folder.mkdir(parents=True, exist_ok=True)
                if folder.is_symlink():
                    return
                target = folder / (name + ".json")
                if not target.is_symlink():
                    target.write_bytes(canonical_validation_json(record))
            except OSError:
                pass  # Diagnostics never replace the original command result.

        save()
        try:
            result = operation()
        except BaseException as error:
            record.update(
                exit_code=getattr(error, "returncode", 1),
                error_type=type(error).__name__,
            )
            if type(error) is device_archive.ArchiveError:
                record["reason"] = str(error)[:1024]
            save()
            raise
        record["exit_code"] = 0
        save()
        return result

    phase("authenticate", job.authenticate)
    phase("prepare", job.prepare)
    archive_path = job.metadata / device_archive.ARCHIVE_ROOT
    try:
        phase("ios-project", lambda: job.run_recipe("ios-project"))
        phase("ios-pods", lambda: job.run_recipe("ios-pods"))
        phase(
            "device-archive",
            lambda: job.command(
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
            ),
        )
    finally:
        try:
            phase("source-post", job.verify_source)
        finally:
            phase("controls-post", job.verify_controls)
    return phase(
        "inspect-pack", lambda: device_archive.pack(archive_path, output_dir, policy)
    )


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
        and 1 <= len(response["jobs"]) <= 32,
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


def _phase_name(kind, run_id, attempt):
    require(kind in PHASE_ARTIFACTS, "Unknown receipt phase")
    return f"{PHASE_ARTIFACTS[kind][1]}-{run_id}-{attempt}"


def phase_artifact_record(kind, *, run_id, run_attempt, artifact_id, artifact_digest):
    record = dict(
        artifact_id=artifact_id,
        artifact_name=_phase_name(kind, run_id, run_attempt),
        artifact_digest="sha256:" + artifact_digest,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    _validation_artifact_record(
        record,
        run_id=run_id,
        run_attempt=run_attempt,
        artifact_name=record["artifact_name"],
    )
    return PHASE_ARTIFACTS[kind][0] + canonical_validation_json(record).decode("ascii")


def parse_phase_artifact_record(log, kind, *, run_id, run_attempt):
    require(
        kind in PHASE_ARTIFACTS and type(log) is bytes and len(log) <= 1024**2,
        "Invalid receipt log",
    )
    prefix = PHASE_ARTIFACTS[kind][0]
    lines = log.decode("utf-8", errors="strict").splitlines()
    records = []
    for line in lines:
        line = re.sub(
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z ",
            "",
            line,
            count=1,
        )
        if line.startswith(prefix):
            records.append(decode(line[len(prefix) :]))
        else:
            require(prefix not in line, "Unknown receipt log format")
    require(len(records) == 1, "Missing or ambiguous receipt record")
    return _validation_artifact_record(
        records[0],
        run_id=run_id,
        run_attempt=run_attempt,
        artifact_name=_phase_name(kind, run_id, run_attempt),
    )


def _phase_job(api, policy, kind, run_id, attempt, *, completed=True):
    """Authenticate the MAIN implementation before interpreting steps or skips."""
    ctx = policy.context
    control = api.control(ctx["trusted_sha"], QA_PATH)
    require(
        device_archive.git_blob(control) == ctx["workflow"]["blob_sha"],
        "Receipt MAIN workflow bytes differ",
    )
    document = api.workflow_document(control)
    key = "sign_export_proof" if kind == "proof" else "upload"
    name = ARCHIVE_SIGN_JOB_NAME if kind == "proof" else PUBLICATION_JOB_NAME
    required = PROOF_STEPS if kind == "proof" else PUBLICATION_STEPS
    definition = document.get("jobs", {}).get(key, {})
    require(definition.get("name") == name, "Receipt MAIN job definition differs")
    definitions = definition.get("steps", [])
    upload = [s for s in definitions if s.get("name") == required[-2]]
    recorder = [s for s in definitions if s.get("name") == required[-1]]
    require(
        len(upload) == len(recorder) == 1
        and upload[0].get("uses") == UPLOAD_ACTION
        and upload[0].get("with", {}).get("overwrite") is False
        and upload[0]["with"].get("name")
        == PHASE_ARTIFACTS[kind][1] + "-${{ github.run_id }}-${{ github.run_attempt }}"
        and recorder[0].get("run")
        == "python -m scripts.testflight_qa "
        + ("proof-record" if kind == "proof" else "publication-record"),
        "Receipt MAIN uploader/recorder differs",
    )
    run = api.run(run_id, attempt)
    require(
        run.get("id") == run_id
        and run.get("run_attempt") == attempt
        and run.get("head_sha") == ctx["trusted_sha"]
        and run.get("workflow_sha", ctx["trusted_sha"]) == ctx["trusted_sha"]
        and run.get("workflow_id") == ctx["workflow"]["id"]
        and run.get("path") == QA_PATH
        and run.get("event") == "workflow_dispatch"
        and run.get("head_branch") == "main"
        and run.get("repository", {}).get("full_name") == REPOSITORY,
        "Receipt run is not the exact MAIN workflow/attempt",
    )
    allowed = {"success"} if kind == "proof" else {"success", "failure", "cancelled"}
    if completed:
        require(
            run.get("status") == "completed" and run.get("conclusion") in allowed,
            "Receipt run is not terminal",
        )
    jobs = api.pages(f"/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
    require(
        type(jobs) is list
        and 1 <= len(jobs) <= 32
        and len({j.get("id") for j in jobs}) == len(jobs)
        and len({j.get("name") for j in jobs}) == len(jobs),
        "Ambiguous receipt jobs",
    )
    known = (
        {c["job_name"] for c in trusted_ci.CHECKS.values()}
        | ARCHIVE_JOB_NAMES
        | {
            FINAL_JOB_NAME,
            "Internal QA preflight",
            "Trusted validation",
            "Authenticate trusted validation dispatch",
            PUBLICATION_JOB_NAME,
            AVAILABILITY_JOB_NAME,
        }
    )
    require(
        all(
            j.get("name") in known
            and (
                j.get("name") == name
                or (j.get("status") == "completed" and j.get("conclusion") == "skipped")
            )
            for j in jobs
        ),
        "Unexpected active receipt job",
    )
    found = [j for j in jobs if j.get("name") == name]
    require(len(found) == 1, "Missing receipt job")
    job = found[0]
    require(
        type(job.get("id")) is int
        and job["id"] > 0
        and job.get("run_id") == run_id
        and job.get("head_sha") == ctx["trusted_sha"]
        and job.get("run_attempt", attempt) == attempt,
        "Receipt job binding differs",
    )
    steps = job.get("steps", [])
    numbers = [s.get("number") for s in steps]
    require(
        all(type(n) is int and n > 0 for n in numbers)
        and numbers == sorted(set(numbers)),
        "Ambiguous receipt step order",
    )
    positions = []
    for step_name in required:
        matches = [s for s in steps if s.get("name") == step_name]
        require(len(matches) == 1, "Missing or duplicate receipt step")
        item = matches[0]
        positions.append(item["number"])
        if not completed and step_name == required[-1]:
            continue
        conclusions = {"success"}
        if kind == "publication" and step_name == PUBLICATION_STEPS[2]:
            conclusions |= {"failure", "cancelled"}
        require(
            item.get("status") == "completed" and item.get("conclusion") in conclusions,
            "Receipt required step did not complete",
        )
    require(positions == sorted(positions), "Receipt steps are out of order")
    if completed:
        require(
            job.get("status") == "completed" and job.get("conclusion") in allowed,
            "Receipt job did not complete",
        )
    return job


def _phase_artifact(api, record, trusted):
    artifact = api.artifact(record["artifact_id"])
    require(
        artifact.get("id") == record["artifact_id"]
        and artifact.get("name") == record["artifact_name"]
        and artifact.get("digest") == record["artifact_digest"]
        and artifact.get("expired") is False
        and type(artifact.get("size_in_bytes")) is int
        and 0 < artifact["size_in_bytes"] <= 1024**2
        and artifact.get("workflow_run", {}).get("id") == record["run_id"]
        and artifact["workflow_run"].get("head_sha") == trusted,
        "Receipt artifact API binding differs",
    )
    return artifact


def consume_phase_receipt(api, policy, kind, run_id, attempt, artifact_id=None):
    job = _phase_job(api, policy, kind, run_id, attempt)
    raw = api.binary(f"/actions/jobs/{job['id']}/logs", limit=1024**2)
    record = parse_phase_artifact_record(raw, kind, run_id=run_id, run_attempt=attempt)
    require(
        artifact_id is None or artifact_id == record["artifact_id"],
        "Receipt artifact ID differs",
    )
    artifact = _phase_artifact(api, record, policy.context["trusted_sha"])
    data = api.binary(f"/actions/artifacts/{record['artifact_id']}/zip", limit=1024**2)
    require(
        type(data) is bytes
        and len(data) == artifact["size_in_bytes"]
        and "sha256:" + hashlib.sha256(data).hexdigest() == record["artifact_digest"],
        "Receipt artifact bytes differ",
    )
    # upload-artifact preserves paths below the inputs' common ancestor.
    names = (
        {"archive-receipt.json": "archive-receipt.json"}
        if kind == "proof"
        else {
            "context.json": "context.json",
            "output/verification.json": "verification.json",
            "output/upload-receipt.json": "upload-receipt.json",
        }
    )
    with zipfile.ZipFile(io.BytesIO(data)) as zipped:
        entries = zipped.infolist()
        require(
            len(entries) == len(names) and {e.filename for e in entries} == set(names),
            "Unexpected receipt artifact files",
        )
        files = {}
        for entry in entries:
            require(
                entry.orig_filename == entry.filename
                and not entry.is_dir()
                and not entry.flag_bits & 1
                and stat.S_IFMT(entry.external_attr >> 16) in {0, stat.S_IFREG}
                and not (entry.external_attr >> 16) & 0o7000
                and entry.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                and 0 < entry.file_size <= 512 * 1024
                and entry.file_size <= max(1, entry.compress_size) * 1000,
                "Unsafe receipt ZIP entry",
            )
            files[names[entry.filename]] = decode(
                zipped.read(entry).decode("utf-8", errors="strict")
            )
    return dict(files=files, artifact=record, job=job)


def _proof_binding(policy, inputs):
    return {
        key: policy.context[key]
        for key in (
            "source_sha",
            "source_tree",
            "base_sha",
            "base_tree",
            "trusted_sha",
            "workflow",
            "version",
            "build",
            "tag",
            "producer",
        )
    } | {
        "validation_run_id": inputs["validation_run_id"],
        "validation_run_attempt": inputs["validation_run_attempt"],
        "archive_artifact_id": inputs["archive_artifact_id"],
    }


def require_export_proof(api, policy, inputs):
    result = consume_phase_receipt(
        api,
        policy,
        "proof",
        inputs["proof_run_id"],
        inputs["proof_run_attempt"],
        inputs["proof_artifact_id"],
    )
    receipt = result["files"]["archive-receipt.json"]
    require(
        receipt.get("qa_binding") == _proof_binding(policy, inputs)
        and receipt.get("native_export_observed") is True
        and receipt.get("delivery_eligible") is False
        and receipt.get("workflowArtifactProvenanceVerified") is False
        and receipt.get("artifact", {}).get("id") == inputs["archive_artifact_id"],
        "Native export proof differs from this exact composition/archive",
    )
    require(
        inputs["proof_run_id"]
        not in {inputs["validation_run_id"], inputs["producer_run_id"]},
        "Native proof requires a separate completed run",
    )
    return result["artifact"]


def publication_receipt(api, policy, run_id, attempt, artifact_id=None):
    result = consume_phase_receipt(
        api, policy, "publication", run_id, attempt, artifact_id
    )
    files = result["files"]
    qa = files["context.json"]
    helper = device_archive._qa_verifier(ROOT, policy)
    helper.validate_qa_context(qa)
    expected = policy.context
    require(
        all(qa[key] == expected[key] for key in qa if key in expected)
        and qa["run_id"] == run_id
        and qa["run_attempt"] == attempt
        and qa["artifact"]["run_id"] == expected["producer"]["run_id"]
        and qa["artifact"]["run_attempt"] == expected["producer"]["run_attempt"],
        "Published identity or archive differs",
    )
    receipt = files["upload-receipt.json"]
    exact_keys(
        receipt,
        {
            "schema",
            "status",
            "qa",
            "delivery_eligible",
            "workflowArtifactProvenanceVerified",
        },
    )
    require(
        receipt["schema"] == 1
        and receipt["qa"] == qa
        and receipt["status"] in {"confirmed", "uncertain", "started"}
        and receipt["delivery_eligible"] is False
        and receipt["workflowArtifactProvenanceVerified"] is False,
        "Unknown upload outcome receipt",
    )
    verification = files["verification.json"]
    require(
        verification.get("qa") == qa
        and all(
            verification.get(k) is True
            for k in (
                "artifactDigestVerified",
                "ipaDigestVerified",
                "bundleDigestsVerified",
            )
        )
        and verification.get("workflowArtifactProvenanceVerified") is False
        and all(verification.get(k) == qa["ipa"][k] for k in ("sha256", "bytes")),
        "Published IPA verification differs",
    )
    upload = next(
        s for s in result["job"]["steps"] if s["name"] == PUBLICATION_STEPS[2]
    )
    require(
        (receipt["status"] == "confirmed") == (upload["conclusion"] == "success"),
        "Upload receipt contradicts API outcome",
    )
    return dict(
        qa=qa,
        state="confirmed" if receipt["status"] == "confirmed" else "uncertain",
        receipt_artifact=result["artifact"],
    )


def _publication_gates(api, policy, inputs, context):
    require(
        (policy.context["version"], policy.context["build"], policy.context["tag"])
        in PREVIEW_PUBLICATION_IDENTITIES,
        "Only a reserved internal preview identity can publish",
    )
    require_export_proof(api, policy, inputs)
    check_ci(
        api,
        policy.context["trusted_sha"],
        policy.context["base_sha"],
        pull_request=False,
        selected={},
    )
    result = reconcile_preview_history(
        api,
        policy,
        context,
        inventory_run_id=inputs["inventory_run_id"],
        inventory_run_attempt=inputs["inventory_run_attempt"],
        now=datetime.now(timezone.utc),
        publication_receipt_reader=lambda run_id, attempt: publication_receipt(
            api, policy, run_id, attempt
        ),
    )
    require(
        result["decision"] == "publish",
        "Upload already attempted; use authenticated availability only",
    )
    require(
        0
        <= (
            datetime.now(timezone.utc)
            - _preview_time(result["inventory"]["finished_at"])
        ).total_seconds()
        <= 900,
        "Apple inventory expired while authenticating history",
    )
    _validation_current_source(api, inputs)
    return result


def _prepared_publication(policy, context):
    temporary = device_archive.absolute_path(Path(os.environ["RUNNER_TEMP"]))
    paths = device_archive._qa_paths(temporary)
    qa = decode(device_archive.absolute_path(paths["context_path"]).read_bytes())
    require(
        qa["run_id"] == context["run_id"]
        and qa["run_attempt"] == context["run_attempt"],
        "Staged publication is from another run",
    )
    return dict(context=qa, **paths)


def _publication_environment(qa):
    return dict(
        os.environ,
        QA_WORKFLOW_SHA=qa["trusted_sha"],
        QA_WORKFLOW_ID=str(qa["workflow"]["id"]),
        QA_WORKFLOW_REF=REPOSITORY + "/" + QA_PATH + "@refs/heads/main",
    )


def run_publication_command(command, inputs, context):
    api = ArchiveGitHub(os.environ.get("GH_TOKEN", ""))
    policy = archive_policy(api, inputs, context, observe_archive_toolchain())
    temporary = device_archive.absolute_path(Path(os.environ["RUNNER_TEMP"]))
    if command in {"publication-gate", "publication-export", "publication-upload"}:
        _publication_gates(api, policy, inputs, context)
        if command == "publication-gate":
            return
        if command == "publication-export":
            device_archive._qa_verifier(ROOT, policy)
            result = device_archive.sign_export(
                api=api,
                policy=policy,
                artifact_id=inputs["archive_artifact_id"],
                runner_temp=temporary,
                trusted_root=ROOT,
            )
            try:
                device_archive.prepare_qa_context(
                    result,
                    policy,
                    runner_temp=temporary,
                    trusted_root=ROOT,
                    run_id=context["run_id"],
                    run_attempt=context["run_attempt"],
                )
            finally:
                shutil.rmtree(result["workspace"])
        else:
            prepared = _prepared_publication(policy, context)
            device_archive.upload_qa_context(
                prepared, policy, runner_temp=temporary, trusted_root=ROOT
            )
    elif command == "availability":
        require(
            (policy.context["version"], policy.context["build"], policy.context["tag"])
            in PREVIEW_PUBLICATION_IDENTITIES,
            "Only an internal preview identity has an availability route",
        )
        require_export_proof(api, policy, inputs)
        previous = publication_receipt(
            api,
            policy,
            inputs["publication_run_id"],
            inputs["publication_run_attempt"],
            inputs["publication_artifact_id"],
        )
        require(
            previous["qa"]["artifact"]["id"] == inputs["archive_artifact_id"],
            "Availability uses another unsigned archive",
        )
        root = device_archive.absolute_path(temporary / "clarify-ios-qa", exists=False)
        require(not root.exists(), "Availability stage must be fresh")
        root.mkdir(mode=0o700)
        (root / "output").mkdir(mode=0o700)
        qa = previous["qa"] | dict(
            run_id=context["run_id"], run_attempt=context["run_attempt"]
        )
        (root / "context.json").write_bytes(canonical_validation_json(qa))
        helper = ROOT / "mobile/scripts/publish-testflight.cjs"
        require(
            device_archive.git_blob(helper.read_bytes())
            == policy.context["controls"]["mobile/scripts/publish-testflight.cjs"],
            "MAIN availability helper differs",
        )
        node = shutil.which("node")
        require(node is not None, "Pinned Node is unavailable")
        result = subprocess.run(
            [node, str(helper), "--qa-context", str(root / "context.json")],
            cwd=ROOT / "mobile",
            env=_publication_environment(qa),
            capture_output=True,
            timeout=3600,
            check=False,
        )
        require(
            result.returncode == 0,
            "Apple processing/internal availability is still pending; do not upload again",
        )
    elif command in {"proof-record", "publication-record"}:
        kind = "proof" if command == "proof-record" else "publication"
        job = _phase_job(
            api,
            policy,
            kind,
            context["run_id"],
            context["run_attempt"],
            completed=False,
        )
        require(
            job.get("status") in {"in_progress", "completed"}, "Recorder is not active"
        )
        identifier = os.environ["QA_UPLOAD_ARTIFACT_ID"]
        require(
            re.fullmatch(r"[1-9][0-9]{0,15}", identifier), "Invalid receipt uploader ID"
        )
        line = phase_artifact_record(
            kind,
            run_id=context["run_id"],
            run_attempt=context["run_attempt"],
            artifact_id=int(identifier),
            artifact_digest=os.environ["QA_UPLOAD_ARTIFACT_DIGEST"],
        )
        record = parse_phase_artifact_record(
            line.encode(),
            kind,
            run_id=context["run_id"],
            run_attempt=context["run_attempt"],
        )
        _phase_artifact(api, record, policy.context["trusted_sha"])
        print(line)
    else:
        raise ReleaseError("Unknown publication command")


def _runtime_archive_inputs(context, command):
    event_path = Path(os.environ["GITHUB_EVENT_PATH"])
    require(event_path.stat().st_size <= 64 * 1024, "Dispatch event is too large")
    event = decode(event_path.read_text(encoding="utf-8"))
    inputs = event.get("inputs")
    allowed = PUBLICATION_INPUTS | {
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
    if command in {"sign-export-proof", "proof-record"}:
        expected_mode = "sign-export-proof"
    elif command.startswith("publication-"):
        expected_mode = "upload"
    elif command == "availability":
        expected_mode = "availability"
    else:
        expected_mode = "archive"
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
    if expected_mode in {"sign-export-proof", "upload", "availability"}:
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
    if expected_mode in {"upload", "availability"}:
        keys += ["proof_run_id", "proof_run_attempt", "proof_artifact_id"]
    if expected_mode == "upload":
        keys += ["inventory_run_id", "inventory_run_attempt"]
    if expected_mode == "availability":
        keys += [
            "publication_run_id",
            "publication_run_attempt",
            "publication_artifact_id",
        ]
    require(
        all(inputs.get(k, "") == "" for k in PUBLICATION_INPUTS - set(keys)),
        "Unexpected publication inputs for this mode",
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
    if expected_mode in {"sign-export-proof", "upload", "availability"}:
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
                device_archive.canonical(
                    result["receipt"]
                    | {
                        "qa_binding": _proof_binding(policy, inputs),
                        "native_export_observed": True,
                    }
                )
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


def _report_error_location(error):
    """Print one trusted code location, never exception values or local paths."""
    trusted = {
        ROOT / "scripts/testflight_qa.py": "scripts/testflight_qa.py",
        ROOT / "scripts/qa_device_archive.py": "scripts/qa_device_archive.py",
    }
    location = None
    trace = error.__traceback__
    while trace is not None:
        code = trace.tb_frame.f_code
        path = trusted.get(Path(code.co_filename))
        if path is not None and code.co_name != "require":
            location = f"{path}:{code.co_name}:{trace.tb_lineno}"
        trace = trace.tb_next
    if location is not None:
        print(f"Internal QA location: {location}.", file=sys.stderr)


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
                ["proof-record"],
                ["publication-gate"],
                ["publication-export"],
                ["publication-upload"],
                ["publication-record"],
                ["availability"],
                ["publication-cleanup"],
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
        if command == "publication-cleanup":
            validate_context(ctx | {"mode": "preflight"})
            temporary = device_archive.absolute_path(Path(os.environ["RUNNER_TEMP"]))
            path = device_archive.absolute_path(
                temporary / "clarify-ios-qa", exists=False
            )
            if path.exists():
                shutil.rmtree(path)
            return 0
        if command in {
            "proof-record",
            "publication-gate",
            "publication-export",
            "publication-upload",
            "publication-record",
            "availability",
        }:
            inputs = _runtime_archive_inputs(ctx, command)
            run_publication_command(command, inputs, ctx)
            return 0
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
    except device_archive.ArchiveError as error:
        # Only fixed MAIN labels can reach the log. Unknown exception text,
        # subprocess arguments and captured streams remain private.
        stage = {
            "Existing signing credential installation failed": "credential-install",
            "Unsigned archive export unsupported or failed": "archive-export",
            "Export signature inspection failed": "signature-verification",
            "Export entitlement inspection failed": "entitlement-verification",
            "Signing credential cleanup failed": "credential-cleanup",
        }.get(str(error), "archive-validation")
        print(f"Internal QA archive blocked at {stage}.", file=sys.stderr)
        _report_error_location(error)
        return 1
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
    ) as error:
        print(
            "Internal QA preflight blocked. Check identity, exact CI, history and helper limits.",
            file=sys.stderr,
        )
        kind = (
            type(error).__name__
            if type(error)
            in {
                KeyError,
                TypeError,
                ValueError,
                OSError,
                subprocess.SubprocessError,
                RecursionError,
            }
            else "validation-error"
        )
        print(f"Internal QA error type: {kind}.", file=sys.stderr)
        _report_error_location(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
