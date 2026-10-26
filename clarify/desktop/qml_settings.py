"""Typed Qt Quick settings controller for the Clarify frontend.

The controller keeps an :class:`repositories.AppConfig` draft and exposes
only typed scalar properties and workflow-route mappings to QML.  Persistence
is delegated to ``ApplicationRepositories.config.apply`` so route validation
and atomic storage remain owned by the existing repository boundary.  Windows
autostart is handled by a small, local Run-key boundary.
"""

from __future__ import annotations

import math
import os
import platform
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot
from clarify_account import AccountService
from account_history import AccountHistory
from history_store import HistoryStore
from clarify.desktop.history_view import HistoryView
from cloud_defaults import DEFAULT_CLOUD_URL
from dictionary_snippets import (
    DictionaryEntry,
    DictionarySnippets,
    Snippet,
    MAX_SNIPPETS,
    account_snippet_entries,
    DictionarySnippetService,
    LocalDictionarySnippetsRepository,
)

from hotkey_config import (
    ActivationMode,
    HotkeyAction,
    HotkeyDefinition,
    HotkeySettings,
    HotkeySettingsController,
    HotkeyValidationError,
)
from local_asr import PROVIDER_ID as LOCAL_ASR_PROVIDER_ID
from local_asr_product import (
    LocalASRProductController,
    LocalASRProductState,
    format_requirement_bytes,
)
from microphone_controls import (
    MicrophoneInventory,
    MicrophoneSelection,
    MicrophoneSelectionState,
    MicrophoneSettings,
    RecordingControls,
    SoundDeviceMicrophoneInventory,
)
from provider_http import CancellationToken
from provider_registry import PROVIDER_REGISTRY
from provider_types import ModelCatalog, ProviderCapability, ProviderConnection
from repositories import (
    AppConfig,
    ApplicationRepositories,
    ConfigRepository,
    SUPPORTED_LANGUAGES,
    SUPPORTED_UI_MODES,
)
from workflow_config import (
    WORKFLOW_CAPABILITIES,
    WORKFLOW_SCOPES,
    WorkflowRoute,
    WorkflowScope,
)
from windows_hotkeys import supports_qt_push_to_talk as supports_push_to_talk


AUTOSTART_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = "Clarify"
_EXPECTED_LIBRARY_ENTRIES_UNSET = object()

_HOTKEY_ACTION_LABELS = {
    HotkeyAction.RECORDING: "Record / stop",
    HotkeyAction.REWRITE: "Rewrite selected text",
    HotkeyAction.TRANSLATION: "Translate selected text",
    HotkeyAction.VOICE_TRANSLATION: "Translate voice",
    HotkeyAction.VISIBILITY: "Show / hide window",
}
_HOTKEY_ACTION_ORDER = tuple(_HOTKEY_ACTION_LABELS)


def _hotkey_action(value: object) -> HotkeyAction:
    """Parse the canonical action IDs exposed to QML."""

    if isinstance(value, HotkeyAction):
        return value
    try:
        return HotkeyAction(str(value or "").strip())
    except ValueError as error:
        raise HotkeyValidationError(
            f"Unknown hotkey action: {value!r}", code="unknown_action"
        ) from error


def _qt_enum_value(value: object) -> int:
    """Read either a Qt enum or the integer QML sends through a slot."""

    raw_value = getattr(value, "value", value)
    return int(raw_value)


def _qml_hotkey_definition(
    key_code: object, modifier_flags: object
) -> HotkeyDefinition:
    """Convert a Qt Quick key event into the shared typed hotkey value."""

    key = _qt_enum_value(key_code)
    special_keys = {
        _qt_enum_value(Qt.Key.Key_Control): "CTRL",
        _qt_enum_value(Qt.Key.Key_Alt): "ALT",
        _qt_enum_value(Qt.Key.Key_Shift): "SHIFT",
        _qt_enum_value(Qt.Key.Key_Meta): "WIN",
        _qt_enum_value(Qt.Key.Key_Space): "SPACE",
        _qt_enum_value(Qt.Key.Key_Tab): "TAB",
        _qt_enum_value(Qt.Key.Key_Enter): "ENTER",
        _qt_enum_value(Qt.Key.Key_Return): "ENTER",
        _qt_enum_value(Qt.Key.Key_Escape): "ESCAPE",
        _qt_enum_value(Qt.Key.Key_Up): "UP",
        _qt_enum_value(Qt.Key.Key_Down): "DOWN",
        _qt_enum_value(Qt.Key.Key_Left): "LEFT",
        _qt_enum_value(Qt.Key.Key_Right): "RIGHT",
    }
    if key in special_keys:
        key_name = special_keys[key]
    elif ord("A") <= key <= ord("Z"):
        key_name = chr(key)
    elif ord("0") <= key <= ord("9"):
        key_name = chr(key)
    else:
        first_function_key = _qt_enum_value(Qt.Key.Key_F1)
        last_function_key = _qt_enum_value(Qt.Key.Key_F24)
        if first_function_key <= key <= last_function_key:
            key_name = f"F{key - first_function_key + 1}"
        else:
            raise HotkeyValidationError(
                "Unsupported hotkey key; choose a letter, number, function key, "
                "or navigation key",
                code="unsupported_key",
            )

    return HotkeyDefinition(
        _qml_hotkey_modifiers(modifier_flags) - {key_name.lower()}, key_name
    )


def _qml_hotkey_modifiers(modifier_flags: object) -> set[str]:
    modifiers_value = _qt_enum_value(modifier_flags)
    modifiers = []
    for name, modifier in (
        ("ctrl", Qt.KeyboardModifier.ControlModifier),
        ("alt", Qt.KeyboardModifier.AltModifier),
        ("shift", Qt.KeyboardModifier.ShiftModifier),
        ("win", Qt.KeyboardModifier.MetaModifier),
    ):
        if modifiers_value & _qt_enum_value(modifier):
            modifiers.append(name)
    return set(modifiers)


def _is_windows() -> bool:
    return sys.platform == "win32"


def _registry_module(registry: Any | None = None) -> Any:
    if registry is not None:
        return registry
    import winreg

    return winreg


def _source_qml_entrypoint() -> Path:
    """Return the source-mode QML entrypoint as an absolute path."""

    return Path(__file__).resolve().parent / "qml_app.py"


def _autostart_command(executable: str | None = None) -> str:
    executable = str(executable or sys.executable)
    arguments = [executable]
    if not getattr(sys, "frozen", False):
        arguments.append(str(_source_qml_entrypoint()))
    arguments.append("--hidden")
    return subprocess.list2cmdline(arguments)


def _set_autostart(enabled: bool, registry: Any | None = None) -> None:
    """Create or remove the current user's QML startup entry."""

    if not _is_windows():
        return
    registry = _registry_module(registry)
    with registry.CreateKey(
        registry.HKEY_CURRENT_USER,
        AUTOSTART_REGISTRY_PATH,
    ) as key:
        if enabled:
            registry.SetValueEx(
                key,
                AUTOSTART_VALUE_NAME,
                0,
                registry.REG_SZ,
                _autostart_command(),
            )
        else:
            try:
                registry.DeleteValue(key, AUTOSTART_VALUE_NAME)
            except FileNotFoundError:
                pass


def _autostart_registry_state(
    registry: Any | None = None,
) -> tuple[bool, Any | None, Any | None]:
    """Capture the current Run value, including its Registry type."""

    if not _is_windows():
        return False, None, None
    registry = _registry_module(registry)
    try:
        with registry.OpenKey(
            registry.HKEY_CURRENT_USER,
            AUTOSTART_REGISTRY_PATH,
        ) as key:
            value, kind = registry.QueryValueEx(key, AUTOSTART_VALUE_NAME)
        return True, value, kind
    except OSError:
        return False, None, None


def _restore_autostart_registry_state(
    state: tuple[bool, Any | None, Any | None],
    registry: Any | None = None,
) -> None:
    """Restore a captured Run value without changing its Registry type."""

    if not _is_windows():
        return
    registry = _registry_module(registry)
    exists, value, kind = state
    with registry.CreateKey(
        registry.HKEY_CURRENT_USER,
        AUTOSTART_REGISTRY_PATH,
    ) as key:
        if exists:
            registry.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, kind, value)
        else:
            try:
                registry.DeleteValue(key, AUTOSTART_VALUE_NAME)
            except FileNotFoundError:
                pass


def _apply_config_with_autostart_transaction(
    config: AppConfig,
    repositories: ApplicationRepositories,
    registry: Any | None = None,
) -> AppConfig:
    """Persist QML settings and the Windows Run entry as one operation."""

    if not _is_windows():
        return repositories.config.apply(config)

    previous_registry_state = _autostart_registry_state(registry)
    try:
        _set_autostart(config.startup.autostart, registry)
        return repositories.config.apply(config)
    except Exception:
        try:
            _restore_autostart_registry_state(previous_registry_state, registry)
        except OSError:
            pass
        raise


def _default_local_asr_product() -> LocalASRProductController:
    """Build the Settings-owned lifecycle around the shared local adapter."""

    adapter = PROVIDER_REGISTRY.adapter(LOCAL_ASR_PROVIDER_ID)
    backend = getattr(adapter, "backend", None)
    installer = getattr(backend, "installer", None)
    if hasattr(adapter, "engines"):
        from local_asr_catalog import ModelInstaller

        installer = ModelInstaller("ggml-small", adapter.engines)
    return LocalASRProductController(installer=installer, backend=backend)


def _format_local_requirements(requirements: dict[str, Any]) -> str:
    """Return a compact, user-facing summary without exposing file paths."""

    download = format_requirement_bytes(requirements.get("download_bytes", 0))
    disk = format_requirement_bytes(requirements.get("disk_bytes", 0))
    memory = format_requirement_bytes(requirements.get("memory_bytes", 0))
    platform = str(requirements.get("platform", "Windows x64"))
    compute = str(requirements.get("compute", "")).strip()
    runtime = str(requirements.get("runtime", "")).strip()
    details = " · ".join(value for value in (compute, runtime) if value)
    suffix = f" · {details}" if details else ""
    return f"{platform} · {download} download · {disk} disk · {memory} RAM{suffix}"


def _default_microphone_inventory_source() -> Any | None:
    """Build the optional PortAudio inventory without making it a hard import."""

    try:
        import sounddevice
    except (ImportError, OSError):
        return None
    return SoundDeviceMicrophoneInventory(sounddevice)


def _read_microphone_inventory(backend, source):
    """Read hardware on the discovery worker, without retaining its Qt owner."""

    backend_snapshot = getattr(backend, "microphone_inventory", None)
    if callable(backend_snapshot):
        inventory = backend_snapshot()
    else:
        if source is None:
            source = _default_microphone_inventory_source()
        inventory = (
            source.snapshot()
            if source is not None
            else MicrophoneInventory.unavailable("portaudio_unavailable")
        )
    if not isinstance(inventory, MicrophoneInventory):
        raise TypeError("microphone inventory source returned an invalid snapshot")
    return inventory, source


class _SettingsMailbox:
    """Coalesce worker data without giving a worker a Qt object reference."""

    def __init__(self):
        self._lock = threading.Lock()
        self._closed = False
        self._pending: dict[str, tuple[int, Any]] = {}

    def post(self, kind: str, generation: int, payload: Any) -> None:
        with self._lock:
            if self._closed:
                return
            previous = self._pending.get(kind)
            if previous is None or generation >= previous[0]:
                self._pending[kind] = (generation, payload)

    def take(self) -> dict[str, tuple[int, Any]]:
        with self._lock:
            pending, self._pending = self._pending, {}
            return pending

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending.clear()


def _merge_library_draft(before, draft, persisted, key):
    """Keep pending row/field edits and adopt untouched synchronized values.

    The domain validates uniqueness and the combined size. Unlike account sync's
    whole-row conflict policy, a text draft must also adopt newer saved flags.
    Keep draft order so an explicit Save can return its row identities in order.
    """
    if draft == before:
        return persisted
    if persisted == before:
        return draft
    baseline = {getattr(item, key).casefold(): item for item in before}
    current = {getattr(item, key).casefold(): item for item in persisted}
    edited = {getattr(item, key).casefold() for item in draft}
    merged = []
    for item in draft:
        identity = getattr(item, key).casefold()
        original, latest = baseline.get(identity), current.get(identity)
        if item == original:
            if latest is not None:
                merged.append(latest)
        elif original is not None and latest is not None:
            previous = original.to_mapping()
            merged.append(
                type(item).from_mapping(
                    {
                        field: latest.to_mapping()[field]
                        if value == previous[field]
                        else value
                        for field, value in item.to_mapping().items()
                    }
                )
            )
        else:
            merged.append(item)
    # An omitted baseline row is a pending deletion, not a remote addition.
    merged.extend(
        item
        for identity, item in current.items()
        if identity not in baseline and identity not in edited
    )
    return tuple(merged)


