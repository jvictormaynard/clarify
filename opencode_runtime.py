"""Verified OpenCode runtime. Reuse a compatible copy or download on Connect.

Manifest source: registry.npmjs.org/@opencode/<package>/2.3.0, checked 2026-11-16.
Direct native npm packages need no npm, Node, admin rights or install scripts.
"""

from __future__ import annotations
import base64
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import platform
import shutil
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from provider_types import ProviderConfigurationError

VERSION = "2.3.0"
MANIFEST = {
    "linux": {
        "url": "https://registry.npmjs.org/@opencode/cli-linux-x64-baseline/-/cli-linux-x64-baseline-2.3.0.tgz",
        "integrity": "sha512-wIMo9anUJIVlnBJlGM0lB7n+jmFMstRwjN6Lw8+s0hp+HpA94LmVMDDkTg+iQqzcsatlJaHre39v8x+jGQErRQ==",
        "member": "package/bin/opencode",
    },
    "win32": {
        "url": "https://registry.npmjs.org/@opencode/cli-windows-x64-baseline/-/cli-windows-x64-baseline-2.3.0.tgz",
        "integrity": "sha512-hzYhXe+NOs7xctyjiOBuwBqJLvtkh2AHJflb+2p5XMzdmLFNqlIcwtE/byzD8LsTpgmrnb6m1m7k15muOFvReQ==",
        "member": "package/bin/opencode.exe",
    },
    "darwin": {
        "url": "https://registry.npmjs.org/@opencode/cli-darwin-arm64/-/cli-darwin-arm64-2.3.0.tgz",
        "integrity": "sha512-ey2HOWX2DK2YJrKta5a+pcvIlkiCyJJsN7NjkJZPsVg9TDXpQWE1OJLWVFqjxZcWNtaMjvKYlrlCY6g8Z2Lb+A==",
        "member": "package/bin/opencode",
    },
}
# Verified against npm's sha512 archive integrity before extracting the hash.
# https://registry.npmjs.org/@opencode/cli-windows-x64/-/cli-windows-x64-2.3.2.tgz
_WINDOWS_INSTALL_VERSION = "2.3.2"
_EXE_LIMIT = 300 * 1024 * 1024
_WINDOWS_INSTALL_SHA256 = (
    "5d52d86e2c3fd2c4d51cefc893f64c9ee66bc2e9535332195802f7c646b2a3a3"
)
MIT_NOTICE = 'MIT License\n\nCopyright (c) 2025 opencode\n\nPermission is hereby granted, free of charge, to any person obtaining a copy\nof this software and associated documentation files (the "Software"), to deal\nin the Software without restriction, including without limitation the rights\nto use, copy, modify, merge, publish, distribute, sublicense, and/or sell\ncopies of the Software, and to permit persons to whom the Software is\nfurnished to do so, subject to the following conditions:\n\nThe above copyright notice and this permission notice shall be included in all\ncopies or substantial portions of the Software.\n\nTHE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\nIMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\nFITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\nAUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\nLIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\nOUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\nSOFTWARE.\n'
_LOCK = threading.Lock()


def runtime_root():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "Clarify" / "runtimes" / "opencode" / VERSION


def supported():
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        return machine == "arm64"
    return sys.platform in MANIFEST and machine in {"x86_64", "amd64"}


def _windows_install_candidates():
    local = Path.home() / "AppData" / "Local"
    bases = dict.fromkeys((Path(os.environ.get("LOCALAPPDATA") or local), local))
    return (base / "Programs" / "OpenCode" / "bin" / "opencode.exe" for base in bases)


@lru_cache(maxsize=8)
def _external_sha256(path, identity):
    # Cache per file identity so frequent Settings snapshots avoid repeated reads.
    with path.open("rb") as exe:
        return hashlib.file_digest(exe, "sha256").hexdigest()


def _matches_windows_runtime(path):
    try:
        stat = path.stat()
        if not path.is_file() or stat.st_size > _EXE_LIMIT:
            return False
        identity = (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )
        return _external_sha256(path, identity) == _WINDOWS_INSTALL_SHA256
    except OSError:
        return False


def _verified_windows_install():
    return next(
        (
            path
            for path in _windows_install_candidates()
            if _matches_windows_runtime(path)
        ),
        None,
    )


