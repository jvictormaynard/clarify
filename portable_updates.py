"""Signed portable releases. Importing this module has no external effects."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import threading
from urllib.parse import urljoin, urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import requests


MANIFEST_ASSET = "Clarify-portable-update.json"
SIGNATURE_ASSET = MANIFEST_ASSET + ".sig"
MAX_MANIFEST_BYTES = 16384
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
_REDIRECT_HOSTS = frozenset(
    {
        "github.com",
        "api.github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
    }
)


class PortableUpdateError(RuntimeError):
    """An update cannot be trusted or safely applied."""


@dataclass(frozen=True)
class PortableUpdatePolicy:
    public_key: bytes
    repository: str = "jvictormaynard/clarify"
    maximum_download_bytes: int = 268435456

    def __post_init__(self):
        if (
            len(self.public_key) != 32
            or self.repository != "jvictormaynard/clarify"
            or type(self.maximum_download_bytes) is not int
            or not 0 < self.maximum_download_bytes <= 268435456
        ):
            raise PortableUpdateError("A política de atualização é inválida.")


@dataclass(frozen=True)
class PortableRelease:
    version: str
    tag: str
    source_sha: str
    url: str
    sha256: str
    size: int
    manifest: bytes
    signature: bytes


def version_tuple(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or len(value) > 32 or not _VERSION.fullmatch(value):
        raise PortableUpdateError("A versão da atualização é inválida.")
    return tuple(int(part) for part in value.split("."))


def load_policy() -> PortableUpdatePolicy:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        payload = json.loads(
            (root / "distribution/portable-update-policy.json").read_text("utf-8")
        )
        key = base64.b64decode(payload["public_key"], validate=True)
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != 1
            or payload["channel"] != "stable"
            or payload["algorithm"] != "Ed25519"
        ):
            raise ValueError("Invalid policy")
        return PortableUpdatePolicy(
            key, payload["repository"], payload["maximum_download_bytes"]
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PortableUpdateError(
            "A política de atualização não está disponível."
        ) from error


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate manifest field")
        result[key] = value
    return result


def verify_manifest(
    data: bytes,
    signature: bytes,
    policy: PortableUpdatePolicy,
    current_version: str,
    expected_tag: str | None = None,
) -> PortableRelease:
    """Authenticate exact bytes before interpreting any release field."""
    try:
        if not 0 < len(data) <= MAX_MANIFEST_BYTES or len(signature) != 64:
            raise ValueError("Invalid signed document size")
        Ed25519PublicKey.from_public_bytes(policy.public_key).verify(signature, data)
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
        fields = {
            "schema_version",
            "repository",
            "channel",
            "version",
            "tag",
            "source_sha",
            "asset",
            "url",
            "sha256",
            "size",
        }
        if not isinstance(payload, dict) or set(payload) != fields:
            raise ValueError("Unexpected manifest fields")
        version = payload["version"]
        if version_tuple(version) <= version_tuple(current_version):
            raise ValueError("Update is not newer")
        tag = "v" + version
        url = f"https://github.com/{policy.repository}/releases/download/{tag}/Clarify.exe"
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != 1
            or payload["repository"] != policy.repository
            or payload["channel"] != "stable"
            or payload["tag"] != tag
            or payload["asset"] != "Clarify.exe"
            or payload["url"] != url
            or expected_tag not in (None, tag)
        ):
            raise ValueError("Unexpected release identity")
        if (
            not isinstance(payload["source_sha"], str)
            or not re.fullmatch(r"[a-f0-9]{40}", payload["source_sha"])
            or not isinstance(payload["sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", payload["sha256"])
            or type(payload["size"]) is not int
            or not 0 < payload["size"] <= policy.maximum_download_bytes
        ):
            raise ValueError("Invalid binary identity")
        return PortableRelease(
            version,
            tag,
            payload["source_sha"],
            url,
            payload["sha256"],
            payload["size"],
            data,
            signature,
        )
    except (InvalidSignature, ValueError, KeyError, TypeError, UnicodeError) as error:
        raise PortableUpdateError(
            "A assinatura ou os dados da atualização são inválidos."
        ) from error


def verify_binary(path: Path, release: PortableRelease) -> None:
    """Recheck the bytes immediately before replacement, not only on download."""
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != release.size:
            raise ValueError("Unexpected binary file")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("Not a Windows executable")
            stream.seek(0)
            for chunk in iter(lambda: stream.read(1048576), b""):
                digest.update(chunk)
        if digest.hexdigest() != release.sha256:
            raise ValueError("Binary checksum mismatch")
    except (OSError, ValueError) as error:
        raise PortableUpdateError(
            "O arquivo da atualização está incompleto ou foi alterado."
        ) from error


class PortableReleaseTransport:
    """Bounded HTTPS requests to the canonical GitHub release endpoints."""

    def __init__(self, policy: PortableUpdatePolicy, session_factory=requests.Session):
        self.policy = policy
        self._session_factory = session_factory

    def _read(self, url, maximum, cancel, consume):
        with self._session_factory() as session:
            # Public release checks must not read .netrc credentials or inherit
            # provider authentication from a private session.
            session.trust_env = False
            session.auth = None
            response = None
            try:
                for _ in range(6):
                    parsed = urlsplit(url)
                    if (
                        parsed.scheme != "https"
                        or parsed.hostname not in _REDIRECT_HOSTS
                        or parsed.username
                        or parsed.password
                        or parsed.port not in (None, 443)
                    ):
                        raise PortableUpdateError(
                            "O endereço da atualização é inválido."
                        )
                    if cancel.is_set():
                        raise PortableUpdateError("Atualização cancelada.")
                    response = session.get(
                        url,
                        stream=True,
                        allow_redirects=False,
                        timeout=(5, 30),
                        headers={
                            "Accept-Encoding": "identity",
                            "User-Agent": "Clarify-Portable-Updater",
                        },
                    )
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        response.close()
                        response = None
                        if not location:
                            raise PortableUpdateError(
                                "O endereço da atualização é inválido."
                            )
                        url = urljoin(url, location)
                        continue
                    if response.status_code != 200:
                        raise PortableUpdateError(
                            "Não foi possível obter a atualização. Tente novamente."
                        )
                    length = response.headers.get("Content-Length")
                    if length is not None and (
                        not length.isdigit() or int(length) > maximum
                    ):
                        raise PortableUpdateError(
                            "O download excede o tamanho permitido."
                        )
                    total = 0
                    for chunk in response.iter_content(chunk_size=65536):
                        if cancel.is_set():
                            raise PortableUpdateError("Atualização cancelada.")
                        total += len(chunk)
                        if total > maximum:
                            raise PortableUpdateError(
                                "O download excede o tamanho permitido."
                            )
                        if chunk:
                            consume(chunk, total)
                    return
                raise PortableUpdateError(
                    "A atualização excedeu o limite de redirecionamentos."
                )
            except (requests.RequestException, ValueError) as error:
                raise PortableUpdateError(
                    "Não foi possível obter a atualização. Tente novamente."
                ) from error
            finally:
                if response is not None:
                    response.close()

    def _bytes(self, url, maximum, cancel):
        chunks = []
        self._read(url, maximum, cancel, lambda chunk, _: chunks.append(chunk))
        return b"".join(chunks)

    def latest(
        self, current_version: str, cancel: threading.Event
    ) -> PortableRelease | None:
        try:
            metadata = json.loads(
                self._bytes(
                    f"https://api.github.com/repos/{self.policy.repository}/releases/latest",
                    524288,
                    cancel,
                )
            )
            if (
                not isinstance(metadata, dict)
                or metadata.get("draft") is not False
                or metadata.get("prerelease") is not False
            ):
                raise ValueError("Not a published stable release")
            tag = metadata["tag_name"]
            if not isinstance(tag, str) or not tag.startswith("v"):
                raise ValueError("Invalid tag")
            if version_tuple(tag[1:]) <= version_tuple(current_version):
                return None
            assets = metadata["assets"]
            if not isinstance(assets, list):
                raise ValueError("Invalid assets")
            for name in (MANIFEST_ASSET, SIGNATURE_ASSET, "Clarify.exe"):
                found = [
                    asset
                    for asset in assets
                    if isinstance(asset, dict)
                    and asset.get("name") == name
                    and asset.get("state") == "uploaded"
                ]
                if len(found) != 1:
                    raise ValueError("Missing or duplicate authenticated asset")
            base = (
                f"https://github.com/{self.policy.repository}/releases/download/{tag}/"
            )
            release = verify_manifest(
                self._bytes(base + MANIFEST_ASSET, MAX_MANIFEST_BYTES, cancel),
                self._bytes(base + SIGNATURE_ASSET, 64, cancel),
                self.policy,
                current_version,
                tag,
            )
            executable = next(
                asset
                for asset in assets
                if isinstance(asset, dict) and asset.get("name") == "Clarify.exe"
            )
            if (
                executable.get("size") != release.size
                or executable.get("digest", "sha256:" + release.sha256)
                != "sha256:" + release.sha256
            ):
                raise ValueError("GitHub asset differs from manifest")
            return release
        except (ValueError, KeyError, TypeError) as error:
            raise PortableUpdateError(
                "A versão publicada não contém uma atualização verificável."
            ) from error

    def download(
        self,
        release,
        directory: Path,
        cancel: threading.Event,
        progress=lambda value: None,
    ) -> Path:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.is_symlink():
            raise PortableUpdateError("A pasta da atualização é inválida.")
        target = directory / "Clarify.exe"
        partial = directory / "Clarify.exe.part"
        partial_created = False
        try:
            with partial.open("xb") as stream:
                partial_created = True

                def consume(chunk, total):
                    stream.write(chunk)
                    progress(min(100, int(total * 100 / release.size)))

                self._read(release.url, release.size, cancel, consume)
                stream.flush()
                os.fsync(stream.fileno())
            verify_binary(partial, release)
            if cancel.is_set():
                raise PortableUpdateError("Atualização cancelada.")
            os.replace(partial, target)
            (directory / MANIFEST_ASSET).write_bytes(release.manifest)
            (directory / SIGNATURE_ASSET).write_bytes(release.signature)
            return target
        except OSError as error:
            raise PortableUpdateError(
                "Não foi possível salvar a atualização."
            ) from error
        finally:
            if partial_created:
                partial.unlink(missing_ok=True)


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def replace_and_restart(
    release, candidate, target, nonce, original_sha, launch, accept, replace=os.replace
):
    """Apply after parent exit. ``accept`` must stop a failed child before returning.

    Stage on the installation volume so both replacements remain atomic even
    when the download cache and executable are on different drives.
    """
    target, candidate = Path(target), Path(candidate)
    verify_binary(candidate, release)
    if (
        not re.fullmatch(r"[a-f0-9]{32}", nonce)
        or target.is_symlink()
        or not target.is_file()
        or file_sha256(target) != original_sha
    ):
        raise PortableUpdateError("A instalação mudou durante a atualização.")
    stage = target.parent / (".clarify-update-" + nonce + ".exe")
    backup = target.with_name(target.name + ".previous-" + nonce)
    if backup.exists() or backup.is_symlink():
        raise PortableUpdateError("A cópia de recuperação já existe.")
    staged = moved = False
    try:
        with candidate.open("rb") as source, stage.open("xb") as output:
            staged = True
            shutil.copyfileobj(source, output, 1048576)
            output.flush()
            os.fsync(output.fileno())
        verify_binary(stage, release)
        if file_sha256(target) != original_sha:
            raise PortableUpdateError("A instalação mudou durante a atualização.")
        replace(target, backup)
        moved = True
        replace(stage, target)
        if not accept(launch(target)):
            raise PortableUpdateError("A nova versão não iniciou corretamente.")
        return backup
    except Exception as error:
        failure = PortableUpdateError(
            "A atualização falhou. A versão anterior foi preservada."
        )
        failure.restarted_previous = False
        if moved:
            try:
                replace(backup, target)
                launch(target)
                failure.restarted_previous = True
            except OSError:
                # Keep the original backup intact if Windows still holds the
                # new target. The platform adapter records the recovery path.
                pass
        raise failure from error
    finally:
        if staged:
            try:
                stage.unlink(missing_ok=True)
            except OSError:
                pass