class QmlSettingsController(QObject):
    accountStateChanged = Signal()
    _accountFinished = Signal(object)
    _libraryPreferenceSynced = Signal(str, str)
    """Expose the typed application configuration to Qt Quick.

    The object owns an editable draft.  ``load`` replaces that draft
    from the configured repository, while ``save`` delegates the complete
    ``AppConfig`` to the repository's atomic ``apply`` operation. Discrete
    ``savePreference`` commands persist only their explicit fields. No legacy
    window or frontend is involved; Windows startup is handled by the local
    Run-key transaction only when settings are saved.
    """

    configChanged = Signal()
    updatesChanged = Signal()
    routeChanged = Signal()
    selectedScopeChanged = Signal()
    dirtyChanged = Signal()
    errorChanged = Signal()
    loaded = Signal()
    saved = Signal()
    providerStateChanged = Signal()
    modelCatalogChanged = Signal()
    _modelDiscoveryFinished = Signal(int, object, object)
    microphoneChanged = Signal()
    microphoneTestChanged = Signal()
    microphoneLevelChanged = Signal()
    hotkeyChanged = Signal()
    _providerValidationFinished = Signal(str, int, bool, object)
    _localBenchmarkPublished = Signal(str)
    _microphoneTestFinished = Signal(int, bool, object)
    _microphoneLevelPublished = Signal(int, float)

    def __init__(
        self,
        repositories: ApplicationRepositories,
        parent: QObject | None = None,
        *,
        registry: Any | None = None,
        local_product: LocalASRProductController | None = None,
        microphone_backend: Any | None = None,
        microphone_inventory_source: Any | None = None,
        hotkey_applier: Callable[[HotkeySettings], Any] | None = None,
        hotkey_capture_changed: Callable[[bool], None] | None = None,
        dictionary_service: DictionarySnippetService | None = None,
        account_service=None,
        account_can_change=None,
    ) -> None:
        super().__init__(parent)
        self._background_mailbox = _SettingsMailbox()
        self._background_timer = QTimer(self)
        self._background_timer.setInterval(25)
        self._background_timer.timeout.connect(self._drain_background_publications)
        self._updates = None
        self.repositories = repositories
        self._account = account_service or AccountService(
            Path(repositories.config.path).parent,
            default_endpoint=os.environ.get("CLARIFY_CLOUD_URL", DEFAULT_CLOUD_URL),
        )
        self._account_can_change = account_can_change or (lambda: True)
        self._history = getattr(self._account, "history", None)
        if self._history is None and isinstance(self._account, AccountService):
            self._history = AccountHistory(
                self._account,
                HistoryStore(Path(repositories.config.path).parent / "history.json"),
            )
            self._account.history = self._history
        self._history_view = (
            HistoryView(self._history) if self._history is not None else None
        )
        self._account_busy = False
        self._account_error = ""
        self._account_shutdown = False
        self._account_social = False
        self._account_cancel = threading.Event()
        self._library_sync_pending = False
        self._library_sync_context = None
        self._library_sync_timer = QTimer(self)
        self._library_sync_timer.setSingleShot(True)
        self._library_sync_timer.setInterval(1000)
        self._library_sync_timer.timeout.connect(self._sync_library_preferences)
        self._accountFinished.connect(
            self._finish_account, Qt.ConnectionType.QueuedConnection
        )
        self._libraryPreferenceSynced.connect(
            self._finish_library_preference_sync, Qt.ConnectionType.QueuedConnection
        )
        self._config_repository: ConfigRepository = repositories.config
        self._dictionary_service = dictionary_service or DictionarySnippetService(
            LocalDictionarySnippetsRepository(
                Path(repositories.config.path).parent / "dictionary.json"
            )
        )
        self._dictionary_draft = self._dictionary_service.state
        self._dictionary_baseline = self._dictionary_draft
        self._snippet_draft_context = self.snippetContext
        self._autostart_registry = registry
        self._local_product = local_product or _default_local_asr_product()
        self._local_state: LocalASRProductState = self._local_product.state
        self._local_profile = "ggml-small"
        self._local_device = "cpu"
        self._local_generation = 0
        self._local_benchmark_busy = False
        self._local_benchmark_detail = ""
        self._local_benchmark_token = None
        self._local_devices = [
            {"id": "auto", "label": "Automatic"},
            {"id": "cpu", "label": "CPU"},
        ]
        self._hotkey_applier = hotkey_applier
        self._hotkey_reapply_required = False
        self._hotkey_capture_changed = hotkey_capture_changed
        self._microphone_backend = microphone_backend
        self._microphone_inventory_source = microphone_inventory_source or getattr(
            microphone_backend, "microphone_inventory_source", None
        )
        self._microphone_inventory = MicrophoneInventory.unavailable("not_refreshed")
        self._microphone_inventory_busy = False
        self._microphone_inventory_generation = 0
        self._microphone_inventory_shutdown = False
        self._microphone_inventory_error_before = ""
        self._microphone_inventory_thread: threading.Thread | None = None
        self._microphone_test_generation = 0
        self._microphone_test_busy = False
        self._microphone_test_level = 0.0
        self._microphone_test_cancel = threading.Event()
        self._microphone_test_thread: threading.Thread | None = None
        self._microphone_test_status = ""
        self._microphone_test_kind = "info"
        self._provider_activity: dict[str, dict[str, Any]] = {}
        self._provider_tokens: dict[str, CancellationToken] = {}
        self._provider_generations: dict[str, int] = {}
        self._model_catalogs: dict[tuple[str, str, str], Any] = {}
        self._model_generation = 0
        self._model_token: CancellationToken | None = None
        self._model_loading_key = None
        self._model_error_key = None
        self._selected_scope = WorkflowScope.TRANSCRIPTION.value
        self._config = self._config_repository.load()
        configured_provider = (
            str(self._config.selection.transcription_provider or "gemini")
            .strip()
            .lower()
        )
        self._selected_provider_id = (
            configured_provider
            if configured_provider in PROVIDER_REGISTRY.provider_ids
            else PROVIDER_REGISTRY.provider_ids[0]
        )
        self._hotkey_settings_controller = HotkeySettingsController(
            self._config.hotkeys,
            push_to_talk_supported=supports_push_to_talk(),
        )
        self._hotkey_capture_action = ""
        self._provider_api_key_draft = ""
        self._provider_base_url_draft = self._config_provider_base_url(
            self._selected_provider_id
        )
        self._dirty = False
        self._last_error = ""
        self._providerValidationFinished.connect(
            self._finish_provider_validation,
            Qt.ConnectionType.QueuedConnection,
        )
        self._microphoneTestFinished.connect(
            self._finish_microphone_test,
            Qt.ConnectionType.QueuedConnection,
        )
        self._microphoneLevelPublished.connect(
            self._apply_microphone_level, Qt.ConnectionType.QueuedConnection
        )
        self._local_state_listener = self._local_state_callback(0)
        self._local_product.subscribe(self._local_state_listener)
        self._localBenchmarkPublished.connect(
            self._finish_local_benchmark, Qt.ConnectionType.QueuedConnection
        )
        mailbox = self._background_mailbox

        def inventory():
            from local_asr_catalog import devices

            values = devices()
            mailbox.post("local_devices", 0, values)

        self._local_inventory_thread = threading.Thread(
            target=inventory, daemon=True, name="LocalASRDevices"
        )
        self._local_inventory_thread.start()
        self._modelDiscoveryFinished.connect(
            self._finish_model_discovery, Qt.ConnectionType.QueuedConnection
        )
        # Forward signals without retaining a Python bound emit callback.
        self.routeChanged.connect(self.modelCatalogChanged)
        self.providerStateChanged.connect(self.modelCatalogChanged)
        if local_product is None:
            from local_asr_catalog import MODELS

            model = self._config.local_asr.audio_model
            if model in MODELS:
                self._browse_local(model, self._config.local_asr_device)
            else:
                self._local_product.refresh_async()
        else:
            self._local_product.refresh_async()
        self.refreshMicrophoneInventory()
        self._background_timer.start()

    @Slot()
    def _drain_background_publications(self):
        for kind, (generation, payload) in self._background_mailbox.take().items():
            if self._account_shutdown:
                return
            if kind == "microphone_inventory":
                self._finish_microphone_inventory(generation, payload)
            elif kind == "local_state":
                self._apply_local_state((generation, payload))
            elif kind == "local_devices":
                self._apply_local_devices(payload)

    @Property("QStringList", constant=True)
    def workflowScopes(self) -> list[str]:
        """Canonical route identifiers available to the settings form."""

        return list(WORKFLOW_SCOPES)

    @Property("QStringList", constant=True)
    def modes(self) -> list[str]:
        return list(SUPPORTED_UI_MODES)

    @Property("QStringList", constant=True)
    def languages(self) -> list[str]:
        return list(SUPPORTED_LANGUAGES)

    @Property("QStringList", constant=True)
    def providerIds(self) -> list[str]:
        return list(PROVIDER_REGISTRY.provider_ids)

    @Property("QVariantList", notify=hotkeyChanged)
    def hotkeyActions(self) -> list[dict[str, Any]]:
        """Return the complete, ordered hotkey catalog for the QML form."""

        return [self._hotkey_mapping(action) for action in _HOTKEY_ACTION_ORDER]

    @Property("QVariantMap", notify=hotkeyChanged)
    def hotkeyDefinitions(self) -> dict[str, dict[str, Any]]:
        """Expose canonical definitions without moving validation into QML."""

        return {
            action.value: self._hotkey_mapping(action)
            for action in _HOTKEY_ACTION_ORDER
        }

    @Property("QStringList", constant=True)
    def hotkeyActivationModes(self) -> list[str]:
        return [mode.value for mode in ActivationMode]

    @Property(str, notify=hotkeyChanged)
    def hotkeyActivationMode(self) -> str:
        return self._hotkey_settings_controller.settings.activation_mode.value

    @Property(bool, constant=True)
    def hotkeyPushToTalkSupported(self) -> bool:
        return self._hotkey_settings_controller.push_to_talk_supported

    @Property(str, notify=hotkeyChanged)
    def hotkeyCaptureAction(self) -> str:
        return self._hotkey_capture_action

    @Property("QVariantMap", notify=providerStateChanged)
    def providerStates(self) -> dict[str, dict[str, Any]]:
        return {
            provider_id: self._provider_state(provider_id)
            for provider_id in PROVIDER_REGISTRY.provider_ids
        }

    @Property(str, notify=providerStateChanged)
    def selectedProviderId(self) -> str:
        return self._selected_provider_id

    @Property(str, notify=providerStateChanged)
    def providerDisplayName(self) -> str:
        return PROVIDER_REGISTRY.describe(self._selected_provider_id).display_name

    @Property(str, notify=providerStateChanged)
    def providerApiKey(self) -> str:
        """Return only the editable key draft, never the stored secret."""

        return self._provider_api_key_draft

    @providerApiKey.setter
    def providerApiKey(self, value: str) -> None:
        self.setProviderApiKey(value)

    @Property(bool, notify=providerStateChanged)
    def providerDirty(self) -> bool:
        return bool(self._provider_api_key_draft) or (
            self._provider_base_url_draft
            != self._config_provider_base_url(self._selected_provider_id)
        )

    @Property(str, notify=providerStateChanged)
    def providerBaseUrl(self) -> str:
        return self._provider_base_url_draft

    @providerBaseUrl.setter
    def providerBaseUrl(self, value: str) -> None:
        self.setProviderBaseUrl(value)

    @Property(bool, notify=providerStateChanged)
    def providerHasApiKey(self) -> bool:
        return bool(
            self._provider_api_key_draft.strip()
            or self._provider_config(self._selected_provider_id).api_key.strip()
        )

    @Property(bool, notify=providerStateChanged)
    def providerSupportsCustomEndpoint(self) -> bool:
        return PROVIDER_REGISTRY.supports(
            self._selected_provider_id,
            ProviderCapability.CUSTOM_BASE_URL,
        )

    @Property(str, notify=providerStateChanged)
    def providerStatus(self) -> str:
        return str(self._provider_state(self._selected_provider_id)["status"])

    @Property(str, notify=providerStateChanged)
    def providerError(self) -> str:
        return str(self._provider_state(self._selected_provider_id).get("error", ""))

    @Property(bool, notify=providerStateChanged)
    def providerBusy(self) -> bool:
        return bool(self._provider_state(self._selected_provider_id).get("busy"))

    @Property(str, notify=providerStateChanged)
    def localAsrStatus(self) -> str:
        return self._local_state.status

    @Property(str, notify=providerStateChanged)
    def localAsrDetail(self) -> str:
        return self._local_state.detail

    @Property(str, notify=providerStateChanged)
    def localAsrRequirements(self) -> str:
        return _format_local_requirements(self._local_state.requirements or {})

    @Property(float, notify=providerStateChanged)
    def localAsrProgress(self) -> float:
        return self._local_state.fraction

    @Property(bool, notify=providerStateChanged)
    def localAsrBusy(self) -> bool:
        # Terminal state can arrive before the worker's finally block clears busy.
        return self._local_state.status in {"checking", "installing", "removing"}

    @Property(str, notify=configChanged)
    def mode(self) -> str:
        return self._config.ui.mode

    @mode.setter
    def mode(self, value: str) -> None:
        self.setMode(value)

    @Property(str, notify=configChanged)
    def language(self) -> str:
        return self._config.ui.language

    @language.setter
    def language(self, value: str) -> None:
        self.setLanguage(value)

    @Property(bool, notify=configChanged)
    def autostart(self) -> bool:
        return self._config.startup.autostart

    @autostart.setter
    def autostart(self, value: bool) -> None:
        self.setAutostart(value)

    @Property(bool, notify=configChanged)
    def historyEnabled(self) -> bool:
        return self._config.history_enabled

    @historyEnabled.setter
    def historyEnabled(self, value: bool) -> None:
        self.setHistoryEnabled(value)

    def bindUpdates(self, updates) -> None:
        """Bind the composition-owned updater; draft edits have no side effects."""
        self._updates = updates
        updates.changed.connect(self.updatesChanged)
        self.updatesChanged.emit()

    @Property(bool, notify=configChanged)
    def automaticUpdates(self) -> bool:
        return self._config.automatic_updates

    @Property(str, constant=True)
    def applicationVersion(self) -> str:
        from version import __version__

        return __version__

    @Property(bool, notify=updatesChanged)
    def updateAvailable(self) -> bool:
        return self._updates is not None and self._updates.available

    @Property(bool, notify=updatesChanged)
    def updateBusy(self) -> bool:
        return self._updates is not None and self._updates.busy

    @Property(bool, notify=updatesChanged)
    def updateInstalling(self) -> bool:
        return self._updates is not None and self._updates.installing

    @Property(bool, notify=updatesChanged)
    def updateSupported(self) -> bool:
        return self._updates is not None and self._updates.supported

    @Property(str, notify=updatesChanged)
    def updateVersion(self) -> str:
        return self._updates.version if self._updates is not None else ""

    @Property(str, notify=updatesChanged)
    def updateStatus(self) -> str:
        return (
            self._updates.status
            if self._updates is not None
            else "A atualização requer a versão portátil para Windows."
        )

    @Property(int, notify=updatesChanged)
    def updateProgress(self) -> int:
        return self._updates.progress if self._updates is not None else 0

    @Slot(bool, result=bool)
    def setAutomaticUpdates(self, value: bool) -> bool:
        if not isinstance(value, bool):
            self._set_error(ValueError("A opção de atualização deve ser um booleano."))
            return False
        return self._update_config(replace(self._config, automatic_updates=value))

    @Slot(result=bool)
    def checkForUpdates(self) -> bool:
        return self._updates is not None and self._updates.check()

    @Slot(result=bool)
    def installUpdate(self) -> bool:
        return self._updates is not None and self._updates.install()

    @Property("QVariant", notify=configChanged)
    def historyRetentionDays(self) -> int | None:
        return self._config.history_retention_days

    @historyRetentionDays.setter
    def historyRetentionDays(self, value: object) -> None:
        self.setHistoryRetentionDays(value)

    @Property("QVariant", notify=microphoneChanged)
    def selectedMicrophoneId(self) -> str | None:
        """Return the draft's stable microphone identity, if one is set."""

        return self._config.microphone.selected_id

    @Property("QVariantList", notify=microphoneChanged)
    def microphoneDevices(self) -> list[dict[str, Any]]:
        """Return a QML-friendly default option plus safe input endpoints."""

        options: list[dict[str, Any]] = [
            {
                "id": "",
                "label": "System default",
                "name": "System default",
                "hostApi": "",
                "isDefault": True,
            }
        ]
        for device in self._microphone_selectable_devices():
            label = device.name
            if device.host_api:
                label = f"{label} · {device.host_api}"
            if any(option["label"] == label for option in options):
                label = f"{label} · {device.stable_id[-6:]}"
            options.append(
                {
                    "id": device.stable_id,
                    "label": label,
                    "name": device.name,
                    "hostApi": device.host_api,
                    "isDefault": bool(device.is_default),
                }
            )
        return options

    @Property(int, notify=microphoneChanged)
    def microphoneSelectionIndex(self) -> int:
        selected = self._config.microphone.selected_id
        if selected:
            for index, option in enumerate(self.microphoneDevices):
                if option.get("id") == selected:
                    return index
        # A stale or backend-unsafe identity is deliberately shown as the
        # recoverable System default option until the user chooses a new one.
        return 0

    @Property("QVariantMap", notify=microphoneChanged)
    def microphoneInventory(self) -> dict[str, Any]:
        return self._microphone_inventory.to_mapping()

    @Property(str, notify=microphoneChanged)
    def microphoneSelectionState(self) -> str:
        return self._microphone_selection().state.value

    @Property(str, notify=microphoneChanged)
    def microphoneStatus(self) -> str:
        return self._microphone_status()[0]

    @Property(str, notify=microphoneChanged)
    def microphoneStatusKind(self) -> str:
        return self._microphone_status()[1]

    @Property(str, notify=microphoneTestChanged)
    def microphoneTestStatus(self) -> str:
        return self._microphone_test_status

    @Property(str, notify=microphoneTestChanged)
    def microphoneTestStatusKind(self) -> str:
        return self._microphone_test_kind

    @Property(bool, notify=microphoneTestChanged)
    def microphoneTestBusy(self) -> bool:
        return self._microphone_test_busy

    @Property(bool, notify=microphoneChanged)
    def microphoneInventoryBusy(self) -> bool:
        return self._microphone_inventory_busy

    @Property(float, notify=microphoneLevelChanged)
    def microphoneTestLevel(self) -> float:
        return self._microphone_test_level

    @Property(bool, notify=microphoneTestChanged)
    def microphoneTestStopping(self) -> bool:
        return self._microphone_test_busy and self._microphone_test_cancel.is_set()

    @Property("QVariantMap", notify=microphoneChanged)
    def recordingControls(self) -> dict[str, Any]:
        """Expose the typed boundary settings without recreating their rules."""

        return self._config.recording_controls.to_mapping()

    @Property(str, notify=configChanged)
    def dictationCleanupLevel(self) -> str:
        level = self._config.dictation_cleanup_level
        return level.value if level is not None else ""

    @Property(bool, notify=configChanged)
    def dictationCleanupRefinementAllowed(self) -> bool:
        if getattr(self._account, "managed", False) is True:
            return getattr(self._account, "signed_in", False) is True
        local = self._config.workflow("transcription").provider_id == "local_asr"
        scope = "local_asr_refinement" if local else "refinement"
        return self._config.workflow(scope).enabled and (
            not local or self._config.local_asr_cloud_refinement
        )

    @Property(bool, notify=configChanged)
    def localAsrCloudRefinement(self) -> bool:
        return self._config.local_asr_cloud_refinement

    @localAsrCloudRefinement.setter
    def localAsrCloudRefinement(self, value: bool) -> None:
        self.setLocalAsrCloudRefinement(value)

    @Property(str, notify=selectedScopeChanged)
    def selectedScope(self) -> str:
        return self._selected_scope

    @selectedScope.setter
    def selectedScope(self, value: str) -> None:
        self.selectWorkflow(value)

    @Property(str, notify=routeChanged)
    def routeProviderId(self) -> str:
        return self._selected_route().provider_id

    @routeProviderId.setter
    def routeProviderId(self, value: str) -> None:
        self.setRouteProviderId(value)

    @Property(str, notify=routeChanged)
    def routeModelId(self) -> str:
        return self._selected_route().model_id

    @routeModelId.setter
    def routeModelId(self, value: str) -> None:
        self.setRouteModelId(value)

    @Property(str, notify=routeChanged)
    def routePrompt(self) -> str:
        return self._selected_route().prompt

    @routePrompt.setter
    def routePrompt(self, value: str) -> None:
        self.setRoutePrompt(value)

    @Property(str, notify=routeChanged)
    def routeCustomEndpoint(self) -> str:
        return self._selected_route().custom_endpoint

    @routeCustomEndpoint.setter
    def routeCustomEndpoint(self, value: str) -> None:
        self.setRouteCustomEndpoint(value)

    @Property(bool, notify=routeChanged)
    def routeEnabled(self) -> bool:
        return self._selected_route().enabled

    @routeEnabled.setter
    def routeEnabled(self, value: bool) -> None:
        self.setRouteEnabled(value)

    @Property("QVariantMap", notify=configChanged)
    def routes(self) -> dict[str, dict[str, Any]]:
        """Return all typed routes in a QML-friendly, non-secret mapping."""

        return {
            scope: self._route_mapping(self._config.workflow(scope), scope)
            for scope in WORKFLOW_SCOPES
        }

    @Property(bool, notify=dirtyChanged)
    def dirty(self) -> bool:
        return self._dirty or self._dictionary_draft != self._dictionary_service.state

    @Property("QVariantList", notify=dirtyChanged)
    def dictionaryEntries(self):
        return [entry.to_mapping() for entry in self._dictionary_draft.dictionary]

    def library_snapshot(self):
        """Pair web rows with their owner even before queued account completion."""
        with self._dictionary_service.transaction():
            context = self.snippetContext
            current = context == self._snippet_draft_context
            return {
                "dictionaryContext": context,
                "snippetContext": context,
                "dictionaryEntries": self.dictionaryEntries if current else [],
                "snippets": self.snippets if current else [],
            }

    def _require_library_context(self, context):
        """Call only under the service's account-before-library guard."""
        if (
            not isinstance(context, str)
            or context != self.snippetContext
            or context != self._snippet_draft_context
            or (self._account_busy and self._library_sync_context is None)
        ):
            raise ValueError("A conta mudou. Descarte as alterações e tente novamente.")

    def _reconcile_library_draft(self, persisted=None):
        """Rebase actual pending edits on storage without writing either copy."""
        persisted = (
            persisted if persisted is not None else self._dictionary_service.state
        )
        before = self._dictionary_baseline
        draft = self._dictionary_draft
        reconciled = replace(
            draft,
            dictionary=_merge_library_draft(
                before.dictionary, draft.dictionary, persisted.dictionary, "term"
            ),
            snippets=_merge_library_draft(
                before.snippets, draft.snippets, persisted.snippets, "trigger"
            ),
        )
        self._dictionary_draft = reconciled
        self._dictionary_baseline = persisted

    def _require_expected_library_entries(self, library, expected):
        """Compare the captured persisted rows under the staging owner guard."""
        if expected is _EXPECTED_LIBRARY_ENTRIES_UNSET:
            return
        try:
            if type(expected) is not list or len(expected) > MAX_SNIPPETS:
                raise ValueError()
            entry_type = DictionaryEntry if library == "dictionary" else Snippet
            entries = tuple(entry_type.from_mapping(item) for item in expected)
            DictionarySnippets(**{library: entries})
            if [item.to_mapping() for item in entries] != expected:
                raise ValueError()
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid settings value") from error
        persisted = self._dictionary_service.reload()
        if entries != getattr(persisted, library):
            raise ValueError("A biblioteca mudou. Atualize e tente novamente.")

    @Slot("QVariantList", result=bool)
    @Slot("QVariantList", str, result=bool)
    @Slot("QVariantList", str, "QVariantList", result=bool)
    def setDictionaryEntries(
        self, entries, context=None, expectedEntries=_EXPECTED_LIBRARY_ENTRIES_UNSET
    ) -> bool:
        context = self._snippet_draft_context if context is None else context
        try:
            with self._dictionary_service.transaction(expected_context=context):
                self._require_library_context(context)
                self._require_expected_library_entries("dictionary", expectedEntries)
                try:
                    if not isinstance(entries, list) or len(entries) > 512:
                        raise ValueError("Use até 512 termos no dicionário.")
                    self._dictionary_draft = DictionarySnippets(
                        dictionary=tuple(
                            DictionaryEntry.from_mapping(entry) for entry in entries
                        ),
                        snippets=self._dictionary_draft.snippets,
                    )
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        "Verifique os termos: use até 256 caracteres, sem duplicatas ou quebras de linha."
                    ) from error
        except Exception as error:
            self._set_error(error)
            return False
        self._set_error(None)
        self.dirtyChanged.emit()
        return True

    @Property(str, notify=accountStateChanged)
    def snippetContext(self):
        if isinstance(self._account, AccountService):
            return self._account.snippet_context()
        scope = getattr(self._account, "scope", None)
        if not isinstance(scope, str) or not scope:
            return "local"
        import hashlib

        identity = self._account.snapshot()
        return hashlib.sha256(
            (str(identity.get("endpoint", "")) + "\n" + scope).encode("utf-8")
        ).hexdigest()

    @Property(str, notify=accountStateChanged)
    def dictionaryContext(self):
        return self.snippetContext

    @Property("QVariantList", notify=dirtyChanged)
    def snippets(self):
        return [snippet.to_mapping() for snippet in self._dictionary_draft.snippets]

    @Slot("QVariantList", str, result=bool)
    @Slot("QVariantList", str, "QVariantList", result=bool)
    def setSnippets(
        self, snippets, context, expectedEntries=_EXPECTED_LIBRARY_ENTRIES_UNSET
    ) -> bool:
        try:
            with self._dictionary_service.transaction(expected_context=context):
                self._require_library_context(context)
                self._require_expected_library_entries("snippets", expectedEntries)
                try:
                    if not isinstance(snippets, list) or len(snippets) > MAX_SNIPPETS:
                        raise ValueError("Use até 512 snippets.")
                    draft = DictionarySnippets(
                        dictionary=self._dictionary_draft.dictionary,
                        snippets=tuple(Snippet.from_mapping(item) for item in snippets),
                    )
                    if any(not item.replacement.strip() for item in draft.snippets):
                        raise ValueError("Snippet text must not be empty")
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        "Verifique os snippets: frases únicas de até 256 caracteres, "
                        "sem quebras de linha, e textos de até 4096 caracteres."
                    ) from error
                if self._account.scope:
                    account_snippet_entries(draft.snippets)
                self._dictionary_draft = draft
        except Exception as error:
            self._set_error(error)
            return False
        self._set_error(None)
        self.dirtyChanged.emit()
        return True

    @Slot(str, "QVariantMap", str, bool, str, result=bool)
    def saveLibraryPreference(self, library, identity, field, value, context) -> bool:
        """Change one persisted flag under its owner guard; never save draft text."""
        if (
            type(library) is not str
            or type(identity) is not dict
            or type(field) is not str
            or type(value) is not bool
            or type(context) is not str
            or library not in {"dictionary", "snippets"}
            or field
            not in (
                {"enabled"}
                if library == "dictionary"
                else {"enabled", "case_sensitive"}
            )
        ):
            self._set_error(ValueError("Invalid settings value"))
            return False
        try:
            entry = (
                DictionaryEntry.from_mapping(identity)
                if library == "dictionary"
                else Snippet.from_mapping(identity)
            )
            if entry.to_mapping() != identity:
                raise ValueError()
        except (TypeError, ValueError):
            self._set_error(ValueError("Invalid settings value"))
            return False
        try:
            with self._dictionary_service.transaction(expected_context=context):
                self._require_library_context(context)
                persisted = self._dictionary_service.reload()
                entries = (
                    persisted.dictionary
                    if library == "dictionary"
                    else persisted.snippets
                )
                matches = [
                    index
                    for index, item in enumerate(entries)
                    if item.to_mapping() == identity
                ]
                if len(matches) != 1:
                    raise ValueError("A entrada mudou. Atualize e tente novamente.")
                index = matches[0]
                updated = (
                    *entries[:index],
                    replace(entries[index], **{field: value}),
                    *entries[index + 1 :],
                )
                candidate = replace(persisted, **{library: updated})
                self._reconcile_library_draft(persisted)
                self._dictionary_service.replace(candidate, expected_context=context)

                # Persistence requires the full identity. The draft merge key
                # only locates the row whose saved flag changed.
                key = "term" if library == "dictionary" else "trigger"
                draft_entries = tuple(
                    replace(item, **{field: value})
                    if getattr(item, key).casefold() == identity[key].casefold()
                    else item
                    for item in getattr(self._dictionary_draft, library)
                )
                self._dictionary_draft = replace(
                    self._dictionary_draft, **{library: draft_entries}
                )
                self._dictionary_baseline = candidate
        except Exception as error:
            self._set_error(error)
            return False

        self._set_error(None)
        self.dirtyChanged.emit()
        self.saved.emit()
        self._sync_library_preferences()
        return True

    def _sync_library_preferences(self):
        """Use account sync without its draft-replacing sign-in completion path."""
        if not self._account.scope or self._account_shutdown:
            self._library_sync_pending = False
            self._library_sync_timer.stop()
            return
        if (
            self._account_busy
            or not self._account_can_change()
            or not self._account.begin_change()
        ):
            self._library_sync_pending = True
            self._library_sync_timer.start()
            return
        self._library_sync_pending = False
        self._library_sync_timer.stop()
        context = self._snippet_draft_context
        try:
            with self._dictionary_service.transaction(expected_context=context):
                self._require_library_context(context)
                self._reconcile_library_draft()
                self._library_sync_context = context
        except Exception as error:
            self._account.end_change()
            self._set_error(error)
            return
        self._account_busy, self._account_error = True, ""
        self.accountStateChanged.emit()

        def perform():
            error = ""
            try:
                self._account.sync_library(self._dictionary_service)
            except Exception as problem:
                from clarify_account import AccountError

                error = (
                    str(problem)
                    if isinstance(problem, AccountError)
                    else "Não foi possível sincronizar a biblioteca."
                )
            if not self._account_shutdown:
                self._libraryPreferenceSynced.emit(context, error)

        threading.Thread(
            target=perform, name="ClarifyLibraryPreference", daemon=True
        ).start()

    @Slot(str, str)
    def _finish_library_preference_sync(self, context, error):
        if self._account_shutdown or context != self._library_sync_context:
            return
        try:
            with self._dictionary_service.transaction(expected_context=context):
                self._require_library_context(context)
                # A failed sync can still have imported dictionary rows before
                # its snippets request failed. Reconcile that durable result too.
                self._reconcile_library_draft()
        except Exception:
            error = error or "A biblioteca mudou. Atualize e tente novamente."
        finally:
            self._library_sync_context = None
            self._account_busy, self._account_error = False, error
            self._account.end_change()
        self.accountStateChanged.emit()
        self.dirtyChanged.emit()
        if self._library_sync_pending:
            self._sync_library_preferences()

    @Property(str, notify=errorChanged)
    def lastError(self) -> str:
        return self._last_error

    @Slot(str, result=bool)
    def selectWorkflow(self, scope: str) -> bool:
        try:
            normalized = self._canonical_scope(scope)
        except ValueError as error:
            self._set_error(error)
            return False
        self._set_error(None)
        if normalized == self._selected_scope:
            return True
        self._selected_scope = normalized
        self.selectedScopeChanged.emit()
        self.routeChanged.emit()
        return True

    @Slot(str, result=bool)
    def setMode(self, value: str) -> bool:
        try:
            self._choice(value, (*SUPPORTED_UI_MODES, "transcription"), "mode")
            normalized = "prompt"
        except ValueError as error:
            self._set_error(error)
            return False
        return self._update_config(
            replace(self._config, ui=replace(self._config.ui, mode=normalized))
        )

    @Slot(str, result=bool)
    def setLanguage(self, value: str) -> bool:
        try:
            normalized = self._choice(value, SUPPORTED_LANGUAGES, "language")
        except ValueError as error:
            self._set_error(error)
            return False
        return self._update_config(
            replace(
                self._config,
                ui=replace(self._config.ui, language=normalized),
            )
        )

    @Slot(bool, result=bool)
    def setAutostart(self, value: bool) -> bool:
        return self._update_config(
            replace(
                self._config,
                startup=replace(self._config.startup, autostart=bool(value)),
            )
        )

    @Slot(bool, result=bool)
    def setHistoryEnabled(self, value: bool) -> bool:
        return self._update_config(replace(self._config, history_enabled=bool(value)))

    @Slot("QVariant", result=bool)
    def setHistoryRetentionDays(self, value: object) -> bool:
        try:
            if value is not None:
                if isinstance(value, bool):
                    raise ValueError("history retention must be an integer")
                if isinstance(value, float) and not value.is_integer():
                    raise ValueError("history retention must be an integer")
                value = int(value)
                if value < 0:
                    raise ValueError("history retention cannot be negative")
            retention = cast(int | None, value)
        except (TypeError, ValueError) as error:
            self._set_error(error)
            return False
        return self._update_config(
            replace(self._config, history_retention_days=retention)
        )

    @Slot(str, result=bool)
    def beginHotkeyCapture(self, action: str) -> bool:
        """Put one QML row into capture mode without changing the draft."""

        if not self._account_can_change():
            self._set_error(ValueError("Finalize a operação antes de continuar."))
            return False
        try:
            parsed = _hotkey_action(action)
        except HotkeyValidationError as error:
            self._set_error(error)
            return False
        self._set_error(None)
        next_action = parsed.value
        if next_action != self._hotkey_capture_action:
            if not self._hotkey_capture_action and self._hotkey_capture_changed:
                try:
                    self._hotkey_capture_changed(True)
                except Exception as error:
                    self._set_error(error)
                    return False
            self._hotkey_capture_action = next_action
            self.hotkeyChanged.emit()
        return True

    @Slot(result=bool)
    def cancelHotkeyCapture(self) -> bool:
        """Leave capture mode without changing the current draft."""

        if self._hotkey_capture_action:
            self._hotkey_capture_action = ""
            self.hotkeyChanged.emit()
            if self._hotkey_capture_changed:
                try:
                    self._hotkey_capture_changed(False)
                except Exception as error:
                    self._set_error(error)
                    return False
        return True

    @Slot(str, object, result=bool)
    def setHotkey(self, action: str, definition: object) -> bool:
        """Validate and stage one canonical hotkey definition."""

        try:
            parsed = _hotkey_action(action)
            settings = self._hotkey_settings_controller.capture(parsed, definition)
        except (HotkeyValidationError, TypeError, ValueError) as error:
            self._set_error(error)
            return False
        updated = self._update_config(replace(self._config, hotkeys=settings))
        if updated:
            return self.cancelHotkeyCapture()
        return updated

    @Slot(str, int, int, result=bool)
    def captureHotkey(
        self,
        action: str,
        key_code: int,
        modifier_flags: int,
    ) -> bool:
        """Capture a Qt Quick key event through the typed hotkey boundary."""

        try:
            definition = _qml_hotkey_definition(key_code, modifier_flags)
        except (TypeError, ValueError, HotkeyValidationError) as error:
            self._set_error(error)
            return False
        return self.setHotkey(action, definition)

    @Slot(str, int, int, result=bool)
    def captureMouseHotkey(self, action: str, button: int, modifier_flags: int) -> bool:
        keys = {
            _qt_enum_value(Qt.MouseButton.BackButton): "XBUTTON1",
            _qt_enum_value(Qt.MouseButton.ForwardButton): "XBUTTON2",
        }
        if button not in keys:
            return False
        return self.setHotkey(
            action,
            HotkeyDefinition(_qml_hotkey_modifiers(modifier_flags), keys[button]),
        )

    @Slot(str, result=bool)
    def resetHotkey(self, action: str) -> bool:
        """Restore one action to its shared default definition."""

        try:
            parsed = _hotkey_action(action)
            settings = self._hotkey_settings_controller.reset(parsed)
        except (HotkeyValidationError, TypeError, ValueError) as error:
            self._set_error(error)
            return False
        self.cancelHotkeyCapture()
        return self._update_config(replace(self._config, hotkeys=settings))

    @Slot(result=bool)
    def resetAllHotkeys(self) -> bool:
        """Restore every action and the recording activation mode."""

        settings = self._hotkey_settings_controller.reset_all()
        self.cancelHotkeyCapture()
        return self._update_config(replace(self._config, hotkeys=settings))

    @Slot(str, result=bool)
    def setHotkeyActivationMode(self, mode: str) -> bool:
        """Stage the recording activation mode using shared validation."""

        try:
            settings = self._hotkey_settings_controller.set_activation_mode(mode)
        except (HotkeyValidationError, TypeError, ValueError) as error:
            self._set_error(error)
            return False
        return self._update_config(replace(self._config, hotkeys=settings))

    @Slot("QVariant", result=bool)
    def setMicrophone(self, value: object) -> bool:
        """Update only the stable microphone preference in the draft."""

        if value is not None and not isinstance(value, str):
            self._set_error(ValueError("microphone ID must be text"))
            return False
        selected_id = str(value or "").strip() or None
        if selected_id and not self._microphone_supports_explicit_selection():
            self._set_error(
                ValueError(
                    "Explicit microphone selection is unavailable with SoX PulseAudio"
                )
            )
            return False
        try:
            microphone = MicrophoneSettings(selected_id)
        except (TypeError, ValueError) as error:
            self._set_error(error)
            return False
        return self._update_config(replace(self._config, microphone=microphone))

    @Slot("QVariant", result=bool)
    def selectMicrophone(self, value: object) -> bool:
        """QML-friendly alias for the explicit selection action."""

        return self.setMicrophone(value)

    @Property(str, notify=microphoneChanged)
    def quickMicrophoneId(self) -> str:
        return self._config_repository.load().microphone.selected_id or ""

    @Slot(str, result=bool)
    def selectQuickMicrophone(self, value: str) -> bool:
        """Apply only this preference; preserve unrelated settings drafts."""
        if value not in {option["id"] for option in self.microphoneDevices}:
            self._set_error(ValueError("Microphone unavailable"))
            return False
        microphone = MicrophoneSettings(value or None)
        if not self._persist_ui_preference(
            lambda config: replace(config, microphone=microphone)
        ):
            return False
        self.stopMicrophoneTest()
        self._config = replace(self._config, microphone=microphone)
        self.configChanged.emit()
        self.microphoneChanged.emit()
        return True

    @Slot("QVariantMap", result=bool)
    def setRecordingControls(self, value: object) -> bool:
        """Validate boundary settings through the shared typed policy."""

        try:
            controls = RecordingControls.from_mapping(value)
        except (TypeError, ValueError) as error:
            self._set_error(error)
            return False
        return self._update_config(replace(self._config, recording_controls=controls))

    @Slot(bool, result=bool)
    def setRecordingVadEnabled(self, value: bool) -> bool:
        """Stage the switch without replacing numeric recording drafts."""
        if type(value) is not bool:
            self._set_error(ValueError("Invalid settings value"))
            return False
        controls = self._config.recording_controls
        return self._update_config(
            replace(
                self._config,
                recording_controls=replace(
                    controls, vad=replace(controls.vad, enabled=value)
                ),
            )
        )

    @Slot(result=bool)
    def refreshMicrophoneInventory(self) -> bool:
        """Share one background query and keep the last completed inventory."""

        if self._microphone_inventory_shutdown:
            return False
        if self._microphone_inventory_busy:
            return True
        self.stopMicrophoneTest()
        self._microphone_inventory_generation += 1
        generation = self._microphone_inventory_generation
        self._microphone_inventory_busy = True
        self._microphone_inventory_error_before = self._last_error
        self.microphoneChanged.emit()
        mailbox = self._background_mailbox
        backend = self._microphone_backend
        source = self._microphone_inventory_source

        def discover():
            try:
                inventory, discovered_source = _read_microphone_inventory(
                    backend, source
                )
                error = None
            except Exception as failure:
                inventory = MicrophoneInventory.unavailable("enumeration_failed")
                discovered_source = source
                error = str(failure).strip() or type(failure).__name__
            mailbox.post(
                "microphone_inventory",
                generation,
                (inventory, discovered_source, error),
            )

        self._microphone_inventory_thread = threading.Thread(
            target=discover, name="ClarifyMicrophoneInventory", daemon=True
        )
        self._microphone_inventory_thread.start()
        return True

    @Slot(int, object)
    def _finish_microphone_inventory(self, generation, payload):
        if (
            self._microphone_inventory_shutdown
            or generation != self._microphone_inventory_generation
        ):
            return
        inventory, source, error = payload
        self._microphone_inventory_busy = False
        self._microphone_inventory_thread = None
        self._microphone_inventory = inventory
        self._microphone_inventory_source = source
        if self._last_error == self._microphone_inventory_error_before:
            self._set_error(ValueError(error) if error else None)
        self.microphoneChanged.emit()

    @Slot(result=bool)
    def refreshMicrophones(self) -> bool:
        """Short alias retained for a concise QML action name."""

        return self.refreshMicrophoneInventory()

    @Slot(result=bool)
    def testMicrophone(self) -> bool:
        """Stream local input levels for up to 30 seconds off the GUI thread."""

        if self._microphone_test_busy or self._microphone_inventory_busy:
            return False
        selection = self._microphone_selection_for_test()
        if selection is None or not selection.can_record:
            self._microphone_test_status = "No safe microphone to test."
            self._microphone_test_kind = "error"
            self.microphoneTestChanged.emit()
            return False

        backend_test = getattr(self._microphone_backend, "test_microphone", None)
        if not callable(backend_test):
            self._microphone_test_status = "Input test unavailable without PortAudio."
            self._microphone_test_kind = "info"
            self.microphoneTestChanged.emit()
            return False

        self._microphone_test_generation += 1
        generation = self._microphone_test_generation
        cancel_event = threading.Event()
        self._microphone_test_cancel = cancel_event
        self._microphone_test_busy = True
        self._microphone_test_level = 0.0
        self.microphoneLevelChanged.emit()
        self._microphone_test_status = "Speak into this microphone · stops after 30 seconds. Audio is not saved or sent."
        self._microphone_test_kind = "info"
        self.microphoneTestChanged.emit()
        inventory = self._microphone_inventory

        def run() -> None:
            try:
                peak = float(
                    backend_test(
                        selection,
                        inventory,
                        on_level=lambda level: self._microphoneLevelPublished.emit(
                            generation, level
                        ),
                        cancel_event=cancel_event,
                        duration=30.0,
                    )
                )
            except Exception as error:
                self._microphoneTestFinished.emit(
                    generation,
                    False,
                    str(error).strip() or type(error).__name__,
                )
                return
            self._microphoneTestFinished.emit(generation, True, peak)

        self._microphone_test_thread = threading.Thread(
            target=run,
            name="ClarifyQmlMicrophoneTest",
            daemon=True,
        )
        self._microphone_test_thread.start()
        return True

    @Slot()
    def stopMicrophoneTest(self) -> None:
        if not self._microphone_test_busy or self._microphone_test_cancel.is_set():
            return
        self._microphone_test_cancel.set()
        self._microphone_test_level = 0.0
        self._microphone_test_status = "Stopping microphone test…"
        self.microphoneLevelChanged.emit()
        self.microphoneTestChanged.emit()

    @Slot(int, float)
    def _apply_microphone_level(self, generation: int, level: float) -> None:
        if (
            generation != self._microphone_test_generation
            or not self._microphone_test_busy
            or self._microphone_test_cancel.is_set()
        ):
            return
        self._microphone_test_level = (
            min(1.0, max(0.0, level)) if math.isfinite(level) else 0.0
        )
        self.microphoneLevelChanged.emit()

    @Slot(str, str, str, str, str, bool, result=bool)
    def setRoute(
        self,
        scope: str,
        provider_id: str,
        model_id: str,
        prompt: str,
        custom_endpoint: str,
        enabled: bool,
    ) -> bool:
        """Replace one route draft using QML form values."""

        try:
            normalized = self._canonical_scope(scope)
        except ValueError as error:
            self._set_error(error)
            return False
        current = self._config.workflow(normalized)
        route = replace(
            current,
            provider_id=str(provider_id or "").strip().lower(),
            model_id=str(model_id or "").strip(),
            prompt=str(prompt or "").strip(),
            custom_endpoint=str(custom_endpoint or "").strip(),
            enabled=bool(enabled),
            independent=True,
        )
        return self._update_config(
            replace(
                self._config,
                workflows=self._config.workflows.with_route(normalized, route),
            )
        )

    @Slot(str, result=bool)
    def setRouteProviderId(self, value: str) -> bool:
        provider_id = str(value or "").strip().lower()
        if provider_id == self.routeProviderId:
            return True
        if provider_id not in self.providersForScope(self._selected_scope):
            self._set_error(ValueError("This provider does not support this task"))
            return False
        metadata = PROVIDER_REGISTRY.describe(provider_id)
        audio = (
            WORKFLOW_CAPABILITIES[self._selected_scope]
            == ProviderCapability.AUDIO_TRANSCRIPTION
        )
        return self._update_selected_route(
            lambda route: replace(
                route,
                provider_id=provider_id,
                custom_endpoint="",
                model_id=metadata.default_audio_model
                if audio
                else metadata.default_text_model,
            )
        )

    def _model_connection_key(self) -> tuple[str, str, str]:
        provider = self.routeProviderId
        if provider == LOCAL_ASR_PROVIDER_ID:
            return (provider, "", "")
        config = self._provider_config(provider)
        return (
            provider,
            self.routeCustomEndpoint or self._config_provider_base_url(provider),
            config.api_key.strip(),
        )

    @Property(str, notify=modelCatalogChanged)
    def routeModelStatus(self) -> str:
        key = self._model_connection_key()
        if key[0] != LOCAL_ASR_PROVIDER_ID and not key[2]:
            return "not_configured"
        if key == self._model_loading_key:
            return "loading"
        if key == self._model_error_key:
            return "error"
        if key in self._model_catalogs:
            return "ready" if self.routeModelOptions else "empty"
        return "idle"

    @Property("QVariantList", notify=modelCatalogChanged)
    def routeModelOptions(self) -> list[dict[str, str]]:
        key = self._model_connection_key()
        catalog = self._model_catalogs.get(key)
        if catalog is None:
            return []
        audio = (
            WORKFLOW_CAPABILITIES[self._selected_scope]
            == ProviderCapability.AUDIO_TRANSCRIPTION
        )
        models = catalog.audio_models if audio else catalog.text_models
        from local_asr_catalog import MODELS, PROFILE_LABELS

        local_labels = dict(zip(MODELS, PROFILE_LABELS))
        return [
            {
                "id": model,
                "label": local_labels.get(model, model)
                if key[0] == LOCAL_ASR_PROVIDER_ID
                else model,
            }
            for model in sorted(set(models))
        ]

    @Slot(result=bool)
    def loadRouteModels(self) -> bool:
        if self.routeModelStatus != "idle":
            return False
        return self.refreshRouteModels()

    @Slot(result=bool)
    def refreshRouteModels(self) -> bool:
        """Discover models without saving credentials or changing the route."""
        if getattr(self._account, "managed", False) is True:
            return False
        key = self._model_connection_key()
        if (
            key[0] != LOCAL_ASR_PROVIDER_ID and not key[2]
        ) or key == self._model_loading_key:
            return False
        if self._model_token is not None:
            self._model_token.cancel()
        self._model_generation += 1
        generation = self._model_generation
        token = CancellationToken()
        self._model_token = token
        self._model_loading_key = key
        self._model_error_key = None
        self.modelCatalogChanged.emit()

        def discover() -> None:
            try:
                if key[0] == LOCAL_ASR_PROVIDER_ID:
                    from local_asr_catalog import MODELS, installer_for

                    installed = []
                    for model in MODELS:
                        token.raise_if_cancelled()
                        if installer_for(model, "cpu").status()["state"] == "installed":
                            installed.append(model)
                    catalog = ModelCatalog(audio_models=tuple(installed))
                else:
                    catalog = PROVIDER_REGISTRY.discover_models(
                        key[0], ProviderConnection(key[2], key[1]), token
                    )
            except Exception:
                # Provider errors can contain URLs or credentials. Do not expose them.
                catalog = None
            self._modelDiscoveryFinished.emit(generation, key, catalog)

        threading.Thread(
            target=discover, name="ClarifyModelDiscovery", daemon=True
        ).start()
        return True

    @Slot(int, object, object)
    def _finish_model_discovery(
        self, generation: int, key: object, catalog: object
    ) -> None:
        if generation != self._model_generation:
            return
        self._model_loading_key = None
        self._model_token = None
        if catalog is None:
            self._model_error_key = key
        else:
            self._model_catalogs[key] = catalog
        self.modelCatalogChanged.emit()

    @Property(str, notify=providerStateChanged)
    def localAsrStep(self) -> str:
        state = self._local_state
        labels = {
            "checking": "Checking installed files",
            "preparing": "Preparing download",
            "download:runtime": "1 of 5 · Downloading engine",
            "verify:runtime": "2 of 5 · Verifying engine",
            "extract:runtime": "3 of 5 · Installing engine",
            "download:model": "4 of 5 · Downloading Whisper Small",
            "verify:model": "5 of 5 · Verifying model",
            "complete": "Ready to use",
        }
        label = labels.get(state.stage, "Preparing local model")
        if state.stage.startswith("download:") and state.total > 0:
            label += f" · {format_requirement_bytes(state.current)} / {format_requirement_bytes(state.total)}"
        return label

    @Property(bool, notify=providerStateChanged)
    def localAsrCanInstall(self) -> bool:
        checker = getattr(self._local_product.installer, "platform_supported", None)
        try:
            return bool(checker()) if callable(checker) else True
        except Exception:
            return False

    @Property("QVariantList", notify=providerStateChanged)
    def localAsrRequirementsList(self) -> list[str]:
        values = self._local_state.requirements or {}
        return [
            f"{format_requirement_bytes(values.get('download_bytes', 0))} maximum download",
            f"{format_requirement_bytes(values.get('disk_bytes', 0))} free disk",
            f"{format_requirement_bytes(values.get('memory_bytes', 0))} RAM",
            str(values.get("platform", "Windows x64")),
            str(values.get("compute", "")),
            str(values.get("runtime", "")),
        ]

    @Property(bool, notify=providerStateChanged)
    def localBenchmarkBusy(self):
        return self._local_benchmark_busy

    @Property(str, notify=providerStateChanged)
    def localBenchmarkDetail(self):
        return self._local_benchmark_detail

    @Slot()
    def cancelLocalMeasurement(self):
        if self._local_benchmark_token is not None:
            self._local_benchmark_token.cancel()

    @Slot(result=bool)
    def measureLocalDevice(self):
        if self.localAsrBusy or self._local_benchmark_busy:
            return False
        from local_asr import default_manifest_path
        from local_asr_catalog import calibrate

        token = CancellationToken()
        self._local_benchmark_token = token
        self._local_benchmark_busy = True
        self._local_benchmark_detail = (
            "Measuring installed engines with local sample audio..."
        )
        model = self._local_profile
        audio = default_manifest_path().parent / "assets" / "asr-benchmark.wav"
        pool = PROVIDER_REGISTRY.adapter(LOCAL_ASR_PROVIDER_ID).engines

        def measure():
            try:
                result = calibrate(pool, model, audio, token)
                from shared.localization import translate

                detail = translate(
                    "Measured: {engine}. Select Automatic and use this model to apply.",
                    engine=result["selected"],
                )
            except Exception as error:
                detail = str(error)
            try:
                self._localBenchmarkPublished.emit(detail)
            except RuntimeError:
                pass

        threading.Thread(target=measure, daemon=True, name="LocalASRBenchmark").start()
        self.providerStateChanged.emit()
        return True

    @Slot(str)
    def _finish_local_benchmark(self, detail):
        self._local_benchmark_busy = False
        self._local_benchmark_detail = detail
        self.providerStateChanged.emit()

    @Property("QStringList", constant=True)
    def localProfiles(self):
        from local_asr_catalog import PROFILE_LABELS

        return list(PROFILE_LABELS)

    @Property(int, notify=providerStateChanged)
    def localProfileIndex(self):
        from local_asr_catalog import MODELS

        return MODELS.index(self._local_profile)

    @Property("QStringList", notify=providerStateChanged)
    def localDevices(self):
        return [item["label"] for item in self._local_devices]

    @Property(int, notify=providerStateChanged)
    def localDeviceIndex(self):
        return next(
            (
                i
                for i, item in enumerate(self._local_devices)
                if item["id"] == self._local_device
            ),
            1,
        )

    @Property(bool, notify=configChanged)
    def localStreaming(self):
        return self._config.local_asr_streaming

    @Slot(bool, result=bool)
    def setLocalStreaming(self, enabled):
        return self._update_config(
            replace(self._config, local_asr_streaming=bool(enabled))
        )

    @Slot(object)
    def _apply_local_devices(self, values):
        if self._account_shutdown:
            return
        self._local_devices = values
        self.providerStateChanged.emit()

    @Slot(int, result=bool)
    def selectLocalProfile(self, index):
        from local_asr_catalog import MODELS

        if (
            self.localAsrBusy
            or self._local_benchmark_busy
            or not 0 <= index < len(MODELS)
        ):
            return False
        return self._browse_local(MODELS[index], self._local_device)

    @Slot(int, result=bool)
    def selectLocalDevice(self, index):
        if (
            self.localAsrBusy
            or self._local_benchmark_busy
            or not 0 <= index < len(self._local_devices)
        ):
            return False
        return self._browse_local(self._local_profile, self._local_devices[index]["id"])

    def _browse_local(self, model, device):
        try:
            from local_asr_catalog import ModelInstaller

            adapter = PROVIDER_REGISTRY.adapter(LOCAL_ASR_PROVIDER_ID)
            backend = adapter.select_backend(model, "cpu")
            product = LocalASRProductController(
                installer=ModelInstaller(model, adapter.engines, self._local_devices),
                backend=backend,
            )
        except Exception as error:
            self._set_error(error)
            return False
        self._local_generation += 1
        generation = self._local_generation
        self._local_profile, self._local_device = model, device
        self._unsubscribe_local_state()
        self._local_product.cancel()
        self._local_product = product
        self._local_state = product.state
        self._local_state_listener = self._local_state_callback(generation)
        product.subscribe(self._local_state_listener)
        product.refresh_async()
        self.providerStateChanged.emit()
        return True

    @Slot(result=bool)
    def useLocalAsr(self) -> bool:
        if self.localAsrStatus != "installed":
            return False
        self.selectWorkflow(WorkflowScope.TRANSCRIPTION.value)
        self.setRouteProviderId(LOCAL_ASR_PROVIDER_ID)
        self.setRouteModelId(self._local_profile)
        self._update_config(replace(self._config, local_asr_device=self._local_device))
        return self.setRouteEnabled(True)

    @Slot(str, result=bool)
    def setRouteModelId(self, value: str) -> bool:
        return self._update_selected_route(
            lambda route: replace(route, model_id=str(value or "").strip())
        )

    @Slot(str, result=bool)
    def setRoutePrompt(self, value: str) -> bool:
        return self._update_selected_route(
            lambda route: replace(route, prompt=str(value or "").strip())
        )

    @Slot(str, result=bool)
    def setRouteCustomEndpoint(self, value: str) -> bool:
        return self._update_selected_route(
            lambda route: replace(route, custom_endpoint=str(value or "").strip())
        )

    @Slot(bool, result=bool)
    def setRouteEnabled(self, value: bool) -> bool:
        return self._update_selected_route(
            lambda route: replace(route, enabled=bool(value))
        )

    @Slot(str, result="QVariantMap")
    def routeFor(self, scope: str) -> dict[str, Any]:
        try:
            normalized = self._canonical_scope(scope)
        except ValueError as error:
            self._set_error(error)
            return {}
        self._set_error(None)
        return self._route_mapping(self._config.workflow(normalized), normalized)

    @Slot(str, result="QStringList")
    def providersForScope(self, scope: str) -> list[str]:
        try:
            normalized = self._canonical_scope(scope)
        except ValueError as error:
            self._set_error(error)
            return []
        self._set_error(None)
        capability = WORKFLOW_CAPABILITIES[normalized]
        return [
            metadata.provider_id
            for metadata in PROVIDER_REGISTRY.metadata
            if metadata.supports(capability)
        ]

    @Slot(str, result=bool)
    def selectProvider(self, provider_id: str) -> bool:
        normalized = str(provider_id or "").strip().lower()
        if normalized not in PROVIDER_REGISTRY.provider_ids:
            self._set_error(ValueError(f"Unknown provider: {normalized or '<empty>'}"))
            return False
        if normalized == self._selected_provider_id:
            return True
        self._selected_provider_id = normalized
        self._provider_api_key_draft = ""
        self._provider_base_url_draft = self._config_provider_base_url(normalized)
        self._set_error(None)
        self.providerStateChanged.emit()
        return True

    @Slot(str, result=bool)
    def setProviderApiKey(self, value: str) -> bool:
        self._provider_api_key_draft = str(value or "")
        self._set_error(None)
        self.providerStateChanged.emit()
        return True

    @Slot(str, result=bool)
    def setProviderBaseUrl(self, value: str) -> bool:
        self._provider_base_url_draft = str(value or "").strip()
        self._set_error(None)
        self.providerStateChanged.emit()
        return True

    @Slot(result=bool)
    def validateProvider(self) -> bool:
        """Validate and persist the selected cloud provider without blocking QML."""
        if getattr(self._account, "managed", False) is True:
            return False

        provider_id = self._selected_provider_id
        if provider_id == LOCAL_ASR_PROVIDER_ID:
            self._set_error(
                ValueError("Local Whisper is configured with the install action")
            )
            return False
        if self.providerBusy:
            return False

        provider_config = self._provider_config(provider_id)
        api_key = (
            self._provider_api_key_draft.strip() or provider_config.api_key.strip()
        )
        if not api_key:
            self._set_error(
                ValueError("Enter an API key before validating the provider")
            )
            return False
        metadata = PROVIDER_REGISTRY.describe(provider_id)
        base_url = self._provider_base_url_draft.strip() or metadata.default_base_url
        if not metadata.supports(ProviderCapability.CUSTOM_BASE_URL):
            base_url = metadata.default_base_url
        token = CancellationToken()
        generation = self._provider_generations.get(provider_id, 0) + 1
        self._provider_generations[provider_id] = generation
        previous = self._provider_tokens.get(provider_id)
        if previous is not None:
            previous.cancel()
        self._provider_tokens[provider_id] = token
        self._provider_activity[provider_id] = {
            "status": "validating",
            "error": "",
            "models": [],
            "textModels": [],
            "busy": True,
        }
        self._set_error(None)
        self.providerStateChanged.emit()

        def validate() -> None:
            try:
                catalog = PROVIDER_REGISTRY.discover_models(
                    provider_id,
                    ProviderConnection(api_key, base_url),
                    token,
                )
            except Exception as error:
                self._providerValidationFinished.emit(
                    provider_id,
                    generation,
                    False,
                    {"error": str(error).strip() or type(error).__name__},
                )
                return
            self._providerValidationFinished.emit(
                provider_id,
                generation,
                True,
                {
                    "api_key": api_key,
                    "base_url": base_url,
                    "models": list(catalog.audio_models),
                    "text_models": list(catalog.text_models),
                },
            )

        threading.Thread(
            target=validate,
            name=f"ClarifyProviderValidation-{provider_id}",
            daemon=True,
        ).start()
        return True

    @Slot(result=bool)
    def clearProvider(self) -> bool:
        """Remove the selected cloud credential from the secure store."""

        provider_id = self._selected_provider_id
        if provider_id == LOCAL_ASR_PROVIDER_ID:
            return False
        generation = self._provider_generations.get(provider_id, 0) + 1
        self._provider_generations[provider_id] = generation
        pending = self._provider_tokens.pop(provider_id, None)
        if pending is not None:
            pending.cancel()
        try:
            persisted = self._config_repository.load()
            persisted_provider = getattr(persisted, provider_id)
            self._persist_provider_credentials(
                provider_id,
                "",
                persisted_provider.base_url,
                persisted_config=persisted,
            )
        except Exception as error:
            message = str(error).strip() or type(error).__name__
            self._provider_activity[provider_id] = {
                "status": "error",
                "error": message,
                "models": [],
                "textModels": [],
                "busy": False,
            }
            self._set_error(error)
            self.providerStateChanged.emit()
            return False
        self._provider_activity[provider_id] = {
            "status": "not_configured",
            "error": "",
            "models": [],
            "textModels": [],
            "busy": False,
        }
        self._provider_api_key_draft = ""
        self._set_error(None)
        self.configChanged.emit()
        self.providerStateChanged.emit()
        return True

    @Slot(result=bool)
    def installLocalAsr(self) -> bool:
        if self.localAsrBusy or self._local_benchmark_busy:
            return False
        self._local_device = "auto"
        try:
            self._local_product.install_async()
        except Exception as error:
            self._set_error(error)
            self.providerStateChanged.emit()
            return False
        self._set_error(None)
        self.providerStateChanged.emit()
        return True

    @Slot(result=bool)
    def removeLocalAsr(self) -> bool:
        try:
            self._local_product.remove_async()
        except Exception as error:
            self._set_error(error)
            self.providerStateChanged.emit()
            return False
        self._set_error(None)
        self.providerStateChanged.emit()
        return True

    @Slot(result=bool)
    def cancelLocalAsr(self) -> bool:
        self._local_product.cancel()
        return True

    @Slot(result=bool)
    def refreshLocalAsr(self) -> bool:
        return bool(self._local_product.refresh_async())

    @Slot()
    def shutdown(self) -> None:
        self._account_shutdown = True
        self._background_mailbox.close()
        self._background_timer.stop()
        self._microphone_inventory_shutdown = True
        self._microphone_inventory_generation += 1
        self._microphone_inventory_busy = False
        self._account_cancel.set()
        self._library_sync_timer.stop()
        self._unsubscribe_local_state()
        self._local_generation += 1
        if self._local_benchmark_token is not None:
            self._local_benchmark_token.cancel()
        self._model_generation += 1
        if self._model_token is not None:
            self._model_token.cancel()
        for token in tuple(self._provider_tokens.values()):
            token.cancel()
        self._provider_tokens.clear()
        self.stopMicrophoneTest()
        if self._microphone_test_thread is not None:
            self._microphone_test_thread.join(timeout=1.0)
        self._microphone_test_generation += 1
        self._microphone_test_busy = False
        self._local_product.shutdown()

    def _unsubscribe_local_state(self) -> None:
        unsubscribe = getattr(self._local_product, "unsubscribe", None)
        if callable(unsubscribe):
            unsubscribe(self._local_state_listener)

    def _local_state_callback(self, generation):
        mailbox = self._background_mailbox

        def publish(state):
            mailbox.post("local_state", generation, state)

        return publish

    @Slot(result=bool)
    def load(self) -> bool:
        self.stopMicrophoneTest()
        if not self.cancelHotkeyCapture():
            return False
        try:
            loaded_config = self._config_repository.load()
            with self._dictionary_service.transaction():
                self._dictionary_draft = self._dictionary_service.reload()
                self._dictionary_baseline = self._dictionary_draft
                self._snippet_draft_context = self.snippetContext
        except Exception as error:  # Repository errors belong in the QML state.
            self._set_error(error)
            return False
        self._replace_loaded_config(loaded_config)
        self._set_error(None)
        self.loaded.emit()
        return True

    @Property(str, constant=True)
    def uiLanguage(self):
        from shared.localization import device_language

        return device_language()

    @Property("QVariantMap", notify=accountStateChanged)
    def accountState(self):
        return {
            **self._account.snapshot(),
            "busy": self._account_busy,
            "socialPending": self._account_busy and self._account_social,
            "error": self._account_error,
        }

    @Property("QVariantMap", notify=accountStateChanged)
    def historyState(self):
        return (
            self._history_view.snapshot()
            if self._history_view is not None
            else {"context": "", "revision": ""}
        )

    def getHistoryPage(self, context, cursor):
        if self._history_view is None and context == "" and cursor == "":
            return {
                "context": "",
                "revision": "",
                "entries": [],
                "cursor": "",
                "hasMore": False,
            }
        if self._history_view is None:
            raise ValueError("Invalid history context")
        return self._history_view.page(context, cursor)

    def getHistoryTextPart(self, context, token, offset, field):
        if self._history_view is None:
            raise ValueError("Invalid history context")
        return self._history_view.text_part(context, token, offset, field)

    @Slot(str, str, result=bool)
    def deleteHistoryEntry(self, token, context):
        try:
            if self._history is not None:
                self._history_view.delete(context, token)
                threading.Thread(
                    target=lambda: self._history.sync_safely(force=True),
                    name="ClarifyHistory",
                    daemon=True,
                ).start()
            self.accountStateChanged.emit()
            return True
        except (OSError, ValueError) as error:
            self._set_error(error)
            return False

    @Slot(str, result=bool)
    def clearHistory(self, context):
        try:
            if self._history is not None:
                self._history_view.clear(context)
                threading.Thread(
                    target=lambda: self._history.sync_safely(force=True),
                    name="ClarifyHistory",
                    daemon=True,
                ).start()
            self.accountStateChanged.emit()
            return True
        except (OSError, ValueError) as error:
            self._set_error(error)
            return False

    @Property(bool, notify=configChanged)
    def onboardingRequired(self):
        return not self._config.onboarding_completed

    @Slot(str, str, result=bool)
    def completeOnboarding(self, mode, key=""):
        """Commit the first-run choice through the existing config transaction."""
        if (
            self._account_busy
            or not self._account_can_change()
            or self.dirty
            or self.providerDirty
        ):
            self._set_error(ValueError("Finalize a operação antes de continuar."))
            return False
        try:
            config = self._config_repository.load()
            if config.onboarding_completed:
                return True
            if mode == "account":
                account = self._account.snapshot()
                if not account.get("signedIn"):
                    raise ValueError("Entre na conta novamente.")
            elif mode in {"byok", "local"}:
                if self._account.snapshot().get("signedIn"):
                    raise ValueError(
                        "Saia da conta para usar sua chave ou modelos locais."
                    )
                if mode == "byok":
                    key = str(key).strip()
                    if not key.startswith("gsk_") or any(c.isspace() for c in key):
                        raise ValueError("Informe uma chave válida do Groq.")
                    config = replace(config, groq=replace(config.groq, api_key=key))
                provider = "groq" if mode == "byok" else "local_asr"
                provider_config = getattr(config, provider)
                routes = config.workflows.with_route(
                    "transcription",
                    replace(
                        config.workflow("transcription"),
                        provider_id=provider,
                        model_id=provider_config.audio_model,
                        custom_endpoint="",
                        independent=True,
                    ),
                )
                if mode == "byok":
                    for scope in ("refinement", "rewrite", "translation"):
                        routes = routes.with_route(
                            scope,
                            replace(
                                config.workflow(scope),
                                provider_id="groq",
                                model_id=config.groq.text_model,
                                custom_endpoint="",
                                independent=True,
                            ),
                        )
                config = replace(
                    config, workflows=routes, local_asr_cloud_refinement=False
                )
            else:
                raise ValueError("Escolha uma opção para continuar.")
            persisted = self._config_repository.apply(
                replace(config, onboarding_completed=True)
            )
        except Exception as error:
            self._set_error(error)
            return False
        self._replace_loaded_config(persisted)
        if mode == "byok":
            self.selectProvider("groq")
        self._set_error(None)
        self.saved.emit()
        return True

    @Slot(str, str, result=bool)
    def accountCommand(self, action, value=""):
        if action == "cancel-social":
            if self._account_busy and self._account_social:
                self._account_cancel.set()
                return True
            return False
        if action == "auto" and (
            self._account_busy
            or not self._account_can_change()
            or self.dirty
            or self.providerDirty
            or not self._account.signed_in
        ):
            return False
        if self._account_busy or not self._account_can_change():
            self._set_error(ValueError("Finalize o ditado antes de alterar a conta."))
            return False
        if self.dirty or self.providerDirty:
            self._set_error(
                ValueError("Salve ou descarte as alterações antes de alterar a conta.")
            )
            return False
        if action not in {
            "auto",
            "configure",
            "login",
            "signup",
            "confirm",
            "social",
            "refresh",
            "sync",
            "sync-local",
            "sync-remote",
            "logout",
            "delete",
        }:
            return False
        if not self._account.begin_change():
            return False
        self._account_busy, self._account_error = True, ""
        self._account_social = action == "social"
        self._account_cancel.clear()
        self.accountStateChanged.emit()

        def perform():
            error = ""
            try:
                if action == "configure":
                    self._account.configure(value)
                elif action == "social":
                    self._account.authenticate_social(
                        value, cancel=self._account_cancel
                    )
                    if self._account.signed_in:
                        self._dictionary_service.reload()
                        self._account.refresh_if_due(
                            self._dictionary_service, force=True
                        )
                elif action in {"login", "signup", "confirm"}:
                    self._account.authenticate(action, value)
                    if action == "confirm":
                        self._dictionary_service.reload()
                        self._account.refresh_if_due(
                            self._dictionary_service, force=True
                        )
                elif action == "auto":
                    self._account.refresh_if_due(self._dictionary_service)
                elif action == "refresh":
                    self._account.refresh()
                elif action in {"sync", "sync-local", "sync-remote"}:
                    self._account.sync_library(
                        self._dictionary_service,
                        prefer=action.removeprefix("sync-")
                        if action != "sync"
                        else None,
                    )
                elif action in {"logout", "delete"}:
                    self._account.logout(delete=action == "delete")
                    self._dictionary_service.reload()
            except Exception as problem:
                from clarify_account import AccountError

                error = (
                    str(problem)
                    if isinstance(problem, AccountError)
                    else "Não foi possível concluir a operação da conta."
                )
            if not self._account_shutdown:
                self._accountFinished.emit(error)

        threading.Thread(target=perform, name="ClarifyAccount", daemon=True).start()
        return True

    @Slot(object)
    def _finish_account(self, error):
        self._account_social = False
        self._account_error = error
        try:
            with self._dictionary_service.transaction():
                self._dictionary_draft = self._dictionary_service.reload()
                self._dictionary_baseline = self._dictionary_draft
                self._snippet_draft_context = self.snippetContext
        finally:
            self._account_busy = False
            self._account.end_change()
        self.accountStateChanged.emit()
        self.loaded.emit()

    @Slot(result=bool)
    @Slot(str, result=bool)
    def save(self, context=None) -> bool:
        context = self._snippet_draft_context if context is None else context
        if not self.cancelHotkeyCapture():
            return False
        try:
            with self._dictionary_service.transaction(expected_context=context):
                self._require_library_context(context)
                self._reconcile_library_draft()
                return self._save_owned_library(context)
        except Exception as error:
            self._set_error(error)
            return False

    @Slot(str, "QVariantList", result=bool)
    def savePreference(self, method: str, args: list) -> bool:
        """Persist one allowlisted control against current storage, never Save All."""
        try:
            with self._dictionary_service.transaction():
                return self._save_preference(method, args)
        except Exception as error:
            self._set_error(error)
            return False

    def _save_preference(self, method: str, args: list) -> bool:
        before = None
        hotkeys_attempted = False
        try:
            before = self._config_repository.load()
            try:
                change = self._preference_change(method, args, before)
                candidate = change(before)
                draft = change(self._config)
            except (TypeError, ValueError):
                self._set_error(ValueError("Invalid settings value"))
                return False
            hotkey_method = method in {
                "setHotkey",
                "setHotkeyActivationMode",
                "resetHotkey",
                "resetAllHotkeys",
            }
            if hotkey_method:
                capture = self._hotkey_capture_action
                if not self.cancelHotkeyCapture():
                    # A failed restore must remain retryable.
                    self._hotkey_capture_action = capture
                    self.hotkeyChanged.emit()
                    return False
            if (
                self._hotkey_applier is not None
                and hotkey_method
                and (
                    candidate.hotkeys != before.hotkeys or self._hotkey_reapply_required
                )
            ):
                hotkeys_attempted = True
                self._hotkey_applier(candidate.hotkeys)
            if method == "setAutostart":
                saved = _apply_config_with_autostart_transaction(
                    candidate, self.repositories, self._autostart_registry
                )
            else:
                saved = self._config_repository.apply(candidate)
        except Exception as error:
            if hotkeys_attempted and before is not None:
                try:
                    self._hotkey_applier(before.hotkeys)
                    self._hotkey_reapply_required = False
                except Exception:
                    self._hotkey_reapply_required = True
                    self._set_error(
                        ValueError(
                            "Não foi possível restaurar os atalhos. Tente novamente."
                        )
                    )
                    return False
            self._set_error(error)
            return False
        if hotkeys_attempted:
            self._hotkey_reapply_required = False
        self._update_config(draft)
        dirty = self._config != saved
        if self._dirty != dirty:
            self._dirty = dirty
            self.dirtyChanged.emit()
        if method == "useLocalAsr":
            self.selectWorkflow(WorkflowScope.TRANSCRIPTION.value)
        self._set_error(None)
        self.saved.emit()
        return True

    def _preference_change(
        self, method: str, args: list, before: AppConfig
    ) -> Callable[[AppConfig], AppConfig]:
        """Small explicit write set; text, credentials and libraries are excluded."""
        bool_fields = {
            "setHistoryEnabled": "history_enabled",
            "setAutomaticUpdates": "automatic_updates",
            "setLocalStreaming": "local_asr_streaming",
            "setLocalAsrCloudRefinement": "local_asr_cloud_refinement",
        }
        bool_methods = {
            *bool_fields,
            "setAutostart",
            "setRouteEnabled",
            "setRecordingVadEnabled",
        }
        text_methods = {
            "setDictationCleanupLevel",
            "setMode",
            "setLanguage",
            "setRouteProviderId",
            "setRouteModelId",
            "setHotkeyActivationMode",
            "resetHotkey",
        }
        if not isinstance(method, str) or not isinstance(args, list):
            raise ValueError("Invalid settings value")
        if method in bool_methods:
            valid = len(args) == 1 and type(args[0]) is bool
        elif method in text_methods:
            valid = len(args) == 1 and type(args[0]) is str
        elif method == "selectMicrophone":
            valid = len(args) == 1 and (args[0] is None or type(args[0]) is str)
        elif method == "setHotkey":
            valid = (
                len(args) == 2
                and type(args[0]) is str
                and isinstance(args[1], (str, dict))
            )
        else:
            valid = method in {"resetAllHotkeys", "useLocalAsr"} and not args
        if not valid:
            raise ValueError("Invalid settings value")
        if (
            method
            in {
                "setRouteProviderId",
                "setRouteModelId",
                "setRouteEnabled",
                "useLocalAsr",
                "setLocalStreaming",
                "setLocalAsrCloudRefinement",
            }
            and getattr(self._account, "managed", False) is True
        ):
            raise ValueError("A conta Clarify gerencia as opções de processamento.")

        if method == "setDictationCleanupLevel":
            from shared.dictation_policy import cleanup_level

            level = cleanup_level(args[0] or None)
            return lambda config: replace(config, dictation_cleanup_level=level)
        if method in bool_fields:
            if method == "setLocalAsrCloudRefinement":
                return lambda config: replace(
                    config,
                    local_asr_cloud_refinement=args[0],
                    workflows=config.workflows.with_route(
                        "local_asr_refinement",
                        replace(
                            config.workflow("local_asr_refinement"),
                            enabled=args[0],
                        ),
                    ),
                )
            return lambda config: replace(config, **{bool_fields[method]: args[0]})
        if method == "setAutostart":
            return lambda config: replace(
                config, startup=replace(config.startup, autostart=args[0])
            )
        if method in {"setMode", "setLanguage"}:
            if method == "setMode":
                self._choice(args[0], (*SUPPORTED_UI_MODES, "transcription"), "mode")
                field, value = "mode", "prompt"
            else:
                field, value = (
                    "language",
                    self._choice(args[0], SUPPORTED_LANGUAGES, "language"),
                )
            return lambda config: replace(
                config, ui=replace(config.ui, **{field: value})
            )
        if method == "selectMicrophone":
            selected = str(args[0] or "").strip() or None
            if selected and not self._microphone_supports_explicit_selection():
                raise ValueError(
                    "Explicit microphone selection is unavailable with SoX PulseAudio"
                )
            microphone = MicrophoneSettings(selected)
            return lambda config: replace(config, microphone=microphone)
        if method == "setRecordingVadEnabled":
            return lambda config: replace(
                config,
                recording_controls=replace(
                    config.recording_controls,
                    vad=replace(config.recording_controls.vad, enabled=args[0]),
                ),
            )
        if method in {
            "setHotkey",
            "resetHotkey",
            "resetAllHotkeys",
            "setHotkeyActivationMode",
        }:
            if method in {"setHotkey", "resetHotkey"}:
                try:
                    action = _hotkey_action(args[0])
                    definition = (
                        HotkeyDefinition.from_mapping(args[1])
                        if method == "setHotkey"
                        else None
                    )
                except (TypeError, ValueError):
                    raise ValueError("Invalid settings value") from None
                if definition is None:
                    return lambda config: replace(
                        config, hotkeys=config.hotkeys.reset(action)
                    )
                return lambda config: replace(
                    config, hotkeys=config.hotkeys.with_hotkey(action, definition)
                )
            if method == "resetAllHotkeys":
                return lambda config: replace(config, hotkeys=HotkeySettings.defaults())
            return lambda config: replace(
                config,
                hotkeys=config.hotkeys.with_activation_mode(
                    args[0],
                    push_to_talk_supported=self._hotkey_settings_controller.push_to_talk_supported,
                ),
            )

        scope = self._selected_scope
        if method == "useLocalAsr":
            if self.localAsrStatus != "installed":
                raise ValueError("Instale o modelo local antes de usar.")
            scope = WorkflowScope.TRANSCRIPTION.value
        old_route = before.workflow(scope)
        fields: dict[str, Any] = {"independent": True}
        if method == "setRouteProviderId":
            provider = args[0].strip().lower()
            if provider not in self.providersForScope(scope):
                raise ValueError("This provider does not support this task")
            fields["provider_id"] = provider
            if provider != old_route.provider_id:
                metadata = PROVIDER_REGISTRY.describe(provider)
                fields["model_id"] = (
                    metadata.default_audio_model
                    if WORKFLOW_CAPABILITIES[scope]
                    == ProviderCapability.AUDIO_TRANSCRIPTION
                    else metadata.default_text_model
                )
                fields["custom_endpoint"] = ""
        elif method == "setRouteModelId":
            metadata = PROVIDER_REGISTRY.describe(old_route.provider_id)
            audio = (
                WORKFLOW_CAPABILITIES[scope] == ProviderCapability.AUDIO_TRANSCRIPTION
            )
            model = args[0].strip() or (
                metadata.default_audio_model if audio else metadata.default_text_model
            )
            fields["model_id"] = (
                PROVIDER_REGISTRY.canonical_audio_model(old_route.provider_id, model)
                if audio
                else model
            )
        elif method == "setRouteEnabled":
            fields["enabled"] = args[0]
        else:  # useLocalAsr
            fields.update(
                provider_id=LOCAL_ASR_PROVIDER_ID,
                model_id=self._local_profile,
                custom_endpoint="",
                enabled=True,
            )

        def change_route(config: AppConfig) -> AppConfig:
            route = config.workflow(scope)
            changes = dict(fields)
            # Provider changes reset saved connection defaults, while pending
            # endpoint/model edits remain in the Settings draft.
            if (
                "custom_endpoint" in changes
                and route.custom_endpoint != old_route.custom_endpoint
            ):
                changes.pop("custom_endpoint")
            if (
                method == "setRouteProviderId"
                and "model_id" in changes
                and route.model_id != old_route.model_id
            ):
                changes.pop("model_id")
            config = replace(
                config,
                workflows=config.workflows.with_route(scope, replace(route, **changes)),
            )
            route = config.workflow(scope)
            # Keep the persisted compatibility projection in the draft too.
            # Otherwise a successful scoped write would still appear dirty.
            if scope == "transcription":
                provider_config = getattr(config, route.provider_id)
                config = replace(
                    config,
                    selection=replace(
                        config.selection, transcription_provider=route.provider_id
                    ),
                    **{
                        route.provider_id: replace(
                            provider_config, audio_model=route.model_id
                        )
                    },
                )
            elif scope == "refinement":
                config = replace(
                    config,
                    selection=replace(
                        config.selection,
                        refinement_provider=route.provider_id,
                        refinement_model=route.model_id,
                    ),
                )
            elif scope == "local_asr_refinement":
                config = replace(config, local_asr_cloud_refinement=route.enabled)
            if method == "useLocalAsr":
                config = replace(config, local_asr_device=self._local_device)
            return config

        return change_route

    def _save_owned_library(self, context) -> bool:
        """Persist settings and library, including rollback, under one owner guard."""
        persisted_before: AppConfig | None = None
        hotkeys_applied = False
        persisted_config = None
        try:
            persisted_before = self._config_repository.load()
            if (
                self._hotkey_applier is not None
                and persisted_before.hotkeys != self._config.hotkeys
            ):
                self._hotkey_applier(self._config.hotkeys)
                hotkeys_applied = True
            persisted_config = _apply_config_with_autostart_transaction(
                self._config,
                self.repositories,
                self._autostart_registry,
            )
            self._require_library_context(context)
            if self._dictionary_draft != self._dictionary_service.state:
                self._dictionary_service.replace(
                    self._dictionary_draft, expected_context=context
                )
        except Exception as error:  # Validation/storage errors are user-facing.
            if persisted_config is not None and persisted_before is not None:
                try:
                    _apply_config_with_autostart_transaction(
                        persisted_before, self.repositories, self._autostart_registry
                    )
                except Exception:
                    self._set_error(
                        ValueError(
                            "Não foi possível salvar o dicionário nem restaurar todas as configurações. Verifique as opções antes de tentar novamente."
                        )
                    )
                    return False
            if hotkeys_applied and self._hotkey_applier is not None:
                try:
                    assert persisted_before is not None
                    self._hotkey_applier(persisted_before.hotkeys)
                except Exception:
                    pass
            self._set_error(error)
            return False
        self._dictionary_baseline = self._dictionary_draft
        self._replace_loaded_config(persisted_config)
        self._set_error(None)
        self.saved.emit()
        if self._account.scope and not self._account_busy:
            self.accountCommand("sync", "")
        return True

    @Slot(str, result=bool)
    def persistMode(self, value: str) -> bool:
        """Persist only the UI mode without applying the editable Settings draft."""

        try:
            self._choice(value, (*SUPPORTED_UI_MODES, "transcription"), "mode")
            normalized = "prompt"
        except ValueError as error:
            self._set_error(error)
            return False
        return self._persist_ui_preference(
            lambda config: replace(
                config,
                ui=replace(config.ui, mode=normalized),
            )
        )

    @Slot(str, result=bool)
    def persistLanguage(self, value: str) -> bool:
        """Persist only the UI language without applying the editable Settings draft."""

        try:
            normalized = self._choice(value, SUPPORTED_LANGUAGES, "language")
        except ValueError as error:
            self._set_error(error)
            return False
        return self._persist_ui_preference(
            lambda config: replace(
                config,
                ui=replace(config.ui, language=normalized),
            )
        )

    @Slot(bool, result=bool)
    def setLocalAsrCloudRefinement(self, value: bool) -> bool:
        return self._update_config(
            replace(self._config, local_asr_cloud_refinement=bool(value))
        )

    def _hotkey_mapping(self, action: HotkeyAction) -> dict[str, Any]:
        settings = self._hotkey_settings_controller.settings
        try:
            definition = settings.definition(action)
        except KeyError:
            # A profile without this binding must not display an inactive
            # shortcut as if it were registered by the native backend.
            return {
                "id": action.value,
                "label": _HOTKEY_ACTION_LABELS[action],
                "display": "Not configured",
                "key": "",
                "modifiers": [],
            }
        mapping = definition.to_mapping()
        return {
            "id": action.value,
            "label": _HOTKEY_ACTION_LABELS[action],
            "display": definition.display,
            "key": mapping["key"],
            "modifiers": list(mapping["modifiers"]),
        }

    def _provider_config(self, provider_id: str):
        return getattr(self._config, provider_id)

    @staticmethod
    def _default_provider_base_url(provider_id: str) -> str:
        return str(PROVIDER_REGISTRY.describe(provider_id).default_base_url or "")

    def _provider_state(self, provider_id: str) -> dict[str, Any]:
        metadata = PROVIDER_REGISTRY.describe(provider_id)
        if provider_id == LOCAL_ASR_PROVIDER_ID:
            state = self._local_state
            return {
                "providerId": provider_id,
                "displayName": metadata.display_name,
                "kind": "local",
                "status": state.status,
                "detail": state.detail,
                "error": state.detail if state.status in {"error", "invalid"} else "",
                "busy": self._local_product.busy,
                "configured": state.status == "installed",
                "hasApiKey": False,
                "baseUrl": "",
                "requirements": _format_local_requirements(state.requirements or {}),
                "progress": state.fraction,
            }
        config = self._provider_config(provider_id)
        activity = self._provider_activity.get(provider_id, {})
        has_key = bool(config.api_key.strip())
        status = str(
            activity.get("status") or ("configured" if has_key else "not_configured")
        )
        return {
            "providerId": provider_id,
            "displayName": metadata.display_name,
            "kind": "cloud",
            "status": status,
            "detail": "",
            "error": str(activity.get("error") or ""),
            "busy": bool(activity.get("busy", False)),
            "configured": has_key and status in {"configured", "active"},
            "hasApiKey": has_key,
            "baseUrl": config.base_url or metadata.default_base_url,
            "models": list(activity.get("models", [])),
            "textModels": list(activity.get("textModels", [])),
        }

    @Slot(str, result=str)
    def providerName(self, provider_id: str) -> str:
        normalized = str(provider_id or "").strip().lower()
        if normalized not in PROVIDER_REGISTRY.provider_ids:
            return normalized
        return PROVIDER_REGISTRY.describe(normalized).display_name

    @Slot(str, int, bool, object)
    def _finish_provider_validation(
        self,
        provider_id: str,
        generation: int,
        success: bool,
        payload: object,
    ) -> None:
        if generation != self._provider_generations.get(provider_id):
            return
        self._provider_tokens.pop(provider_id, None)
        data = payload if isinstance(payload, dict) else {}
        if not success:
            self._provider_activity[provider_id] = {
                "status": "error",
                "error": str(data.get("error") or "Provider validation failed"),
                "models": [],
                "textModels": [],
                "busy": False,
            }
            self._set_error(ValueError(self._provider_activity[provider_id]["error"]))
            self.providerStateChanged.emit()
            return
        try:
            self._persist_provider_credentials(
                provider_id,
                str(data.get("api_key") or ""),
                str(data.get("base_url") or ""),
            )
        except Exception as error:
            self._provider_activity[provider_id] = {
                "status": "error",
                "error": str(error).strip() or type(error).__name__,
                "models": [],
                "textModels": [],
                "busy": False,
            }
            self._set_error(error)
            self.providerStateChanged.emit()
            return
        self._provider_activity[provider_id] = {
            "status": "active",
            "error": "",
            "models": list(data.get("models") or []),
            "textModels": list(data.get("text_models") or []),
            "busy": False,
        }
        if provider_id == self._selected_provider_id:
            self._provider_api_key_draft = ""
            self._provider_base_url_draft = self._config_provider_base_url(provider_id)
        self._set_error(None)
        self.configChanged.emit()
        self.providerStateChanged.emit()

    def _config_provider_base_url(self, provider_id: str) -> str:
        config = self._provider_config(provider_id)
        return config.base_url or self._default_provider_base_url(provider_id)

    def _persist_provider_credentials(
        self,
        provider_id: str,
        api_key: str,
        base_url: str,
        *,
        persisted_config: AppConfig | None = None,
    ) -> AppConfig:
        """Persist only provider credentials, without applying the QML draft."""

        persisted = persisted_config or self._config_repository.load()
        persisted_provider = getattr(persisted, provider_id)
        updated_persisted = replace(
            persisted,
            **{
                provider_id: replace(
                    persisted_provider,
                    api_key=str(api_key or "").strip(),
                    base_url=str(base_url or "").strip(),
                )
            },
        )
        saved = self._config_repository.apply(updated_persisted)

        # Keep unrelated unsaved Settings edits in the local draft while
        # reflecting the credential that was just persisted.
        draft_provider = self._provider_config(provider_id)
        self._config = replace(
            self._config,
            **{
                provider_id: replace(
                    draft_provider,
                    api_key=str(api_key or "").strip(),
                    base_url=str(base_url or "").strip(),
                )
            },
        )
        return saved

    @Slot(object)
    def _apply_local_state(self, state: object) -> None:
        if self._account_shutdown:
            return
        if isinstance(state, tuple):
            generation, state = state
            if generation != self._local_generation:
                return
        if isinstance(state, LocalASRProductState):
            self._local_state = state
            self._model_catalogs.pop((LOCAL_ASR_PROVIDER_ID, "", ""), None)
            self.providerStateChanged.emit()

    def _microphone_supports_explicit_selection(self) -> bool:
        backend_method = getattr(
            self._microphone_backend,
            "supports_explicit_microphone_selection",
            None,
        )
        if callable(backend_method):
            try:
                return bool(backend_method())
            except Exception:
                return False
        return platform.system() in {"Windows", "Darwin"}

    def _microphone_selectable_devices(self) -> tuple[Any, ...]:
        if not self._microphone_supports_explicit_selection():
            return ()
        backend_filter = getattr(
            self._microphone_backend,
            "selectable_microphone_devices",
            None,
        )
        if callable(backend_filter):
            try:
                return tuple(backend_filter(self._microphone_inventory))
            except Exception:
                return ()
        return tuple(self._microphone_inventory.available_devices)

    def _microphone_selection(self) -> MicrophoneSelection:
        return self._microphone_inventory.resolve(self._config.microphone.selected_id)

    def _microphone_selection_for_test(self) -> MicrophoneSelection | None:
        if self._microphone_inventory.error_code == "not_refreshed":
            return None
        requested_id = self._config.microphone.selected_id
        if not self._microphone_supports_explicit_selection():
            requested_id = None
        selection = self._microphone_inventory.resolve(requested_id)
        if selection.state is MicrophoneSelectionState.SELECTED:
            selectable_ids = {
                device.stable_id for device in self._microphone_selectable_devices()
            }
            if selection.selected_id not in selectable_ids:
                return MicrophoneSelection(
                    MicrophoneSelectionState.UNAVAILABLE,
                    requested_id=requested_id,
                    reason="unsafe_backend_name",
                )
        return selection

    def _microphone_status(self) -> tuple[str, str]:
        requested_id = self._config.microphone.selected_id
        if not self._microphone_supports_explicit_selection():
            if requested_id:
                return (
                    "Explicit input selection is unavailable with SoX PulseAudio; "
                    "System default remains active.",
                    "warning",
                )
            return (
                "Explicit input selection is unavailable with SoX PulseAudio; "
                "System default remains active.",
                "info",
            )

        if self._microphone_inventory.error_code in {
            "not_refreshed",
            "portaudio_unavailable",
            "enumeration_failed",
        }:
            return (
                "Input inventory unavailable; System default remains active.",
                "info",
            )

        selection = self._microphone_selection()
        if selection.state is MicrophoneSelectionState.SELECTED:
            selectable_ids = {
                device.stable_id for device in self._microphone_selectable_devices()
            }
            if selection.selected_id not in selectable_ids:
                return (
                    "Saved microphone cannot be routed safely; choose System default.",
                    "error",
                )
        if not selection.can_record:
            from shared.localization import translate

            return (
                translate(
                    "No safe input device ({code}).",
                    code=self._microphone_inventory.error_code or "unavailable",
                ),
                "error",
            )
        if selection.is_fallback:
            assert selection.device is not None
            from shared.localization import translate

            return (
                translate(
                    "Saved microphone unavailable; using current default: {name}",
                    name=selection.device.name,
                ),
                "warning",
            )
        assert selection.device is not None
        return (
            f"{selection.device.name} · {selection.device.host_api or 'default'}",
            "ok",
        )

    @Slot(int, bool, object)
    def _finish_microphone_test(
        self,
        generation: int,
        success: bool,
        payload: object,
    ) -> None:
        if generation != self._microphone_test_generation:
            return
        self._microphone_test_busy = False
        self._microphone_test_level = 0.0
        self.microphoneLevelChanged.emit()
        if self._microphone_test_cancel.is_set():
            self._microphone_test_status = "Test stopped."
            self._microphone_test_kind = "info"
        elif success:
            try:
                peak = float(payload)
            except (TypeError, ValueError):
                peak = 0.0
            self._microphone_test_status = (
                "Microphone input detected."
                if peak > 0.01
                else "No input detected. Check your microphone or choose another input."
            )
            self._microphone_test_kind = "ok" if peak > 0.01 else "warning"
        else:
            from shared.localization import translate

            message = str(payload or "Input test failed")
            self._microphone_test_status = translate(
                "Input test failed: {message}", message=translate(message)
            )
            self._microphone_test_kind = "error"
        self.microphoneTestChanged.emit()

    def _selected_route(self) -> WorkflowRoute:
        return self._config.workflow(self._selected_scope)

    @staticmethod
    def _canonical_scope(scope: str | WorkflowScope) -> str:
        if isinstance(scope, WorkflowScope):
            return scope.value
        normalized = str(scope or "").strip().lower()
        if normalized not in WORKFLOW_SCOPES:
            raise ValueError(f"Unknown workflow scope: {normalized or '<empty>'}")
        return normalized

    @staticmethod
    def _choice(value: object, choices: tuple[str, ...], field_name: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in choices:
            choices_text = ", ".join(choices)
            raise ValueError(
                f"Invalid {field_name} '{normalized}'; choose one of: {choices_text}"
            )
        return normalized

    @staticmethod
    def _route_mapping(route: WorkflowRoute, scope: str) -> dict[str, Any]:
        return {
            "scope": scope,
            "providerId": route.provider_id,
            "modelId": route.model_id,
            "prompt": route.prompt,
            "customEndpoint": route.custom_endpoint,
            "enabled": route.enabled,
        }

    def _update_selected_route(
        self, change: Callable[[WorkflowRoute], WorkflowRoute]
    ) -> bool:
        route = replace(change(self._selected_route()), independent=True)
        return self._update_config(
            replace(
                self._config,
                workflows=self._config.workflows.with_route(
                    self._selected_scope, route
                ),
            )
        )

    def _update_config(self, config: AppConfig) -> bool:
        self._set_error(None)
        if config == self._config:
            return True
        hotkeys_changed = config.hotkeys != self._config.hotkeys
        microphone_changed = (
            config.microphone != self._config.microphone
            or config.recording_controls != self._config.recording_controls
        )
        if config.microphone != self._config.microphone:
            self.stopMicrophoneTest()
        route_changed = config.workflow(self._selected_scope) != self._config.workflow(
            self._selected_scope
        )
        self._config = config
        capture_restored = True
        capture_changed = bool(self._hotkey_capture_action)
        if hotkeys_changed:
            self._hotkey_settings_controller.replace(config.hotkeys)
            capture_restored = self.cancelHotkeyCapture()
        if not self._dirty:
            self._dirty = True
            self.dirtyChanged.emit()
        self.configChanged.emit()
        if hotkeys_changed and not capture_changed:
            self.hotkeyChanged.emit()
        if microphone_changed:
            self.microphoneChanged.emit()
        if route_changed:
            self.routeChanged.emit()
        return capture_restored

    def _persist_ui_preference(
        self,
        change: Callable[[AppConfig], AppConfig],
    ) -> bool:
        """Read-modify-write one persisted preference, leaving the draft intact."""

        try:
            persisted_config = self._config_repository.load()
            self._config_repository.apply(change(persisted_config))
        except Exception as error:  # Repository errors belong in the QML state.
            self._set_error(error)
            return False
        self._set_error(None)
        return True

    def _replace_loaded_config(self, config: AppConfig) -> None:
        hotkeys_changed = config.hotkeys != self._config.hotkeys
        capture_changed = bool(self._hotkey_capture_action)
        microphone_changed = (
            config.microphone != self._config.microphone
            or config.recording_controls != self._config.recording_controls
        )
        route_changed = config.workflow(self._selected_scope) != self._config.workflow(
            self._selected_scope
        )
        config_changed = config != self._config
        self._config = config
        self._hotkey_settings_controller.replace(config.hotkeys)
        self.cancelHotkeyCapture()
        self._provider_api_key_draft = ""
        self._provider_base_url_draft = self._config_provider_base_url(
            self._selected_provider_id
        )
        if config_changed:
            self.configChanged.emit()
        if microphone_changed:
            self.microphoneChanged.emit()
        if hotkeys_changed and not capture_changed:
            self.hotkeyChanged.emit()
        self.providerStateChanged.emit()
        if route_changed:
            self.routeChanged.emit()
        if self._dirty:
            self._dirty = False
            self.dirtyChanged.emit()

    def _set_error(self, error: BaseException | None) -> None:
        message = "" if error is None else str(error).strip()
        if not message and error is not None:
            message = type(error).__name__
        if message == self._last_error:
            return
        self._last_error = message
        self.errorChanged.emit()


__all__ = ["QmlSettingsController"]
