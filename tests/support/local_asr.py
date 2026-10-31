"""Reusable local asr fixtures. This module defines no test cases."""

import hashlib

import io

import json


import zipfile


from pathlib import Path


import local_asr


ROOT = Path(__file__).resolve().parents[2]


class FakeResponse:
    def __init__(self, *, content=b"", payload=None, status_code=200):
        self.content = content
        self._payload = payload or {}
        self.status_code = status_code

    def iter_content(self, chunk_size):
        for index in range(0, len(self.content), max(1, chunk_size // 2)):
            yield self.content[index : index + max(1, chunk_size // 2)]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class InstallerSession:
    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(content=self.responses[url])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def make_zip(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


class InstallerFixture:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.runtime = b"verified-sidecar"
        self.model = b"verified-model"
        self.archive = make_zip(
            {
                "Release/whisper-server.exe": self.runtime,
                "../../outside.exe": b"must-not-extract",
            }
        )
        self.manifest = {
            "schema_version": 1,
            "provider": "local_asr",
            "engine": {
                "name": "whisper.cpp",
                "version": "v-test",
                "source_url": "https://example.test/source",
                "license": "MIT",
            },
            "recommended_model": {
                "id": "ggml-test",
                "display_name": "Test",
                "source_url": "https://example.test/model-source",
                "license": "MIT",
            },
            "requirements": {
                "platform": "Windows x64",
                "compute": "CPU only",
                "memory_bytes": 1,
                "disk_bytes": 1,
                "download_bytes": len(self.archive) + len(self.model),
            },
            "license_files": ["licenses/whisper.cpp-MIT.txt"],
            "assets": {
                "runtime": {
                    "filename": "runtime.zip",
                    "url": "https://example.test/runtime.zip",
                    "size": len(self.archive),
                    "sha256": digest(self.archive),
                    "license": "MIT",
                    "source_url": "https://example.test/runtime-source",
                    "archive": "zip",
                },
                "model": {
                    "filename": "model.bin",
                    "url": "https://example.test/model.bin",
                    "size": len(self.model),
                    "sha256": digest(self.model),
                    "license": "MIT",
                    "source_url": "https://example.test/model-source",
                },
            },
            "extracted_files": [
                {
                    "archive_path": "Release/whisper-server.exe",
                    "path": "runtime/whisper-server.exe",
                    "size": len(self.runtime),
                    "sha256": digest(self.runtime),
                }
            ],
        }
        self.manifest_path = self.directory / "manifest.json"
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.root = self.directory / "assets"

    def installer(self, responses=None):
        responses = responses or {
            self.manifest["assets"]["runtime"]["url"]: self.archive,
            self.manifest["assets"]["model"]["url"]: self.model,
        }
        session = InstallerSession(responses)
        return local_asr.LocalASRInstaller(
            root=self.root, manifest_path=self.manifest_path, session=session
        ), session


class FakeProcess:
    next_pid = 12000

    def __init__(self, terminated_event=None):
        type(self).next_pid += 1
        self.pid = type(self).next_pid
        self.returncode = None
        self.alive = True
        self.terminated_event = terminated_event
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return None if self.alive else self.returncode

    def terminate(self):
        self.terminate_calls += 1
        self.alive = False
        self.returncode = 0
        if self.terminated_event:
            self.terminated_event.set()

    def kill(self):
        self.kill_calls += 1
        self.alive = False
        self.returncode = -9
        if self.terminated_event:
            self.terminated_event.set()

    def wait(self, timeout=None):
        return self.returncode


class PopenFactory:
    def __init__(self, terminated_event=None):
        self.calls = []
        self.processes = []
        self.terminated_event = terminated_event

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        process = FakeProcess(self.terminated_event)
        self.processes.append(process)
        return process


class SidecarSession:
    def __init__(self, post_results=None):
        self.trust_env = True
        self.get_calls = []
        self.post_calls = []
        self.post_results = list(
            post_results or [FakeResponse(payload={"text": "local text"})]
        )

    def get(self, url, timeout=None):
        self.get_calls.append((url, timeout))
        return FakeResponse(payload={"status": "ok"})

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        result = self.post_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            return result()
        return result


class FakeInstaller:
    def __init__(self, root):
        self.root = Path(root)
        self.install_dir = self.root / "installed"
        self.executable_path = self.install_dir / "runtime" / "whisper-server.exe"
        self.model_path = self.install_dir / "models" / "model.bin"
        self.process_record_path = self.root / "sidecar-process.json"
        self.verify_calls = 0
        self.executable_path.parent.mkdir(parents=True)
        self.model_path.parent.mkdir(parents=True)
        self.executable_path.write_bytes(b"exe")
        self.model_path.write_bytes(b"model")

    def verify(self, cancel_check=None):
        self.verify_calls += 1
        if cancel_check is not None and cancel_check():
            raise local_asr.LocalASRCancelledError("cancelled during verification")
        return self.install_dir


class LocalASRSidecarFixture:
    def _manager(self, directory, session=None, factory=None, **kwargs):
        installer = FakeInstaller(directory)
        session = session or SidecarSession()
        factory = factory or PopenFactory()
        manager = local_asr.LocalASRSidecarManager(
            installer,
            session=session,
            popen_factory=factory,
            elevation_checker=kwargs.get("elevation_checker", lambda: False),
            startup_timeout=kwargs.get("startup_timeout", 0.5),
            request_timeout=kwargs.get("request_timeout", 0.5),
            idle_seconds=kwargs.get("idle_seconds", 0),
        )
        return manager, installer, session, factory
