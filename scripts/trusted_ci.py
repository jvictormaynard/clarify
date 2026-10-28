"""MAIN-controlled internal QA; consistency observations, not hostile-code attestation.

The caller/final and publication policy belong to testflight_qa. This adapter
never signs, publishes, or approves QA. Product processes receive no workflow
command files or tokens, and their output is retained as inert diagnostic data.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from urllib.request import urlopen

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import delivery_policy

TRUST_MODEL = "reviewed-source-internal-qa-v1"
_BEFORE = ["Authenticate trusted controls", "Verify source checkout"]
_AFTER = [
    "Verify source checkout after execution",
    "Verify trusted controls after execution",
]
_EXECUTORS = {
    "repository": ("Repository checks", ["Run trusted repository checks"]),
    "python_linux": ("Tests (ubuntu-latest)", ["Run trusted Python validation"]),
    "python_windows": ("Tests (windows-latest)", ["Run trusted Python validation"]),
    "settings": ("Settings web and bridge", ["Run trusted Settings validation"]),
    "package_windows": (
        "Package Windows executable",
        ["Build candidate package with trusted controls"],
    ),
    "installer_windows": (
        "Windows installer lifecycle",
        ["Validate candidate installer with trusted controls"],
    ),
    "server": (
        "Server validation / Server tests and container",
        ["Validate candidate server with trusted controls"],
    ),
    "mobile": ("Mobile checks", ["Run trusted mobile checks"]),
    "ios_native": (
        "iOS validation / Native keyboard and library tests",
        [
            "Run trusted mobile checks",
            "Run native contracts with trusted harness",
            "Run UIKit integration with trusted harness",
        ],
    ),
    "ios_build": (
        "iOS validation / Unsigned app and extensions build",
        [
            "Generate native project with trusted controls",
            "Install native dependencies with trusted controls",
            "Build unsigned candidate app and extensions",
        ],
    ),
    "audit_python_linux": (
        "Dependency audits / Python audit (ubuntu-latest)",
        ["Audit candidate Python dependencies"],
    ),
    "audit_python_windows": (
        "Dependency audits / Python audit (windows-latest)",
        ["Audit candidate Python dependencies"],
    ),
    "audit_settings": (
        "Dependency audits / Settings dependency audit",
        ["Audit candidate Settings dependencies"],
    ),
}
CHECKS = {
    "selection": {
        "job_name": "Trusted validation / Select component validation",
        "required_steps": [
            "Authenticate trusted workflow and controls",
            "Resolve source and base Git objects",
            "Select trusted validation plan",
        ],
    },
    **{
        key: {
            "job_name": "Trusted validation / " + name,
            "required_steps": _BEFORE + steps + _AFTER,
        }
        for key, (name, steps) in _EXECUTORS.items()
    },
}
# Insertion order is part of the decoder contract.
_ORDER = (
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
CHECKS["ios_aggregate"] = {
    "job_name": "Trusted validation / iOS validation / Native tests and unsigned build",
    "required_steps": [
        "Authenticate trusted workflow and controls",
        "Require native tests and unsigned compilation",
    ],
}
CHECKS["ci_required"] = {
    "job_name": "Trusted validation / CI required",
    "required_steps": [
        "Authenticate trusted workflow and controls",
        "Recompute trusted validation plan",
        "Require every selected check to pass",
    ],
}
CHECKS = {key: CHECKS[key] for key in _ORDER}

PYTHON_LINT_PATHS = [
    "desktop_state.py",
    "windows_hotkeys.py",
    "scripts/dependency_audit.py",
    "scripts/format_staged.py",
    "scripts/run_tests.py",
    "tests/test_test_environment.py",
    "clarify/desktop/qml_app.py",
    "clarify/desktop/qml_bridge.py",
    "clarify/desktop/qml_runtime.py",
    "workflow_provider.py",
    "tests/test_workflow_provider.py",
    "clarify/desktop/qml_settings.py",
    "clarify/desktop/qml_status.py",
    "clarify/desktop/qml_audio_batch.py",
    "clarify/desktop/qml_clipboard.py",
    "clarify/desktop/qml_voice_translation.py",
    "clarify/desktop/qt_shell.py",
    "tests/test_repository.py",
    "tests/test_pyside6_qml.py",
    "tests/test_pyside6_qml_runtime.py",
    "tests/test_pyside6_qml_audio_batch.py",
    "tests/test_pyside6_qml_clipboard.py",
    "tests/test_pyside6_qml_voice_translation.py",
    "tests/test_pyside6_qt_shell.py",
    "scripts/qt_distribution.py",
    "scripts/qt_package_policy.py",
    "scripts/check_settings_payload.py",
    "tests/test_qt_distribution.py",
    "tests/test_qt_package_policy.py",
    "portable_updates.py",
    "portable_update_windows.py",
    "clarify/desktop/qml_updates.py",
    "scripts/create_portable_update_manifest.py",
    "scripts/test_portable_update.py",
    "scripts/portable_crypto_inventory.py",
    "tests/test_portable_updates.py",
    "tests/test_qml_updates.py",
    "tests/test_portable_update_windows.py",
    "tests/test_portable_update_manifest.py",
    "scripts/delivery_policy.py",
    "scripts/release_delivery.py",
    "tests/test_delivery_policy.py",
    "tests/test_release_delivery.py",
]
PYTHON_FORMAT_PATHS = [
    "scripts/dependency_audit.py",
    "scripts/format_staged.py",
    "scripts/run_tests.py",
    "tests/test_test_environment.py",
    "tests/test_repository.py",
    "clarify/desktop/qml_app.py",
    "clarify/desktop/qml_bridge.py",
    "clarify/desktop/qml_runtime.py",
    "workflow_provider.py",
    "tests/test_workflow_provider.py",
    "clarify/desktop/qml_settings.py",
    "clarify/desktop/qml_status.py",
    "clarify/desktop/qml_audio_batch.py",
    "clarify/desktop/qml_clipboard.py",
    "clarify/desktop/qml_voice_translation.py",
    "clarify/desktop/qt_shell.py",
    "tests/test_pyside6_qml.py",
    "tests/test_pyside6_qml_runtime.py",
    "tests/test_pyside6_qml_audio_batch.py",
    "tests/test_pyside6_qml_clipboard.py",
    "tests/test_pyside6_qml_voice_translation.py",
    "tests/test_pyside6_qt_shell.py",
    "scripts/qt_distribution.py",
    "scripts/qt_package_policy.py",
    "scripts/check_settings_payload.py",
    "tests/test_qt_distribution.py",
    "tests/test_qt_package_policy.py",
    "portable_updates.py",
    "portable_update_windows.py",
    "clarify/desktop/qml_updates.py",
    "scripts/create_portable_update_manifest.py",
    "scripts/test_portable_update.py",
    "scripts/portable_crypto_inventory.py",
    "tests/test_portable_updates.py",
    "tests/test_qml_updates.py",
    "tests/test_portable_update_windows.py",
    "tests/test_portable_update_manifest.py",
    "scripts/delivery_policy.py",
    "scripts/release_delivery.py",
    "tests/test_delivery_policy.py",
    "tests/test_release_delivery.py",
]

CORE = "mobile/modules/clarify-core/"
CORE_ADDITIONS = (
    "ComputerProtocol.swift",
    "ComputerCredential.swift",
    "ComputerTransport.swift",
    "ComputerWAV.swift",
    "ComputerAudio.swift",
    "ComputerConnection.swift",
    "ProcessingDestination.swift",
)
CORE_SOURCES = (
    "SharedState.swift",
    "SessionDeadline.swift",
    "KeyboardVocabulary.swift",
    "KeyStore.swift",
    "GroqClient.swift",
    "RewritePrompt.swift",
    "KeyboardState.swift",
    "TypingCorrection.swift",
    "LocalLibrary.swift",
    "Snippets.swift",
    "ActivationRequest.swift",
    "CloudAccount.swift",
    "SocialAuthentication.swift",
    "AccountCredential.swift",
    "Onboarding.swift",
    "Localization.swift",
    "AudioClipWriter.swift",
)
CORE_APP_ONLY = (
    "ComputerScanner.swift",
    "AudioSession.swift",
    "MicrophoneFailure.swift",
    "ClarifyCoreModule.swift",
    "ClarifyCore.podspec",
    "HapticFeedback.swift",
    "LiveActivity.swift",
    "ClarifyActivityAttributes.swift",
    "ClarifyMark.swift",
    "ClarifyReturnBridge.h",
    "ClarifyReturnBridge.m",
    "KeyboardOpeningDiagnostic.swift",
)
CONTROL_FILES = {
    "docs/testflight-qa.md",
    ".github/workflows/ci.yml",
    ".github/workflows/ios-validation.yml",
    ".github/workflows/server-validation.yml",
    ".github/workflows/dependency-audit.yml",
    ".github/workflows/ios-qa.yml",
    ".github/actions/settings-build/action.yml",
    "pyproject.toml",
    "dependency-audit.json",
    "desktop/playwright.config.ts",
    "desktop/vite.config.ts",
    "desktop/tsconfig.json",
    "mobile/tsconfig.json",
    "mobile/eslint.config.js",
    "mobile/metro.config.js",
    CORE + "Package.swift",
    "mobile/app.json",
    "mobile/eas.json",
    "mobile/third-party/KeyboardHostBundleID/LICENSE",
}
CONTROL_PREFIXES = (
    "scripts/",
    "tests/",
    "desktop/tests/",
    "desktop/scripts/",
    "mobile/scripts/",
    "mobile/tests/",
    "mobile/native/tests/",
    CORE + "tests/",
)
_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.I)
MAX_FILES = 4096
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TREE_BYTES = 256 * 1024 * 1024


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def safe_path(value):
    if not isinstance(value, str) or not value or any(c in value for c in '\\:<>"|?*'):
        raise ValueError("Invalid Git input path")
    parts = value.split("/")
    if any(
        not p
        or p.casefold() in {".", "..", ".git"}
        or p[-1] in " ."
        or _RESERVED.match(p)
        or any(ord(c) < 32 for c in p)
        for p in parts
    ):
        raise ValueError("Unsafe or aliased Git input path")
    return value


def validate_roots(trusted, source, execution):
    roots = [Path(p).absolute() for p in (trusted, source, execution)]
    for root in roots:
        for parent in (root, *root.parents):
            if parent.is_symlink() or (
                hasattr(parent, "is_junction") and parent.is_junction()
            ):
                raise ValueError("QA roots must not use links or junctions")
    resolved = [p.resolve() for p in roots]
    for i, left in enumerate(resolved):
        for right in resolved[i + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise ValueError(
                    "QA source, trusted and execution roots must be separate"
                )


def git(repo, *args, data=None):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=data,
        capture_output=True,
        check=True,
        timeout=60,
    ).stdout


def commit_sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("QA boundaries must be full lowercase commit SHAs")
    return value


def git_tree(repo, revision):
    commit_sha(revision)
    if git(repo, "rev-parse", revision + "^{commit}").decode().strip() != revision:
        raise ValueError("QA boundary is not the exact commit")
    result = {}
    aliases = set()
    total = 0
    for row in git(repo, "ls-tree", "-r", "--long", "-z", revision).split(b"\0"):
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        mode, kind, blob, size = metadata.decode("ascii").split()
        path = safe_path(raw_path.decode("utf-8"))
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("Links and nonregular Git inputs are forbidden")
        alias = unicodedata.normalize("NFC", path).casefold()
        if alias in aliases:
            raise ValueError("Case-insensitive input collision")
        aliases.add(alias)
        size = int(size)
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TREE_BYTES or len(result) >= MAX_FILES:
            raise ValueError("QA input inventory exceeds its limits")
        result[path] = {"blob": blob, "mode": mode, "bytes": size}
    return result


def git_blobs(repo, tree):
    """One bounded Git request, rather than one subprocess/API request per file."""
    ids = list(dict.fromkeys(row["blob"] for row in tree.values()))
    raw = git(repo, "cat-file", "--batch", data=("\n".join(ids) + "\n").encode())
    result = {}
    offset = 0
    for expected in ids:
        end = raw.index(b"\n", offset)
        name, kind, size = raw[offset:end].decode("ascii").split()
        if name != expected or kind != "blob":
            raise ValueError("Unexpected Git object response")
        offset = end + 1
        result[name] = raw[offset : offset + int(size)]
        offset += int(size) + 1
    if offset != len(raw):
        raise ValueError("Unexpected trailing Git objects")
    return result


def is_control(path):
    if path == "mobile/scripts/ios-signing.rb":
        return False  # Publication never executes this Ruby helper in QA.
    return (
        path in CONTROL_FILES
        or path.startswith(CONTROL_PREFIXES)
        or (
            path.startswith("server/")
            and (
                PurePosixPath(path).name in {"tests.py", "test_settings.py"}
                or "/tests/" in path
                or PurePosixPath(path).name.startswith("test_")
            )
        )
    )


def control_inventory(trusted_repo: Path, trusted_sha: str):
    return {
        path: row["blob"]
        for path, row in git_tree(trusted_repo, trusted_sha).items()
        if is_control(path)
    }


def validation_plan(source_repo: Path, base_sha: str, source_sha: str):
    for sha in (base_sha, source_sha):
        commit_sha(sha)
    git(source_repo, "merge-base", "--is-ancestor", base_sha, source_sha)
    components = delivery_policy.event_components(
        source_repo, "push", {"before": base_sha}, source_sha
    )
    components["mobile"] = components["ios"] = True
    selected = {
        "selection",
        "repository",
        "mobile",
        "ios_native",
        "ios_build",
        "ios_aggregate",
        "ci_required",
    }
    routing = {
        "desktop": ("python_linux", "python_windows"),
        "settings": ("settings",),
        "package": ("package_windows",),
        "installer": ("installer_windows",),
        "server": ("server",),
        "audit": ("audit_python_linux", "audit_python_windows", "audit_settings"),
    }
    for component, keys in routing.items():
        if components[component]:
            selected.update(keys)
    return {
        "components": components,
        "selected_keys": [key for key in CHECKS if key in selected],
    }


def build_plan(trusted_repo, source_repo, trusted_sha, base_sha, source_sha):
    commit_sha(trusted_sha)
    result = validation_plan(source_repo, base_sha, source_sha)
    return {
        "schema": 1,
        "kind": "clarify-trusted-ci-plan",
        "trust_model": TRUST_MODEL,
        "source_sha": source_sha,
        "source_tree": git(source_repo, "rev-parse", source_sha + "^{tree}")
        .decode()
        .strip(),
        "base_sha": base_sha,
        "base_tree": git(source_repo, "rev-parse", base_sha + "^{tree}")
        .decode()
        .strip(),
        "trusted_sha": trusted_sha,
        **result,
        "checks": {key: CHECKS[key] for key in result["selected_keys"]},
        "controls": control_inventory(trusted_repo, trusted_sha),
    }


def project_native_contracts(manifest, oracles):
    text = manifest.decode("utf-8")
    matches = list(re.finditer(r"sources: \[([^]]*)\]", text))
    if (
        len(matches) != 1
        or tuple(re.findall(r'"([^"]+)"', matches[0].group(1))) != CORE_SOURCES
    ):
        raise ValueError("Unexpected MAIN contracts manifest")
    if text.count("exclude: [") != 1 or "ComputerScanner.swift" in text:
        raise ValueError("Unexpected MAIN native exclusions")
    match = matches[0]
    replacement = (
        "sources: ["
        + ", ".join('"' + n + '"' for n in CORE_ADDITIONS)
        + ", "
        + match.group(1)
        + "]"
    )
    text = text[: match.start()] + replacement + text[match.end() :]
    text = text.replace("exclude: [", 'exclude: ["ComputerScanner.swift", ', 1)
    contracts = "testAtomicBridgeKeepsCommandsReceiptsAndStateSeparate"
    cancelled = "testCancelledReadyResultCannotClaimAReceiptAfterStoreRecreation"
    markers = "testCancellationMarkersPreserveOtherCancellationsAndLegacySharedData"
    changes = {
        "ContractsTests.swift": [
            (contracts, "store", action, "second", "nil")
            for action in ("start", "lock", "finish")
        ],
        "RecordingTests.swift": [
            (cancelled, "store", "cancel", "cancelled", "state.processingContext"),
            (markers, "first", "cancel", "../cancelled/a\u00e7\u00e3o", "nil"),
            (markers, "first", "cancel", "aaa", "nil"),
            (markers, "second", "cancel", "another", "nil"),
        ],
    }
    result = dict(oracles)
    for name, operations in changes.items():
        original = oracles[name].decode("utf-8")
        updated = original
        pairs = []
        if len(re.findall(r"\.send\(", original)) != len(operations):
            raise ValueError("Unexpected MAIN legacy call count")
        for function, receiver, action, operation, context in operations:
            before = f'{receiver}.send("{action}", operationID: "{operation}")'
            after = before[:-1] + ", context: " + context + ")"
            anchor = "func " + function + "("
            if (
                original.count(anchor) != 1
                or original.count(before) != 1
                or after in original
            ):
                raise ValueError("Unexpected MAIN legacy call shape")
            start = original.index(anchor)
            end = original.find("\n  func ", start + len(anchor))
            if original[start : None if end < 0 else end].count(before) != 1:
                raise ValueError("Legacy call moved outside the expected MAIN test")
            updated = updated.replace(before, after, 1)
            pairs.append((before, after))
        restored = updated
        for before, after in reversed(pairs):
            restored = restored.replace(after, before, 1)
        if restored.encode("utf-8") != oracles[name]:
            raise ValueError("QA oracle transformation changed unrelated bytes")
        result[name] = updated.encode("utf-8")
    return {"manifest": text.encode("utf-8"), "oracles": result}


def source_role(path, trusted_tree):
    safe_path(path)
    if (
        PurePosixPath(path).name.startswith(".env")
        and PurePosixPath(path).name != ".env.example"
    ):
        raise ValueError("Environment files are not QA inputs")
    if path in trusted_tree:
        return "product-or-data"
    if path.startswith(
        (
            "tests/",
            "desktop/tests/",
            "mobile/tests/",
            "mobile/native/tests/",
            CORE + "tests/",
        )
    ):
        return "candidate-diagnostic-not-required"
    if path == "scripts/testflight_candidate.py":
        return "candidate-policy-inspection-only"
    suffix = PurePosixPath(path).suffix
    if "/" not in path and suffix == ".py":
        return "product"
    roots = (
        "clarify/",
        "desktop/src/",
        "desktop/src-tauri/src/",
        "mobile/src/",
        "mobile/app/",
        "mobile/plugins/",
        CORE + "ios/",
        "mobile/native/keyboard/",
        "mobile/native/activity/",
        "server/",
        "shared/",
        "assets/",
        "licenses/",
        "connect/",
        "docs/",
    )
    allowed = {
        ".py",
        ".qml",
        ".ts",
        ".tsx",
        ".js",
        ".cjs",
        ".css",
        ".swift",
        ".h",
        ".m",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".txt",
        ".md",
        ".svg",
        ".png",
        ".ico",
        ".woff2",
        ".podspec",
        ".dockerignore",
    }
    if path.startswith(roots) and (
        suffix in allowed or PurePosixPath(path).name == "Dockerfile"
    ):
        return "product-or-data"
    raise ValueError("Unclassified QA input: " + path)


def materialize_trees(
    trusted_repo, source_repo, execution_root, trusted_sha, source_sha
):
    """Construct a reviewed-source test workspace; this is not an OS sandbox."""
    validate_roots(trusted_repo, source_repo, execution_root)
    trusted_tree, source_tree = (
        git_tree(trusted_repo, trusted_sha),
        git_tree(source_repo, source_sha),
    )
    trusted_blobs, source_blobs = (
        git_blobs(trusted_repo, trusted_tree),
        git_blobs(source_repo, source_tree),
    )
    files = {}
    for path, row in source_tree.items():
        if (
            path.startswith(("mobile/native/keyboard/", "mobile/native/activity/"))
            and path not in trusted_tree
        ):
            raise ValueError("Unreconciled native product input: " + path)
        role = source_role(path, trusted_tree)
        if role in {
            "candidate-diagnostic-not-required",
            "candidate-policy-inspection-only",
        }:
            continue
        files[path] = {
            "origin_ref": source_sha,
            "origin_blob": row["blob"],
            "mode": row["mode"],
            "role": role,
            "data": source_blobs[row["blob"]],
        }
    for path, row in trusted_tree.items():
        if is_control(path) and path not in {
            "mobile/app.json",
            "mobile/eas.json",
            "mobile/third-party/KeyboardHostBundleID/LICENSE",
        }:
            files[path] = {
                "origin_ref": trusted_sha,
                "origin_blob": row["blob"],
                "mode": row["mode"],
                "role": "trusted-control-or-oracle",
                "data": trusted_blobs[row["blob"]],
            }
    manifest_path = CORE + "Package.swift"
    if manifest_path in trusted_tree:
        names = {
            p.removeprefix(CORE + "ios/")
            for p in source_tree
            if p.startswith(CORE + "ios/")
        }
        expected = set(CORE_SOURCES + CORE_ADDITIONS + CORE_APP_ONLY)
        if names != expected:
            raise ValueError(
                "Native source inputs have not been reconciled with the MAIN QA projection"
            )
        oracle_paths = {
            name: CORE + "tests/" + name
            for name in ("ContractsTests.swift", "RecordingTests.swift")
        }
        projection = project_native_contracts(
            files[manifest_path]["data"],
            {name: files[path]["data"] for name, path in oracle_paths.items()},
        )
        for path, data in [
            (manifest_path, projection["manifest"]),
            *(
                (oracle_paths[name], data)
                for name, data in projection["oracles"].items()
            ),
        ]:
            files[path]["data"] = data
            files[path]["transform"] = "computer-connect-179-v1"
    execution_root = Path(execution_root)
    destinations = {unicodedata.normalize("NFC", path).casefold() for path in files}
    if len(destinations) != len(files) or any(
        parent.as_posix().casefold() in destinations
        for path in files
        for parent in PurePosixPath(path).parents
        if parent.as_posix() != "."
    ):
        raise ValueError("Colliding materialization destinations")
    if execution_root.exists():
        raise ValueError("QA execution destination already exists")
    execution_root.mkdir(parents=True)
    inventory = []
    for path, item in sorted(files.items()):
        target = execution_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item["data"])
        if item["mode"] == "100755":
            target.chmod(0o755)
        inventory.append(
            {
                "canonical_path": path,
                **{k: v for k, v in item.items() if k != "data"},
                "sha256": hashlib.sha256(item["data"]).hexdigest(),
            }
        )
    return {
        "schema": 1,
        "trust_model": TRUST_MODEL,
        "source_sha": source_sha,
        "trusted_sha": trusted_sha,
        "files": inventory,
    }


def verify_tracked(repo, revision, only=None):
    tree = git_tree(repo, revision)
    if git(repo, "rev-parse", "HEAD").decode().strip() != revision:
        raise ValueError("Checkout HEAD differs from the declared Git object")
    blobs = git_blobs(repo, tree)
    for path, row in tree.items():
        if only is not None and path not in only:
            continue
        target = Path(repo) / path
        for part in (target, *target.parents):
            if part == Path(repo).parent:
                break
            if part.is_symlink() or (
                hasattr(part, "is_junction") and part.is_junction()
            ):
                raise ValueError("Linked checkout input")
        actual, expected = target.read_bytes(), blobs[row["blob"]]
        # Git's Windows checkout may use CRLF; materialization uses Git bytes.
        if actual != expected and (
            b"\0" in expected or actual.replace(b"\r\n", b"\n") != expected
        ):
            raise ValueError("Checkout input differs from its Git blob: " + path)


def verify_execution(root, inventory, trusted_only=False):
    for row in inventory["files"]:
        if trusted_only and row["role"] != "trusted-control-or-oracle":
            continue
        path = Path(root) / safe_path(row["canonical_path"])
        for part in (path, *path.parents):
            if part == Path(root).parent:
                break
            if part.is_symlink() or (
                hasattr(part, "is_junction") and part.is_junction()
            ):
                raise ValueError("Materialized input was replaced by a link")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Materialized input changed: " + row["canonical_path"])


def product_environment(environ):
    """Do not forward runner command transports, auth, or interpreter injection."""
    removed = ("GITHUB_", "ACTIONS_", "QA_", "INPUT_", "GIT_CONFIG")
    exact = {
        "GH_TOKEN",
        "PYTHONPATH",
        "PYTHONHOME",
        "NODE_OPTIONS",
        "NODE_PATH",
        "RUBYOPT",
        "BASH_ENV",
        "ENV",
    }
    return {
        k: v
        for k, v in environ.items()
        if not k.upper().startswith(removed)
        and k.upper() not in exact
        and not re.search(r"(?:TOKEN|SECRET|PASSWORD|PRIVATE_KEY|API_KEY)$", k, re.I)
    }


def authenticate_context(environ, trusted_repo, source_repo):
    source, base, trusted = (
        commit_sha(environ.get("QA_" + key + "_SHA"))
        for key in ("SOURCE", "BASE", "TRUSTED")
    )
    expected = {
        "GITHUB_REPOSITORY": "jvictormaynard/clarify",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": trusted,
        "QA_WORKFLOW_SHA": trusted,
        "GITHUB_WORKFLOW_REF": "jvictormaynard/clarify/.github/workflows/ios-qa.yml@refs/heads/main",
    }
    if any(environ.get(k) != v for k, v in expected.items()) or base != trusted:
        raise ValueError(
            "QA must be called by the exact current MAIN workflow and base"
        )
    if git(trusted_repo, "rev-parse", "HEAD").decode().strip() != trusted:
        raise ValueError("Trusted checkout differs from github.workflow_sha")
    if git(source_repo, "rev-parse", "HEAD").decode().strip() != source:
        raise ValueError("Source checkout differs from source_sha")
    git(source_repo, "merge-base", "--is-ancestor", base, source)
    return source, base, trusted


class Job:
    def __init__(self, environ=None):
        self.env = dict(os.environ if environ is None else environ)
        self.workspace = Path(self.env["GITHUB_WORKSPACE"]).resolve()
        self.trusted = self.workspace / "trusted"
        self.source = self.workspace / "source"
        self.execution = self.workspace / "execution"
        validate_roots(self.trusted, self.source, self.execution)
        self.component = self.env["QA_COMPONENT_KEY"]
        if self.component not in CHECKS:
            raise ValueError("Unknown QA executor")
        self.source_sha, self.base_sha, self.trusted_sha = authenticate_context(
            self.env, self.trusted, self.source
        )
        self.metadata = Path(self.env["RUNNER_TEMP"]) / "clarify-trusted-ci"
        if self.metadata.is_symlink():
            raise ValueError("QA metadata directory is linked")
        self.metadata.mkdir(exist_ok=True)
        self.plan = build_plan(
            self.trusted, self.source, self.trusted_sha, self.base_sha, self.source_sha
        )
        self.qa_policy = delivery_policy.event_validation(
            self.source, "push", {"before": self.base_sha}, self.source_sha
        )[1]
        self.plan_path = self.metadata / "plan.json"
        self.inventory_path = self.metadata / "inventory.json"
        self.python = Path(sys.executable).resolve()
        node = shutil.which("node")
        self.node = Path(node).resolve() if node else None
        self.tools = {}

    def write(self, path, value):
        if path.is_symlink():
            raise ValueError("QA metadata file is linked")
        path.write_text(canonical_json(value) + "\n", encoding="utf-8", newline="\n")

    def inventory(self):
        if not self.inventory_path.exists():
            return {"files": []}
        if self.inventory_path.is_symlink():
            raise ValueError("QA inventory is linked")
        value = json.loads(
            self.inventory_path.read_text(encoding="utf-8"),
            object_pairs_hook=delivery_policy.json_object,
        )
        if (
            value.get("source_sha") != self.source_sha
            or value.get("trusted_sha") != self.trusted_sha
        ):
            raise ValueError("QA inventory belongs to another composition")
        return value

    def observe(self, phase, exit_code=None):
        record = {
            "schema": 1,
            "trust_model": TRUST_MODEL,
            "phase": phase,
            "component_key": self.component,
            **{
                k: self.plan[k]
                for k in (
                    "source_sha",
                    "source_tree",
                    "base_sha",
                    "base_tree",
                    "trusted_sha",
                )
            },
            "inventory_sha256": digest(self.inventory()),
            "exit_code": exit_code,
        }
        self.write(self.metadata / (phase + ".json"), record)
        print("TRUSTED_CI_OBSERVATION " + canonical_json(record), flush=True)

    def authenticate(self):
        verify_tracked(self.trusted, self.trusted_sha, set(self.plan["controls"]))
        self.write(self.plan_path, self.plan)
        self.observe("authenticate")

    def prepare(self, materialize=True):
        verify_tracked(self.source, self.source_sha)
        if self.component not in self.plan["selected_keys"]:
            raise ValueError("An executor excluded by trusted policy cannot execute")
        if materialize:
            inventory = materialize_trees(
                self.trusted,
                self.source,
                self.execution,
                self.trusted_sha,
                self.source_sha,
            )
            self.write(self.inventory_path, inventory)
        self.observe("source-pre")

    def outputs(self):
        values = {
            key: str(value).lower() for key, value in self.plan["components"].items()
        }
        values.update(
            qa_policy=str(self.qa_policy).lower(),
            selected_keys=canonical_json(self.plan["selected_keys"]),
            source_tree=self.plan["source_tree"],
            base_tree=self.plan["base_tree"],
            plan_digest=digest(self.plan),
            controls_digest=digest(self.plan["controls"]),
        )
        path = Path(self.env["GITHUB_OUTPUT"])
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            for key, value in values.items():
                stream.write(key + "=" + value + "\n")

    def verify_source(self):
        verify_tracked(self.source, self.source_sha)
        if self.execution.exists():
            verify_execution(self.execution, self.inventory())
        self.observe("source-post")

    def verify_controls(self):
        verify_tracked(self.trusted, self.trusted_sha, set(self.plan["controls"]))
        if self.execution.exists():
            verify_execution(self.execution, self.inventory(), trusted_only=True)
        self.observe("controls-post")

    def command(self, args, cwd=None, extra_env=None):
        """Candidate output never reaches the Actions stdout command parser."""
        cwd = Path(cwd or self.execution)
        if not cwd.is_dir():
            raise ValueError("Missing recipe working directory")
        program = str(args[0])
        if not Path(program).is_absolute():
            if program not in self.tools:
                found = shutil.which(program)
                if not found:
                    raise ValueError("Missing trusted runner tool: " + program)
                self.tools[program] = str(Path(found).resolve())
            program = self.tools[program]
        logs = self.metadata / "logs"
        logs.mkdir(exist_ok=True)
        log = logs / (str(time.monotonic_ns()) + ".log")
        env = product_environment(self.env)
        env.update(
            CI="true",
            QT_QPA_PLATFORM="offscreen",
            QT_QUICK_CONTROLS_STYLE="Basic",
            PYTHONDONTWRITEBYTECODE="1",
            EXPO_NO_TELEMETRY="1",
        )
        env.update(extra_env or {})
        with log.open("xb") as output:
            result = subprocess.run(
                [program, *map(str, args[1:])],
                cwd=cwd,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if result.returncode:
            raise subprocess.CalledProcessError(result.returncode, [Path(program).name])
        return log

    def results(self):
        needs = json.loads(
            self.env["CI_NEEDS"], object_pairs_hook=delivery_policy.json_object
        )
        if set(needs) != {
            "components",
            "repository",
            "test",
            "settings",
            "package",
            "installer",
            "server",
            "mobile",
            "ios",
            "audit",
        }:
            raise ValueError("Unknown or missing aggregate CI result")
        selected = {
            **{k: str(v).lower() for k, v in self.plan["components"].items()},
            "qa_policy": str(self.qa_policy).lower(),
        }
        if needs.get("components", {}).get("outputs", {}) | selected != needs.get(
            "components", {}
        ).get("outputs", {}):
            raise ValueError("Selector outputs differ from recomputed trusted plan")
        delivery_policy.validate_ci_results(needs)

    def ios_gate(self):
        if (
            self.env.get("NATIVE_RESULT") != "success"
            or self.env.get("BUILD_RESULT") != "success"
        ):
            raise ValueError("Both native tests and unsigned compilation must succeed")

    def npm(self, *args, cwd):
        if self.node is None:
            raise ValueError("The pinned Node runtime is required")
        candidates = (
            self.node.parent / "node_modules/npm/bin/npm-cli.js",
            self.node.parent.parent / "lib/node_modules/npm/bin/npm-cli.js",
        )
        cli = next((p for p in candidates if p.is_file()), None)
        if cli is None:
            raise ValueError(
                "Cannot find the npm CLI supplied with the pinned Node runtime"
            )
        return self.command([self.node, cli, *args], cwd=cwd)

    def node_tool(self, area, relative, *args, cwd=None, extra_env=None):
        if self.node is None:
            raise ValueError("The pinned Node runtime is required")
        tool_root = self.trusted / area
        if not (tool_root / "node_modules").is_dir():
            self.npm("ci", "--ignore-scripts", "--no-fund", cwd=tool_root)
        tool = tool_root / "node_modules" / relative
        if not tool.is_file():
            raise ValueError("Missing tool from the MAIN dependency lock")
        return self.command(
            [self.node, tool, *args],
            cwd=cwd or self.execution / area,
            extra_env=extra_env,
        )

    def runtime_python(self):
        root = self.execution
        interpreter = (
            root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        marker = self.metadata / "python-ready"
        if not marker.exists():
            if not interpreter.exists():
                self.command([self.python, "-m", "venv", root / ".venv"])
            lock = (
                "requirements-lock-windows.txt"
                if os.name == "nt"
                else "requirements-lock-linux.txt"
            )
            self.command(
                [
                    interpreter,
                    root / "scripts/install_bootstrap_tools.py",
                    "--lock-file",
                    root / lock,
                ]
            )
            self.command(
                [
                    interpreter,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "-r",
                    root / "requirements-dev.txt",
                    "-c",
                    root / lock,
                ]
            )
            marker.write_text("ready\n", encoding="ascii")
        return interpreter

    def mobile_dependencies(self):
        root = self.execution / "mobile"
        if not (root / "node_modules").exists():
            self.npm("ci", "--no-fund", cwd=root)

    def mobile_checks(self):
        self.mobile_dependencies()
        root = self.execution / "mobile"
        self.command(
            [self.python, self.execution / "scripts/sync_locales.py", "--check"]
        )
        self.command([self.python, root / "scripts/sync-prompts.py", "--check"])
        self.node_tool("mobile", "typescript/bin/tsc", "--noEmit")
        self.node_tool("mobile", "expo/bin/cli", "lint")
        tests = sorted((root / "tests").glob("*.test.ts"))
        if not tests:
            raise ValueError("Missing MAIN mobile test inventory")
        self.command(
            [self.node, "--experimental-strip-types", "--test", *tests], cwd=root
        )
        self.node_tool("mobile", "expo/bin/cli", "install", "--check")
        if self.component == "mobile":
            self.node_tool(
                "mobile",
                "expo/bin/cli",
                "export",
                "--platform",
                "ios",
                "--max-workers",
                "2",
                "--output-dir",
                self.metadata / "mobile-export",
            )

    def _settings_playwright_modules(self):
        """Bind config/spec imports to the physical modules used by the MAIN CLI."""
        modules = self.execution / "desktop/node_modules"
        trusted_modules = self.trusted / "desktop/node_modules"
        if not modules.resolve().is_relative_to(
            self.execution.resolve()
        ) or not trusted_modules.resolve().is_relative_to(self.trusted.resolve()):
            raise ValueError("Playwright dependency root escapes its checkout")
        lock = json.loads(
            (self.trusted / "desktop/package-lock.json").read_text(encoding="utf-8")
        )
        bindings = []
        for name in ("@playwright/test", "playwright", "playwright-core"):
            origin = (trusted_modules / name).resolve(strict=True)
            if not origin.is_relative_to(trusted_modules.resolve()):
                raise ValueError("Playwright dependency escapes MAIN tools")
            package = json.loads((origin / "package.json").read_text(encoding="utf-8"))
            version = lock["packages"]["node_modules/" + name]["version"]
            if (
                not isinstance(version, str)
                or not version
                or package.get("name") != name
                or package.get("version") != version
            ):
                raise ValueError("Playwright dependency differs from the MAIN lock")
            target = modules / name
            if not target.parent.resolve().is_relative_to(modules.resolve()):
                raise ValueError("Playwright import parent escapes execution")
            if target.is_symlink():
                if target.resolve() == origin:
                    continue
                raise ValueError("Unknown Playwright import link")
            if target.exists() and (
                not target.is_dir()
                or not target.resolve().is_relative_to(modules.resolve())
            ):
                raise ValueError("Unsafe Playwright import target")
            bindings.append((target, origin))
        for target, origin in bindings:
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(origin, target_is_directory=True)

    def settings(self, native=False, test=True):
        python = self.runtime_python()
        root = self.execution / "desktop"
        if not (root / "node_modules").exists():
            self.npm("ci", "--no-fund", cwd=root)
        self.node_tool("desktop", "typescript/bin/tsc", "--noEmit")
        self.node_tool("desktop", "vite/bin/vite.js", "build")
        if test:
            self._settings_playwright_modules()
            self.node_tool(
                "desktop", "playwright/cli.js", "install", "--with-deps", "chromium"
            )
            self.node_tool(
                "desktop",
                "playwright/cli.js",
                "test",
                "--config",
                root / "playwright.config.ts",
                extra_env={
                    "CLARIFY_TEST_PYTHON": str(python),
                    "CLARIFY_TEST_FIXTURE": str(
                        self.execution / "tests/web_settings_fixture.py"
                    ),
                    "CLARIFY_TEST_BROWSER": "chromium",
                },
            )
        if native:
            self.command(
                [
                    "cargo",
                    "build",
                    "--locked",
                    "--manifest-path",
                    "src-tauri/Cargo.toml",
                    "--release",
                    "--features",
                    "custom-protocol",
                ],
                cwd=root,
            )
            output = self.execution / "dist"
            output.mkdir(exist_ok=True)
            shutil.copyfile(
                root / "src-tauri/target/release/clarify-settings.exe",
                output / "clarify-settings.exe",
            )
            self.command(
                [
                    python,
                    self.execution / "scripts/settings_inventory.py",
                    "--desktop",
                    root,
                    "--output-dir",
                    output,
                ]
            )

    def python_checks(self):
        python = self.runtime_python()
        root = self.execution
        lock = (
            "requirements-lock-windows.txt"
            if os.name == "nt"
            else "requirements-lock-linux.txt"
        )
        self.command(
            [
                python,
                "scripts/check_dependency_lock.py",
                "--lock-file",
                lock,
                "--allow-unsafe",
            ]
        )
        if os.name == "nt":
            self.command(
                [
                    python,
                    "scripts/check_dependency_lock.py",
                    "--lock-file",
                    "requirements-lock-runtime-windows.txt",
                    "--requirements-file",
                    "requirements.txt",
                ]
            )
            self.command([python, "scripts/check_runtime_lock.py"])
        if os.name != "nt":
            # These are the existing MAIN lint boundaries plus the reviewed new
            # product/adapter modules; configuration and recipe are always MAIN.
            extra = ["scripts/trusted_ci.py", "tests/test_trusted_ci.py"]
            extra += [p.name for p in root.glob("computer_*.py")]
            if (root / "clarify/desktop/qml_computer.py").exists():
                extra.append("clarify/desktop/qml_computer.py")
            self.command(
                [
                    python,
                    "-m",
                    "ruff",
                    "check",
                    "--config",
                    root / "pyproject.toml",
                    *PYTHON_LINT_PATHS,
                    *extra,
                ]
            )
            self.command(
                [
                    python,
                    "-m",
                    "ruff",
                    "format",
                    "--check",
                    "--config",
                    root / "pyproject.toml",
                    *PYTHON_FORMAT_PATHS,
                    *extra,
                ]
            )
            # Retain the original type boundary, with MAIN configuration.
            self.command(
                [
                    python,
                    "-m",
                    "mypy",
                    "--config-file",
                    root / "pyproject.toml",
                    "desktop_state.py",
                    "windows_hotkeys.py",
                ]
            )
        self.command(
            [python, "scripts/run_tests.py", "discover", "-s", "tests", "-v"],
            extra_env={"CLARIFY_TRUSTED_CI_TEST_ROOT": str(self.trusted)},
        )
        self.command(
            [
                python,
                "-m",
                "compileall",
                "-q",
                *sorted(root.glob("*.py")),
                root / "clarify",
                root / "scripts",
                root / "tests",
            ]
        )
        qml = root / "clarify/desktop/qml"
        if not (qml / "Main.qml").is_file() or not list(qml.glob("*.qml")):
            raise ValueError("Missing candidate QML assets")

    def powershell(self, script, extra_env=None):
        path = self.metadata / (str(time.monotonic_ns()) + ".ps1")
        path.write_text("$ErrorActionPreference = 'Stop'\n" + script, encoding="utf-8")
        self.command(["pwsh", "-NoProfile", "-File", path], extra_env=extra_env)

    def package(self):
        if os.name != "nt":
            raise ValueError("Windows package validation requires Windows")
        self.settings(native=True, test=False)
        self.powershell(
            "& ./scripts/build.ps1 -SkipGitHooks -SettingsExecutable dist/clarify-settings.exe\nif ($LASTEXITCODE -ne 0) { throw 'Portable build failed' }"
        )
        if self.plan["components"]["installer"]:
            self.powershell("""& ./scripts/build.ps1 -SkipGitHooks -SettingsExecutable dist/clarify-settings.exe -OutputDirectory dist/baseline -PayloadIdentity baseline-msi-0.1.1
