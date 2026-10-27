"""Select CI validation from the complete Git range and check its final results."""

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

if __package__:
    from .release_delivery import validate_intent
    from .sync_locales import CATALOG_PATH, DESKTOP_KEYS_PATH, native_catalog
else:
    from release_delivery import validate_intent
    from sync_locales import CATALOG_PATH, DESKTOP_KEYS_PATH, native_catalog


COMPONENTS = (
    "desktop",
    "settings",
    "package",
    "installer",
    "server",
    "mobile",
    "ios",
    "audit",
)
DESKTOP_BUILD = {"desktop", "settings", "package"}
SHARED_CONSUMERS = DESKTOP_BUILD | {"server", "mobile", "ios"}
RELEASE_INTENT = ".github/release-intent.json"
FULL_INPUTS = {
    "scripts/delivery_policy.py",
    "tests/test_delivery_policy.py",
    ".github/workflows/ci.yml",
    ".github/workflows/repository-validation.yml",
}
SHARED_INPUTS = {
    "scripts/sync_locales.py",
    "mobile/scripts/sync-prompts.py",
    "mobile/modules/clarify-core/ios/RewritePrompt.swift",
}
SERVER_INPUTS = {
    ".dockerignore",
    "dictionary_snippets.py",
    "clarify_account.py",
    "social_login.py",
    "account_history.py",
    "history_store.py",
    "secret_store.py",
    "provider_types.py",
    "scripts/server_image_context.py",
    "tests/test_server_image_context.py",
    ".github/workflows/server-validation.yml",
    ".github/workflows/shared-account.yml",
}
IOS_INPUTS = {
    ".github/workflows/ios-validation.yml",
    ".github/workflows/ios-testflight.yml",
    ".github/workflows/shared-account.yml",
    ".github/workflows/ios-audio-contracts.yml",
}
SETTINGS_INPUTS = {
    "clarify/desktop/qml_web_settings.py",
    "clarify/desktop/qml_settings.py",
    "clarify/desktop/qml_bridge.py",
    "clarify/desktop/history_view.py",
    "account_history.py",
    "clarify_account.py",
    "cloud_defaults.py",
    "dictionary_settings.py",
    "dictionary_snippets.py",
    "history_store.py",
    "hotkey_config.py",
    "local_asr.py",
    "local_asr_product.py",
    "microphone_controls.py",
    "provider_registry.py",
    "provider_types.py",
    "repositories.py",
    "secret_store.py",
    "social_login.py",
    "workflow_config.py",
    "workflow_settings.py",
    "tests/web_settings_fixture.py",
    "tests/test_web_settings.py",
    "tests/test_settings_navigation.py",
    "tests/test_pyside6_qml_settings.py",
}
PACKAGE_INPUTS = {
    "build.bat",
    "scripts/build.ps1",
    "scripts/build-settings.ps1",
    "scripts/windows-build-paths.ps1",
    "scripts/deploy.ps1",
    "scripts/setup.ps1",
    "scripts/install_bootstrap_tools.py",
    "scripts/check_settings_payload.py",
    "scripts/settings_inventory.py",
    "scripts/qt_distribution.py",
    "scripts/qt_package_policy.py",
    "scripts/qt_sources.json",
    "scripts/portable_crypto_inventory.py",
    "scripts/sox-runtime-manifest.json",
    "tests/test_settings_packaging.py",
    "tests/test_settings_inventory.py",
    "tests/test_qt_distribution.py",
    "tests/test_qt_package_policy.py",
    ".github/workflows/community-release.yml",
    ".github/workflows/release.yml",
    ".github/workflows/package-validation.yml",
}
INSTALLER_INPUTS = {
    "scripts/build-installer.ps1",
    "scripts/test-installer.ps1",
    "scripts/build-manifest-container.ps1",
    "scripts/create_release_manifest.py",
    ".github/workflows/installer-validation.yml",
}
DEPENDENCY_NAMES = {
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.toml",
    "Cargo.lock",
    "pyproject.toml",
    "uv.lock",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "Podfile",
    "Podfile.lock",
    "Package.swift",
    "Package.resolved",
    "Gemfile",
    "Gemfile.lock",
}
REPOSITORY_INPUTS = {
    ".editorconfig",
    ".gitignore",
    ".gitattributes",
    ".github/CODEOWNERS",
    ".agents/skills/upstream-lock.json",
}


def documentation(path: str) -> bool:
    return path.startswith("docs/") or PurePosixPath(path).suffix.lower() in {
        ".md",
        ".rst",
    }


