"""Windows parent verification, graceful restart, and portable update recovery.

The helper is a copy of the installed executable. It never loads a profile,
registers hotkeys, starts audio, or changes credentials. All launch arguments
are fixed lists; no shell interprets downloaded metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from portable_updates import (
    MANIFEST_ASSET,
    SIGNATURE_ASSET,
    PortableUpdateError,
    file_sha256,
    load_policy,
    replace_and_restart,
    verify_binary,
    verify_manifest,
)


RECEIPT_ENV = "CLARIFY_UPDATE_RECEIPT"


def is_portable_installation():
    """Do not replace an MSI-owned file outside Windows Installer's transaction."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Clarify") as key:
            location, kind = winreg.QueryValueEx(key, "InstallLocation")
        if kind != winreg.REG_SZ or not isinstance(location, str):
            return False
        return Path(location).resolve() != Path(sys.executable).resolve().parent
    except FileNotFoundError:
        return True
    except OSError:
        return False


def update_cache_root() -> Path:
    if sys.platform != "win32" or not os.environ.get("LOCALAPPDATA"):
        raise PortableUpdateError("A atualização portátil requer Windows.")
    return Path(os.environ["LOCALAPPDATA"]) / "Clarify" / "updates"


def _document(path):
    if path.is_symlink() or path.stat().st_size > 16384:
        raise PortableUpdateError("O plano da atualização é inválido.")
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise PortableUpdateError("O plano da atualização é inválido.")
    return value


def _write_document(path, value):
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _try_write_document(path, value):
    """Diagnostic persistence must never prevent recovery after parent exit."""
    try:
        _write_document(path, value)
    except OSError:
        pass


def prune_portable_cache(root=None, now=None):
    """Remove only old, bounded attempts owned by this updater, never profiles."""
    root = Path(root) if root is not None else update_cache_root()
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        return
    expected = {
        "Clarify.exe",
        "Clarify.exe.part",
        MANIFEST_ASSET,
        SIGNATURE_ASSET,
        "helper.exe",
        "plan.json",
        "armed.json",
        "cancel.json",
        "ready.json",
        "result.json",
    }
    expected |= {
        name + ".part"
        for name in (
            "plan.json",
            "armed.json",
            "cancel.json",
            "ready.json",
            "result.json",
        )
    }
    cutoff = (time.time() if now is None else now) - 86400
    for index, directory in enumerate(root.iterdir()):
        if index >= 100:
            break
        try:
            if (
                not re.fullmatch(r"update-\d+\.\d+\.\d+-[a-z0-9_]{8}", directory.name)
                or directory.is_symlink()
                or directory.is_junction()
                or not directory.is_dir()
                or directory.resolve().parent != root.resolve()
                or directory.stat().st_mtime >= cutoff
            ):
                continue
            files = list(directory.iterdir())
            if len(files) > len(expected) or any(
                path.name not in expected
                or path.is_symlink()
                or not path.is_file()
                or path.stat().st_mtime >= cutoff
                for path in files
            ):
                continue
            for path in files:
                path.unlink()
            directory.rmdir()
        except OSError:
            continue


def _prune_previous_backup(target, new_backup):
    try:
        previous = _document(update_cache_root() / "last-success.json")
        backup = Path(previous["backup"])
        if (
            Path(previous["target"]) != target
            or backup == new_backup
            or backup.parent != target.parent
            or backup.is_symlink()
            or not backup.is_file()
            or not re.fullmatch(
                re.escape(target.name) + r"\.previous-[a-f0-9]{32}", backup.name
            )
            or file_sha256(backup) != previous["previous_sha256"]
        ):
            return
        backup.unlink()
    except (OSError, ValueError, KeyError, TypeError, PortableUpdateError):
        return


def _plan_directory(path: Path) -> Path:
    root = update_cache_root().resolve()
    if (
        path.is_symlink()
        or path.parent.is_junction()
        or path.parent.is_symlink()
        or not path.resolve().is_relative_to(root)
    ):
        raise PortableUpdateError("A pasta da atualização é inválida.")
    directory = path.resolve().parent
    if (
        directory.parent != root
        or not directory.name.startswith("update-")
        or path.name != "plan.json"
    ):
        raise PortableUpdateError("A pasta da atualização é inválida.")
    return directory


