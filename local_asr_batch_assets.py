"""Explicit, guarded installation of pinned CPU batch recognizers."""

import os
import platform
import shutil
import tarfile

from local_asr import (
    LocalASRInstaller,
    LocalASRIntegrityError,
    LocalASRCancelledError,
    ManifestAsset,
    default_install_root,
    default_manifest_path,
    _safe_path_component,
    _safe_relative_path,
    _sha256,
    _valid_digest,
)

MODELS = frozenset({"parakeet-v3-int8", "granite-5-turboctc"})


class BatchInstaller(LocalASRInstaller):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        model = self.manifest["recommended_model"]["id"]
        if model not in MODELS:
            raise LocalASRIntegrityError("Unknown batch recognition model")
        files = self.manifest.get("batch_model_files", [])
        if not isinstance(files, list) or any(
            not isinstance(value, dict) for value in files
        ):
            raise LocalASRIntegrityError("Invalid batch model files")
        names = [
            _safe_path_component(value.get("filename"), "batch_model_files.filename")
            for value in files
        ]
        expected = (
            {"decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"}
            if model == "parakeet-v3-int8"
            else set()
        )
        if len(names) != len(expected) or set(names) != expected:
            raise LocalASRIntegrityError("Incomplete or duplicate batch model files")
        for value in files:
            _safe_path_component(value.get("filename"), "batch_model_files.filename")
            if (
                not _valid_digest(value.get("sha256"))
                or not isinstance(value.get("size"), int)
                or value["size"] <= 0
                or not str(value.get("url", "")).startswith("https://")
                or not str(value.get("source_url", "")).startswith("https://")
                or not value.get("license")
            ):
                raise LocalASRIntegrityError("Invalid batch model asset")

    @property
    def executable_path(self):
        if self.manifest["recommended_model"]["id"] == "parakeet-v3-int8":
            return (
                self.install_dir
                / "runtime"
                / "bin"
                / (
                    "sherpa-onnx-offline.exe"
                    if "windows" in self.manifest_path.name
                    else "sherpa-onnx-offline"
                )
            )
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

    def _expected_installed_files(self):
        yield from super()._expected_installed_files()
        for value in self.manifest.get("batch_model_files", []):
            yield (
                self.model_path.parent / value["filename"],
                value["size"],
                value["sha256"],
            )

    def _copy_license_notices(self, staging, cancel_event=None):
        # This hook runs inside the existing installation transaction, before
        # receipt publication. Supplemental ONNX files have the same guards.
        for value in self.manifest.get("batch_model_files", []):
            asset = ManifestAsset(name="model", archive="", **value)
            self._download(
                asset, staging / "models" / asset.filename, None, cancel_event
            )
        super()._copy_license_notices(staging, cancel_event)

    def _extract_runtime(
        self, archive_path, staging, cancel_event=None, asset_name="runtime"
    ):
        try:
            with tarfile.open(archive_path, "r:*") as archive:
                for entry in self.manifest["extracted_files"]:
                    if cancel_event is not None and cancel_event.is_set():
                        raise LocalASRCancelledError("Local setup was cancelled")
                    member = archive.getmember(entry["archive_path"])
                    if not member.isfile() or member.size != entry["size"]:
                        raise LocalASRIntegrityError("Invalid batch runtime member")
                    path = staging / _safe_relative_path(entry["path"])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with (
                        archive.extractfile(member) as source,
                        path.open("wb") as output,
                    ):
                        shutil.copyfileobj(source, output, 1024 * 1024)
                    if _sha256(path) != entry["sha256"]:
                        raise LocalASRIntegrityError("Batch runtime checksum failed")
                    if os.name != "nt" and path.name == "sherpa-onnx-offline":
                        path.chmod(0o700)
        except (tarfile.TarError, KeyError) as error:
            raise LocalASRIntegrityError("Invalid batch runtime archive") from error


def installer_for_batch(model):
    if model not in MODELS:
        raise LocalASRIntegrityError("Unknown batch recognition model")
    system = platform.system().lower()
    if system not in ("windows", "linux"):
        raise LocalASRIntegrityError(
            "Batch recognition is not packaged for this platform"
        )
    return BatchInstaller(
        root=default_install_root().parent
        / "local-asr-profiles"
        / f"{model}-{system}-cpu",
        manifest_path=default_manifest_path().parent
        / "local_asr_manifests"
        / f"{model}-{system}-cpu.json",
    )
