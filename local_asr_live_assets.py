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


NATIVE_TARGETS = {
    "windows": ("windows", {"amd64", "x86_64"}, "transcribe.dll"),
    "linux": ("linux", {"amd64", "x86_64"}, "libtranscribe.so"),
    "darwin": ("macos", {"arm64", "aarch64"}, "libtranscribe.dylib"),
}


class NativeInstaller(LocalASRInstaller):
    @property
    def executable_path(self):
        for target, _, library in NATIVE_TARGETS.values():
            if self.manifest_path.name.endswith(f"-{target}-cpu.json"):
                return self.install_dir / "runtime" / library
        raise LocalASRIntegrityError("Unknown native streaming runtime")

    def platform_supported(self):
        target = NATIVE_TARGETS.get(platform.system().lower())
        if target is None:
            return False
        name, architectures, _ = target
        return (
            self.manifest_path.name.endswith(f"-{name}-cpu.json")
            and platform.machine().lower() in architectures
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
    target = NATIVE_TARGETS.get(platform.system().lower())
    if target is None:
        raise LocalASRIntegrityError(
            "Native streaming is not packaged for this platform"
        )
    name, _, _ = target
    profile = f"nemotron-3.5-streaming-{name}-cpu"
    return NativeInstaller(
        root=default_install_root().parent / "local-asr-profiles" / profile,
        manifest_path=default_manifest_path().parent
        / "local_asr_manifests"
        / f"{profile}.json",
    )
