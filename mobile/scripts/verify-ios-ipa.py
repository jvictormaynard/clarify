"""Check exported artifacts. QA receipts still require workflow provenance."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata
import zipfile

TEAM = "8K353P3496"
BUNDLE = "com.jvictormaynard.clarify"
BUNDLES = {BUNDLE, BUNDLE + ".keyboard", BUNDLE + ".activity"}
ROOT = Path(__file__).resolve().parents[2]
MOBILE = ROOT / "mobile"
MAX_BYTES = 8 * 1024**3
MAX_INTEGER = 2**53 - 1
WORKFLOW = ".github/workflows/ios-qa.yml"
BUNDLE_PATHS = {
    BUNDLE: ("Payload/Clarify.app", "Clarify"),
    BUNDLE + ".keyboard": (
        "Payload/Clarify.app/PlugIns/ClarifyKeyboard.appex",
        "ClarifyKeyboard",
    ),
    BUNDLE + ".activity": (
        "Payload/Clarify.app/PlugIns/ClarifyActivity.appex",
        "ClarifyActivity",
    ),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact_keys(value, keys):
    require(
        type(value) is dict and set(value) == set(keys), "Invalid QA context fields"
    )


def positive(value, maximum=MAX_INTEGER):
    require(type(value) is int and 1 <= value <= maximum, "Invalid QA integer")


def match(value, pattern):
    require(
        isinstance(value, str) and re.fullmatch(pattern, value), "Invalid QA identity"
    )


def validate_qa_context(context):
    exact_keys(
        context,
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
    require(
        type(context["schema"]) is int
        and context["schema"] == 1
        and type(context["pr"]) is int
        and context["pr"] == 179
        and context["repository"] == "jvictormaynard/clarify",
        "Unexpected QA scope",
    )
    for key in ("source_sha", "source_tree", "base_sha", "base_tree", "trusted_sha"):
        match(context[key], r"[0-9a-f]{40}")
    exact_keys(context["workflow"], {"id", "path", "blob_sha"})
    positive(context["workflow"]["id"])
    require(context["workflow"]["path"] == WORKFLOW, "Unexpected QA workflow path")
    match(context["workflow"]["blob_sha"], r"[0-9a-f]{40}")
    require(
        context["base_sha"] == context["trusted_sha"]
        and context["source_sha"] != context["base_sha"],
        "Unexpected QA composition",
    )
    match(context["version"], r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
    require(
        all(int(part) <= 65535 for part in context["version"].split(".")),
        "Invalid QA version",
    )
    match(context["build"], r"[1-9][0-9]{0,8}")
    require(
        context["tag"] == f"ios/pr-179/v{context['version']}-build{context['build']}",
        "Invalid QA tag",
    )
    positive(context["run_id"])
    positive(context["run_attempt"], 100)
    artifact = context["artifact"]
    exact_keys(artifact, {"id", "name", "run_id", "run_attempt", "sha256", "bytes"})
    positive(artifact["id"])
    require(
        artifact["name"] == "clarify-ios-qa-unsigned-" + context["source_sha"],
        "Invalid QA artifact name",
    )
    positive(artifact["run_id"])
    positive(artifact["run_attempt"], 100)
    exact_keys(context["ipa"], {"sha256", "bytes"})
    for item in (artifact, context["ipa"]):
        match(item["sha256"], r"[0-9a-f]{64}")
        positive(item["bytes"], MAX_BYTES)
    require(
        type(context["bundles"]) is list and len(context["bundles"]) == 3,
        "Expected three QA bundle digests",
    )
    for item, identifier in zip(context["bundles"], BUNDLE_PATHS):
        exact_keys(
            item,
            {
                "id",
                "path",
                "sha256",
                "executable",
                "executable_sha256",
                "executable_bytes",
            },
        )
        expected_path, expected_executable = BUNDLE_PATHS[identifier]
        require(
            item["id"] == identifier
            and item["path"] == expected_path
            and item["executable"] == expected_executable,
            "Unexpected QA bundle or executable path",
        )
        match(item["sha256"], r"[0-9a-f]{64}")
        match(item["executable_sha256"], r"[0-9a-f]{64}")
        positive(item["executable_bytes"], 512 * 1024**2)
    return context


def safe_qa_path(value, relative, *, must_exist=True):
    """Accept fixed regular files under the runner's private QA directory."""
    runner = Path(os.environ["RUNNER_TEMP"])
    require(runner.is_absolute(), "RUNNER_TEMP must be absolute")
    expected = runner / "clarify-ios-qa" / relative
    path = Path(value)
    require(
        path.is_absolute() and path == expected and ".." not in path.parts,
        "Unexpected QA data path",
    )
    for current in reversed([path, *path.parents]):
        if (
            current == path
            and not must_exist
            and not current.exists()
            and not current.is_symlink()
        ):
            continue
        info = current.lstat()
        require(
            not stat.S_ISLNK(info.st_mode)
            and not (hasattr(current, "is_junction") and current.is_junction()),
            "QA paths must not contain links",
        )
        if current == path:
            require(
                stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                "QA data must be one regular file",
            )
        else:
            require(stat.S_ISDIR(info.st_mode), "QA parent must be a directory")
    return path