class WindowsProcess:
    """Keep an opened process object so PID reuse cannot change its identity."""

    def __init__(self, process_id):
        if sys.platform != "win32" or type(process_id) is not int or process_id <= 0:
            raise PortableUpdateError("O processo da instalação é inválido.")
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self._kernel.OpenProcess.restype = wintypes.HANDLE
        self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._kernel.WaitForSingleObject.restype = wintypes.DWORD
        self._kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
            ctypes.POINTER(wintypes.FILETIME)
        ] * 4
        self.handle = self._kernel.OpenProcess(0x100000 | 0x1000, False, process_id)
        if not self.handle:
            raise PortableUpdateError(
                "Não foi possível verificar o processo da instalação."
            )
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if not self._kernel.QueryFullProcessImageNameW(
                self.handle, 0, buffer, ctypes.byref(size)
            ):
                raise PortableUpdateError("Não foi possível verificar a instalação.")
            self.path = Path(buffer.value).resolve()
            created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
            if not self._kernel.GetProcessTimes(
                self.handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                raise PortableUpdateError(
                    "Não foi possível verificar o processo da instalação."
                )
            self.created = (created.dwHighDateTime << 32) | created.dwLowDateTime
        except Exception:
            self.close()
            raise

    def exited(self, timeout_ms=0):
        result = self._kernel.WaitForSingleObject(self.handle, timeout_ms)
        if result == 0xFFFFFFFF:
            raise PortableUpdateError("Não foi possível aguardar o fim do processo.")
        return result == 0

    def close(self):
        if self.handle:
            self._kernel.CloseHandle(self.handle)
            self.handle = None


@dataclass
class PreparedPortableUpdate:
    directory: Path
    nonce: str
    process: subprocess.Popen

    def armed(self):
        try:
            return (
                self.process.poll() is None
                and _document(self.directory / "armed.json").get("nonce") == self.nonce
            )
        except (OSError, ValueError, PortableUpdateError):
            return False

    def cancel(self):
        try:
            _write_document(self.directory / "cancel.json", {"nonce": self.nonce})
        except OSError:
            if self.process.poll() is None:
                try:
                    subprocess.Popen(
                        ["taskkill.exe", "/PID", str(self.process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        close_fds=True,
                    )
                except OSError:
                    pass


def prepare_portable_update(release, candidate: Path, current_version: str):
    if not is_portable_installation():
        raise PortableUpdateError("Instale a versão portátil para usar a atualização.")
    target = Path(sys.executable)
    if target.is_symlink() or not target.is_file():
        raise PortableUpdateError("O caminho da instalação é inválido.")
    candidate = Path(candidate)
    directory = candidate.parent
    root = update_cache_root().resolve()
    if (
        directory.is_symlink()
        or directory.is_junction()
        or directory.resolve().parent != root
        or not directory.name.startswith("update-")
    ):
        raise PortableUpdateError("A pasta da atualização é inválida.")
    authenticated = verify_manifest(
        (directory / MANIFEST_ASSET).read_bytes(),
        (directory / SIGNATURE_ASSET).read_bytes(),
        load_policy(),
        current_version,
        release.tag,
    )
    verify_binary(candidate, authenticated)
    if (directory / "plan.json").exists() or (directory / "helper.exe").exists():
        # Keep a cancelled helper's files isolated until it exits. A retry must
        # not consume its stale acknowledgment, plan, or cancellation marker.
        retry = Path(
            tempfile.mkdtemp(prefix=f"update-{authenticated.version}-", dir=root)
        )
        for name in ("Clarify.exe", MANIFEST_ASSET, SIGNATURE_ASSET):
            shutil.copyfile(directory / name, retry / name)
        directory = retry
        candidate = retry / "Clarify.exe"
        verify_binary(candidate, authenticated)
    nonce = uuid.uuid4().hex
    with (target.parent / (".clarify-write-test-" + nonce)).open("xb") as stream:
        stream.write(b"")
    (target.parent / (".clarify-write-test-" + nonce)).unlink()
    identity = WindowsProcess(os.getpid())
    try:
        if identity.path != target.resolve() or identity.exited():
            raise PortableUpdateError("O processo da instalação mudou.")
        plan = {
            "schema_version": 1,
            "nonce": nonce,
            "target": str(target.resolve()),
            "parent_pid": os.getpid(),
            "parent_created": identity.created,
            "previous_version": current_version,
            "original_sha256": file_sha256(target),
        }
    finally:
        identity.close()
    helper = directory / "helper.exe"
    shutil.copyfile(target, helper)
    if file_sha256(helper) != plan["original_sha256"]:
        raise PortableUpdateError("A instalação mudou durante a preparação.")
    plan_path = directory / "plan.json"
    _write_document(plan_path, plan)
    process = subprocess.Popen(
        [str(helper), "--apply-portable-update", str(plan_path)],
        env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
    return PreparedPortableUpdate(directory, nonce, process)


def _retry_replace(source, target):
    # The one-file bootloader can outlive the Python parent for a short time.
    deadline = time.monotonic() + 30
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def _launch(path, receipt=None):
    environment = os.environ.copy()
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    environment.pop(RECEIPT_ENV, None)
    if receipt is not None:
        environment[RECEIPT_ENV] = str(receipt)
    return subprocess.Popen(
        [str(path), "--hidden"],
        env=environment,
        close_fds=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _accept_child(child, directory, nonce, version, target):
    deadline = time.monotonic() + 60
    while child.poll() is None and time.monotonic() < deadline:
        try:
            receipt = _document(directory / "ready.json")
            if receipt.get("nonce") == nonce and receipt.get("version") == version:
                identity = WindowsProcess(receipt["pid"])
                try:
                    if identity.path == target.resolve() and not identity.exited():
                        return True
                finally:
                    identity.close()
        except (OSError, ValueError, KeyError, PortableUpdateError):
            pass
        time.sleep(0.2)
    if child.poll() is None:
        # This is exclusively the new child we launched; retain its process
        # handle and stop its one-file descendants before restoring the backup.
        subprocess.run(
            ["taskkill.exe", "/PID", str(child.pid), "/T", "/F"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=15,
        )
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            return False
    return False


def run_portable_update_helper(plan_path: Path, current_version: str) -> int:
    directory = None
    release = None
    parent_exited = False
    plan = None
    try:
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            raise PortableUpdateError(
                "O auxiliar de atualização requer a versão instalada."
            )
        directory = _plan_directory(Path(plan_path))
        plan = _document(directory / "plan.json")
        if (
            plan.get("schema_version") != 1
            or plan.get("previous_version") != current_version
            or not isinstance(plan.get("nonce"), str)
            or not re.fullmatch(r"[a-f0-9]{32}", plan["nonce"])
            or not isinstance(plan.get("original_sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", plan["original_sha256"])
        ):
            raise PortableUpdateError("O plano da atualização é inválido.")
        target = Path(plan["target"])
        release = verify_manifest(
            (directory / MANIFEST_ASSET).read_bytes(),
            (directory / SIGNATURE_ASSET).read_bytes(),
            load_policy(),
            current_version,
        )
        candidate = directory / "Clarify.exe"
        verify_binary(candidate, release)
        identity = WindowsProcess(plan["parent_pid"])
        try:
            if (
                identity.path != target.resolve()
                or identity.created != plan["parent_created"]
                or target.is_symlink()
                or file_sha256(target) != plan["original_sha256"]
                or identity.exited()
            ):
                raise PortableUpdateError("O processo da instalação mudou.")
            _write_document(directory / "armed.json", {"nonce": plan["nonce"]})
            deadline = time.monotonic() + 600
            while not identity.exited(200):
                if (directory / "cancel.json").exists() or time.monotonic() > deadline:
                    raise PortableUpdateError("Atualização cancelada.")
            if (directory / "cancel.json").exists():
                raise PortableUpdateError("Atualização cancelada.")
            parent_exited = True
        finally:
            identity.close()

        def launch(path):
            receipt = (
                directory / "plan.json" if file_sha256(path) == release.sha256 else None
            )
            return _launch(path, receipt)

        backup = replace_and_restart(
            release,
            candidate,
            target,
            plan["nonce"],
            plan["original_sha256"],
            launch,
            lambda child: _accept_child(
                child, directory, plan["nonce"], release.version, target
            ),
            _retry_replace,
        )
        _try_write_document(
            directory / "result.json", {"status": "success", "version": release.version}
        )
        _prune_previous_backup(target, backup)
        _try_write_document(
            update_cache_root() / "last-success.json",
            {
                "target": str(target),
                "backup": str(backup),
                "previous_sha256": plan["original_sha256"],
                "version": release.version,
            },
        )
        try:
            (update_cache_root() / "failed-version.json").unlink(missing_ok=True)
        except OSError:
            pass
        return 0
    except Exception as error:
        if directory is not None:
            _try_write_document(directory / "result.json", {"status": "failed"})
        if parent_exited and release is not None:
            _try_write_document(
                update_cache_root() / "failed-version.json",
                {"version": release.version},
            )
            if plan is not None and not getattr(error, "restarted_previous", False):
                target = Path(plan["target"])
                try:
                    if file_sha256(target) == plan["original_sha256"]:
                        _launch(target)
                except OSError:
                    pass
        return 2


def acknowledge_portable_update(current_version: str):
    """Called on the first Qt event-loop tick after complete native startup."""
    value = os.environ.pop(RECEIPT_ENV, None)
    if not value:
        return
    try:
        path = Path(value)
        directory = _plan_directory(path)
        plan = _document(path)
        release = verify_manifest(
            (directory / MANIFEST_ASSET).read_bytes(),
            (directory / SIGNATURE_ASSET).read_bytes(),
            load_policy(),
            plan["previous_version"],
        )
        if (
            release.version != current_version
            or Path(plan["target"]).resolve() != Path(sys.executable).resolve()
            or file_sha256(Path(sys.executable)) != release.sha256
        ):
            return
        _write_document(
            directory / "ready.json",
            {"nonce": plan["nonce"], "version": current_version, "pid": os.getpid()},
        )
    except (OSError, ValueError, KeyError, PortableUpdateError):
        return
