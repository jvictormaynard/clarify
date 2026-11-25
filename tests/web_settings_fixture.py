"""Isolated real-controller RPC fixture. Never opens user config or a microphone."""

import json
import base64
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QObject, Signal, Qt, Slot
from types import SimpleNamespace
from tests.support.settings import _repositories, _MicrophoneBackend
from microphone_controls import MicrophoneInventory, MicrophoneDevice
from local_asr_product import LocalASRProductState
from clarify.desktop.qml_settings import QmlSettingsController
from clarify.desktop.qml_web_settings import SettingsProtocol
from contextlib import ExitStack

_fixture_stdout_lock = threading.Lock()


def emit_fixture(value):
    with _fixture_stdout_lock:
        print(json.dumps(value), flush=True)


def weekly_usage():
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    usage = dict(
        schema_version=2,
        period_start=start.isoformat(),
        reset_at=(start + timedelta(days=7)).isoformat(),
        used_percent=12.5,
        remaining_percent=82.5,
        reserved_percent=5,
        allocation_status="available",
        hosted_available=True,
    )
    if "--usage-legacy" in sys.argv:
        return dict(used_ms=450000, reserved_ms=60000, limit_ms=18000000)
    if "--usage-malformed" in sys.argv:
        usage["remaining_percent"] = "invalid"
    for status in ("waiting", "unfunded", "inactive"):
        if f"--usage-{status}" in sys.argv:
            # A bad old cache must not make an unallocated account look usable.
            usage.update(
                allocation_status=status,
                used_percent=0,
                remaining_percent=100,
                reserved_percent=0,
                hosted_available=False,
            )
    if "--usage-paused" in sys.argv:
        usage["hosted_available"] = False
    if "--usage-exhausted" in sys.argv:
        usage.update(
            used_percent=100,
            remaining_percent=0,
            reserved_percent=0,
            hosted_available=False,
        )
    return usage


