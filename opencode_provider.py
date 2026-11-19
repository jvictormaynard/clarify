"""Text-only OpenCode CLI boundary. No shared user auth or workspaces.

Catalog: opencode.ai/docs/cli. Text turns: official ACP v1 stdio.
Free model availability is discovered, never inferred from a successful login.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import signal
import sys
import subprocess
import tempfile
import threading
import time

import opencode_runtime
from opencode_acp import TextSession

from provider_adapters import ProviderAdapter
from provider_http import ProviderCancelledError, ProviderTimeoutError
from transcription_performance import memory_bytes
from provider_types import (
    ModelCatalog,
    ProviderCapability,
    ProviderConfigurationError,
    ProviderMetadata,
    ProviderResponseError,
    RewriteResult,
    TranslationResult,
)

RECOMMENDED_FREE_REWRITE_MODEL = "opencode/deepseek-v4.1-flash-free"

_FREE_CATALOG_TTL = 60
_ACP_IDLE_SECONDS = 25
_ACP_MAX_TURNS = 6
_ACP_RAM_RESERVE = 768 * 1024**2


@dataclass
class _IdleACP:
    runtime: tuple
    resources: ExitStack
    client: TextSession
    work: Path
    turns: int
    expires: float
    timer: threading.Timer | None = None

    def close(self):
        if self.timer is not None:
            self.timer.cancel()
        self.resources.close()


def _runtime_identity(executable):
    if not executable:
        return None
    try:
        stat = Path(executable).stat()
    except OSError:
        return None
    return (
        str(executable),
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def _reject_managed_configuration():
    # Refuse host-managed configuration: it can override tool denials.
    managed = (
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "opencode"
        if os.name == "nt"
        else Path(
            "/Library/Application Support/opencode"
            if sys.platform == "darwin"
            else "/etc/opencode"
        )
    )
    if managed.exists() or (
        sys.platform == "darwin" and Path("/Library/Managed Preferences").exists()
    ):
        raise ProviderConfigurationError(
            "opencode",
            "Managed OpenCode configuration prevents an isolated text session.",
        )


@contextmanager
def _private_directory():
    directory = tempfile.TemporaryDirectory(prefix="clarify-opencode-")
    try:
        yield directory.name
    finally:
        original = sys.exception()
        deadline = time.monotonic() + 5
        while True:
            try:
                directory.cleanup()
                break
            except PermissionError as cleanup_error:
                if os.name != "nt" or time.monotonic() >= deadline:
                    if original is not None:
                        raise original from cleanup_error
                    raise
                time.sleep(0.05)


def _windows_job(process):
    """Assign the suspended child to a kill-on-close job before it can fork."""
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_working", ctypes.c_size_t),
            ("max_working", ctypes.c_size_t),
            ("active", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits),
            ("io", ctypes.c_uint64 * 6),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process", ctypes.c_size_t),
            ("peak_job", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (
        not job
        or not kernel.SetInformationJobObject(
            job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        )
        or not kernel.AssignProcessToJobObject(job, int(process._handle))
    ):
        if job:
            kernel.CloseHandle(job)
        process.kill()
        process.wait()
        raise ProviderConfigurationError(
            "opencode", "Cannot isolate the OpenCode process tree."
        )
    resume = ctypes.WinDLL("ntdll").NtResumeProcess
    resume.argtypes = [wintypes.HANDLE]
    if resume(int(process._handle)) != 0:
        kernel.CloseHandle(job)
        process.wait()
        raise ProviderConfigurationError(
            "opencode", "Cannot start the isolated OpenCode process."
        )

    def close_tree():
        # Closing the Job kills descendants asynchronously. Wait for their
        # termination before deleting the private directory and Bun DLLs.
        class Accounting(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_int64)
                for name in ("user", "kernel", "period_user", "period_kernel")
            ] + [
                (name, wintypes.DWORD)
                for name in ("faults", "total", "active", "terminated")
            ]

        try:
            kernel.TerminateJobObject(job, 1)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                accounting = Accounting()
                if (
                    not kernel.QueryInformationJobObject(
                        job,
                        1,
                        ctypes.byref(accounting),
                        ctypes.sizeof(accounting),
                        None,
                    )
                    or not accounting.active
                ):
                    break
                time.sleep(0.025)
        finally:
            kernel.CloseHandle(job)

    return close_tree


class OpenCodeAdapter(ProviderAdapter):
    def __init__(self, http=None, *, executable=None, timeout=45):
        super().__init__(
            ProviderMetadata(
                provider_id="opencode",
                display_name="OpenCode (free models)",
                capabilities=frozenset(
                    {
                        ProviderCapability.TEXT_GENERATION,
                        ProviderCapability.MODEL_DISCOVERY,
                    }
                ),
                default_base_url="",
                audio_model_key="opencode_audio_model",
                text_model_key="opencode_text_model",
                default_audio_model="",
                default_text_model="",
                authentication="local_cli",
            ),
            http,
        )
        self.executable = executable
        self.timeout = timeout
        self._verified_runtime = None
        self._catalog_lock = threading.Lock()
        self._catalog_started = 0
        self._catalog_completed = 0
        self._free_catalog = None
        self._acp_lock = threading.Lock()
        self._idle_lock = threading.Lock()
        self._idle_acp = None
        self._stopping = threading.Event()

    @staticmethod
    def _reap_idle(worker):
        """Keep process cleanup owned after the Qt window has closed."""
        reaper = threading.Thread(
            target=worker.close, name="clarify-opencode-reaper", daemon=False
        )
        reaper.start()
        return reaper

    def _retire_idle(self, worker):
        with self._idle_lock:
            if self._idle_acp is worker:
                self._idle_acp = None
                return self._reap_idle(worker)

    def cancel(self):
        self._stopping.set()
        with self._idle_lock:
            if self._idle_acp is not None:
                worker, self._idle_acp = self._idle_acp, None
                return self._reap_idle(worker)

    shutdown = cancel

    def available(self):
        return bool(self.executable or opencode_runtime.available())

    def install(self, cancel_token=None):
        return opencode_runtime.install(cancel_token)

    @contextmanager
    def _launch(self, args, prompt, expected_runtime):
        acp = args == ["acp"]
        executable = self.executable or opencode_runtime.executable()
        if not executable:
            raise ProviderConfigurationError(
                "opencode", "Select Connect to install the verified OpenCode runtime."
            )
        runtime = _runtime_identity(executable)
        if expected_runtime is not None and runtime != expected_runtime:
            raise ProviderConfigurationError(
                "opencode", "The OpenCode runtime changed. Retry the request."
            )
        # Each command gets a private home, data store and working directory.
        # Do not inherit provider keys, OAuth stores, plugins or CLI overrides.
        with _private_directory() as root:
            base = Path(root)
            env = {
                k: v
                for k, v in os.environ.items()
                if k.upper()
                in {
                    "PATH",
                    "SYSTEMROOT",
                    "WINDIR",
                    "COMSPEC",
                    "PATHEXT",
                    "LANG",
                    "LC_ALL",
                }
            }
            for key, folder in {
                "HOME": "home",
                "USERPROFILE": "home",
                "XDG_CONFIG_HOME": "config",
                "XDG_DATA_HOME": "data",
                "XDG_CACHE_HOME": "cache",
                "XDG_STATE_HOME": "state",
                "APPDATA": "config",
                "LOCALAPPDATA": "data",
                "TMPDIR": "tmp",
                "TEMP": "tmp",
                "TMP": "tmp",
            }.items():
                path = base / folder
                path.mkdir(exist_ok=True)
                env[key] = str(path)
            _reject_managed_configuration()
            if runtime is None or runtime != self._verified_runtime:
                version = subprocess.run(
                    [str(executable), "--version"],
                    cwd=base,
                    env=env,
                    capture_output=True,
                    timeout=10,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                match = re.fullmatch(
                    rb"(?:opencode v)?2\.\d+\.\d+(?:[-+][^\s]+)?\s*",
                    version.stdout.strip(),
                )
                if version.returncode or not match:
                    raise ProviderConfigurationError(
                        "opencode", "This OpenCode CLI version is not supported."
                    )
            config = {
                "permissions": [{"action": "*", "resource": "*", "effect": "deny"}],
                "policies": [
                    {"action": "provider.use", "resource": "*", "effect": "deny"},
                    {
                        "action": "provider.use",
                        "resource": "opencode",
                        "effect": "allow",
                    },
                    {"action": "tool.use", "resource": "*", "effect": "deny"},
                    {"action": "plugin.use", "resource": "*", "effect": "deny"},
                    {"action": "mcp.use", "resource": "*", "effect": "deny"},
                ],
                "update": "disable",
                "snapshots": False,
                "compaction": {"auto": False},
                "agents": {
                    "title": {"disabled": True},
                    "summary": {"disabled": True},
                    "clarify": {
                        "mode": "primary",
                        "system": "Transform text only. Never use tools.",
                        "permissions": [
                            {"action": "*", "resource": "*", "effect": "deny"}
                        ],
                    },
                },
            }
            if acp:
                env["OPENCODE_DB"] = ":memory:"
                # Ask keeps these tools in the catalog. ACP cancels all requests.
                # A tool.use deny policy or agent-level deny would hide them.
                config.pop("permissions")
                config["permission"] = {"*": "deny", "bash": "ask", "read": "ask"}
                config["policies"] = [
                    policy
                    for policy in config["policies"]
                    if policy["action"] != "tool.use"
                ]
                config["agents"]["clarify"]["permissions"] = [
                    {"action": "*", "resource": "*", "effect": "deny"},
                    {"action": "shell", "resource": "*", "effect": "ask"},
                    {"action": "read", "resource": "*", "effect": "ask"},
                ]
            env["OPENCODE_DISABLE_AUTOUPDATE"] = "true"
            env["OPENCODE_DISABLE_LSP_DOWNLOAD"] = "true"
            env["OPENCODE_DISABLE_DEFAULT_PLUGINS"] = "true"
            env["OPENCODE_CONFIG_DIR"] = str(base / "config")
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
            work = base / "work"
            work.mkdir()
            # ACP owns its stdio context; only catalog CLI accepts --standalone.
            (work / "opencode.json").write_text(json.dumps(config), encoding="utf-8")
            with ExitStack() as streams:
                if acp:
                    stdin = stdout = stderr = subprocess.PIPE
                else:
                    stdout = streams.enter_context((base / "stdout").open("w+b"))
                    stderr = streams.enter_context((base / "stderr").open("w+b"))
                    stdin = streams.enter_context(tempfile.TemporaryFile())
                    stdin.write(prompt.encode("utf-8"))
                    stdin.seek(0)
                if runtime is not None and _runtime_identity(executable) != runtime:
                    raise ProviderConfigurationError(
                        "opencode", "The OpenCode runtime changed. Retry the request."
                    )
                self._verified_runtime = runtime
                process = subprocess.Popen(
                    [str(executable), "acp", "--log-level", "none"]
                    if acp
                    else [
                        str(executable),
                        *args,
                        "--print-logs",
                        "--log-level",
                        "error",
                        "--standalone",
                    ],
                    cwd=work,
                    env=env,
                    stdin=stdin,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=os.name != "nt",
                    creationflags=subprocess.CREATE_NO_WINDOW
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                    | 0x00000004
                    if os.name == "nt"
                    else 0,
                )
                close_job = _windows_job(process) if os.name == "nt" else None
                try:
                    yield process, work, stdout, stderr
                finally:
                    # Terminate the private server too, including after normal CLI exit.
                    if os.name != "nt":
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    elif close_job is not None:
                        close_job()
                    process.wait()

    @contextmanager
    def _open_acp(self, runtime):
        client = None
        try:
            with self._launch(["acp"], "", runtime) as (process, work, _, _):
                client = TextSession(process, self._stopping)
                yield client, work
        finally:
            if client is not None:
                client.close()

    def _run_acp(self, prompt, model, runtime, token, authorize, reuse):
        options = {"timeout": self.timeout, "cancel_token": token}
        if not reuse or runtime is None or not self._acp_lock.acquire(blocking=False):
            with self._open_acp(runtime) as (client, work):
                return client.generate(
                    work, model, prompt, authorize, reuse=False, **options
                )
        try:
            with self._idle_lock:
                previous, self._idle_acp = self._idle_acp, None
            if previous is not None:
                previous.timer.cancel()
                if (
                    previous.runtime != runtime
                    or time.monotonic() >= previous.expires
                    or previous.client.process.poll() is not None
                    or previous.client.failure
                ):
                    previous.close()
                    previous = None
            with (
                previous.resources if previous is not None else ExitStack() as resources
            ):
                if previous is None:
                    turns = 0
                    client, work = resources.enter_context(self._open_acp(runtime))
                else:
                    turns, client, work = previous.turns, previous.client, previous.work
                    _reject_managed_configuration()
                text = client.generate(
                    work, model, prompt, authorize, reuse=True, **options
                )
                memory = memory_bytes()
                with self._idle_lock:
                    if (
                        client.reusable
                        and turns + 1 < _ACP_MAX_TURNS
                        and not self._stopping.is_set()
                        and memory is not None
                        and memory[1] >= _ACP_RAM_RESERVE
                    ):
                        idle = _IdleACP(
                            runtime,
                            resources.pop_all(),
                            client,
                            work,
                            turns + 1,
                            time.monotonic() + _ACP_IDLE_SECONDS,
                        )
                        timer = threading.Timer(
                            _ACP_IDLE_SECONDS, self._retire_idle, args=(idle,)
                        )
                        timer.daemon = True
                        idle.timer = timer
                        self._idle_acp = idle
                        timer.start()
                return text
        finally:
            self._acp_lock.release()

    def _run(
        self,
        args,
        prompt="",
        cancel_token=None,
        *,
        model=None,
        expected_runtime=None,
        authorize_prompt=None,
        reuse=False,
    ):
        if self._stopping.is_set():
            raise ProviderCancelledError(provider="opencode")
        if args == ["acp"]:
            return self._run_acp(
                prompt, model, expected_runtime, cancel_token, authorize_prompt, reuse
            )
        with self._launch(args, prompt, expected_runtime) as (
            process,
            work,
            stdout,
            stderr,
        ):
            started = time.monotonic()
            while process.poll() is None:
                if self._stopping.is_set():
                    raise ProviderCancelledError(provider="opencode")
                if cancel_token is not None:
                    cancel_token.raise_if_cancelled()
                if time.monotonic() - started > self.timeout:
                    raise ProviderTimeoutError(
                        provider="opencode", operation="text_generation"
                    )
                # The CLI can retry a rejected request without emitting
                # a JSON error. Inspect only known refusal markers and
                # never expose raw stderr, keys, or prompt contents.
                with (work.parent / "stderr").open("rb") as diagnostics:
                    refusal = diagnostics.read(1024 * 1024).lower()
                if b"free usage limit reached" in refusal:
                    raise ProviderResponseError(
                        "opencode",
                        "OpenCode free usage limit reached. Retry later or explicitly select another service. No fallback was used.",
                    )
                if stdout.tell() > 4 * 1024 * 1024 or stderr.tell() > 1024 * 1024:
                    raise ProviderResponseError(
                        "opencode", "OpenCode output exceeded the limit."
                    )
                time.sleep(0.025)
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            if process.returncode:
                if args[:2] == ["api", "model.list"]:
                    raise ProviderConfigurationError(
                        "opencode",
                        "Could not load OpenCode's free models. Check your connection and try again.",
                    )
                raise ProviderResponseError(
                    "opencode",
                    "OpenCode refused or could not complete this free request. Retry later or select another free model explicitly.",
                )
            stdout.seek(0)
            output = stdout.read(4 * 1024 * 1024 + 1)
            if len(output) > 4 * 1024 * 1024:
                raise ProviderResponseError(
                    "opencode", "OpenCode output exceeded the limit."
                )
            return output.decode("utf-8")

    def discover_models(self, connection, cancel_token=None):
        runtime = _runtime_identity(self.executable or opencode_runtime.executable())
        started = time.monotonic()
        with self._catalog_lock:
            self._catalog_started += 1
            generation = self._catalog_started
        cached = None
        cancelled = False
        try:
            output = self._run(
                ["api", "model.list"],
                cancel_token=cancel_token,
                expected_runtime=runtime,
            )
            catalog = self._free_text_models(output)
            if runtime is not None and catalog.text_models:
                cached = (
                    runtime,
                    started + _FREE_CATALOG_TTL,
                    frozenset(catalog.text_models),
                )
            return catalog
        except ProviderCancelledError:
            cancelled = True
            raise
        finally:
            with self._catalog_lock:
                # Only a completed check can replace the last result. Ignore
                # completions from lookups started before a newer result.
                if not cancelled and generation > self._catalog_completed:
                    self._catalog_completed = generation
                    self._free_catalog = cached

    @staticmethod
    def _free_text_models(output):
        models, names = [], {}
        try:
            payload = json.loads(output)
        except ValueError:
            payload = {}
        entries = payload.get("data", []) if isinstance(payload, dict) else []
        for metadata in entries if isinstance(entries, list) else []:
            if (
                not isinstance(metadata, dict)
                or metadata.get("providerID") != "opencode"
            ):
                continue
            identifier = metadata.get("id", "")
            if not isinstance(identifier, str) or not re.fullmatch(
                r"[a-zA-Z0-9._-]+", identifier
            ):
                continue
            model = "opencode/" + identifier
            if not (model.endswith("-free") or model == "opencode/big-pickle"):
                continue
            if (
                metadata.get("enabled") is not True
                or metadata.get("type") != "chat"
                or metadata.get("status") == "deprecated"
            ):
                continue
            costs = metadata.get("cost", [])
            if (
                not isinstance(costs, list)
                or not costs
                or any(
                    not isinstance(cost, dict)
                    or any(
                        type(cost.get(field)) not in (int, float) or cost[field] != 0
                        for field in ("input", "output")
                    )
                    for cost in costs
                )
            ):
                continue
            if model not in models:
                models.append(model)
                name = metadata.get("name")
                names[model] = name if isinstance(name, str) and name.strip() else model
        return ModelCatalog(text_models=tuple(models), display_names=names)

    def validate(self, connection, cancel_token=None, **kwargs):
        catalog = self.discover_models(connection, cancel_token)
        if not catalog.text_models:
            raise ProviderConfigurationError(
                "opencode", "No anonymous free OpenCode text model is available."
            )
        return catalog

    def _catalog_allows(self, runtime, model, *, startup_time=0):
        """Call with the catalog lock held."""
        catalog = self._free_catalog
        return (
            catalog is not None
            and catalog[0] == runtime
            and time.monotonic() + startup_time < catalog[1]
            and model in catalog[2]
        )

    @contextmanager
    def _authorize_prompt(self, runtime, model):
        with self._catalog_lock:
            if not self._catalog_allows(runtime, model):
                raise ProviderConfigurationError(
                    "opencode",
                    "The selected free OpenCode model could not be verified. Retry or choose another free model.",
                )
            yield self._catalog_completed

    def _generate(self, request, connection, cancel_token):
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        runtime = _runtime_identity(self.executable or opencode_runtime.executable())
        with self._catalog_lock:
            # Refresh a nearly expired catalog before starting the private session.
            recently_verified = self._catalog_allows(
                runtime, request.model, startup_time=5
            )
        if not recently_verified:
            self.discover_models(connection, cancel_token)
        with self._authorize_prompt(runtime, request.model) as catalog_generation:
            pass

        @contextmanager
        def authorize_prompt():
            nonlocal catalog_generation
            _reject_managed_configuration()
            with self._authorize_prompt(runtime, request.model) as generation:
                catalog_generation = generation
                yield

        try:
            return self._run(
                ["acp"],
                request.instruction + "\n\n" + request.source_message,
                cancel_token,
                model=request.model,
                expected_runtime=runtime,
                authorize_prompt=authorize_prompt,
                reuse=True,
            )
        except (
            ProviderConfigurationError,
            ProviderResponseError,
            ProviderTimeoutError,
        ):
            # Do not resend text automatically. Refresh availability before the
            # next request after a rejection or incomplete response.
            with self._catalog_lock:
                if self._catalog_completed == catalog_generation:
                    self._free_catalog = None
            raise

    def rewrite(self, request, connection, cancel_token=None):
        return RewriteResult(
            self._generate(request, connection, cancel_token), "opencode", request.model
        )

    def translate(self, request, connection, cancel_token=None):
        return TranslationResult(
            self._generate(request, connection, cancel_token),
            "opencode",
            request.model,
            request.target_language,
        )
