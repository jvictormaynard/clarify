"""Select component validation from the complete Git change range."""

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess


COMPONENTS = ("desktop", "server", "ios")
SHARED_INPUTS = {
    "workflow_provider.py",
    "scripts/sync_locales.py",
    "mobile/scripts/sync-prompts.py",
    "mobile/modules/clarify-core/ios/RewritePrompt.swift",
    "scripts/delivery_policy.py",
    "tests/test_delivery_policy.py",
    ".github/workflows/ci.yml",
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
}


def documentation(path: str) -> bool:
    return path.startswith(("docs/", ".agents/")) or PurePosixPath(
        path
    ).suffix.lower() in {".md", ".rst"}


def affected_components(paths: list[str]) -> dict[str, bool]:
    selected = dict.fromkeys(COMPONENTS, False)
    for path in paths:
        if documentation(path):
            continue
        if path.startswith("shared/") or path in SHARED_INPUTS:
            selected.update(dict.fromkeys(COMPONENTS, True))
            continue
        if path.startswith("server/") or path in SERVER_INPUTS:
            selected["server"] = True
        if path.startswith("mobile/") or path in IOS_INPUTS:
            selected["ios"] = True
        if (
            path.startswith(("desktop/", "clarify/", "distribution/", "extra/"))
            or "/" not in path
            and PurePosixPath(path).suffix in {".py", ".json", ".txt", ".spec"}
            or path.startswith(
                ("scripts/", "tests/", ".github/actions/settings-build/")
            )
            or path == ".github/workflows/community-release.yml"
        ):
            selected["desktop"] = True
    return selected


def changed_paths(repo: Path, base: str, head: str) -> list[str]:
    for revision in (base, head):
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
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
    )
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


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
    return affected_components(changed_paths(repo, base, head))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
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


if __name__ == "__main__":
    main()