def json_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate QA JSON field")
        result[key] = value
    return result


def load_qa_context(value):
    path = safe_qa_path(value, "context.json")
    require(path.stat().st_size <= 8192, "QA context is too large")
    context = validate_qa_context(
        json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=json_pairs)
    )
    expected_env = {
        "GITHUB_REPOSITORY": context["repository"],
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": context["trusted_sha"],
        "QA_WORKFLOW_SHA": context["trusted_sha"],
        "QA_WORKFLOW_ID": str(context["workflow"]["id"]),
        "QA_WORKFLOW_REF": "jvictormaynard/clarify/.github/workflows/ios-qa.yml@refs/heads/main",
        "GITHUB_RUN_ID": str(context["run_id"]),
        "GITHUB_RUN_ATTEMPT": str(context["run_attempt"]),
    }
    require(
        all(os.environ.get(key) == expected for key, expected in expected_env.items()),
        "QA context does not match the trusted manual run",
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    require(
        head == context["trusted_sha"], "Helper checkout does not match trusted main"
    )
    for revision, expected in (
        (context["trusted_sha"] + "^{tree}", context["base_tree"]),
        (context["trusted_sha"] + ":" + WORKFLOW, context["workflow"]["blob_sha"]),
    ):
        actual = subprocess.run(
            ["git", "rev-parse", revision],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        require(
            actual == expected, "Trusted tree or workflow blob differs from context"
        )
    subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            context["trusted_sha"],
            "--",
            "mobile/scripts/verify-ios-ipa.py",
            "mobile/app.json",
            "mobile/third-party/KeyboardHostBundleID/LICENSE",
            WORKFLOW,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=30,
    )
    return context


def check_digest(path, expected):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            require(size <= expected["bytes"], "QA artifact size differs from context")
            digest.update(chunk)
    require(
        size == expected["bytes"] and digest.hexdigest() == expected["sha256"],
        "QA artifact digest differs from context",
    )


def check_zip(archive):
    """Reject links, duplicate extraction targets, escapes and oversized input."""
    items = archive.infolist()
    require(len(items) <= 50000, "IPA contains too many entries")
    names = set()
    total = 0
    for item in items:
        name = item.orig_filename
        parts = PurePosixPath(name).parts
        require(
            name
            and not name.startswith("/")
            and "\\" not in name
            and ":" not in name
            and "\0" not in name
            and ".." not in parts
            and all(
                part and part != "." and not part.endswith((" ", "."))
                for part in name.rstrip("/").split("/")
            ),
            "Unsafe IPA extraction path",
        )
        canonical = unicodedata.normalize("NFC", name.rstrip("/")).casefold()
        require(canonical not in names, "Duplicate IPA extraction target")
        names.add(canonical)
        mode = stat.S_IFMT(item.external_attr >> 16)
        require(
            mode in (0, stat.S_IFREG, stat.S_IFDIR) and not item.flag_bits & 1,
            "IPA contains a link, special node or encrypted entry",
        )
        total += item.file_size
        require(
            item.file_size <= 512 * 1024**2 and total <= 2 * 1024**3,
            "IPA extraction exceeds the size limit",
        )


def bundle_digest(bundle):
    """Hash a canonical file manifest; this is byte identity, not provenance."""
    records = []
    for path in bundle.rglob("*"):
        require(not path.is_symlink(), "Bundle manifest must not follow links")
        if path.is_dir():
            continue
        require(path.is_file(), "Bundle manifest contains a special node")
        data = path.read_bytes()
        records.append(
            {
                "path": unicodedata.normalize(
                    "NFC", path.relative_to(bundle).as_posix()
                ),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    records.sort(key=lambda item: item["path"])
    return hashlib.sha256(
        json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def verify_ipa(ipa_value=None, *, qa_context=None):
    context = load_qa_context(qa_context) if qa_context is not None else None
    if context:
        ipa = safe_qa_path(ipa_value, "output/Clarify.ipa")
        source = safe_qa_path(
            Path(os.environ["RUNNER_TEMP"])
            / "clarify-ios-qa/input/unsigned.xcarchive.zip",
            "input/unsigned.xcarchive.zip",
        )
        check_digest(source, context["artifact"])
        config = json.loads((MOBILE / "app.json").read_text())["expo"]
        license_source = MOBILE / "third-party/KeyboardHostBundleID/LICENSE"
    else:
        config = json.loads(Path("app.json").read_text())["expo"]
        ipa = Path(sys.argv[1] if ipa_value is None else ipa_value).resolve()
        license_source = Path("third-party/KeyboardHostBundleID/LICENSE")
    verified = []
    with tempfile.TemporaryDirectory(prefix="clarify-ipa-") as directory:
        root = Path(directory)
        extracted = root / "extracted" if context else root
        zip_path = ipa
        if context:
            extracted.mkdir()
            zip_path = root / "snapshot.ipa"
            with ipa.open("rb") as incoming, zip_path.open("wb") as outgoing:
                size = 0
                while chunk := incoming.read(1024 * 1024):
                    size += len(chunk)
                    require(
                        size <= context["ipa"]["bytes"], "IPA exceeds its context size"
                    )
                    outgoing.write(chunk)
            check_digest(zip_path, context["ipa"])
        with zipfile.ZipFile(zip_path) as archive:
            if context:
                check_zip(archive)
            archive.extractall(extracted)
        apps = list((extracted / "Payload").glob("*.app"))
        require(len(apps) == 1, "Expected one container app")
        app = apps[0]
        bundles = [app, *sorted((app / "PlugIns").glob("*.appex"))]
        expected = set(BUNDLES)
        require(len(bundles) == 3, "Expected app, keyboard and activity")
        if context:
            discovered = {
                path
                for path in extracted.rglob("*")
                if path.suffix.lower() in {".app", ".appex"}
            }
            require(discovered == set(bundles), "Unexpected nested app or extension")
            # Validate every data binding before invoking the signature inspector.
            for binding in context["bundles"]:
                path = extracted / binding["path"]
                require(path in bundles, "Unexpected bundle path")
                info = plistlib.loads((path / "Info.plist").read_bytes())
                require(
                    info.get("CFBundleIdentifier") == binding["id"]
                    and info.get("CFBundleExecutable") == binding["executable"],
                    "Bundle executable declaration differs from context",
                )
                executable = path / binding["executable"]
                require(
                    executable.is_file() and not executable.is_symlink(),
                    "Expected a regular bundle executable",
                )
                binary = executable.read_bytes()
                require(
                    len(binary) >= 32
                    and binary[:8] == b"\xcf\xfa\xed\xfe\x0c\x00\x00\x01",
                    "Expected a thin ARM64 Mach-O executable",
                )
                check_digest(
                    executable,
                    {
                        "sha256": binding["executable_sha256"],
                        "bytes": binding["executable_bytes"],
                    },
                )
                require(
                    bundle_digest(path) == binding["sha256"],
                    "Bundle digest differs from context",
                )
        for path in bundles:
            info = plistlib.loads((path / "Info.plist").read_bytes())
            identifier = info["CFBundleIdentifier"]
            require(identifier in expected, "Unexpected bundle identifier")
            if identifier == BUNDLE:
                endpoint = config["ios"]["infoPlist"]["ClarifyCloudURL"]
                require(
                    endpoint.startswith("https://")
                    and info.get("ClarifyCloudURL") == endpoint,
                    "Artifact must use the declared production endpoint",
                )
            expected.remove(identifier)
            require(
                info["CFBundleShortVersionString"]
                == (context["version"] if context else config["version"])
                and info["CFBundleVersion"]
                == (context["build"] if context else config["ios"]["buildNumber"]),
                "Artifact version does not match source",
            )
            subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", str(path)],
                check=True,
                capture_output=bool(context),
            )
            signed = subprocess.run(
                ["codesign", "-d", "--entitlements", ":-", str(path)],
                check=True,
                capture_output=True,
            )
            entitlements = plistlib.loads(signed.stdout)
            require(
                entitlements.get("com.apple.developer.team-identifier") == TEAM
                and not entitlements.get("get-task-allow", False),
                "Expected non-debug Apple distribution signature",
            )
            require(
                entitlements.get("application-identifier") == TEAM + "." + identifier,
                "Unexpected signed application identifier",
            )
            require(
                identifier == BUNDLE + ".activity"
                or "group." + BUNDLE
                in entitlements.get("com.apple.security.application-groups", []),
                "Shared app group missing from signature",
            )
            require(
                (path / "embedded.mobileprovision").is_file(),
                "Missing distribution profile",
            )
            verified.append(
                {
                    "bundleId": identifier,
                    "version": info["CFBundleShortVersionString"],
                    "build": info["CFBundleVersion"],
                }
            )
        license_path = (
            app / "PlugIns/ClarifyKeyboard.appex/KeyboardHostBundleID.LICENSE"
        )
        require(
            license_path.read_bytes() == license_source.read_bytes(),
            "Bundled third-party license differs from source",
        )
    if context:
        safe_qa_path(ipa, "output/Clarify.ipa")
        check_digest(ipa, context["ipa"])
        digest = context["ipa"]["sha256"]
    else:
        digest = hashlib.sha256(ipa.read_bytes()).hexdigest()
    if context:
        result = {"sha256": digest, "bytes": ipa.stat().st_size, "bundles": verified}
        result.update(
            qa=context,
            appId="6820869157",
            team=TEAM,
            artifactDigestVerified=True,
            ipaDigestVerified=True,
            bundleDigestsVerified=True,
            workflowArtifactProvenanceVerified=False,
        )
        safe_qa_path(
            ipa.with_suffix(".ipa.sha256"),
            "output/Clarify.ipa.sha256",
            must_exist=False,
        )
        safe_qa_path(
            ipa.with_name("verification.json"),
            "output/verification.json",
            must_exist=False,
        )
    ipa.with_suffix(".ipa.sha256").write_text(digest + "  " + ipa.name + "\n")
    if not context:
        result = {"sha256": digest, "bytes": ipa.stat().st_size, "bundles": verified}
    ipa.with_name("verification.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    args = sys.argv[1:]
    if "--qa-context" in args:
        require(
            len(args) == 3 and args[1] == "--qa-context",
            "Use IPA [--qa-context ABS_JSON]",
        )
        result = verify_ipa(args[0], qa_context=args[2])
    else:
        result = verify_ipa()
    print(json.dumps(result))


if __name__ == "__main__":
    if "--qa-context" not in sys.argv[1:]:
        main()
    else:
        try:
            main()
        except Exception:
            print("QA IPA verification failed.", file=sys.stderr)
            raise SystemExit(1) from None