if ($LASTEXITCODE -ne 0) { throw 'Baseline build failed' }
if ((Get-FileHash dist/baseline/Clarify.exe).Hash -eq (Get-FileHash dist/Clarify.exe).Hash) { throw 'Baseline must be byte-distinct' }
""")
        python = self.runtime_python()
        self.command([python, "scripts/test_portable_update.py"])
        self.powershell("""$qaSmokeDirectory = Join-Path $env:RUNNER_TEMP 'clarify-qa-packaged-smoke'
New-Item -ItemType Directory -Path $qaSmokeDirectory -Force | Out-Null
$env:CLARIFY_DATA_DIR = $qaSmokeDirectory
$process = Start-Process -FilePath (Resolve-Path dist/Clarify.exe).Path -ArgumentList @('--hidden') -WindowStyle Hidden -PassThru
try { Start-Sleep -Seconds 5; if ($process.HasExited) { throw 'Packaged QML exited during launch' } }
finally { if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force } }
""")
        self.command(
            [
                python,
                "-c",
                "import sys; sys.argv=['app.py','secret-store-self-test']; import app; raise SystemExit(app._run_cli(['secret-store-self-test']))",
            ]
        )

    def installer(self):
        if os.name != "nt":
            raise ValueError("Installer validation requires Windows")
        self.powershell(
            """& ./scripts/build-installer.ps1 -Version 0.1.1 -SourceExe dist/baseline/Clarify.exe -OutputPath dist/Clarify-windows-x64-baseline.msi
