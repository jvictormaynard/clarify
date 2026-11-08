#!/usr/bin/env python3
"""Check project-local skill metadata, references, and pinned upstream inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
LINK = re.compile(r"\[[^\]\n]+\]\(([^)\n]+)\)")


def scalar(value: str) -> str | bool:
    """Read the simple scalar form used by this project's skill metadata."""
    value = value.strip()
    if value.startswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if value in ("true", "false"):
        return value == "true"
    return value


def frontmatter(path: Path) -> dict[str, str | bool]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("missing YAML frontmatter")
    header = text[4:].split("\n---\n", 1)[0]
    fields: dict[str, str | bool] = {}
    for line in header.splitlines():
        if not line or line.startswith((" ", "\t", "#")):
            continue
        key, separator, value = line.partition(":")
        if not separator or key in fields:
            raise ValueError(f"invalid or duplicate field: {key}")
        fields[key] = scalar(value)
    for key in ("name", "description"):
        value = fields.get(key)
        if not isinstance(value, str) or not value.strip() or value in ("|", ">"):
            raise ValueError(f"{key} must be a nonempty single-line scalar")
    return fields


def local_links(path: Path, repo: Path) -> list[str]:
    errors = []
    # Examples in code fences are not navigable document references.
    text = re.sub(
        r"(?ms)^\x60\x60\x60[^\n]*\n.*?^\x60\x60\x60\s*$",
        "",
        path.read_text(encoding="utf-8"),
    )
    for match in LINK.finditer(text):
        target = match.group(1).strip().strip("<>")
        parsed = urlsplit(target)
        if parsed.scheme in ("http", "https", "mailto", "codex") or parsed.netloc:
            continue
        if parsed.scheme:
            errors.append(
                f"{path.relative_to(repo)}: unsupported local reference: {target}"
            )
            continue
        if not parsed.path:
            continue
        resolved = (path.parent / unquote(parsed.path)).resolve()
        if not resolved.is_relative_to(repo):
            errors.append(
                f"{path.relative_to(repo)}: reference escapes project: {target}"
            )
        elif not resolved.exists():
            errors.append(f"{path.relative_to(repo)}: missing reference: {target}")
    return errors


def check(repo: Path, upstream: Path | None = None) -> list[str]:
    repo = repo.resolve()
    base = repo / ".agents" / "skills"
    if base.is_symlink() or not base.resolve().is_relative_to(repo):
        return ["skill directory escapes the project"]
    errors: list[str] = []
    try:
        manifest = json.loads((base / "upstream-lock.json").read_text(encoding="utf-8"))
        if manifest["schema_version"] != 1:
            raise ValueError("unsupported manifest schema")
        if manifest["repository"] != "https://github.com/mattpocock/skills":
            raise ValueError("unexpected upstream repository")
        if not re.fullmatch(r"[0-9a-f]{40}", manifest["commit"]):
            raise ValueError("upstream commit must be an immutable SHA")
        entries = manifest["skills"]
        projects = manifest["project_skills"]
        if (
            not isinstance(entries, list)
            or not entries
            or not isinstance(projects, list)
        ):
            raise ValueError("invalid skill inventory")
        expected = set(projects)
        if len(expected) != len(projects):
            raise ValueError("duplicate project skill")
        source_names: set[str] = set()
        for entry in entries:
            name = entry["name"]
            if entry["bucket"] not in (
                "engineering",
                "productivity",
                "misc",
                "in-progress",
            ):
                raise ValueError(f"invalid upstream bucket: {name}")
            if not NAME.fullmatch(name) or name in source_names:
                raise ValueError(f"invalid or duplicate upstream skill: {name}")
            source_names.add(name)
            if entry["source_path"] != f"skills/{entry['bucket']}/{name}":
                raise ValueError(f"invalid upstream path: {name}")
            if entry["decision"] not in ("adapted", "excluded") or not entry["reason"]:
                raise ValueError(f"missing audit decision: {name}")
            files = entry["source_files"]
            if "SKILL.md" not in files or any(
                not DIGEST.fullmatch(v) for v in files.values()
            ):
                raise ValueError(f"invalid source digests: {name}")
            if entry["decision"] == "adapted":
                if entry["local_skill"] != name or name in expected:
                    raise ValueError(f"invalid or duplicate local mapping: {name}")
                expected.add(name)
            elif entry["local_skill"] is not None:
                raise ValueError(f"excluded skill has a local mapping: {name}")
        if any(not NAME.fullmatch(name) for name in expected):
            raise ValueError("invalid project skill name")
        license_path = (base / manifest["license_file"]).resolve()
        if not license_path.is_relative_to(base.resolve()):
            raise ValueError("license path escapes project skills")
        if (
            hashlib.sha256(license_path.read_bytes()).hexdigest()
            != manifest["license_sha256"]
        ):
            raise ValueError("upstream license is missing or modified")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"skill inventory: {exc}"]

    for path in base.rglob("*"):
        if path.is_symlink():
            errors.append(
                f"{path.relative_to(repo)}: keep project skills as regular files"
            )

    found: set[str] = set()
    for path in sorted(base.rglob("SKILL.md")):
        try:
            fields = frontmatter(path)
            name = str(fields["name"])
            if not NAME.fullmatch(name) or len(name) >= 64 or name != path.parent.name:
                raise ValueError("skill name must match its directory and naming rules")
            if len(str(fields["description"])) > 1024:
                raise ValueError("skill description exceeds 1024 characters")
            if name in found or path != base / name / "SKILL.md":
                raise ValueError("duplicate or nested skill entrypoint")
            found.add(name)
            metadata = path.parent / "agents" / "openai.yaml"
            ui = metadata.read_text(encoding="utf-8")
            policies = re.findall(
                r"^  allow_implicit_invocation: (true|false)\s*$", ui, re.M
            )
            if "allow_implicit_invocation" in ui and len(policies) != 1:
                raise ValueError("invalid invocation policy")
            if fields.get("disable-model-invocation") is True and policies != ["false"]:
                raise ValueError("explicit-only skill conflicts with invocation policy")
            for document in path.parent.rglob("*.md"):
                errors.extend(local_links(document, repo))
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"{path.relative_to(repo)}: {exc}")

    if found != expected:
        errors.append(
            f"skill inventory mismatch: missing={sorted(expected - found)}, unexpected={sorted(found - expected)}"
        )

    if upstream is not None:
        upstream = upstream.resolve()
        result = subprocess.run(
            ["git", "-C", str(upstream), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode or result.stdout.strip() != manifest["commit"]:
            errors.append("upstream checkout does not match the pinned commit")
        actual = {
            p.parent.relative_to(upstream).as_posix()
            for p in (upstream / "skills").rglob("SKILL.md")
        }
        recorded = {entry["source_path"] for entry in entries}
        if actual != recorded:
            errors.append("upstream audit does not cover every SKILL.md")
        for entry in entries:
            folder = upstream / entry["source_path"]
            actual_files = {
                p.relative_to(folder).as_posix(): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in folder.rglob("*")
                if p.is_file()
            }
            if actual_files != entry["source_files"]:
                errors.append(f"upstream source digest mismatch: {entry['name']}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--upstream",
        type=Path,
        help="Optional checkout for full source/commit verification",
    )
    args = parser.parse_args()
    errors = check(args.repo, args.upstream)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Project skills: metadata, references, scope, license, and inventory passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