class OnboardingAccount:
    """Offline account double for first-run UI acceptance. Never sends e-mail."""

    @property
    def scope(self):
        return "00000000-0000-4000-8000-000000000001" if self.signed_in else None

    def sync_library(self, service, *, prefer=None):
        if not self.import_on_sync:
            return
        self.import_on_sync = False
        from dictionary_snippets import DictionaryEntry, DictionarySnippets, Snippet

        state = service.state
        service.replace(
            DictionarySnippets(
                dictionary=(*state.dictionary, DictionaryEntry(term="Remote term")),
                snippets=(
                    *state.snippets,
                    Snippet(trigger="remote phrase", replacement="Remote replacement"),
                ),
            )
        )

    @property
    def signed_in(self):
        return self.state["signedIn"]

    @property
    def managed(self):
        return self.state.get("managed", False)

    def refresh_if_due(self, service, *, force=False):
        if "--usage-error" in sys.argv:
            from clarify_account import AccountError

            raise AccountError("Não foi possível conectar ao Clarify. Tente novamente.")
        if self.signed_in:
            self.state["usage"] = weekly_usage()

    def refresh(self):
        self.refresh_if_due(None)

    def __init__(self, directory):
        self.directory = Path(directory)
        self._lock = threading.RLock()
        self._generation = 0
        self._action_library = {
            "revision": 0,
            "actions": [
                dict(
                    id="rewrite",
                    name="Reescrita",
                    prompt="Edit the source.",
                    kind="rewrite",
                    enabled=True,
                    revision=1,
                ),
                dict(
                    id="translation",
                    name="Tradução",
                    prompt="Translate into {lang}.",
                    kind="translation",
                    enabled=True,
                    revision=1,
                ),
            ],
        }
        self.import_on_sync = False
        self.state = dict(
            endpoint="https://clarify.example",
            signedIn=False,
            email="",
            pending="",
            hosted=False,
            syncEnabled=False,
            usage={},
        )
        if "--signed-in" in sys.argv:
            self.state.update(
                signedIn=True, hosted=False, managed=False, email="test@example.test"
            )

    def snapshot(self):
        return dict(self.state)

    def snapshot_guard(self):
        return self._lock

    def context_stamp(self):
        with self._lock:
            return self._generation, "", self.state.get("endpoint", "")

    @property
    def hosted(self):
        return self.state.get("hosted", False)

    def history_identity(self):
        from clarify_account import HistoryIdentity

        return (
            HistoryIdentity(self.state["endpoint"], self.scope, self._generation)
            if self.signed_in
            else None
        )

    def text_actions_path(self, identity):
        return self.directory / "fixture-text-actions.json"

    def text_actions(self, *, expected_identity=None, cancel=None):
        return json.loads(json.dumps(self._action_library))

    def save_text_actions(
        self, actions, expected_revision, *, expected_identity, cancel=None
    ):
        from clarify_account import TextActionsConflict

        if getattr(self, "reject_text_action_save", False):
            self.reject_text_action_save = False
            raise ValueError("Fixture action save rejected")

        if expected_identity != self.history_identity():
            raise ValueError("Fixture account changed")
        if expected_revision != self._action_library["revision"]:
            raise TextActionsConflict(self.text_actions())
        previous = {action["id"]: action for action in self._action_library["actions"]}
        values = []
        for action in actions:
            before = previous.get(action["id"])
            revision = before["revision"] if before else 0
            if before is None or any(
                before[key] != value for key, value in action.items()
            ):
                revision += 1
            values.append({**action, "revision": revision})
        self._action_library = {"revision": expected_revision + 1, "actions": values}
        return self.text_actions()

    def execute_text_action(
        self,
        snapshot,
        text,
        language,
        *,
        cancel=None,
        output_language=None,
        writing_style=None,
    ):
        return f"Preview ({language}): {text}"

    def begin_change(self):
        return True

    def end_change(self):
        pass

    def authenticate(self, action, value):
        from clarify_account import AccountError

        if action == "confirm":
            if value != "123456":
                raise AccountError("Código inválido. Tente novamente.")
            self.state.update(signedIn=True, pending="", hosted=False, managed=False)
            self.state["usage"] = weekly_usage()
        else:
            self.state.update(email=value, pending=action)

    def logout(self, **_):
        self._generation += 1
        self.state.update(signedIn=False, pending="", hosted=False, managed=False)

    def authenticate_social(self, provider, *, cancel):
        if "--social-wait" in sys.argv:
            from clarify_account import AccountError

            cancel.wait(30)
            raise AccountError("O login foi cancelado.")
        self.state.update(
            signedIn=True,
            pending="",
            hosted=False,
            managed=False,
            email=f"{provider}@example.test",
        )

    def discover_social_providers(self):
        return (
            ["google", "microsoft", "github"]
            if "--social-all" in sys.argv
            else ["google"]
        )