def _adopted_windows_path():
    return runtime_root().with_name(_WINDOWS_INSTALL_VERSION) / "opencode.exe"


def executable():
    if not supported():
        return None
    path = runtime_root() / ("opencode.exe" if os.name == "nt" else "opencode")
    if path.is_file():
        return str(path)
    if sys.platform == "win32":
        adopted = _adopted_windows_path()
        if _matches_windows_runtime(adopted):
            return str(adopted)
    return None


def available():
    return bool(
        executable()
        or (sys.platform == "win32" and supported() and _verified_windows_install())
    )


def _adopt_windows_runtime(source, check):
    path = _adopted_windows_path()
    try:
        path.parent.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".reuse-", dir=path.parent.parent
        ) as directory:
            staged = Path(directory) / "opencode.exe"
            digest = hashlib.sha256()
            size = 0
            with source.open("rb") as incoming, staged.open("wb") as outgoing:
                while chunk := incoming.read(1024 * 1024):
                    check()
                    size += len(chunk)
                    if size > _EXE_LIMIT:
                        raise ValueError("Runtime size limit")
                    digest.update(chunk)
                    outgoing.write(chunk)
            if digest.hexdigest() != _WINDOWS_INSTALL_SHA256:
                raise ValueError("Runtime integrity mismatch")
            check()
            path.parent.mkdir(exist_ok=True)
            (path.parent / "LICENSE.txt").write_text(MIT_NOTICE, encoding="utf-8")
            os.replace(staged, path)
    except (OSError, ValueError) as error:
        raise ProviderConfigurationError(
            "opencode", "Could not reuse the installed OpenCode runtime. Retry Connect."
        ) from error
    return str(path)


@contextmanager
def _installation_lock(check):
    while not _LOCK.acquire(timeout=0.1):
        check()
    try:
        check()
        yield
    finally:
        _LOCK.release()


def install(cancel_token=None):
    """Verify a bounded archive before extracting its one executable atomically."""

    def check():
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()

    if not supported():
        raise ProviderConfigurationError(
            "opencode",
            "OpenCode installation supports Windows and Linux x64 and Apple Silicon Macs.",
        )
    with _installation_lock(check):
        check()
        existing = executable()
        if existing:
            return existing
        if sys.platform == "win32" and (installed := _verified_windows_install()):
            return _adopt_windows_runtime(installed, check)
        spec = MANIFEST[sys.platform]
        root = runtime_root()
        root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".install-", dir=root.parent
        ) as temporary:
            stage = Path(temporary)
            archive = stage / "runtime.tgz"
            digest = hashlib.sha512()
            size = 0
            started = time.monotonic()
            try:
                with (
                    urllib.request.urlopen(spec["url"], timeout=15) as response,
                    archive.open("wb") as target,
                ):
                    if response.geturl() != spec["url"]:
                        raise ValueError("Unexpected runtime redirect")
                    while chunk := response.read(1024 * 1024):
                        check()
                        size += len(chunk)
                        if size > 160 * 1024 * 1024 or time.monotonic() - started > 180:
                            raise ValueError("Runtime download limit")
                        digest.update(chunk)
                        target.write(chunk)
                if (
                    "sha512-" + base64.b64encode(digest.digest()).decode()
                    != spec["integrity"]
                ):
                    raise ValueError("Runtime integrity mismatch")
                with tarfile.open(archive, "r:gz") as bundle:
                    member = bundle.getmember(spec["member"])
                    if not member.isfile() or member.size > _EXE_LIMIT:
                        raise ValueError("Invalid runtime archive")
                    destination = stage / Path(spec["member"]).name
                    with (
                        bundle.extractfile(member) as source,
                        destination.open("wb") as target,
                    ):
                        shutil.copyfileobj(source, target)
                destination.chmod(0o700)
                check()
                root.mkdir(exist_ok=True)
                (root / "LICENSE.txt").write_text(MIT_NOTICE, encoding="utf-8")
                os.replace(destination, root / destination.name)
            except (OSError, ValueError, KeyError, tarfile.TarError) as error:
                raise ProviderConfigurationError(
                    "opencode",
                    "OpenCode installation failed. Check the connection and disk space, then retry Connect.",
                ) from error
        return executable()
