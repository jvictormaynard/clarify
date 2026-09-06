"""Qt-facing workflow boundary for the QML frontend.

The bridge owns only presentation state.  Dictation orchestration remains in
``workflows.WorkflowService`` and all long-running commands are submitted to
the injected dispatcher so a QML slot never waits for recording, providers,
clipboard work, or statistics.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

try:
    from workflows import (
        CancelDictation,
        CancelTranslation,
        ChooseTranslationLanguage,
        DismissMicrophoneUnavailable,
        StartDictation,
        StartRewrite,
        StartTranslation,
        StopDictation,
        RetryDictation,
        UndoCancelDictation,
        WorkflowPhase,
        WorkflowState,
    )
except ImportError:  # PyInstaller may analyze the spike as a standalone file.
    from ...workflows import (  # type: ignore[no-redef]
        CancelDictation,
        CancelTranslation,
        ChooseTranslationLanguage,
        DismissMicrophoneUnavailable,
        StartDictation,
        StartRewrite,
        StartTranslation,
        StopDictation,
        RetryDictation,
        UndoCancelDictation,
        WorkflowPhase,
        WorkflowState,
    )


try:
    from voice_translation import VoiceTranslationPhase
except ImportError:  # PyInstaller may analyze the spike as a package module.
    from ...voice_translation import VoiceTranslationPhase  # type: ignore[no-redef]


class QmlWorkflowBridge(QObject):
    """Expose one injected :class:`WorkflowService` to QML.

    The service listener is expected to be delivered by the service scheduler
    on the Qt GUI thread.  ``dispatch_runner`` is deliberately injectable so
    tests can execute commands deterministically; the real entrypoint passes
    the Qt scheduler's background runner.
    """

    surfaceChanged = Signal()
    statusChanged = Signal()
    resultChanged = Signal()
    busyChanged = Signal()
    canShowResultChanged = Signal()
    voiceChanged = Signal()
    recordingChanged = Signal()
    targetExecutableChanged = Signal()
    modeChanged = Signal()
    languageChanged = Signal()
    copyCompleted = Signal(bool)
    resultRequested = Signal()
    quickPasteCompleted = Signal(str)

    _TRANSLATION_OPTIONS = (
        {"code": "en", "label": "English"},
        {"code": "pt", "label": "Portuguese"},
        {"code": "es", "label": "Spanish"},
        {"code": "de", "label": "German"},
        {"code": "ru", "label": "Russian"},
    )

    _STATUS = {
        WorkflowPhase.READY: "Ready to capture your voice",
        WorkflowPhase.RECORDING: "Listening to your microphone",
        WorkflowPhase.PROCESSING: "Polishing your words",
        WorkflowPhase.REWRITING: "Polishing your words",
        WorkflowPhase.PREPARING_TRANSLATION: "Preparing translation",
        WorkflowPhase.TRANSLATION_PICKER: "Choose a translation language",
        WorkflowPhase.TRANSLATING: "Translating your words",
        WorkflowPhase.PUBLISHING: "Publishing your result",
        WorkflowPhase.MICROPHONE_UNAVAILABLE: "Microphone unavailable",
        WorkflowPhase.COMPLETED: "Your result is ready",
        WorkflowPhase.FAILED: "The dictation could not be completed",
    }
    _STATUS_KEYS = {
        "error": "The dictation could not be completed",
        "no_audio": "No usable audio was captured",
        "refinement_failed": "Refinement failed. Original text is available.",
        "transcription_network": "Could not connect to the transcription service",
        "no_selection": "No text selected. Select text and try again.",
        "rewrite_failed": "Could not rewrite the selected text. Try again.",
        "translation_failed": "Could not translate the selected text. Try again.",
        "provider_network": "Connection interrupted. Check your connection and try again.",
        "provider_timeout": "The service took too long to respond. Try again.",
        "provider_authentication": "Invalid API key. Check the provider connection in settings.",
        "provider_quota": "Provider quota exceeded. Check your balance or plan.",
        "provider_rate_limit": "Too many requests. Wait a moment and try again.",
        "provider_unavailable": "Service temporarily unavailable. Try again later.",
        "provider_invalid_model": "Model unavailable. Select another model in settings.",
        "provider_invalid_request": "The service rejected the request. Check the model settings.",
        "provider_invalid_response": "The service returned an invalid response. Try again.",
        "provider_cancelled": "Operation cancelled.",
    }
    _ERROR_MESSAGES_PT = {
        "error": "Não foi possível concluir a operação. Tente novamente.",
        "no_audio": "Nenhum áudio foi capturado. Verifique o microfone.",
        "no_selection": "Nenhum texto selecionado. Selecione um texto e tente novamente.",
        "rewrite_failed": "Não foi possível reescrever o texto. Tente novamente.",
        "translation_failed": "Não foi possível traduzir o texto. Tente novamente.",
        "transcription_network": "Falha de conexão com o serviço de transcrição.",
        "microphone_unavailable": "Microfone indisponível. Verifique a conexão e selecione um microfone.",
        "provider_network": "Conexão interrompida. Verifique sua conexão e tente novamente.",
        "provider_timeout": "O serviço demorou para responder. Tente novamente.",
        "provider_authentication": "Chave de API inválida. Verifique a conexão do provedor nas configurações.",
        "provider_quota": "Limite do provedor atingido. Verifique seu saldo ou plano.",
        "provider_rate_limit": "Muitas solicitações. Aguarde um pouco e tente novamente.",
        "provider_unavailable": "Serviço temporariamente indisponível. Tente novamente mais tarde.",
        "provider_invalid_model": "Modelo indisponível. Selecione outro modelo nas configurações.",
        "provider_invalid_request": "O serviço recusou a solicitação. Verifique a configuração do modelo.",
        "provider_invalid_response": "O serviço retornou uma resposta inválida. Tente novamente.",
        "provider_cancelled": "Operação cancelada.",
    }
    _ERROR_PHASES = frozenset(
        {
            WorkflowPhase.MICROPHONE_UNAVAILABLE,
            WorkflowPhase.FAILED,
        }
    )
    _BUSY_PHASES = frozenset(
        {
            WorkflowPhase.RECORDING,
            WorkflowPhase.PROCESSING,
            WorkflowPhase.REWRITING,
            WorkflowPhase.PREPARING_TRANSLATION,
            WorkflowPhase.TRANSLATION_PICKER,
            WorkflowPhase.TRANSLATING,
            WorkflowPhase.PUBLISHING,
        }
    )

    def __init__(
        self,
        workflow_service: Any,
        *,
        app_config: Any | None = None,
        dispatch_runner: Callable[[Callable[[], None]], None] | None = None,
        copy_runner: Callable[[str], Any] | None = None,
        voice_translation_handler: Callable[[], Any] | None = None,
        voice_translation_controller: Any | None = None,
        audio_batch_controller: Any | None = None,
        target_provider: Callable[[], Any | None] | None = None,
        paste_runner: Callable | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._workflow_service = workflow_service
        self._dispatch_runner = dispatch_runner or (lambda callback: callback())
        default_copy_runner = getattr(workflow_service, "copy_result", None)
        self._copy_runner = copy_runner or (
            default_copy_runner if callable(default_copy_runner) else lambda _text: None
        )
        self._voice_translation_handler = voice_translation_handler
        self._voice_translation_controller = voice_translation_controller
        self._audio_batch_controller = audio_batch_controller
        self._target_provider = target_provider
        self._paste_runner = paste_runner
        self._last_transcription = ""
        self._quick_paste_busy = False
        self._quick_feedback = ""
        self._quick_feedback_id = 0
        self.quickPasteCompleted.connect(self._finish_quick_paste)
        self._voice_state = (
            getattr(voice_translation_controller, "state", None)
            if voice_translation_controller is not None
            else None
        )
        self._state = workflow_service.state
        self._result_visible = False
        self._settings_visible = False
        self._files_visible = False
        self._finishing = False
        self._pending_workflow_action: Callable[[], None] | None = None
        self._target_executable = ""
        saved_config = app_config
        if saved_config is None:
            config_provider = getattr(workflow_service, "_config", None)
            current_config = getattr(config_provider, "current", None)
            if callable(current_config):
                saved_config = current_config()
        ui_preferences = getattr(saved_config, "ui", None)
        self._mode = self._normalize_mode(getattr(ui_preferences, "mode", "prompt"))
        self._language = self._normalize_language(
            getattr(ui_preferences, "language", "en")
        )
        workflow_service.subscribe(self._on_workflow_state)
        if voice_translation_controller is not None:
            voice_translation_controller.stateChanged.connect(
                self._on_voice_translation_state
            )
        if audio_batch_controller is not None:
            audio_batch_controller.runningChanged.connect(
                self._on_audio_batch_running_changed
            )

    @Property(str, notify=surfaceChanged)
    def surface(self) -> str:
        if self._settings_visible:
            return "settings"
        if self._result_visible:
            return "result"
        if self._files_visible:
            return "files"
        voice_surface = self._voice_surface()
        if voice_surface:
            return voice_surface
        if self._finishing:
            return "idle"
        return self._surface_for_phase(self._state.phase)

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        if self.cancellationVisible:
            return (
                "Transcrição cancelada"
                if self._language == "pt"
                else "Transcript cancelled"
            )
        voice_status = self._voice_status()
        if voice_status:
            return voice_status
        if self._finishing:
            return self._STATUS[WorkflowPhase.READY]
        if self._state.phase in self._ERROR_PHASES and self._language == "pt":
            key = (
                "microphone_unavailable"
                if self._state.phase is WorkflowPhase.MICROPHONE_UNAVAILABLE
                else self._state.status_key or "error"
            )
            return self._ERROR_MESSAGES_PT.get(key, self._ERROR_MESSAGES_PT["error"])
        if self._state.status_key in self._STATUS_KEYS:
            return self._STATUS_KEYS[self._state.status_key]
        return self._STATUS.get(
            self._state.phase,
            "The dictation could not be completed",
        )

    @Property(bool, notify=statusChanged)
    def refinementFailed(self) -> bool:
        return (
            not self._finishing
            and self._state.phase is WorkflowPhase.COMPLETED
            and self._state.status_key == "refinement_failed"
        )

    @Property(str, notify=resultChanged)
    def result(self) -> str:
        voice_result = self._voice_result()
        if self.surface in {"voice_result", "voice_error"}:
            return voice_result or self._voice_status()
        return self._state.result_text or ""

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return bool(
            self._state.phase in self._BUSY_PHASES
            or self._quick_paste_busy
            or getattr(self._voice_translation_controller, "active", False)
            or getattr(self._audio_batch_controller, "running", False)
        )

    @Property(bool, notify=recordingChanged)
    def recording(self) -> bool:
        return bool(
            self._state.phase is WorkflowPhase.RECORDING
            or self._voice_phase() is VoiceTranslationPhase.RECORDING
        )

    @Property(str, notify=targetExecutableChanged)
    def targetExecutable(self) -> str:
        return self._target_executable

    @Property(bool, notify=canShowResultChanged)
    def canShowResult(self) -> bool:
        if self.surface == "voice_result":
            return bool(self._voice_result())
        return self._state.phase is WorkflowPhase.COMPLETED and bool(
            self._state.result_text
        )

    @Property(bool, notify=surfaceChanged)
    def canRetryTranscription(self) -> bool:
        return self._state.phase is WorkflowPhase.FAILED and self._state.can_retry

    @Property(bool, notify=surfaceChanged)
    def cancellationVisible(self) -> bool:
        return self._state.phase is WorkflowPhase.CANCELLED and not self._finishing

    @Property(bool, notify=surfaceChanged)
    def canUndoCancellation(self) -> bool:
        return self.cancellationVisible and self._state.can_undo

    @Slot(result=bool)
    def undoCancellation(self) -> bool:
        if not self.canUndoCancellation:
            return False
        operation_id = self._state.operation_id
        self._submit(
            lambda: self._workflow_service.dispatch(UndoCancelDictation(operation_id))
        )
        return True

    @Property(bool, notify=surfaceChanged)
    def feedbackVisible(self) -> bool:
        return (
            not self._settings_visible
            and not self._files_visible
            and not self._voice_surface()
            and not self._result_visible
            and not self._finishing
            and (
                self._state.phase in self._ERROR_PHASES
                or self.refinementFailed
                or self.cancellationVisible
                or bool(self._quick_feedback)
            )
        )

    @Property(bool, notify=surfaceChanged)
    def transitionPending(self) -> bool:
        return self._pending_workflow_action is not None

    @Property(int, notify=surfaceChanged)
    def feedbackOperationId(self) -> int:
        return (
            self._quick_feedback_id
            if self._quick_feedback
            else self._state.operation_id
        )

    @Property(str, notify=statusChanged)
    def feedbackTitle(self) -> str:
        if self.refinementFailed:
            return self.status
        return self._quick_feedback or self.status.partition(". ")[0].rstrip(".")

    @Slot(int)
    def dismissFeedback(self, operation_id: int) -> None:
        if operation_id == self._state.operation_id and self.refinementFailed:
            self.finish()
            return
        if operation_id == self._state.operation_id and self.cancellationVisible:
            self.finish()
            return
        if self._quick_feedback and operation_id == self._quick_feedback_id:
            self._quick_feedback = ""
            self._notify_all()
            return
        # An old animation/timer must never dismiss a newer operation or
        # discard audio that the user can still explicitly resend.
        if (
            operation_id == self._state.operation_id
            and self._state.phase in self._ERROR_PHASES
            and not self.canRetryTranscription
        ):
            self.reset()

    @Slot(result=bool)
    def retryTranscription(self) -> bool:
        if not self.canRetryTranscription:
            return False
        operation_id = self._state.operation_id
        self._submit(
            lambda: self._workflow_service.dispatch(RetryDictation(operation_id))
        )
        return True

    @Property(str, notify=modeChanged)
    def mode(self) -> str:
        return self._mode

    @Property(str, notify=languageChanged)
    def language(self) -> str:
        return self._language

    @Property("QVariantList", constant=True)
    def translationOptions(self) -> list[dict[str, str]]:
        """Return the supported target languages in a QML-friendly shape."""

        return [dict(option) for option in self._TRANSLATION_OPTIONS]

    def _voice_runtime_state(self) -> Any | None:
        return self._voice_state

    def _voice_phase(self) -> VoiceTranslationPhase | None:
        state = self._voice_runtime_state()
        return getattr(state, "phase", None)

    def _voice_workflow_state(self) -> Any | None:
        state = self._voice_runtime_state()
        return getattr(state, "workflow_state", None)

    def _voice_result(self) -> str:
        state = self._voice_workflow_state()
        if state is None:
            return ""
        return str(
            getattr(state, "published_text", "")
            or getattr(state, "translated_text", "")
            or getattr(state, "raw_transcript", "")
            or ""
        )

    def _voice_surface(self) -> str:
        phase = self._voice_phase()
        controller = self._voice_translation_controller
        if phase is None or controller is None:
            return ""
        if bool(getattr(controller, "active", False)):
            return "voice_processing"
        if phase is VoiceTranslationPhase.COMPLETED:
            # Publication already copied/pasted the result. Success is silent.
            return ""
        if phase is VoiceTranslationPhase.FAILED:
            return "voice_result" if self._voice_result() else "voice_error"
        return ""

    def _voice_status(self) -> str:
        phase = self._voice_phase()
        if phase is None or self._voice_translation_controller is None:
            return ""
        statuses = {
            VoiceTranslationPhase.RECORDING: "Listening for voice translation",
            VoiceTranslationPhase.TRANSCRIBING: "Transcribing voice translation",
            VoiceTranslationPhase.TRANSLATING: "Translating your words",
            VoiceTranslationPhase.PUBLISHING: "Publishing your translation",
            VoiceTranslationPhase.COMPLETED: "Voice translation is ready",
            VoiceTranslationPhase.FAILED: "Voice translation could not be completed",
            VoiceTranslationPhase.CANCELLED: "Voice translation cancelled",
        }
        state = self._voice_runtime_state()
        error = str(getattr(state, "error", "") or "")
        return (
            error
            if phase is VoiceTranslationPhase.FAILED and error
            else statuses.get(phase, "")
        )

    @staticmethod
    def _surface_for_phase(phase: WorkflowPhase) -> str:
        if phase is WorkflowPhase.RECORDING:
            return "recording"
        if phase is WorkflowPhase.TRANSLATION_PICKER:
            return "translation_picker"
        if phase in (
            WorkflowPhase.PROCESSING,
            WorkflowPhase.REWRITING,
            WorkflowPhase.PREPARING_TRANSLATION,
            WorkflowPhase.TRANSLATING,
            WorkflowPhase.PUBLISHING,
        ):
            return "processing"
        if phase is WorkflowPhase.COMPLETED:
            # Keep the text available to quick paste without opening a panel.
            return "idle"
        if phase in QmlWorkflowBridge._ERROR_PHASES:
            return "error"
        return "idle"

    def _notify_all(self) -> None:
        self.surfaceChanged.emit()
        self.statusChanged.emit()
        self.resultChanged.emit()
        self.busyChanged.emit()
        self.canShowResultChanged.emit()
        self.voiceChanged.emit()
        self.recordingChanged.emit()

    @Slot(object)
    def _on_workflow_state(self, state: WorkflowState) -> None:
        self._state = state
        self._quick_feedback = ""
        if (
            state.phase is WorkflowPhase.COMPLETED
            and state.kind == "dictation"
            and state.result_text
        ):
            self._last_transcription = state.result_text
        if state.target_executable:
            self.setTargetExecutable(state.target_executable)
        self._finishing = False
        if state.phase is not WorkflowPhase.COMPLETED:
            self._result_visible = False
        self._notify_all()
        if state.phase is WorkflowPhase.READY:
            pending_action = self._pending_workflow_action
            self._pending_workflow_action = None
            if pending_action is not None:
                pending_action()

    @Slot(object)
    def _on_voice_translation_state(self, state: Any) -> None:
        self._voice_state = state
        self._notify_all()

    @Slot()
    def _on_audio_batch_running_changed(self) -> None:
        self._notify_all()

    def _submit(self, callback: Callable[[], None]) -> None:
        self._dispatch_runner(callback)

    def _run_when_ready(self, action: Callable[[], None]) -> bool:
        """Release a terminal result before starting the next workflow.

        The workflow service deliberately keeps terminal operations alive until
        the view releases them, so the result can still be copied or inspected.
        A new hotkey is an explicit request to move on, though, and should not
        require a separate Dismiss click.  Queue one action while the service
        publishes READY, including the case where clipboard publication is
        still finishing in the background.
        """

        if self._state.phase is WorkflowPhase.READY:
            action()
            return True
        if self._state.phase not in (
            WorkflowPhase.COMPLETED,
            WorkflowPhase.FAILED,
            WorkflowPhase.CANCELLED,
        ):
            return False
        if self._pending_workflow_action is not None:
            return False
        self._pending_workflow_action = action
        if not self._finishing:
            self.finish()
        return True

    def _capture_target(self) -> Any | None:
        if self._target_provider is None:
            return None
        try:
            target = self._target_provider()
        except Exception:
            return None
        if target is not None:
            self.setTargetExecutable(getattr(target, "executable", "") or "")
        return target

    @Slot(str)
    def setTargetExecutable(self, executable: str) -> None:
        normalized = str(executable or "")
        if normalized == self._target_executable:
            return
        self._target_executable = normalized
        self.targetExecutableChanged.emit()

    @staticmethod
    def _normalize_mode(mode: Any) -> str:
        return "prompt"

    @staticmethod
    def _normalize_language(language: Any) -> str:
        normalized = str(language or "").strip().lower()
        return normalized or "en"

    @Slot(str)
    def setMode(self, mode: str) -> None:
        normalized = self._normalize_mode(mode)
        if normalized != self._mode:
            self._mode = normalized
            self.modeChanged.emit()

    @Slot(str)
    def setLanguage(self, language: str) -> None:
        normalized = str(language or "").strip().lower()
        if normalized and normalized != self._language:
            self._language = normalized
            self.languageChanged.emit()
            self.statusChanged.emit()

    @Slot(str, result=bool)
    def chooseTranslation(self, language: str) -> bool:
        """Dispatch a real translation-language choice from the picker."""

        if self._state.phase is not WorkflowPhase.TRANSLATION_PICKER:
            return False
        normalized = str(language or "").strip().lower()
        supported = {option["code"] for option in self._TRANSLATION_OPTIONS}
        if normalized not in supported:
            return False
        self._submit(
            lambda: self._workflow_service.dispatch(
                ChooseTranslationLanguage(normalized)
            )
        )
        return True

    @Slot(result=bool)
    def cancelTranslation(self) -> bool:
        """Cancel the active picker through the workflow service."""

        if self._state.phase is not WorkflowPhase.TRANSLATION_PICKER:
            return False
        self._submit(lambda: self._workflow_service.dispatch(CancelTranslation()))
        return True

    @Slot()
    def startRecording(self) -> None:
        if self._quick_paste_busy:
            return
        if self._state.phase in (
            WorkflowPhase.COMPLETED,
            WorkflowPhase.FAILED,
            WorkflowPhase.CANCELLED,
        ):
            self._run_when_ready(self.startRecording)
            return
        if self._state.phase is not WorkflowPhase.READY:
            return
        self._settings_visible = False
        self._result_visible = False
        target = self._capture_target()
        self._submit(
            lambda: self._workflow_service.dispatch(
                StartDictation(target, self._mode, self._language)
            )
        )

    @Slot()
    def stopRecording(self) -> None:
        if self._state.phase is not WorkflowPhase.RECORDING:
            return
        self._submit(lambda: self._workflow_service.dispatch(StopDictation()))

    @Slot()
    def cancelRecording(self) -> None:
        if self._state.phase is not WorkflowPhase.RECORDING:
            return
        self._submit(
            lambda: self._workflow_service.dispatch(CancelDictation(retain_audio=True))
        )

    def _dismiss_files_before_workflow(self) -> bool:
        if not self._files_visible:
            return True
        self.closeFiles()
        return not self._files_visible

    @Slot(str, result=bool)
    def handleHotkey(self, action: str) -> bool:
        """Dispatch a native-shell action through the real workflow service."""

        if self._quick_paste_busy:
            return False
        normalized = str(action or "").strip().lower()
        if normalized == "voice_translation_hotkey":
            # Dedicated voice translation intentionally lives outside
            # WorkflowService.  Keep the old runtime's toggle command as an
            # explicit composition seam rather than silently treating voice
            # translation as dictation or selected-text translation.
            if self._voice_translation_handler is None:
                return False
            if self._state.phase is WorkflowPhase.CANCELLED:
                return self._run_when_ready(
                    lambda: self.handleHotkey("voice_translation_hotkey")
                )
            voice_active = bool(
                getattr(self._voice_translation_controller, "active", False)
            )
            if self.busy and not voice_active:
                return False
            if not voice_active and not self._dismiss_files_before_workflow():
                return False
            self._submit(self._voice_translation_handler)
            return True

        if normalized == "recording_hotkey":
            if self._state.phase is WorkflowPhase.RECORDING:
                self.stopRecording()
                return True
            if self.busy:
                return False
            if self._state.phase in (
                WorkflowPhase.COMPLETED,
                WorkflowPhase.FAILED,
                WorkflowPhase.CANCELLED,
            ):
                return self._run_when_ready(self.startRecording)
            if self._state.phase is WorkflowPhase.READY:
                if not self._dismiss_files_before_workflow():
                    return False
                self.startRecording()
                return True
            return False

        if normalized == "rewrite_hotkey":
            if self.busy:
                return False
            if self._state.phase in (
                WorkflowPhase.COMPLETED,
                WorkflowPhase.FAILED,
                WorkflowPhase.CANCELLED,
            ):
                return self._run_when_ready(lambda: self.handleHotkey("rewrite_hotkey"))
            if self._state.phase is not WorkflowPhase.READY:
                return False
            if not self._dismiss_files_before_workflow():
                return False
            target = self._capture_target()
            self._submit(lambda: self._workflow_service.dispatch(StartRewrite(target)))
            return True

        if normalized == "translation_hotkey":
            if self.busy:
                return False
            if self._state.phase in (
                WorkflowPhase.COMPLETED,
                WorkflowPhase.FAILED,
                WorkflowPhase.CANCELLED,
            ):
                return self._run_when_ready(
                    lambda: self.handleHotkey("translation_hotkey")
                )
            if self._state.phase is not WorkflowPhase.READY:
                return False
            if not self._dismiss_files_before_workflow():
                return False
            target = self._capture_target()
            self._submit(
                lambda: self._workflow_service.dispatch(StartTranslation(target))
            )
            return True

        if normalized == "escape":
            if self._state.phase is WorkflowPhase.RECORDING:
                self.cancelRecording()
                return True
            if self._state.phase is WorkflowPhase.TRANSLATION_PICKER:
                return self.cancelTranslation()
        return False

    @Slot()
    def showResult(self) -> None:
        if not self.canShowResult:
            return
        self._result_visible = True
        self._settings_visible = False
        self._notify_all()
        self.resultRequested.emit()

    @Slot(result=bool)
    def copyResult(self) -> bool:
        if not self.canShowResult:
            return False
        result = self.result

        def copy() -> None:
            try:
                self._copy_runner(result)
            except Exception:
                self.copyCompleted.emit(False)
            else:
                self.copyCompleted.emit(True)

        self._submit(copy)
        return True

    @Slot()
    def finish(self) -> None:
        if self._state.phase not in (
            WorkflowPhase.COMPLETED,
            WorkflowPhase.FAILED,
            WorkflowPhase.CANCELLED,
        ):
            return
        operation_id = self._state.operation_id
        self._finishing = True
        self._result_visible = False
        self._settings_visible = False
        self._notify_all()
        self._submit(lambda: self._workflow_service.finish(operation_id))

    @Slot()
    def reset(self) -> None:
        if self._quick_feedback:
            self.dismissFeedback(self._quick_feedback_id)
            return
        controller = self._voice_translation_controller
        if controller is not None:
            voice_surface = self._voice_surface()
            if bool(getattr(controller, "active", False)):
                controller.cancel()
                return
            if voice_surface in {"voice_result", "voice_error"}:
                clear = getattr(controller, "clear", None)
                if callable(clear):
                    clear()
                self._notify_all()
                return
        if self._settings_visible:
            self.closeSettings()
            return
        if self._files_visible:
            self.closeFiles()
            return
        if self._state.phase is WorkflowPhase.RECORDING:
            self.cancelRecording()
            return
        if self._state.phase is WorkflowPhase.MICROPHONE_UNAVAILABLE:
            self._submit(
                lambda: self._workflow_service.dispatch(DismissMicrophoneUnavailable())
            )
            return
        if self._state.phase in (
            WorkflowPhase.COMPLETED,
            WorkflowPhase.FAILED,
            WorkflowPhase.CANCELLED,
        ):
            self.finish()

    @Slot()
    def openSettings(self) -> None:
        if self.busy:
            return

        def show_settings() -> None:
            self._files_visible = False
            self._settings_visible = True
            self._result_visible = False
            self._notify_all()

        if self._state.phase in (WorkflowPhase.FAILED, WorkflowPhase.CANCELLED):
            # Editing settings must not discard retained audio or undo state.
            show_settings()
        else:
            self._run_when_ready(show_settings)

    @Slot()
    def closeSettings(self) -> None:
        if not self._settings_visible:
            return
        self._settings_visible = False
        self._notify_all()

    @Slot()
    def openFiles(self) -> None:
        if self.busy or self._state.phase is not WorkflowPhase.READY:
            return
        self._settings_visible = False
        self._files_visible = True
        self._result_visible = False
        self._notify_all()

    @Slot()
    def closeFiles(self) -> None:
        if not self._files_visible:
            return
        if bool(getattr(self._audio_batch_controller, "running", False)):
            return
        self._files_visible = False
        self._notify_all()

    @Property(bool, notify=surfaceChanged)
    def canPasteLastTranscription(self) -> bool:
        return bool(self._last_transcription and self._paste_runner and not self.busy)

    @Slot(result=bool)
    def pasteLastTranscription(self) -> bool:
        if not self.canPasteLastTranscription:
            return False
        self._quick_feedback = ""
        self._quick_paste_busy = True
        self._notify_all()
        try:
            self._paste_runner(self._last_transcription, self.quickPasteCompleted.emit)
        except Exception:
            self.quickPasteCompleted.emit("failed")
        return True

    @Slot(str)
    def showQuickNotice(self, text: str) -> None:
        self._quick_feedback_id -= 1
        self._quick_feedback = text
        self._notify_all()

    @Slot(str)
    def _finish_quick_paste(self, result: str) -> None:
        self._quick_paste_busy = False
        if result != "pasted":
            self._quick_feedback_id -= 1
            if result == "copied":
                self._quick_feedback = (
                    "Texto copiado. Use Ctrl+V para colar"
                    if self._language == "pt"
                    else "Text copied. Press Ctrl+V to paste"
                )
            else:
                self._quick_feedback = (
                    "Não foi possível colar a transcrição"
                    if self._language == "pt"
                    else "Could not paste the transcript"
                )
        self._notify_all()
