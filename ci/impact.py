"""Conservative dependency selection for complete Git ranges and local changes."""

import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

from ci.tasks import JOBS
from scripts.sync_locales import CATALOG_PATH, DESKTOP_KEYS_PATH, native_catalog

COMPONENTS = (
    "desktop",
    "settings",
    "desktop_shell",
    "package",
    "installer",
    "server",
    "mobile",
    "ios",
    "audit",
)
DESKTOP_BUILD = {"desktop", "settings", "desktop_shell", "package"}
SHARED_CONSUMERS = DESKTOP_BUILD | {"server", "mobile", "ios"}
RELEASE_INTENT = ".github/release-intent.json"
POLICY_TOOLS = {
    "scripts/release_delivery.py",
    "scripts/release_candidate.py",
    "scripts/app_store_handoff.py",
    "scripts/check_agent_skills.py",
    "scripts/format_staged.py",
}
FULL_INPUTS = {
    "ci/impact.py",
    "ci/tasks.py",
    "ci/cli.py",
    "scripts/run_tests.py",
    "scripts/test_suites.py",
    "tests/__init__.py",
    "scripts/ci.py",
    "pyproject.toml",
    "tests/policy/test_delivery_policy.py",
    ".github/workflows/ci.yml",
}
SHARED_INPUTS = {
    "scripts/sync_locales.py",
}
SERVER_INPUTS = {
    "computer_relay_protocol.py",
    "computer_relay_server.py",
    "computer_relay_client.py",
    "tests/integration/test_computer_relay.py",
    ".dockerignore",
    "dictionary_snippets.py",
    "clarify_account.py",
    "social_login.py",
    "account_history.py",
    "history_store.py",
    "secret_store.py",
    "provider_types.py",
    "scripts/server_image_context.py",
    "tests/integration/test_server_image_context.py",
    ".github/workflows/server-validation.yml",
    ".github/workflows/server-recovery.yml",
}
IOS_INPUTS = {
    ".github/workflows/ios-validation.yml",
    ".github/workflows/ios-testflight.yml",
    ".github/workflows/ios-app-store.yml",
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
    "tests/contract/test_web_settings.py",
    "tests/contract/test_settings_navigation.py",
    "tests/contract/test_pyside6_qml_settings.py",
}
PACKAGE_INPUTS = {
    "build.bat",
    "scripts/build.ps1",
    "scripts/build-settings.ps1",
    "scripts/build-desktop.ps1",
    "scripts/windows-build-paths.ps1",
    "scripts/deploy.ps1",
    "scripts/setup.ps1",
    "scripts/install_bootstrap_tools.py",
    "scripts/check_settings_payload.py",
    "scripts/desktop_payload.py",
    "scripts/settings_inventory.py",
    "scripts/qt_distribution.py",
    "scripts/qt_package_policy.py",
    "scripts/qt_sources.json",
    "scripts/portable_crypto_inventory.py",
    "scripts/sox-runtime-manifest.json",
    "tests/policy/test_settings_packaging.py",
    "tests/contract/test_settings_inventory.py",
    "tests/integration/test_settings_inventory.py",
    "tests/contract/test_qt_distribution.py",
    "tests/contract/test_qt_package_policy.py",
    ".github/workflows/release.yml",
}
INSTALLER_INPUTS = {
    "scripts/build-installer.ps1",
    "scripts/test-installer.ps1",
    "scripts/build-manifest-container.ps1",
    "scripts/create_release_manifest.py",
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
    if path in FULL_INPUTS or path == RELEASE_INTENT or path.startswith("ci/"):
        return set(COMPONENTS)
    if path.startswith("tests/support/"):
        return {"desktop", "settings", "desktop_shell"}
    if path.startswith("tests/policy/"):
        return set()
    if path in POLICY_TOOLS:
        return {"static"}
    if path.startswith(("desktop/unit-tests/", "desktop/test-support/")) or path in {
        "desktop/vitest.config.ts",
        "desktop/tsconfig.unit.json",
        "desktop/scripts/test-unit.mjs",
    }:
        return {"settings_unit"}
    if path.startswith(
        (".github/actions/ios-env/", ".github/actions/ios-fixture-toolchain/")
    ):
        return {"mobile", "ios"}
    if path.startswith(".github/actions/python-env/"):
        return DESKTOP_BUILD.copy()
    if path in {
        ".github/workflows/release-preparation.yml",
        ".github/workflows/release-promotion.yml",
    }:
        return set()
    if path in {"LICENSE", "THIRD_PARTY_NOTICES.md"}:
        return {"desktop", "package", "desktop_shell"}
    if (
        documentation(path)
        or path in REPOSITORY_INPUTS
        or path.startswith(".github/ISSUE_TEMPLATE/")
    ):
        return set()
    if path in {
        "scripts/release_delivery.py",
        "scripts/app_store_handoff.py",
        "tests/contract/test_ios_ipa.py",
    }:
        # Repository checks exercise publication policy; this is not app input.
        return set()
    if path == "workflow_provider.py":
        # Mobile checks verify the generated prompts before native code is built.
        return DESKTOP_BUILD | {"server", "mobile"}
    if path.startswith("shared/") or path in SHARED_INPUTS:
        return SHARED_CONSUMERS.copy()
    if path in IOS_INPUTS:
        return {"mobile", "ios"} | ({"server"} if path in SERVER_INPUTS else set())
    if path.startswith(("server/", "connect/")):
        return {"server"}
    if path.startswith("mobile/"):
        if dependency_input(path):
            return {"mobile", "ios"}
        name = PurePosixPath(path).name
        if (
            name.startswith("app.config.")
            or name in {"app.json", "expo-module.config.json"}
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
        if path == "requirements-lock-linux.txt":
            # Connect installs through this constraint file inside its image.
            return DESKTOP_BUILD | {"audit", "server"}
        if "/" not in path or path.startswith("desktop/"):
            return DESKTOP_BUILD | {"audit"}
        return set(COMPONENTS)
    if (
        path in PACKAGE_INPUTS
        or PurePosixPath(path).suffix == ".spec"
        or path.startswith(
            (
                "scripts/pyinstaller-hooks/",
                ".github/actions/settings-build/",
                ".github/actions/electron-runtime-cache/",
            )
        )
    ):
        return DESKTOP_BUILD.copy()
    if path in {
        "clarify/desktop/qml_electron.py",
        "clarify/desktop/qml_app.py",
        "clarify/desktop/qt_shell.py",
        "tests/qt/test_electron_desktop.py",
    }:
        return {"desktop", "desktop_shell"}
    if path.startswith(("desktop/electron/", "desktop/electron-tests/")) or path in {
        "desktop/scripts/test-electron.mjs",
        "desktop/scripts/run-electron-smoke.mjs",
        "desktop/scripts/electron.test.cjs",
        "desktop/scripts/package-electron.mjs",
    }:
        return {"desktop_shell"}
    if path.startswith("desktop/"):
        # Page content cannot change Electron startup or native window ownership.
        # Shell entry points, pill, titlebar, platform adapter and public assets
        # retain the Windows lane below.
        if path.startswith("desktop/src/pages/") or path in {
            "desktop/src/styles/pages.css",
            "desktop/src/styles/snippets.css",
            "desktop/src/styles/provider-brands.css",
        }:
            return {"settings"}
        if path.startswith(
            ("desktop/src/", "desktop/tests/", "desktop/public/")
        ) or path in {
            "desktop/playwright.config.ts",
            "desktop/playwright.boot.config.ts",
        }:
            return {"settings", "desktop_shell"}
        if path.startswith("desktop/boot-tests/"):
            return {"settings", "desktop_shell"}
        return DESKTOP_BUILD.copy()
    if (
        path.startswith(
            ("assets/", "licenses/", "local_asr_manifests/", "distribution/", "extra/")
        )
        or path == "local_asr_manifest.json"
    ):
        return {"desktop", "package", "desktop_shell"}
    selected = {"server"} if path in SERVER_INPUTS else set()
    if path in SETTINGS_INPUTS:
        return selected | {"desktop", "settings", "desktop_shell"}
    if path.startswith(("clarify/", "tests/")) or (
        "/" not in path and PurePosixPath(path).suffix == ".py"
    ):
        return selected | {"desktop"}
    return selected or set(COMPONENTS)


def select_jobs(paths, repo=None):
    """Return the task closure. Invalid, unknown and linked inputs select all."""
    selected = set()
    for path in paths:
        if (
            not isinstance(path, str)
            or not path
            or "\\" in path
            or PurePosixPath(path).is_absolute()
            or ":" in path
            or any(part in {".", ".."} for part in path.split("/"))
        ):
            return set(JOBS)
        if repo is not None and any(
            (p.is_symlink() or getattr(p, "is_junction", lambda: False)())
            for p in (Path(repo) / path, *(Path(repo) / path).parents)
        ):
            return set(JOBS)
        old = path_components(path)
        mapping = {
            "desktop": {"static", "python", "qt"},
            "settings": {"settings_unit", "settings_browser"},
            "static": {"static"},
            "settings_unit": {"settings_unit"},
            **{
                name: {name}
                for name in (
                    "desktop_shell",
                    "package",
                    "installer",
                    "server",
                    "mobile",
                    "ios",
                    "audit",
                )
            },
        }
        for component in old:
            selected.update(mapping[component])
        if path.startswith("tests/policy/"):
            selected.add("static")
        if dependency_input(path):
            selected.add("audit")
    if "installer" in selected:
        selected.add("package")
    return selected


def release_component(repo, revision=None):
    """Read the selected metadata from the tested Git blob, or local candidate."""
    if revision:
        mode = subprocess.check_output(
            ["git", "-C", str(repo), "ls-tree", revision, "--", RELEASE_INTENT],
            timeout=30,
        )
        if not mode.startswith((b"100644 blob ", b"100755 blob ")):
            raise ValueError("Release intent must be a regular Git blob")
        raw = subprocess.check_output(
            ["git", "-C", str(repo), "show", f"{revision}:{RELEASE_INTENT}"], timeout=30
        )
    else:
        raw = (Path(repo) / RELEASE_INTENT).read_bytes()
    intent = json.loads(raw, object_pairs_hook=json_object)
    if (
        not isinstance(intent, dict)
        or type(intent.get("schema")) is not int
        or intent["schema"] != 2
        or intent.get("component") not in {"desktop", "mobile"}
    ):
        raise ValueError("Invalid release validation scope")
    return intent["component"]


def select_candidate(paths, repo, revision=None):
    """Keep release coverage explicit without adding unrelated client platforms."""
    from ci.tasks import release_jobs

    paths = set(paths)
    scopes = set()
    if RELEASE_INTENT in paths:
        scopes.add(release_component(repo, revision))
        paths.remove(RELEASE_INTENT)
    if "version.py" in paths:
        scopes.add("desktop")
    selected = select_jobs(paths, repo=repo)
    for scope in scopes:
        selected.update(release_jobs(scope))
    return selected


def explain(paths, selected, repo=None):
    """Explain paths that select jobs. This is diagnostic data, not authority."""
    reasons = {job: [] for job in sorted(selected)}
    for path in sorted(paths):
        for job in select_jobs([path], repo=repo) & set(selected):
            reasons[job].append(path)
    return reasons


def event_selection(repo, event_name, event, head):
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("CI head must be a complete commit SHA")

    def result(jobs, paths=(), reason=""):
        return {
            "jobs": sorted(jobs),
            "paths": sorted(paths),
            "reason": reason,
            "reasons": explain(paths, jobs, repo),
        }

    if event_name == "schedule":
        return result(JOBS, reason="Scheduled full validation")
    if event_name == "workflow_dispatch":
        scope = event.get("inputs", {}).get("scope", "full")
        if scope == "full":
            return result(JOBS, reason="Manual full validation")
        from ci.tasks import release_jobs

        return result(release_jobs(scope), reason=f"Manual {scope} release validation")
    if event_name not in {"pull_request", "push"}:
        raise ValueError("Unsupported validation event")
    try:
        base = (
            event["before"]
            if event_name == "push"
            else event["pull_request"]["base"]["sha"]
        )
        paths = changed_paths(repo, base, head)
        if git_links(repo, (base, head), paths):
            return result(
                JOBS, paths, "Linked validation inputs require full validation"
            )
        # Release scope is read only if metadata changed; ordinary edits need no intent.
        if RELEASE_INTENT in paths or "version.py" in paths:
            selected = select_candidate(paths, repo, head)
        else:
            selected = select_jobs(paths, repo=repo)
        if CATALOG_PATH in paths and native_catalog_unchanged(repo, base, head):
            other = select_jobs([p for p in paths if p != CATALOG_PATH], repo=repo)
            if "ios" not in other:
                selected.discard("ios")
        reason = "Affected validation"
        if selected == set(JOBS):
            reason = (
                "Full validation required by changed controls or unclassified paths"
            )
        return result(selected, paths, reason)
    except (KeyError, OSError, ValueError, subprocess.SubprocessError) as error:
        # An unavailable diff is a request for full validation, never no checks.
        return result(
            JOBS,
            reason=f"Full validation: cannot establish impact ({type(error).__name__})",
        )


def event_jobs(repo, event_name, event, head):
    return set(event_selection(repo, event_name, event, head)["jobs"])


def git_links(repo, revisions, paths, *, index=False):
    """Inspect removed links and the index; lstat alone cannot see either."""
    paths = sorted(paths)
    for offset in range(0, len(paths), 32):
        chunk = [":(literal)" + path for path in paths[offset : offset + 32]]
        commands = [["ls-tree", "-z", revision, "--", *chunk] for revision in revisions]
        if index:
            commands.append(["ls-files", "--stage", "-z", "--", *chunk])
        for args in commands:
            data = subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                check=True,
                timeout=30,
            ).stdout
            if any(entry.startswith(b"120000 ") for entry in data.split(b"\0")):
                return True
    return False


def runner_profile(provider="github", owner_type="User"):
    if not isinstance(provider, str) or provider not in {"github", "blacksmith"}:
        raise ValueError("CI_RUNNER_PROVIDER must be github or blacksmith")
    if provider == "blacksmith" and owner_type != "Organization":
        raise ValueError("Blacksmith requires a GitHub organization repository")
    return {
        "linux": "blacksmith-4vcpu-ubuntu-2404"
        if provider == "blacksmith"
        else "ubuntu-24.04",
        "windows": "windows-2025",
    }


def validate_ci_results(needs):
    expected = {"plan", "policy", *JOBS}
    if not isinstance(needs, dict) or set(needs) != expected:
        raise ValueError("CI results must contain exactly the declared jobs")
    plan = needs["plan"]
    if not isinstance(plan, dict) or plan.get("result") != "success":
        raise ValueError("The CI plan must succeed")
    flags = plan.get("outputs", {})
    if not isinstance(flags, dict):
        raise ValueError("CI plan outputs must be an object")
    for name in JOBS:
        if not isinstance(flags.get(name), str) or flags[name] not in {"true", "false"}:
            raise ValueError(f"Invalid plan output: {name}")
    for name, record in needs.items():
        required = name in {"plan", "policy"} or flags.get(name) == "true"
        allowed = {"success"} if required else {"success", "skipped"}
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("result"), str)
            or record["result"] not in allowed
        ):
            raise ValueError(f"Unsuccessful CI job: {name}")


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
