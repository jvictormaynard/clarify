"""Pinned, per-user OpenCode runtime. Download only on explicit Connect.

Manifest source: registry.npmjs.org/@opencode/<package>/2.3.0, checked 2026-11-16.
Direct native npm packages need no npm, Node, admin rights or install scripts.
"""

from __future__ import annotations
import base64
from contextlib import contextmanager
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
}
MIT_NOTICE = 'MIT License\n\nCopyright (c) 2025 opencode\n\nPermission is hereby granted, free of charge, to any person obtaining a copy\nof this software and associated documentation files (the "Software"), to deal\nin the Software without restriction, including without limitation the rights\nto use, copy, modify, merge, publish, distribute, sublicense, and/or sell\ncopies of the Software, and to permit persons to whom the Software is\nfurnished to do so, subject to the following conditions:\n\nThe above copyright notice and this permission notice shall be included in all\ncopies or substantial portions of the Software.\n\nTHE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\nIMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\nFITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\nAUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\nLIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\nOUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\nSOFTWARE.\n'
_LOCK = threading.Lock()


def runtime_root():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "Clarify" / "runtimes" / "opencode" / VERSION


def supported():
    return sys.platform in MANIFEST and platform.machine().lower() in {
        "x86_64",
        "amd64",
    }


def executable():
    if not supported():
        return None
    path = runtime_root() / ("opencode.exe" if os.name == "nt" else "opencode")
    return str(path) if path.is_file() else None


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
            "opencode", "OpenCode installation supports Windows and Linux x64 only."
        )
    with _installation_lock(check):
        check()
        if executable():
            return executable()
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
                    if not member.isfile() or member.size > 300 * 1024 * 1024:
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
