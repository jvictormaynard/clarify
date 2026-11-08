"""Prepare a manual App Store action from an existing verified TestFlight build.

GitHub reads authenticate the evidence producer. This tool never calls Apple,
uploads a binary, submits an app, or claims public availability.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import hashlib
import tempfile

try:
    from . import release_delivery as release
    from . import release_candidate as candidate
except ImportError:
    import release_delivery as release
    import release_candidate as candidate

EVIDENCE_FILES = {
    "verification.json",
    "upload-receipt.json",
    "testflight-availability.json",
}
EVIDENCE_MANIFEST = "TestFlight-candidate.json"


def seal_evidence(directory, output, source, tag, run_id, attempt):
    release.sha(source)
    release.require(not output.exists(), "Evidence output already exists")
    records = {
        name: candidate.file_record(directory / name) for name in sorted(EVIDENCE_FILES)
    }
    receipt = release.decode(
        (directory / "upload-receipt.json").read_text(encoding="utf-8")
    )
    verification = release.decode(
        (directory / "verification.json").read_text(encoding="utf-8")
    )
    release.require(
        receipt.get("state") == "confirmed"
        and receipt.get("source") == source
        and receipt.get("run_id") == str(run_id)
        and receipt.get("attempt") == str(attempt)
        and receipt.get("ipa_sha256") == verification.get("sha256"),
        "Uncertain or unrelated Apple upload receipt",
    )
    output.mkdir(parents=True)
    for name in EVIDENCE_FILES:
        (output / name).write_bytes((directory / name).read_bytes())
    (output / EVIDENCE_MANIFEST).write_text(
        json.dumps(
            {
                "schema": 1,
                "source_sha": source,
                "tag": tag,
                "run_id": candidate.positive(run_id),
                "run_attempt": candidate.positive(attempt),
                "files": records,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def authenticated_evidence(
    api, source, tag, run_id, attempt, artifact_id, artifact_digest, output
):
    verify_producer(api, source, tag, run_id, attempt)
    artifact_id = candidate.positive(artifact_id)
    artifact = api.request("GET", f"/actions/artifacts/{artifact_id}")
    artifacts = api.pages(f"/actions/runs/{int(run_id)}/artifacts", "artifacts")
    name = f"clarify-testflight-candidate-{run_id}-{attempt}"
    matches = [item for item in artifacts if item.get("name") == name]
    release.require(
        len(matches) == 1
        and matches[0] == artifact
        and artifact.get("id") == artifact_id
        and artifact.get("expired") is False
        and artifact.get("digest") == candidate.digest(artifact_digest)
        and artifact.get("workflow_run", {}).get("id") == int(run_id)
        and artifact.get("workflow_run", {}).get("head_sha") == source,
        "TestFlight artifact identity or digest differs",
    )
    data = candidate.download(api, f"/actions/artifacts/{artifact_id}/zip")
    release.require(
        "sha256:" + hashlib.sha256(data).hexdigest() == artifact_digest,
        "TestFlight artifact bytes differ",
    )
    # The shared extractor enforces flat, exact allowed paths and regular files.
    candidate.extract_files(data, EVIDENCE_FILES | {EVIDENCE_MANIFEST}, output)
    manifest = release.decode((output / EVIDENCE_MANIFEST).read_text(encoding="utf-8"))
    release.require(
        manifest
        == {
            "schema": 1,
            "source_sha": source,
            "tag": tag,
            "run_id": int(run_id),
            "run_attempt": int(attempt),
            "files": {
                name: candidate.file_record(output / name)
                for name in sorted(EVIDENCE_FILES)
            },
        },
        "TestFlight evidence manifest differs",
    )
    receipt = release.decode(
        (output / "upload-receipt.json").read_text(encoding="utf-8")
    )
    verification = release.decode(
        (output / "verification.json").read_text(encoding="utf-8")
    )
    release.require(
        receipt.get("state") == "confirmed"
        and receipt.get("source") == source
        and receipt.get("run_id") == str(run_id)
        and receipt.get("attempt") == str(attempt)
        and receipt.get("ipa_sha256") == verification.get("sha256"),
        "TestFlight upload is uncertain or unrelated",
    )
    verify_producer(api, source, tag, run_id, attempt)


def verify_producer(api, source, tag, run_id, attempt):
    release.sha(source)
    release.require(
        str(run_id).isdigit() and int(run_id) > 0 and 1 <= int(attempt) <= 100,
        "Select the exact TestFlight run and attempt",
    )
    release.verify_publication(
        api, "mobile", source, tag, run_id, availability_only=True
    )
    run = api.request("GET", f"/actions/runs/{int(run_id)}")
    release.require(
        run.get("repository", {}).get("full_name") == release.REPOSITORY
        and run.get("head_repository", {}).get("full_name") == release.REPOSITORY
        and run.get("head_sha") == source
        and run.get("head_branch") == tag
        and run.get("event") == "workflow_dispatch"
        and run.get("path") == ".github/workflows/ios-testflight.yml"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("run_attempt") == int(attempt),
        "TestFlight producer identity or result differs",
    )
    workflow = api.request("GET", f"/actions/workflows/{int(run['workflow_id'])}")
    release.require(
        workflow.get("path") == ".github/workflows/ios-testflight.yml",
        "Unexpected TestFlight workflow",
    )
    jobs = api.pages(
        f"/actions/runs/{int(run_id)}/attempts/{int(attempt)}/jobs", "jobs"
    )
    uploads = [job for job in jobs if job.get("name") == "Test, sign and upload iOS"]
    release.require(
        len(uploads) == 1
        and uploads[0].get("conclusion") == "success"
        and uploads[0].get("status") == "completed"
        and uploads[0].get("run_attempt") == int(attempt),
        "Missing signed delivery evidence",
    )
    for name in (
        "Verify signed app and both extensions",
        "Upload directly to App Store Connect",
        "Verify processing and publish to the existing internal group",
        "Seal TestFlight candidate evidence",
        "Preserve TestFlight candidate evidence",
    ):
        steps = [
            step for step in uploads[0].get("steps", []) if step.get("name") == name
        ]
        release.require(
            len(steps) == 1
            and steps[0].get("conclusion") == "success"
            and steps[0].get("status") == "completed",
            "Missing completed TestFlight step: " + name,
        )


def handoff(
    intent, verification, availability, apple_build_id, action, evidence, now=None
):
    release.validate_intent(intent)
    release.require(intent["component"] == "mobile", "Select a mobile release")
    release.require(
        action in {"prepare-submission", "prepare-release"}, "Unknown App Store action"
    )
    release.require(
        isinstance(apple_build_id, str)
        and re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", apple_build_id
        ),
        "Select an exact Apple build ID",
    )
    version, build = intent["version"], intent["evidence"]["build"]
    bundles = verification.get("bundles", [])
    release.require(
        len(bundles) == 3
        and {item.get("bundleId") for item in bundles}
        == {
            "com.jvictormaynard.clarify",
            "com.jvictormaynard.clarify.keyboard",
            "com.jvictormaynard.clarify.activity",
        }
        and all(
            item.get("version") == version and item.get("build") == build
            for item in bundles
        )
        and re.fullmatch(r"[0-9a-f]{64}", verification.get("sha256", ""))
        and type(verification.get("bytes")) is int
        and verification["bytes"] > 0
        and "qa" not in verification,
        "Signed IPA evidence differs from the reviewed build",
    )
    release.require(
        availability.get("id") == apple_build_id
        and availability.get("version") == version
        and availability.get("build") == build
        and availability.get("processing") == "VALID"
        and availability.get("internalState") == "IN_BETA_TESTING"
        and availability.get("group") == "Clarify Interno"
        and availability.get("availableInGroup") is True
        and type(availability.get("existingTesters")) is int
        and availability["existingTesters"] > 0
        and "qa" not in availability,
        "TestFlight availability differs from the selected Apple build",
    )
    release.exact_keys(
        evidence,
        {
            "report_url",
            "checked_at",
            "metadata_reviewed",
            "native_accepted",
            "store_policy_reviewed",
            "existing_submissions_checked",
            "manual_release",
            "store_state",
        },
    )
    release.require(
        all(
            evidence[key] is True
            for key in (
                "metadata_reviewed",
                "native_accepted",
                "store_policy_reviewed",
                "existing_submissions_checked",
                "manual_release",
            )
        ),
        "Complete metadata, native, store-policy and duplicate-submission review",
    )
    release.require(
        re.fullmatch(
            r"https://github\.com/jvictormaynard/clarify/(?:issues|actions/runs)/[1-9][0-9]*(?:#[A-Za-z0-9_-]+)?",
            evidence["report_url"],
        ),
        "Use a canonical readiness report",
    )
    checked = datetime.strptime(evidence["checked_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    release.require(
        0 <= ((now or datetime.now(timezone.utc)) - checked).total_seconds() <= 86400,
        "Repeat the manual App Store check within 24 hours",
    )
    states = (
        {"PREPARE_FOR_SUBMISSION", "READY_FOR_REVIEW"}
        if action == "prepare-submission"
        else {"PENDING_DEVELOPER_RELEASE"}
    )
    release.require(
        evidence["store_state"] in states,
        "App Store state does not permit this manual action",
    )
    return {
        "schema": 1,
        "action": action,
        "app_id": "6820869157",
        "apple_build_id": apple_build_id,
        "version": version,
        "build": build,
        "ipa_sha256": verification["sha256"],
        "readiness_asserted_by_operator": evidence,
        "apple_mutation_performed": False,
        "public_availability_verified": False,
        "next_step": "Submit this existing build for review in App Store Connect. Record the submission ID; do not create a duplicate."
        if action == "prepare-submission"
        else "Release this approved build in App Store Connect. Verify regional availability separately.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["seal-evidence", "prepare-submission", "prepare-release"]
    )
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--apple-build-id")
    parser.add_argument("--artifact-id")
    parser.add_argument("--artifact-digest")
    parser.add_argument("--evidence-directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "seal-evidence":
        seal_evidence(
            args.evidence_directory,
            args.output,
            args.source_sha,
            args.tag,
            args.run_id,
            args.attempt,
        )
        return
    release.require(
        os.environ.get("GITHUB_REPOSITORY") == release.REPOSITORY
        and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.environ.get("GITHUB_REF") == "refs/tags/" + args.tag
        and os.environ.get("GITHUB_SHA") == args.source_sha,
        "Use the reviewed immutable tag and exact source",
    )
    api = release.GitHub(os.environ.get("GH_TOKEN", ""))
    with tempfile.TemporaryDirectory(prefix="clarify-testflight-handoff-") as temporary:
        directory = Path(temporary) / "evidence"
        authenticated_evidence(
            api,
            args.source_sha,
            args.tag,
            args.run_id,
            args.attempt,
            args.artifact_id,
            args.artifact_digest,
            directory,
        )
        result = handoff(
            release.intent_at(api, args.source_sha),
            release.decode(
                (directory / "verification.json").read_text(encoding="utf-8")
            ),
            release.decode(
                (directory / "testflight-availability.json").read_text(encoding="utf-8")
            ),
            args.apple_build_id,
            args.action,
            release.decode(os.environ.get("APP_STORE_READINESS", "{}")),
        )
    result.update(
        source_sha=args.source_sha,
        tag=args.tag,
        testflight_run_id=args.run_id,
        testflight_run_attempt=args.attempt,
        testflight_artifact_id=args.artifact_id,
        testflight_artifact_digest=args.artifact_digest,
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        "Manual App Store handoff prepared. No Apple submission or release was performed."
    )


if __name__ == "__main__":
    try:
        main()
    except (release.ReleaseError, KeyError, ValueError, TypeError, OSError):
        raise SystemExit(
            "App Store handoff blocked. Check identity, producer evidence and manual readiness."
        ) from None
