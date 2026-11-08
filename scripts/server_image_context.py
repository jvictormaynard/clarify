"""Prepare and verify the fixed server recovery image without runtime credentials."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import tempfile


@dataclass(frozen=True)
class SourcePin:
    source: str
    archive_sha256: str
    file_count: int
    critical_hashes: dict[str, str]


PIN = SourcePin(
    source="ced75d817decd55e7ed6f350e34e008b59f9cb26",
    archive_sha256="7ec00c023c8fa627dfbbca0064a5605d4b022b793ff71bebad19b6340042dca9",
    file_count=49,
    critical_hashes={
        "server/cloud/service/api.py": "b5652f6295de72f472d94f7c515f33538403708e7b914c3f0ac942e8a343f2a1",
        "server/cloud/service/groq.py": "0e1bbca2bf5004b3217ce1d43359c41d0053e422d4e3df8d60fa8df4ed87d784",
    },
)
ARCHIVE_PATHS = (".dockerignore", "server", "shared", "dictionary_snippets.py")
IMAGE_REPOSITORY = "ghcr.io/jvictormaynard/clarify-server"
IMAGE_OMISSIONS = {".dockerignore", "server/.env.example"}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _allowed_path(name: str) -> bool:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or path.as_posix() != name
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        return False
    if not (name in ARCHIVE_PATHS or name.startswith(("server/", "shared/"))):
        return False
    private = {
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        "recordings",
        "account-data",
        "config.json",
        "account.json",
        "secrets.json",
    }
    for part in path.parts:
        if (
            part.lower() in private
            or part.lower().startswith(("account-secrets", "secrets."))
            or ".sqlite3" in part.lower()
        ):
            return False
        if part.lower().startswith(".env") and name != "server/.env.example":
            return False
    return True


def archive_files(data: bytes, pin: SourcePin = PIN) -> dict[str, bytes]:
    if len(data) > 2 * 1024 * 1024 or _digest(data) != pin.archive_sha256:
        raise ValueError("Archive differs from the reviewed Git archive")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        if archive.pax_headers.get("comment") != pin.source:
            raise ValueError("Archive is not from the pinned commit")
        files: dict[str, bytes] = {}
        seen: set[str] = set()
        for member in archive.getmembers():
            name = member.name.rstrip("/") if member.isdir() else member.name
            if not _allowed_path(name) or name in seen:
                raise ValueError("Unexpected or duplicate archive path")
            seen.add(name)
            if member.isdir():
                continue
            if not member.isreg() or member.issparse() or member.size > 2 * 1024 * 1024:
                raise ValueError("Archive contains a non-regular source")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("Archive source is unavailable")
            payload = stream.read()
            if len(payload) != member.size:
                raise ValueError("Archive source is incomplete")
            files[name] = payload
    if len(files) != pin.file_count:
        raise ValueError("Archive file count differs from the reviewed source")
    if any(
        _digest(files.get(name, b"")) != value
        for name, value in pin.critical_hashes.items()
    ):
        raise ValueError("Reviewed server correction differs")
    return files


def make_manifest(files: dict[str, bytes], pin: SourcePin = PIN) -> dict:
    hashes = {name: _digest(data) for name, data in sorted(files.items())}
    return {
        "schema_version": 1,
        "source": pin.source,
        "archive_sha256": pin.archive_sha256,
        "files": hashes,
        "image_files": {
            name: value for name, value in hashes.items() if name not in IMAGE_OMISSIONS
        },
    }


def git_archive(repo: Path, pin: SourcePin = PIN) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", pin.source, *ARCHIVE_PATHS],
        capture_output=True,
        timeout=30,
        check=True,
    )
    return result.stdout


def prepare(repo: Path, context: Path, manifest: Path, pin: SourcePin = PIN) -> dict:
    files = archive_files(git_archive(repo, pin), pin)
    if (
        context.exists()
        or manifest.exists()
        or manifest.resolve().is_relative_to(context.resolve())
    ):
        raise ValueError("Use a new context and a separate new manifest")
    context.mkdir(parents=True)
    for name, data in files.items():
        destination = context / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(data)
        destination.chmod(0o644)
    for directory in (context, *(path for path in context.rglob("*") if path.is_dir())):
        directory.chmod(0o755)
    value = make_manifest(files, pin)
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return value


def validated_manifest(repo: Path, manifest: Path, pin: SourcePin = PIN) -> dict:
    expected = make_manifest(archive_files(git_archive(repo, pin), pin), pin)
    if json.loads(manifest.read_text(encoding="utf-8")) != expected:
        raise ValueError("Manifest differs from the pinned Git archive")
    return expected


def verify_tree(directory: Path, expected: dict[str, str]) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Source directory is unavailable or redirected")
    actual = {}
    for path in directory.rglob("*"):
        kind = path.lstat().st_mode
        if stat.S_ISDIR(kind):
            continue
        if not stat.S_ISREG(kind):
            raise ValueError("Source tree contains a non-regular file")
        actual[path.relative_to(directory).as_posix()] = _digest(path.read_bytes())
    if actual != expected:
        raise ValueError("Source tree has missing, changed, or extra files")


def _check_image(image: str) -> None:
    if not re.fullmatch(
        re.escape(IMAGE_REPOSITORY) + ":recovery-" + PIN.source + r"-[0-9]+-[0-9]+",
        image,
    ):
        raise ValueError("Unexpected image repository, source, or unique run tag")


def _docker(*args: str) -> str:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=60, check=True
    )
    return result.stdout.strip()


def verify_image(image: str, expected: dict[str, str]) -> None:
    _check_image(image)
    container = _docker("create", "--entrypoint", "true", image)
    if not re.fullmatch("[0-9a-f]{64}", container):
        raise ValueError("Docker returned an invalid container identity")
    try:
        with tempfile.TemporaryDirectory(prefix="clarify-server-image-") as temporary:
            _docker("cp", container + ":/app", temporary)
            verify_tree(Path(temporary) / "app", expected)
    finally:
        _docker("rm", "-f", container)


def record_image(
    image: str, manifest: dict, manifest_path: Path, workflow_sha: str
) -> dict:
    _check_image(image)
    if not re.fullmatch("[0-9a-f]{40}", workflow_sha):
        raise ValueError("Invalid workflow source identity")
    candidates = json.loads(
        _docker("image", "inspect", "--format", "{{json .RepoDigests}}", image)
    )
    matches = [
        item
        for item in candidates
        if isinstance(item, str)
        and re.fullmatch(re.escape(IMAGE_REPOSITORY) + "@sha256:[0-9a-f]{64}", item)
    ]
    if len(matches) != 1:
        raise ValueError("Published image digest is unavailable or ambiguous")
    image_id = _docker("image", "inspect", "--format", "{{.Id}}", image)
    if not re.fullmatch("sha256:[0-9a-f]{64}", image_id):
        raise ValueError("Invalid local image identity")
    platform = _docker(
        "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", image
    )
    if platform != "linux/amd64":
        raise ValueError("Published image must be linux/amd64")
    return {
        "image": image,
        "digest_reference": matches[0],
        "image_id": image_id,
        "os": "linux",
        "architecture": "amd64",
        "source": manifest["source"],
        "archive_sha256": manifest["archive_sha256"],
        "manifest_sha256": _digest(manifest_path.read_bytes()),
        "workflow_sha": workflow_sha,
        "source_files": len(manifest["files"]),
        "image_files": len(manifest["image_files"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("prepare", "verify-context", "verify-image", "record")
    )
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--image")
    parser.add_argument("--workflow-sha")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.context is None:
            parser.error("--context is required")
        prepare(args.repo, args.context, args.manifest)
        return
    manifest = validated_manifest(args.repo, args.manifest)
    if args.command == "verify-context":
        if args.context is None:
            parser.error("--context is required")
        verify_tree(args.context, manifest["files"])
    elif args.command == "verify-image":
        if not args.image:
            parser.error("--image is required")
        verify_image(args.image, manifest["image_files"])
    else:
        if not args.image or not args.workflow_sha or args.output is None:
            parser.error("--image, --workflow-sha and --output are required")
        metadata = record_image(args.image, manifest, args.manifest, args.workflow_sha)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(metadata, stream, sort_keys=True, indent=2)
            stream.write("\n")


if __name__ == "__main__":
    main()