def dependency_input(path: str) -> bool:
    name = PurePosixPath(path).name
    return (
        name in DEPENDENCY_NAMES
        or name.endswith(".podspec")
        or re.fullmatch(r"requirements(?:[-.][\w.-]+)?\.(?:txt|in)", name) is not None
    )


def path_components(path: str) -> set[str]:
    # Unknown names must not turn an untested change into a green CI run.
    if path in FULL_INPUTS or path == RELEASE_INTENT:
        return set(COMPONENTS)
    if path in {"LICENSE", "THIRD_PARTY_NOTICES.md"}:
        return {"desktop", "package"}
    if (
        documentation(path)
        or path in REPOSITORY_INPUTS
        or path.startswith(".github/ISSUE_TEMPLATE/")
    ):
        return set()
    if path == "scripts/release_delivery.py":
        # Repository checks exercise publication policy; this is not app input.
        return set()
    if path == "workflow_provider.py":
        # Mobile checks verify the generated prompts before native code is built.
        return DESKTOP_BUILD | {"server", "mobile"}
    if path.startswith("shared/") or path in SHARED_INPUTS:
        return SHARED_CONSUMERS.copy()
    if path in IOS_INPUTS:
        return {"mobile", "ios"} | ({"server"} if path in SERVER_INPUTS else set())
    if path.startswith("server/"):
        return {"server"}
    if path.startswith("mobile/"):
        if dependency_input(path):
            return {"mobile", "ios"}
        name = PurePosixPath(path).name
        if (
            name.startswith("app.config.")
            or name in {"app.json", "eas.json", "expo-module.config.json"}
            or path.startswith(
                (
                    "mobile/plugins/",
                    "mobile/native/",
                    "mobile/ios/",
                    "mobile/android/",
                    "mobile/locales/",
                )
            )
        ):
            return {"mobile", "ios"}
        if PurePosixPath(path).suffix in {".ts", ".tsx", ".js", ".jsx"} or (
            path.startswith(("mobile/src/", "mobile/tests/", "mobile/locales/"))
            and PurePosixPath(path).suffix == ".json"
        ):
            return {"mobile"}
        return {"mobile", "ios"}
    if path.startswith("installer/") or path in INSTALLER_INPUTS:
        return DESKTOP_BUILD | {"installer"}
    if path in {
        "dependency-audit.json",
        ".github/dependabot.yml",
        ".github/workflows/dependency-audit.yml",
        "scripts/dependency_audit.py",
    }:
        return {"audit"}
    if dependency_input(path):
        if "/" not in path or path.startswith("desktop/"):
            return DESKTOP_BUILD | {"audit"}
        return set(COMPONENTS)
    if (
        path in PACKAGE_INPUTS
        or PurePosixPath(path).suffix == ".spec"
        or path.startswith(
            ("scripts/pyinstaller-hooks/", ".github/actions/settings-build/")
        )
    ):
        return DESKTOP_BUILD.copy()
    if path.startswith("desktop/"):
        if path.startswith(
            ("desktop/src/", "desktop/tests/", "desktop/public/")
        ) or path in {"desktop/playwright.config.ts"}:
            return {"settings"}
        return DESKTOP_BUILD.copy()
    if path == ".github/workflows/settings-validation.yml":
        return {"settings"}
    if (
        path.startswith(
            ("assets/", "licenses/", "local_asr_manifests/", "distribution/", "extra/")
        )
        or path == "local_asr_manifest.json"
    ):
        return {"desktop", "package"}
    selected = {"server"} if path in SERVER_INPUTS else set()
    if path in SETTINGS_INPUTS:
        return selected | {"desktop", "settings"}
    if path.startswith(("clarify/", "tests/")) or (
        "/" not in path and PurePosixPath(path).suffix == ".py"
    ):
        return selected | {"desktop"}
    return selected or set(COMPONENTS)


def affected_components(paths: list[str]) -> dict[str, bool]:
    selected: set[str] = set()
    for path in paths:
        selected.update(path_components(path))
    return {component: component in selected for component in COMPONENTS}


def changed_paths(repo: Path, base: str, head: str) -> list[str]:
    for revision in (base, head):
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Change boundaries must be complete commit SHAs")
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "diff",
            "--no-renames",
            "--name-only",
            "-z",
            base,
            head,
            "--",
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


def json_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON fields are not allowed")
        result[key] = value
    return result