class Dispatcher(QObject):
    request = Signal(object)

    def __init__(self, protocol):
        super().__init__()
        self.protocol = protocol
        self.request.connect(self.dispatch, Qt.QueuedConnection)

    @Slot(object)
    def dispatch(self, request):
        if request.get("method") == "nativePillInput":
            from tests.support.electron_native_input import native_pill_input

            emit_fixture(
                {"id": request["id"], "result": native_pill_input(request["args"][0])}
            )
            return
        if request.get("method") == "quit":
            QCoreApplication.quit()
            return
        if request.get("method") == "testComputer":
            controller = self.protocol.settings._computer
            action = request.get("args", [""])[0]
            if action == "paired":
                controller._host.devices.append(
                    {"device_id": "fixture-phone", "device_name": "Fixture iPhone"}
                )
                controller.refresh()
            elif action == "expire":
                controller._expires = 1
            elif action == "offline":
                controller._host.enabled = False
                controller._host.ready = False
                controller.refresh()
            elif action in ("internet", "local"):
                controller._host.relay_connected = action == "internet"
                controller.refresh()
            print(json.dumps({"id": request.get("id"), "result": True}), flush=True)
            return
        if (
            "--text-actions" in sys.argv
            and request.get("method") == "testRejectTextActionSave"
        ):
            self.protocol.settings._account.reject_text_action_save = True
            emit_fixture({"id": request.get("id"), "result": True})
            return
        if (
            "--text-actions" in sys.argv
            and request.get("method") == "testRequireTextActionRefresh"
        ):
            settings = self.protocol.settings
            settings._text_actions._incomplete = True
            settings._text_action_mutation.update(status="failed", restoreRequired=True)
            settings.textActionsChanged.emit()
            emit_fixture({"id": request.get("id"), "result": True})
            return
        if (
            "--library-sync" in sys.argv
            and request.get("method") == "testArmLibrarySync"
        ):
            # Test-only remote import on the next real controller sync worker.
            self.protocol.settings._account.import_on_sync = True
            emit_fixture({"id": request.get("id"), "result": True})
            return
        if (
            "--history" in sys.argv
            and request.get("method") == "testHistoryContextChange"
        ):
            # Test-only session transition, outside the product RPC allowlist.
            self.protocol.settings._account._generation += 1
            emit_fixture({"id": request.get("id"), "result": True})
            return
        if "--history" in sys.argv and request.get("method") == "testHistoryClipboard":
            emit_fixture(
                {
                    "id": request.get("id"),
                    "result": self.protocol.settings._history_test_clipboard,
                }
            )
            return
        emit_fixture(self.protocol.dispatch(request))


