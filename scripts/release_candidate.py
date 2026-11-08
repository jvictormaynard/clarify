"""Seal a desktop candidate, or publish its authenticated bytes without a build.

The build owns packaging and signing. This owner binds its exact outputs to a
successful producer and rejects ambiguous publication state. No retry overwrites
an artifact, tag or release asset.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from . import release_delivery as release
except ImportError:
    import release_delivery as release

require = release.require
WORKFLOW = ".github/workflows/release.yml"
BUILD_JOB = "Build desktop candidate"
MANIFEST = "Clarify-candidate.json"
MAX_BYTES = 1024 * 1024 * 1024
BASE_ASSETS = release.ASSETS - {
    "Clarify-portable-update.json",
    "Clarify-portable-update.json.sig",
}


def allowed_assets(channel):
    require(channel in {"preview", "stable"}, "Unknown candidate channel")
    return set(
        release.ASSETS
        if channel == "stable"
        else BASE_ASSETS | {"Clarify-preview.json"}
    )


def positive(value):
    require(
        re.fullmatch(r"[1-9][0-9]*", str(value)) is not None,
        "Expected a positive identifier",
    )
    return int(value)


def digest(value):
    require(
        isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value),
        "Expected an exact SHA-256 artifact digest",
    )
    return value


def identity(source, source_ref, run_id, attempt, channel, version):
    release.sha(source)
    release.version(version)
    allowed_assets(channel)
    run_id, attempt = positive(run_id), positive(attempt)
    require(attempt <= 100, "Candidate retry limit exceeded")
    if channel == "stable":
        tag = "v" + version
        require(
            source_ref == "refs/tags/" + tag,
            "Stable candidate requires its final immutable tag",
        )
    else:
        require(
            isinstance(source_ref, str)
            and source_ref.startswith("refs/heads/")
            and len(source_ref) > 11,
            "Preview requires an exact branch source",
        )
        tag = release.preview_tag(source, str(run_id), attempt)
    return {
        "schema": 1,
        "repository": release.REPOSITORY,
        "workflow": WORKFLOW,
        "job": BUILD_JOB,
        "source_sha": source,
        "source_ref": source_ref,
        "run_id": run_id,
        "run_attempt": attempt,
        "channel": channel,
        "version": version,
        "tag": tag,
    }


def file_record(path):
    require(
        path.is_file() and not path.is_symlink() and not path.is_junction(),
        "Candidate input must be a regular file",
    )
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            hasher.update(block)
    size = path.stat().st_size
    require(0 < size <= MAX_BYTES, "Invalid candidate asset size")
    return {"sha256": hasher.hexdigest(), "size": size}


def seal(inputs, output, expected):
    """Copy only final allowed files from build output into a new artifact root."""
    require(not output.exists(), "Candidate output already exists")
    allowed = allowed_assets(expected["channel"])
    forbidden = allowed_assets("stable") - allowed
    require(
        not any((inputs / name).exists() for name in forbidden),
        "Preview must have no update metadata",
    )
    # Build directories also contain intermediate SBOM and notice files. Only
    # allowlisted files cross this boundary; publication accepts no extras.
    records = {name: file_record(inputs / name) for name in sorted(allowed)}
    output.mkdir(parents=True)
    for name in sorted(allowed):
        shutil.copyfile(inputs / name, output / name)
    manifest = dict(expected, assets=records)
    (output / MANIFEST).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    verify_directory(output, expected)
    return manifest


def verify_directory(directory, expected):
    require(
        directory.is_dir()
        and not directory.is_symlink()
        and not directory.is_junction(),
        "Invalid candidate directory",
    )
    document = release.decode((directory / MANIFEST).read_text(encoding="utf-8"))
    require(set(document) == set(expected) | {"assets"}, "Unexpected manifest fields")
    require(
        all(
            type(document.get(key)) is type(value) and document.get(key) == value
            for key, value in expected.items()
        ),
        "Candidate identity differs",
    )
    allowed = allowed_assets(expected["channel"])
    require(
        isinstance(document["assets"], dict) and set(document["assets"]) == allowed,
        "Candidate asset inventory differs",
    )
    require(
        {entry.name for entry in directory.iterdir()} == allowed | {MANIFEST},
        "Extra or missing candidate inputs",
    )
    for name in allowed | {MANIFEST}:
        record = file_record(directory / name)
        if name != MANIFEST:
            release.exact_keys(document["assets"][name], {"sha256", "size"})
            require(
                type(document["assets"][name]["size"]) is int
                and record == document["assets"][name],
                "Candidate asset hash or size differs: " + name,
            )
    return document


def extract(data, expected_digest, output):
    require(
        "sha256:" + hashlib.sha256(data).hexdigest() == digest(expected_digest),
        "Downloaded artifact digest differs",
    )
    allowed = allowed_assets("stable") | allowed_assets("preview") | {MANIFEST}
    extract_files(data, allowed, output, required={MANIFEST})


def extract_files(data, allowed, output, *, required=None):
    require(not output.exists(), "Artifact extraction destination already exists")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        require(
            len(names) == len(set(names))
            and set(names) <= allowed
            and (required or allowed) <= set(names),
            "Duplicate, escaping or unexpected archive paths",
        )
        require(
            sum(entry.file_size for entry in entries) <= MAX_BYTES,
            "Candidate archive exceeds size limit",
        )
        for entry in entries:
            mode = entry.external_attr >> 16
            require(
                not entry.is_dir()
                and not (mode and stat.S_IFMT(mode) not in {0, stat.S_IFREG}),
                "Archive contains a nonregular input",
            )
            require(
                not entry.flag_bits & 1 and 0 < entry.file_size <= MAX_BYTES,
                "Invalid archived asset",
            )
        output.mkdir(parents=True)
        for entry in entries:
            with (output / entry.filename).open("xb") as stream:
                stream.write(archive.read(entry))


def producer_steps(channel):
    steps = [
        "Build portable executable",
        "Verify frozen portable replacement and recovery",
        "Seal desktop candidate",
        "Attest candidate provenance",
        "Upload desktop candidate",
    ]
    if channel == "stable":
        steps.append("Sign portable update metadata")
    return steps


def authenticate(api, expected, artifact_id, artifact_digest):
    """Authenticate live run, attempt, workflow, build steps and immutable artifact."""
    run_id, attempt, artifact_id = (
        expected["run_id"],
        expected["run_attempt"],
        positive(artifact_id),
    )
    artifact_digest = digest(artifact_digest)
    run = api.request("GET", f"/actions/runs/{run_id}")
    require(
        run.get("id") == run_id
        and run.get("run_attempt") == attempt
        and run.get("repository", {}).get("full_name") == release.REPOSITORY
        and run.get("head_repository", {}).get("full_name") == release.REPOSITORY
        and run.get("event") == "workflow_dispatch"
        and run.get("head_sha") == expected["source_sha"]
        and run.get("head_branch") == expected["source_ref"].split("/", 2)[2]
        and run.get("path") == WORKFLOW
        and run.get("status") == "completed"
        and run.get("conclusion") == "success",
        "Candidate producer identity, attempt or result differs",
    )
    workflow = api.request("GET", f"/actions/workflows/{positive(run['workflow_id'])}")
    require(
        workflow.get("path") == WORKFLOW and workflow.get("name") == "Desktop Release",
        "Unexpected producer workflow",
    )
    jobs = api.pages(f"/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
    matches = [job for job in jobs if job.get("name") == BUILD_JOB]
    require(
        len(matches) == 1
        and matches[0].get("status") == "completed"
        and matches[0].get("conclusion") == "success"
        and matches[0].get("run_attempt") == attempt,
        "Candidate build job is not successful",
    )
    for name in producer_steps(expected["channel"]):
        steps = [
            step for step in matches[0].get("steps", []) if step.get("name") == name
        ]
        require(
            len(steps) == 1
            and steps[0].get("status") == "completed"
            and steps[0].get("conclusion") == "success",
            "Missing successful producer step: " + name,
        )
    artifact = api.request("GET", f"/actions/artifacts/{artifact_id}")
    listed = api.pages(f"/actions/runs/{run_id}/artifacts", "artifacts")
    name = f"desktop-candidate-{run_id}-{attempt}"
    matches = [row for row in listed if row.get("name") == name]
    require(
        len(matches) == 1
        and matches[0] == artifact
        and artifact.get("id") == artifact_id
        and artifact.get("name") == name
        and artifact.get("expired") is False
        and artifact.get("digest") == artifact_digest
        and artifact.get("workflow_run", {}).get("id") == run_id
        and artifact.get("workflow_run", {}).get("head_sha") == expected["source_sha"],
        "Candidate artifact identity or digest differs",
    )
    return artifact


def acceptance(expected, artifact_digest, evidence, now=None):
    release.exact_keys(
        evidence,
        {
            "schema",
            "source_sha",
            "candidate_digest",
            "windows_accepted",
            "checked_at",
            "report_url",
        },
    )
    require(
        type(evidence["schema"]) is int
        and evidence["schema"] == 1
        and evidence["source_sha"] == expected["source_sha"]
        and evidence["candidate_digest"] == digest(artifact_digest)
        and evidence["windows_accepted"] is True,
        "Windows acceptance must cover the packaged candidate",
    )
    require(
        isinstance(evidence["report_url"], str)
        and re.fullmatch(
            r"https://github\.com/jvictormaynard/clarify/issues/[1-9][0-9]*(?:#issuecomment-[1-9][0-9]*)?",
            evidence["report_url"],
        ),
        "Use a canonical candidate acceptance report",
    )
    checked = datetime.strptime(evidence["checked_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    require(
        0 <= ((now or datetime.now(timezone.utc)) - checked).total_seconds() <= 86400,
        "Repeat Windows acceptance reporting within 24 hours",
    )


def verify_acceptance_report(api, expected, artifact_digest, evidence, now=None):
    acceptance(expected, artifact_digest, evidence, now)
    issue = evidence["report_url"].split("/issues/", 1)[1]
    path = (
        "/issues/comments/" + issue.split("#issuecomment-")[1]
        if "#issuecomment-" in issue
        else "/issues/" + issue
    )
    report = api.request("GET", path)
    require(
        report.get("html_url") == evidence["report_url"]
        and "pull_request" not in report,
        "Acceptance report identity differs",
    )
    actor = report.get("user", {}).get("login", "")
    require(
        re.fullmatch(r"[A-Za-z0-9-]+", actor) is not None,
        "Acceptance report has no maintainer",
    )
    require(
        api.request("GET", "/collaborators/" + actor + "/permission").get("permission")
        in {"write", "maintain", "admin"},
        "Acceptance needs a maintainer report",
    )
    blocks = re.findall(
        r"```clarify-candidate-acceptance\s*\n(.*?)\n```",
        report.get("body", ""),
        re.DOTALL,
    )
    require(
        len(blocks) == 1 and release.decode(blocks[0]) == evidence,
        "Canonical report does not accept this exact candidate",
    )
    updated = datetime.strptime(report["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    require(
        0 <= ((now or datetime.now(timezone.utc)) - updated).total_seconds() <= 86400,
        "Canonical acceptance report is stale",
    )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def download(api, path):
    """Keep the API token off the signed cross-origin download redirect."""
    require(
        path.startswith("/actions/artifacts/") or path.startswith("/releases/assets/"),
        "Invalid binary API path",
    )
    request = Request(
        api.base + path,
        headers={
            "Authorization": "Bearer " + api.token,
            "Accept": "application/octet-stream",
        },
    )
    try:
        response = build_opener(NoRedirect()).open(request, timeout=60)
    except HTTPError as error:
        require(error.code in {301, 302, 303, 307}, "Artifact download failed")
        location = error.headers.get("Location", "")
        parsed = urlsplit(location)
        require(
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and (parsed.hostname or "").endswith(
                (".githubusercontent.com", ".blob.core.windows.net")
            ),
            "Unexpected artifact download host",
        )
        response = urlopen(location, timeout=60)
    with response:
        data = response.read(MAX_BYTES + 1)
    require(len(data) <= MAX_BYTES, "Download exceeds candidate limit")
    return data


def verify_provenance(directory, expected):
    for name in sorted(allowed_assets(expected["channel"]) | {MANIFEST}):
        subprocess.run(
            [
                "gh",
                "attestation",
                "verify",
                str(directory / name),
                "--repo",
                release.REPOSITORY,
                "--signer-workflow",
                release.REPOSITORY + "/" + WORKFLOW,
                "--source-digest",
                expected["source_sha"],
                "--source-ref",
                expected["source_ref"],
                "--signer-digest",
                expected["source_sha"],
                "--deny-self-hosted-runners",
            ],
            check=True,
        )


def verify_payload(directory, expected, *, building=False):
    """Recheck checksum, source licenses, archive membership and stable signature."""
    executable = file_record(directory / "Clarify.exe")
    require(
        (directory / "Clarify.exe.sha256").read_text(encoding="ascii").strip()
        == executable["sha256"] + "  Clarify.exe",
        "Executable checksum differs",
    )
    require(
        file_record(directory / "sox-14.4.2-source.tar.gz")["sha256"]
        == "b45f598643ffbd8e363ff24d61166ccec4836fea6d3888881b8df53e3bb55f6c",
        "SoX source digest differs",
    )
    with zipfile.ZipFile(directory / "Clarify-windows-x64.zip") as archive:
        names = archive.namelist()
        required = {
            "Clarify.exe",
            "Clarify.exe.sha256",
            "Clarify.sbom.json",
            "LICENSE",
            "THIRD_PARTY_NOTICES.md",
            "Clarify-settings-NOTICES.txt",
            "Clarify-qt-NOTICES.txt",
            "Clarify-crypto-NOTICES.txt",
        }
        require(
            len(names) == len(set(names)) and set(names) == required,
            "Portable ZIP inventory differs",
        )
        for name in ("Clarify.exe", "Clarify.exe.sha256", "Clarify.sbom.json"):
            require(
                hashlib.sha256(archive.read(name)).hexdigest()
                == file_record(directory / name)["sha256"],
                "Portable ZIP bytes differ",
            )
    if expected["channel"] == "stable":
        # OpenSSL and gh are runner tools. The publisher installs no application
        # dependencies and has no signing key. Verify against its trusted pin.
        policy = release.decode(
            (
                Path(__file__).resolve().parents[1]
                / "distribution/portable-update-policy.json"
            ).read_text(encoding="utf-8")
        )
        public_key = base64.b64decode(policy["public_key"], validate=True)
        require(
            len(public_key) == 32
            and policy["channel"] == "stable"
            and policy["algorithm"] == "Ed25519"
            and policy["repository"] == release.REPOSITORY,
            "Invalid stable update pin",
        )
        metadata_path = directory / "Clarify-portable-update.json"
        signature_path = directory / "Clarify-portable-update.json.sig"
        require(
            0 < metadata_path.stat().st_size <= 16384
            and signature_path.stat().st_size == 64,
            "Invalid signed metadata size",
        )
        if building:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )

            Ed25519PublicKey.from_public_bytes(public_key).verify(
                signature_path.read_bytes(), metadata_path.read_bytes()
            )
        else:
            with tempfile.TemporaryDirectory(prefix="clarify-public-key-") as temporary:
                key_path = Path(temporary) / "public.der"
                key_path.write_bytes(
                    bytes.fromhex("302a300506032b6570032100") + public_key
                )
                subprocess.run(
                    [
                        "openssl",
                        "pkeyutl",
                        "-verify",
                        "-pubin",
                        "-inkey",
                        str(key_path),
                        "-keyform",
                        "DER",
                        "-rawin",
                        "-in",
                        str(metadata_path),
                        "-sigfile",
                        str(signature_path),
                    ],
                    check=True,
                    capture_output=True,
                )
        metadata = release.decode(metadata_path.read_text(encoding="utf-8"))
        require(
            metadata
            == {
                "schema_version": 1,
                "repository": release.REPOSITORY,
                "channel": "stable",
                "version": expected["version"],
                "tag": expected["tag"],
                "source_sha": expected["source_sha"],
                "asset": "Clarify.exe",
                "url": f"https://github.com/{release.REPOSITORY}/releases/download/{expected['tag']}/Clarify.exe",
                "sha256": executable["sha256"],
                "size": executable["size"],
            },
            "Signed update identity differs",
        )
    else:
        preview = release.decode(
            (directory / "Clarify-preview.json").read_text(encoding="utf-8")
        )
        require(
            preview
            == {
                "schema": 1,
                "channel": "preview",
                "source_sha": expected["source_sha"],
                "run_id": str(expected["run_id"]),
                "run_attempt": expected["run_attempt"],
                "tag": expected["tag"],
                "version": expected["version"],
                "updater_enabled": False,
            }
            and type(preview["schema"]) is int
            and type(preview["run_attempt"]) is int
            and preview["updater_enabled"] is False,
            "Preview identity differs",
        )


def verify_source(api, expected, *, building=False, allow_published=False):
    if expected["channel"] == "stable":
        intent = release.verify_source(
            api, "desktop", expected["source_sha"], expected["tag"]
        )
        require(intent["version"] == expected["version"], "Reviewed version differs")
        if building:
            require(
                api.request("GET", "/git/ref/heads/main")["object"]["sha"]
                == expected["source_sha"],
                "Stable build source is stale against main",
            )
        if not allow_published:
            release.require_new_desktop_release(api, intent)
    else:
        # The producer run authenticates the exact historical branch SHA. A
        # subsequent branch push cannot change this candidate's source identity.
        release.sha(expected["source_sha"])


def release_state(api, expected, manifest, artifact_digest, *, downloaded=False):
    current = release.tag_source(api, expected["tag"])
    require(current in {None, expected["source_sha"]}, "Existing immutable tag differs")
    if expected["channel"] == "stable":
        require(current == expected["source_sha"], "Stable tag is missing")
    existing = api.request(
        "GET", "/releases/tags/" + quote(expected["tag"], safe=""), missing=True
    )
    if existing is None:
        require(not downloaded, "Published release disappeared")
        return None
    require(
        current == expected["source_sha"]
        and existing.get("draft") is False
        and existing.get("prerelease") is (expected["channel"] == "preview")
        and f"Candidate {artifact_digest}" in existing.get("body", ""),
        "Existing release is partial or belongs to another candidate; inspect without replacing assets",
    )
    assets = api.pages(f"/releases/{positive(existing['id'])}/assets")
    require(
        len(assets) == len(manifest["assets"])
        and {asset.get("name") for asset in assets} == set(manifest["assets"]),
        "Existing release asset inventory differs",
    )
    for asset in assets:
        record = manifest["assets"][asset["name"]]
        require(
            asset.get("state") == "uploaded"
            and asset.get("size") == record["size"]
            and asset.get("digest") == "sha256:" + record["sha256"],
            "Existing release asset is uncertain or replaced",
        )
        data = download(api, f"/releases/assets/{positive(asset['id'])}")
        require(
            len(data) == record["size"]
            and hashlib.sha256(data).hexdigest() == record["sha256"],
            "Downloaded release asset differs",
        )
    return existing


def upload(api, release_id, name, path):
    request = Request(
        f"https://uploads.github.com/repos/{release.REPOSITORY}/releases/{positive(release_id)}/assets?name={quote(name, safe='')}",
        data=path.read_bytes(),
        method="POST",
        headers={
            "Authorization": "Bearer " + api.token,
            "Content-Type": "application/octet-stream",
            "Accept": "application/vnd.github+json",
        },
    )
    with build_opener(NoRedirect()).open(request, timeout=120) as response:
        return release.decode(response.read())


def publish(
    api,
    directory,
    expected,
    artifact_id,
    artifact_digest,
    evidence,
    *,
    provenance=verify_provenance,
    payload=verify_payload,
    uploader=upload,
):
    manifest = verify_directory(directory, expected)
    authenticate(api, expected, artifact_id, artifact_digest)
    if expected["channel"] == "stable":
        verify_acceptance_report(api, expected, artifact_digest, evidence)
    verify_source(api, expected, allow_published=True)
    existing = release_state(api, expected, manifest, artifact_digest)
    if existing is not None:
        return "already-published"
    verify_source(api, expected)
    payload(directory, expected)
    provenance(directory, expected)
    # Recheck all identities and bytes after the slow read-only verification.
    authenticate(api, expected, artifact_id, artifact_digest)
    verify_directory(directory, expected)
    require(
        release_state(api, expected, manifest, artifact_digest) is None,
        "Publication state changed",
    )
    verify_source(api, expected)
    if expected["channel"] == "stable":
        verify_acceptance_report(api, expected, artifact_digest, evidence)
    if expected["channel"] == "preview":
        require(
            release.tag_source(api, expected["tag"]) is None,
            "Preview tag already exists; inspect the interrupted publication",
        )
        api.request(
            "POST",
            "/git/refs",
            {"ref": "refs/tags/" + expected["tag"], "sha": expected["source_sha"]},
        )
    require(
        release.tag_source(api, expected["tag"]) == expected["source_sha"],
        "Tag changed before publication",
    )
    notes = (
        release.community_release_notes(
            api.file("CHANGELOG.md", expected["source_sha"]), expected["tag"]
        )
        if expected["channel"] == "stable"
        else "Manual preview. Packaged updates are disabled.\n"
    )
    draft = api.request(
        "POST",
        "/releases",
        {
            "tag_name": expected["tag"],
            "target_commitish": expected["source_sha"],
            "name": "Clarify " + expected["tag"],
            "body": notes + "\nCandidate " + artifact_digest,
            "draft": True,
            "prerelease": expected["channel"] == "preview",
            "make_latest": "false",
        },
    )
    for name, record in manifest["assets"].items():
        require(file_record(directory / name) == record, "Asset changed before upload")
        asset = uploader(api, draft["id"], name, directory / name)
        require(
            asset.get("name") == name
            and asset.get("state") == "uploaded"
            and asset.get("size") == record["size"]
            and asset.get("digest") == "sha256:" + record["sha256"],
            "Upload outcome is uncertain; inspect the draft without retrying",
        )
    assets = api.pages(f"/releases/{positive(draft['id'])}/assets")
    require(
        len(assets) == len(manifest["assets"])
        and {item.get("name") for item in assets} == set(manifest["assets"]),
        "Draft inventory differs; inspect without replacing assets",
    )
    for asset in assets:
        record = manifest["assets"][asset["name"]]
        require(
            asset.get("state") == "uploaded"
            and asset.get("digest") == "sha256:" + record["sha256"]
            and asset.get("size") == record["size"],
            "Draft asset differs; inspect without replacing assets",
        )
    authenticate(api, expected, artifact_id, artifact_digest)
    verify_source(api, expected)
    if expected["channel"] == "stable":
        verify_acceptance_report(api, expected, artifact_digest, evidence)
    require(
        release.tag_source(api, expected["tag"]) == expected["source_sha"],
        "Tag changed during upload",
    )
    api.request(
        "PATCH",
        f"/releases/{positive(draft['id'])}",
        {
            "draft": False,
            "make_latest": "true" if expected["channel"] == "stable" else "false",
        },
    )
    release_state(api, expected, manifest, artifact_digest, downloaded=True)
    if expected["channel"] == "stable":
        require(
            api.request("GET", "/releases/latest").get("id") == draft["id"],
            "Stable latest release does not identify the published candidate",
        )
    return "published"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build-gate", "seal", "publish"])
    parser.add_argument("--channel", choices=["preview", "stable"], required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--version")
    parser.add_argument("--run-id")
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--artifact-id")
    parser.add_argument("--artifact-digest")
    parser.add_argument("--inputs", type=Path, default=Path("dist"))
    parser.add_argument("--output", type=Path, default=Path("candidate"))
    args = parser.parse_args()
    require(
        os.environ.get("GITHUB_REPOSITORY") == release.REPOSITORY
        and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch",
        "Use a canonical manual release action",
    )
    api = release.GitHub(os.environ.get("GH_TOKEN", ""))
    if args.command == "publish":
        require(
            os.environ.get("CLARIFY_RELEASE_PUBLICATION_ENABLED") == "true",
            "Candidate publication is disabled",
        )
        require(
            os.environ.get("GITHUB_REF") == "refs/heads/main",
            "Publish from the trusted main workflow",
        )
        run = api.request("GET", f"/actions/runs/{positive(args.run_id)}")
        source_ref = (
            "refs/tags/" if args.channel == "stable" else "refs/heads/"
        ) + run["head_branch"]
        expected = identity(
            args.source_sha,
            source_ref,
            args.run_id,
            args.attempt,
            args.channel,
            args.version,
        )
        authenticate(api, expected, args.artifact_id, args.artifact_digest)
        with tempfile.TemporaryDirectory(prefix="clarify-candidate-") as temporary:
            directory = Path(temporary) / "candidate"
            extract(
                download(api, f"/actions/artifacts/{positive(args.artifact_id)}/zip"),
                args.artifact_digest,
                directory,
            )
            result = publish(
                api,
                directory,
                expected,
                args.artifact_id,
                args.artifact_digest,
                release.decode(os.environ.get("CANDIDATE_ACCEPTANCE", "{}")),
            )
        print(result)
    else:
        require(
            os.environ.get("GITHUB_SHA") == args.source_sha,
            "Build source must match the exact dispatched SHA",
        )
        text = Path("version.py").read_text(encoding="utf-8")
        match = re.search(r'^__version__ = "([0-9.]+)"$', text, re.MULTILINE)
        require(match is not None, "Cannot read candidate version")
        require(
            release.decode(Path("package.json").read_text(encoding="utf-8")).get(
                "version"
            )
            == match[1],
            "Candidate package and executable versions differ",
        )
        expected = identity(
            args.source_sha,
            os.environ["GITHUB_REF"],
            os.environ["GITHUB_RUN_ID"],
            os.environ["GITHUB_RUN_ATTEMPT"],
            args.channel,
            match[1],
        )
        if args.command == "build-gate":
            verify_source(api, expected, building=True)
            require(
                api.request(
                    "GET",
                    "/releases/tags/" + quote(expected["tag"], safe=""),
                    missing=True,
                )
                is None,
                "Release exists; select and inspect its existing candidate",
            )
        else:
            verify_payload(args.inputs, expected, building=True)
            seal(args.inputs, args.output, expected)
        print(json.dumps(expected, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (
        release.ReleaseError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.CalledProcessError,
        zipfile.BadZipFile,
    ):
        raise SystemExit(
            "Candidate action blocked. Check source, producer, artifact digest, acceptance and publication state. No automatic upload retry is allowed."
        ) from None