if ($LASTEXITCODE -ne 0) { throw 'Baseline installer failed' }
& ./scripts/build-installer.ps1 -SourceExe dist/Clarify.exe -OutputPath dist/Clarify-windows-x64.msi
if ($LASTEXITCODE -ne 0) { throw 'Current installer failed' }
& ./scripts/test-installer.ps1 -BaselineInstaller dist/Clarify-windows-x64-baseline.msi -CurrentInstaller dist/Clarify-windows-x64.msi -BaselinePayloadSha256 ((Get-FileHash dist/baseline/Clarify.exe -Algorithm SHA256).Hash) -CurrentPayloadSha256 ((Get-FileHash dist/Clarify.exe -Algorithm SHA256).Hash)
if ($LASTEXITCODE -ne 0) { throw 'Installer lifecycle failed' }
""",
            extra_env={
                "GITHUB_ACTIONS": self.env.get("GITHUB_ACTIONS", ""),
                "GITHUB_WORKSPACE": str(self.execution),
            },
        )
        # Version is data, never a candidate Python import.
        assignments = [
            node
            for node in ast.parse((self.execution / "version.py").read_text()).body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__version__"
        ]
        value = assignments[0].value if len(assignments) == 1 else None
        version = value.value if isinstance(value, ast.Constant) else None
        if not isinstance(version, str) or not re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+", version
        ):
            raise ValueError("Unknown candidate version data")
        self.command(
            [
                self.python,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "requests",
                "-c",
                self.trusted / "requirements-lock-windows.txt",
            ]
        )
        self.command(
            [
                self.python,
                "scripts/create_release_manifest.py",
                "--version",
                version,
                "--installer",
                "dist/Clarify-windows-x64.msi",
                "--output",
                "dist/release-manifest.json",
            ]
        )
        self.powershell(
            "& ./scripts/build-manifest-container.ps1 -Manifest dist/release-manifest.json -OutputPath dist/Clarify-release-manifest.cab\nif ($LASTEXITCODE -ne 0) { throw 'Manifest container failed' }"
        )

    def server(self):
        root = self.execution
        self.command(
            [
                self.python,
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "-r",
                "server/requirements.txt",
            ]
        )
        self.command(
            [
                self.python,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_server_image_context.py",
                "-v",
            ]
        )
        self.command(
            [
                self.python,
                "-m",
                "django",
                "makemigrations",
                "--check",
                "--dry-run",
                "--settings",
                "cloud.settings",
            ],
            cwd=root / "server",
            extra_env={"PYTHONPATH": str(root)},
        )
        # Candidate settings cannot substitute their own test runner/selector.
        self.command(
            [
                self.python,
                "-c",
                "import os; os.environ['DJANGO_SETTINGS_MODULE']='cloud.settings'; import django; django.setup(); from django.test.runner import DiscoverRunner; raise SystemExit(bool(DiscoverRunner(interactive=False).run_tests(['cloud.service.tests'])))",
            ],
            cwd=root / "server",
            extra_env={"PYTHONPATH": str(root)},
        )
        self.command([self.python, "mobile/scripts/sync-prompts.py", "--check"])
        self.command(
            [
                "docker",
                "build",
                "-f",
                "server/Dockerfile",
                "-t",
                "clarify-account-qa",
                "--label",
                "org.opencontainers.image.revision=" + self.source_sha,
                ".",
            ]
        )
        try:
            self.command(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    "clarify-account-qa-smoke",
                    "--network",
                    "host",
                    "-e",
                    "CLARIFY_DEVELOPMENT=1",
                    "-e",
                    "DATABASE_URL",
                    "-e",
                    "PORT=8080",
                    "clarify-account-qa",
                ]
            )
            healthy = False
            for _ in range(60):
                try:
                    with urlopen("http://127.0.0.1:8080/health", timeout=2) as response:
                        healthy = json.load(response).get("status") == "ok"
                except (OSError, ValueError):
                    pass
                if healthy:
                    break
                time.sleep(1)
            if not healthy:
                raise ValueError("Server container did not become healthy")
            self.command(
                [
                    "docker",
                    "exec",
                    "clarify-account-qa-smoke",
                    "python",
                    "server/manage.py",
                    "migrate",
                    "--check",
                ]
            )
        finally:
            active_error = sys.exception()
            try:
                self.command(["docker", "rm", "-f", "clarify-account-qa-smoke"])
            except subprocess.SubprocessError:
                if active_error is None:
                    raise
        if (root / "connect/Dockerfile").exists():
            self.command(
                [
                    "docker",
                    "build",
                    "-f",
                    "connect/Dockerfile",
                    "-t",
                    "clarify-relay-qa",
                    "--label",
                    "org.opencontainers.image.revision=" + self.source_sha,
                    ".",
                ]
            )

    def run_recipe(self, recipe, settings_tests=True):
        allowed = {
            "repository": {"repository"},
            "python_linux": {"python"},
            "python_windows": {"python"},
            "settings": {"settings", "settings-native"},
            "package_windows": {"package"},
            "installer_windows": {"installer"},
            "server": {"server"},
            "mobile": {"mobile"},
            "ios_native": {"mobile", "native-contracts", "native-uikit"},
            "ios_build": {"ios-project", "ios-pods", "ios-build"},
            "audit_python_linux": {"audit-python"},
            "audit_python_windows": {"audit-python"},
            "audit_settings": {"audit-settings"},
        }
        if recipe not in allowed.get(self.component, set()) or (
            not settings_tests and recipe not in {"settings", "settings-native"}
        ):
            raise ValueError("Recipe does not belong to this trusted executor")
        root = self.execution
        if recipe == "repository":
            self.command([self.python, "scripts/check_agent_skills.py", "--repo", root])
            names = (
                "test_delivery_policy.py",
                "test_release_delivery.py",
                "test_trusted_ci.py",
            )
            environment = {"CLARIFY_TRUSTED_CI_TEST_ROOT": str(self.trusted)}
            if self.qa_policy:
                self.npm(
                    "ci", "--ignore-scripts", "--no-fund", cwd=self.trusted / "desktop"
                )
                names += ("test_testflight_qa.py", "test_qa_device_archive.py")
                environment.update(
                    CLARIFY_QA_TEST_NODE=str(self.node),
                    CLARIFY_QA_TEST_YAML_MODULE=str(
                        self.trusted / "desktop/node_modules/yaml"
                    ),
                )
            for name in names:
                self.command(
                    [
                        self.python,
                        "-m",
                        "unittest",
                        "discover",
                        "-s",
                        "tests",
                        "-p",
                        name,
                        "-v",
                    ],
                    extra_env=environment,
                )
        elif recipe == "python":
            self.python_checks()
        elif recipe in {"settings", "settings-native"}:
            self.settings(native=recipe == "settings-native", test=settings_tests)
        elif recipe == "package":
            self.package()
        elif recipe == "installer":
            self.installer()
        elif recipe == "server":
            self.server()
        elif recipe == "mobile":
            self.mobile_checks()
        elif recipe == "native-contracts":
            self.command(
                ["swift", "test", "--package-path", "modules/clarify-core"],
                cwd=root / "mobile",
            )
        elif recipe == "native-uikit":
            self.command(
                [self.node, root / "mobile/scripts/test-keyboard-ui.cjs"],
                cwd=root / "mobile",
                extra_env={
                    "CLARIFY_NATIVE_TESTS": "1",
                    "CLARIFY_KEYBOARD_UI_SOURCE_ROOT": str(root / "mobile"),
                    "CLARIFY_KEYBOARD_UI_TEST_ROOT": str(self.trusted / "mobile"),
                    "CLARIFY_IOS_UI_DERIVED_DATA": str(
                        self.metadata / "UIKitDerivedData"
                    ),
                    "CLARIFY_IOS_UI_FIXTURE_ROOT": str(self.metadata / "UIKitFixture"),
                },
            )
        elif recipe == "ios-project":
            self.mobile_dependencies()
            self.node_tool(
                "mobile",
                "expo/bin/cli",
                "prebuild",
                "--clean",
                "--platform",
                "ios",
                "--no-install",
            )
        elif recipe == "ios-pods":
            self.command(
                ["pod", "install", "--project-directory=ios"], cwd=root / "mobile"
            )
        elif recipe == "ios-build":
            self.command(
                [
                    "xcodebuild",
                    "-workspace",
                    "ios/Clarify.xcworkspace",
                    "-scheme",
                    "Clarify",
                    "-configuration",
                    "Debug",
                    "-destination",
                    "generic/platform=iOS Simulator",
                    "-derivedDataPath",
                    self.metadata / "UnsignedSimulator",
                    "-showBuildTimingSummary",
                    "CODE_SIGNING_ALLOWED=NO",
                    "build",
                ],
                cwd=root / "mobile",
            )
        elif recipe == "audit-python":
            lock = self.execution / (
                "requirements-lock-windows.txt"
                if os.name == "nt"
                else "requirements-lock-linux.txt"
            )
            trusted_lock = self.trusted / lock.name
            self.command(
                [
                    self.python,
                    self.trusted / "scripts/install_bootstrap_tools.py",
                    "--lock-file",
                    trusted_lock,
                ]
            )
            self.command(
                [
                    self.python,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "pip-audit",
                    "-c",
                    trusted_lock,
                ]
            )
            self.command(
                [
                    self.python,
                    self.trusted / "scripts/dependency_audit.py",
                    "--lock-file",
                    lock,
                ]
            )
        elif recipe == "audit-settings":
            self.npm("ci", "--ignore-scripts", "--no-fund", cwd=root / "desktop")
            self.npm(
                "audit", "--include=dev", "--audit-level=high", cwd=root / "desktop"
            )
        else:
            raise ValueError("Unknown MAIN QA recipe")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "authenticate",
            "prepare",
            "resolve",
            "select",
            "verify-source",
            "verify-controls",
            "run",
            "results",
            "ios-gate",
        ),
    )
    parser.add_argument("--recipe")
    parser.add_argument("--skip-settings-tests", action="store_true")
    args = parser.parse_args()
    job = None
    try:
        job = Job()
        if args.operation == "authenticate":
            job.authenticate()
        elif args.operation in {"prepare", "resolve"}:
            job.prepare(materialize=args.operation == "prepare")
        elif args.operation == "select":
            job.outputs()
        elif args.operation == "verify-source":
            job.verify_source()
        elif args.operation == "verify-controls":
            job.verify_controls()
        elif args.operation == "run":
            job.run_recipe(args.recipe, settings_tests=not args.skip_settings_tests)
            job.observe("recipe", 0)
        elif args.operation == "results":
            job.results()
        elif args.operation == "ios-gate":
            job.ios_gate()
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        code = (
            error.returncode
            if isinstance(error, subprocess.CalledProcessError) and error.returncode > 0
            else 1
        )
        if job is not None and args.operation == "run":
            job.observe("recipe", code)
        print("Trusted QA failed: " + str(error), file=sys.stderr)
        return code


if __name__ == "__main__":
    raise SystemExit(main())
