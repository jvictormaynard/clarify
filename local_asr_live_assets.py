"""Pinned Nemotron assets using the existing guarded installation owner."""

import platform
import shutil
import tarfile

from local_asr import (
    LocalASRInstaller,
    LocalASRIntegrityError,
    LocalASRCancelledError,
    default_install_root,
    default_manifest_path,
    _sha256,
    _safe_relative_path,
)


class NativeInstaller(LocalASRInstaller):
    @property
    def executable_path(self):
        return (
            self.install_dir
            / "runtime"
            / (
                "transcribe.dll"
                if "windows" in self.manifest_path.name
                else "libtranscribe.so"
            )
        )

    def platform_supported(self):
        system = platform.system().lower()
        return (
            system in ("windows", "linux")
            and system in self.manifest_path.name
            and platform.machine().lower() in ("amd64", "x86_64")
        )

    def _extract_runtime(
        self, archive_path, staging, cancel_event=None, asset_name="runtime"
    ):
        # Copy only pinned regular members, never links, directories or paths
        # selected by the archive. Existing publication/root locks remain active.
        with tarfile.open(archive_path, "r:gz") as archive:
            for entry in self.manifest["extracted_files"]:
                if cancel_event is not None and cancel_event.is_set():
                    raise LocalASRCancelledError("Local setup was cancelled")
                member = archive.getmember(entry["archive_path"])
                if not member.isfile() or member.size != entry["size"]:
                    raise LocalASRIntegrityError("Invalid native runtime member")
                destination = staging / _safe_relative_path(entry["path"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                with (
                    archive.extractfile(member) as source,
                    destination.open("wb") as output,
                ):
                    shutil.copyfileobj(source, output, 1024 * 1024)
                if _sha256(destination) != entry["sha256"]:
                    raise LocalASRIntegrityError("Native runtime checksum failed")


def installer_for_native():
    system = platform.system().lower()
    if system not in ("windows", "linux"):
        raise LocalASRIntegrityError(
            "Native streaming is not packaged for this platform"
        )
    return NativeInstaller(
        root=default_install_root().parent
        / "local-asr-profiles"
        / f"nemotron-3.5-streaming-{system}-cpu",
        manifest_path=default_manifest_path().parent
        / "local_asr_manifests"
        / f"nemotron-3.5-streaming-{system}-cpu.json",
    )