def main():
    # Match production's UTF-8 byte pipes, including non-ASCII instructions.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    app = QCoreApplication([])
    with (
        TemporaryDirectory() as directory,
        patch(
            "shared.localization.device_language",
            return_value=os.environ.get("CLARIFY_TEST_UI_LANGUAGE", "pt"),
        ),
        patch("clarify.desktop.qml_settings._is_windows", return_value=False),
        patch(
            "clarify_account.AccountService.discover_social_providers", return_value=[]
        ),
        patch(
            "local_asr_catalog.installer_for",
            side_effect=lambda model, device="cpu": Mock(
                manifest={"recommended_model": {"id": model}},
                status=lambda **kwargs: {
                    "state": "missing"
                    if "--personal-missing" in sys.argv
                    else "installed"
                },
                requirements=lambda: {
                    "download_bytes": 157286400 if model == "ggml-base" else 314572800
                },
            ),
        ),
    ):
        inventory = MicrophoneInventory(
            devices=(
                MicrophoneDevice(
                    stable_id="usb",
                    name="USB Microphone",
                    is_default=True,
                    input_channels=1,
                ),
            ),
            default_id="usb",
        )
        backend = _MicrophoneBackend(inventory)

        def preview(selection, inventory, *, on_level, cancel_event, duration):
            for level in (0.1, 0.5, 0.8, 0.3) * 50:
                if cancel_event.wait(0.05):
                    break
                on_level(level)
            return 0.5

        backend.test_microphone = preview
        repositories = _repositories(directory)
        chatgpt = None
        fixtures = ExitStack()
        if "--chatgpt" in sys.argv:
            from tests.support.chatgpt_settings import (
                FakeChatGPTAdapter,
                FakeChatGPTSession,
            )
            from provider_registry import PROVIDER_REGISTRY

            chatgpt = FakeChatGPTSession()
            if "--chatgpt-connected" in sys.argv:
                chatgpt.sign_in(open_browser=Mock())
                chatgpt.acknowledge_plan_notice()
            if "--chatgpt-no-plan" in sys.argv:
                chatgpt.state.update(
                    connected=True,
                    planEnabled=False,
                    email="demo@example.test",
                    accountId="personal",
                    accounts=[
                        dict(id="personal", label="demo@example.test · Personal")
                    ],
                )
            if "--chatgpt-wait" in sys.argv:
                chatgpt.wait = threading.Event()
            fixtures.enter_context(
                patch.dict(
                    PROVIDER_REGISTRY._adapters, chatgpt=FakeChatGPTAdapter(chatgpt)
                )
            )
            fixtures.enter_context(patch("webbrowser.open", return_value=True))
        if "--personal-catalog" in sys.argv:
            from provider_registry import PROVIDER_REGISTRY
            from provider_types import ModelCatalog

            # Synthetic catalog only; never install or call a real text service.
            adapter = PROVIDER_REGISTRY.adapter("opencode")
            available = fixtures.enter_context(
                patch.object(
                    adapter,
                    "available",
                    return_value="--opencode-runtime-missing" not in sys.argv,
                )
            )

            def install_opencode(_token=None):
                available.return_value = True

            fixtures.enter_context(
                patch.object(adapter, "install", side_effect=install_opencode)
            )
            catalog = ModelCatalog(
                (),
                (
                    "opencode/fixture-free-a",
                    *(f"opencode/fixture-free-{number}" for number in range(12)),
                    "opencode/fixture-free-b",
                ),
            )
            fixtures.enter_context(
                patch.object(adapter, "validate", return_value=catalog)
            )
            fixtures.enter_context(
                patch.object(adapter, "discover_models", return_value=catalog)
            )
            if "--personal-catalog-error" in sys.argv:
                from provider_types import ProviderConfigurationError

                adapter.validate.side_effect = ProviderConfigurationError(
                    "opencode",
                    "Could not load OpenCode's free models. Check your connection and try again.",
                )
                fixtures.enter_context(
                    patch.object(
                        PROVIDER_REGISTRY.adapter("openai"),
                        "validate",
                        side_effect=ProviderConfigurationError(
                            "openai", "Invalid API key."
                        ),
                    )
                )
        onboarding = "--onboarding" in sys.argv
        if not onboarding:
            repositories.config.apply(
                replace(repositories.config.load(), onboarding_completed=True)
            )
        local_product = Mock(
            state=LocalASRProductState(
                "installed", requirements={"download_bytes": 314572800}
            ),
            busy=False,
        )
        if "--personal-install" in sys.argv:
            from local_asr import (
                LocalASRInstaller,
                LocalASRSidecarManager,
                default_manifest_path,
            )
            from tests.support.local_asr_product import FakeInstaller
            from local_asr_product import LocalASRProductController

            class SetupInstaller(FakeInstaller):
                def platform_supported(self):
                    return True

                def status(self, cancel_check=None):
                    return super().status()

                def install(self, callback=None, cancel_event=None):
                    if self.install_calls:
                        threading.Timer(1.0, self.release.set).start()
                    return super().install(callback, cancel_event)

            setup_installer = SetupInstaller()
            pack = LocalASRInstaller(
                manifest_path=default_manifest_path().parent
                / "local_asr_manifests/ggml-turbo-q5-cuda.json",
            )
            setup_installer.requirements_value = pack.requirements()
            setup_installer.asset = pack.asset
            missing = Mock(
                requirements=pack.requirements,
                asset=pack.asset,
                status=lambda **kwargs: {"state": "not_installed"},
            )
            fixtures.enter_context(
                patch(
                    "local_asr_catalog.memory_bytes",
                    return_value=(15 * 1024**3, 1495 * 1024**2),
                )
            )
            fixtures.enter_context(
                patch("local_asr_catalog._free_install_disk", return_value=42 * 1024**3)
            )
            fixtures.enter_context(
                patch(
                    "local_asr_catalog.devices",
                    return_value=[
                        {"id": "auto", "label": "Automatic"},
                        {"id": "cpu", "label": "CPU"},
                        {
                            "id": "cuda:0",
                            "label": "GeForce RTX 3070 Ti Laptop GPU",
                            "driver": "591.59",
                            "memory_mb": 8192,
                        },
                    ],
                )
            )
            fixtures.enter_context(
                patch(
                    "local_asr_catalog.installer_for",
                    side_effect=lambda model, device="cpu": (
                        setup_installer
                        if (model, device) == ("ggml-turbo-q5", "cuda:0")
                        else missing
                    ),
                )
            )
            fixtures.enter_context(
                patch.object(LocalASRSidecarManager, "start", return_value=0.0)
            )
            local_product = LocalASRProductController(installer=setup_installer)
        settings = QmlSettingsController(
            repositories,
            account_service=OnboardingAccount(directory)
            if onboarding or "--signed-in" in sys.argv or "--social-wait" in sys.argv
            else None,
            microphone_backend=backend,
            local_product=local_product,
            chatgpt_session=chatgpt,
        )
        if "--text-actions" in sys.argv:
            from provider_registry import PROVIDER_REGISTRY, ProviderRegistry
            from provider_types import RewriteResult, ModelCatalog
            from workflow_provider import WorkflowProviderService

            config = repositories.config.load()
            repositories.config.apply(
                replace(
                    config,
                    groq=replace(config.groq, api_key="fixture-only"),
                    openai=replace(config.openai, api_key="fixture-only"),
                )
            )
            settings._replace_loaded_config(repositories.config.load())
            registry = Mock(spec=ProviderRegistry)
            registry.describe.side_effect = PROVIDER_REGISTRY.describe
            registry.connection_for_route.side_effect = (
                PROVIDER_REGISTRY.connection_for_route
            )
            original_discovery = PROVIDER_REGISTRY.discover_models

            def discover(provider, connection, cancel=None):
                if provider == "chatgpt":
                    return original_discovery(provider, connection, cancel)
                return ModelCatalog(text_models=("fixture-text", "fixture-text-large"))

            fixtures.enter_context(
                patch.object(PROVIDER_REGISTRY, "discover_models", side_effect=discover)
            )

            def transform(provider, request, connection, cancel):
                return RewriteResult(
                    f"Preview ({getattr(request, 'target_language', 'auto')}): {request.text}",
                    provider,
                    request.model,
                )

            registry.rewrite.side_effect = transform
            registry.translate.side_effect = transform
            settings._text_action_provider = WorkflowProviderService(
                SimpleNamespace(current=repositories.config.load),
                Mock(),
                registry=registry,
                account=settings._account,
                text_actions=settings._text_actions,
            )
        from tests.support.practice_settings_fixture import bind_practice

        bind_practice(settings, app)
        from clarify.desktop.qml_computer import QmlComputerController

        computer = QmlComputerController(
            Path(directory) / "computer.sqlite3",
            FixtureComputerHost,
            render_qr=fixture_qr,
            blocked=lambda: bool(
                settings.accountState.get("signedIn")
                or settings.accountState.get("managed")
            ),
        )
        settings.bindComputer(computer)
        computer.initialize()
        if "--history" in sys.argv or "--text-actions" in sys.argv:
            # Clipboard effects stay inside the isolated fixture.
            settings._history_test_clipboard = []
            settings._write_history_clipboard = settings._history_test_clipboard.append
        if "--recording-recovery" in sys.argv:
            from recording_recovery import RecordingRecovery
            from tests.support.audio_history import wav_bytes

            recovery = RecordingRecovery(Path(directory))
            recovery.save(wav_bytes(frames=16000 * 181))
            from clarify.desktop.qml_runtime import (
                QtRecordingAudioGateway,
                QtHistoryRecorder,
            )
            from tests.support.workflows import WorkflowFixture
            from provider_types import TranscriptionResult

            fixture = WorkflowFixture()
            fixture.setUp()
            fixture.provider.transcribe = lambda *_args, **_kwargs: TranscriptionResult(
                "Texto recuperado editado.",
                "gemini",
                "gemini-test",
                raw_text="Texto recuperado original.",
                refined_text="Texto recuperado editado.",
            )
            repositories.config.apply(
                replace(repositories.config.load(), history_enabled=True)
            )
            history = QtHistoryRecorder(repositories, fixture.scheduler)
            fixture.service.subscribe(history.on_state)
            audio = QtRecordingAudioGateway(SimpleNamespace(config=None, sox=None))

            def reprocess_recording(path):
                with patch(
                    "clarify.desktop.qml_runtime._data_directory",
                    return_value=Path(directory),
                ):
                    recording = audio.create_recovery_session(path)
                return recording is not None and fixture.service.recover_dictation(
                    recording, "auto"
                )

            settings._recording_reprocessor = reprocess_recording
        if "--history" in sys.argv:
            from history_store import HistoryRecord, HistoryStore
            from datetime import datetime, timezone

            store = HistoryStore(
                settings._history.local.path, enabled=True, retention_days=None
            )
            store.append(
                HistoryRecord(
                    raw_text="Isolated desktop history.",
                    refined_text="Isolated revised desktop history.",
                    timestamp=datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
                )
            )
            store.append(
                HistoryRecord(
                    raw_text="Isolated mobile history.",
                    source_device="mobile",
                    timestamp=datetime(2026, 10, 16, 13, tzinfo=timezone.utc),
                )
            )
            if "--history-review" in sys.argv:
                store.append(
                    HistoryRecord(
                        raw_text=None,
                        refined_text="Result without original.",
                        timestamp=datetime(2026, 10, 16, 11, tzinfo=timezone.utc),
                    )
                )
            if "--history-large" in sys.argv:
                from datetime import timedelta

                records = store.list_records()
                base = datetime(2026, 10, 16, 14, tzinfo=timezone.utc)
                records.extend(
                    HistoryRecord(
                        raw_text=f"Isolated large row {index}: " + "é" * 16000,
                        timestamp=base + timedelta(minutes=index),
                    )
                    for index in range(45)
                )
                records.append(
                    HistoryRecord(
                        raw_text="Giant legacy " + "x" * 1100000 + " legacy end.",
                        timestamp=base + timedelta(hours=2),
                    )
                )
                store.path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "records": [record.to_mapping() for record in records],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
        dispatcher = Dispatcher(SettingsProtocol(settings))

        def read():
            for line in sys.stdin:
                dispatcher.request.emit(json.loads(line))
            app.quit()

        threading.Thread(target=read, daemon=True).start()
        try:
            result = app.exec()
        finally:
            computer.shutdown()
            settings.shutdown()
            fixtures.close()
        return result