def release_components(repo: Path, head: str) -> set[str]:
    """Read routing metadata from the tested Git tree, never the working copy."""
    try:
        tree = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", head, "--", RELEASE_INTENT],
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        # Do not follow a release-intent symlink or accept a directory.
        if not tree.startswith((b"100644 blob ", b"100755 blob ")):
            return set(COMPONENTS)
        source = subprocess.run(
            ["git", "-C", str(repo), "show", f"{head}:{RELEASE_INTENT}"],
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        intent = validate_intent(json.loads(source, object_pairs_hook=json_object))
        component = intent["component"]
        if component == "desktop":
            return DESKTOP_BUILD | {"audit"}
        if component == "mobile":
            return {"mobile", "ios"}
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, RecursionError):
        pass
    return set(COMPONENTS)


def event_components(
    repo: Path, event_name: str, event: dict, head: str
) -> dict[str, bool]:
    if event_name == "workflow_dispatch":
        return dict.fromkeys(COMPONENTS, True)
    if event_name == "pull_request":
        base = event["pull_request"]["base"]["sha"]
    elif event_name == "push":
        base = event["before"]
        if base == "0" * 40:
            return dict.fromkeys(COMPONENTS, True)
    else:
        raise ValueError("Unsupported validation event")
    paths = changed_paths(repo, base, head)
    selected = affected_components(
        [path for path in paths if path not in {RELEASE_INTENT, CATALOG_PATH}]
    )
    if CATALOG_PATH in paths:
        consumers = path_components(CATALOG_PATH)
        if native_catalog_unchanged(repo, base, head):
            consumers.discard("ios")
        for component in consumers:
            selected[component] = True
    if RELEASE_INTENT in paths:
        for component in release_components(repo, head):
            selected[component] = True
    return selected


def native_catalog_unchanged(repo: Path, base: str, head: str) -> bool:
    """Compare reviewed native inputs from Git; uncertainty retains native CI."""

    def read_json(revision: str, path: str):
        tree = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", revision, "--", path],
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        if not tree.startswith((b"100644 blob ", b"100755 blob ")):
            raise ValueError("Catalog inputs must be regular Git blobs")
        source = subprocess.run(
            ["git", "-C", str(repo), "show", f"{revision}:{path}"],
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        return json.loads(source, object_pairs_hook=json_object)

    try:
        return native_catalog(
            read_json(base, CATALOG_PATH), read_json(base, DESKTOP_KEYS_PATH)
        ) == native_catalog(
            read_json(head, CATALOG_PATH), read_json(head, DESKTOP_KEYS_PATH)
        )
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, RecursionError):
        return False


def validate_ci_results(needs: dict) -> None:
    """Reject missing jobs, invalid flags, and every unsuccessful required job."""
    if not isinstance(needs, dict):
        raise ValueError("CI needs must be a JSON object")
    errors = []
    selector = needs.get("components")
    outputs = selector.get("outputs") if isinstance(selector, dict) else None
    flags = {}
    if not isinstance(outputs, dict):
        errors.append("components.outputs must contain all component flags")
    else:
        for component in COMPONENTS:
            value = outputs.get(component)
            if not isinstance(value, str) or value not in {"true", "false"}:
                errors.append(f"components.outputs.{component} must be true or false")
            else:
                flags[component] = value == "true"
    required = {"components", "repository"}
    jobs = {
        "test" if component == "desktop" else component: component
        for component in COMPONENTS
    }
    for job in ("components", "repository", *jobs):
        if job not in needs:
            errors.append(f"Missing CI job: {job}")
    for job, record in needs.items():
        if not isinstance(record, dict):
            errors.append(f"Invalid CI job: {job}")
            continue
        must_succeed = job in required or flags.get(jobs.get(job), False)
        allowed = {"success"} if must_succeed else {"success", "skipped"}
        result = record.get("result")
        if not isinstance(result, str) or result not in allowed:
            errors.append(
                f"{job} must {'succeed' if must_succeed else 'succeed or be skipped'} (result: {result!r})"
            )
    if errors:
        raise ValueError("; ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--check-results", action="store_true")
    args = parser.parse_args()
    try:
        if args.check_results:
            validate_ci_results(
                json.loads(os.environ["CI_NEEDS"], object_pairs_hook=json_object)
            )
            print("CI results passed")
            return 0
        event = json.loads(
            Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
        )
        selected = event_components(
            args.repo, os.environ["GITHUB_EVENT_NAME"], event, os.environ["GITHUB_SHA"]
        )
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            for component, required in selected.items():
                output.write(f"{component}={str(required).lower()}\n")
        print(json.dumps(selected, sort_keys=True))
        return 0
    except (
        KeyError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
        RecursionError,
    ) as error:
        print(f"CI validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