class FixtureComputerHost:
    """Offline mobile host. Its QR and devices are synthetic test data."""

    def __init__(self):
        self.enabled = False
        self.ready = False
        self.devices = []
        self.sequence = 0
        self.relay_connected = False

    def start(self):
        # Pairing is available before processing has been configured.
        self.enabled = True

    def stop(self):
        self.enabled = False
        self.ready = False

    def create_pairing(self):
        import time

        self.sequence += 1
        return {
            "pairing_url": f"clarify://computer?data=FAKE-QR-{self.sequence}",
            "expires_at": time.time() + 300,
        }

    def snapshot(self):
        return {
            "enabled": self.enabled,
            "ready": self.ready,
            "devices": list(self.devices),
            "relay_configured": True,
            "relay_connected": self.relay_connected,
        }

    def revoke_device(self, device_id):
        self.devices = [
            device for device in self.devices if device["device_id"] != device_id
        ]


def fixture_qr(value):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="white"/><rect x="24" y="24" width="60" height="60" fill="black"/><rect x="172" y="24" width="60" height="60" fill="black"/><rect x="24" y="172" width="60" height="60" fill="black"/><text x="90" y="140" fill="black" font-size="16">FAKE QR</text><!-- '
        + value.rsplit("-", 1)[-1]
        + " --></svg>"
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


if __name__ == "__main__":
    raise SystemExit(main())
