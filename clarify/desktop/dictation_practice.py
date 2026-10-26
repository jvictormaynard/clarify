"""Optional dictation practice through the existing workflow interface."""

from collections.abc import Callable

from workflows import (
    DismissMicrophoneUnavailable,
    SelectionDisposition,
    StartDictation,
    StopDictation,
    WorkflowPhase,
    WorkflowService,
)


class PracticeDestination:
    """A dictation destination with no operating-system clipboard access."""

    def write_dictation_result(self, target, text):
        if target is not None:
            raise ValueError("Practice cannot have an external target")
        return SelectionDisposition.COPIED


class PracticeController:
    """Own presentation only; the workflow owns audio, providers and accounting.

    Commands run on the Qt thread. WorkflowService schedules capture and provider
    work off that thread and rejects stale results before publication.
    """

    def __init__(
        self,
        workflow: WorkflowService,
        *,
        language: Callable[[], str],
        readiness: Callable[[], str],
        can_open: Callable[[], bool] = lambda: True,
        identity: Callable[[], object] = lambda: None,
    ):
        self.workflow = workflow
        self.language = language
        self.readiness = readiness
        self.can_open = can_open
        self.identity = identity
        self._identity = None
        self._operation_id = None
        self._generation = 0
        self.open = False
        self._listeners = []
        self._held = False
        workflow.subscribe(self._on_state)

    def _on_state(self, _state):
        if self.open and self.identity() != self._identity:
            self.command("close")
        self._notify()

    @property
    def busy(self) -> bool:
        return self.workflow.state.phase in {
            WorkflowPhase.RECORDING,
            WorkflowPhase.PROCESSING,
        }

    @property
    def blocks_processing(self) -> bool:
        return self.open or self.workflow.state.phase is not WorkflowPhase.READY

    def subscribe(self, callback):
        self._listeners.append(callback)

    def _notify(self):
        for callback in tuple(self._listeners):
            callback()

    def snapshot(self):
        if self.open and self.identity() != self._identity:
            self.command("close")
        state = self.workflow.state
        visible = self.open and state.operation_id == self._operation_id
        return {
            "open": self.open,
            "phase": state.phase.value if visible else "ready",
            "text": (state.result_text or "") if visible else "",
            "source": (state.source_text or "") if visible else "",
            "status": (state.status_key or "") if visible else "",
            "blocked": self.readiness() if self.open else "",
        }

    def command(self, action):
        if action == "open":
            # Opening the screen never allocates a recording or calls a provider.
            if not self.can_open():
                return False
            if self.open:
                return True
            self._generation += 1
            self._identity = self.identity()
            self._operation_id = None
            self.open = True
        elif action == "close":
            self.open = False
            self._held = False
            self._operation_id = None
            self._generation += 1
            self.workflow.cancel_active()
        elif not self.open:
            return False
        elif self.identity() != self._identity:
            self.command("close")
            return False
        elif action == "cancel":
            self._held = False
            self.workflow.cancel_active()
        elif action == "start":
            if self.busy or self.readiness():
                return True
            state = self.workflow.state
            if state.phase is WorkflowPhase.MICROPHONE_UNAVAILABLE:
                self.workflow.dispatch(DismissMicrophoneUnavailable())
            elif state.phase is not WorkflowPhase.READY:
                self.workflow.finish(state.operation_id)
            generation = self._generation
            if self.workflow.dispatch(StartDictation(None, "prompt", self.language())):
                if generation == self._generation and self.identity() == self._identity:
                    self._operation_id = self.workflow.state.operation_id
                else:
                    self.workflow.cancel_active()
        elif action == "stop":
            self.workflow.dispatch(StopDictation())
        else:
            return False
        self._notify()
        return True

    def handle_hotkey(self, action):
        if not self.open:
            return False
        if action == "recording_hotkey":
            self.command(
                "stop"
                if self.workflow.state.phase is WorkflowPhase.RECORDING
                else "start"
            )
        elif action == "recording_hold_press" and not self._held:
            self._held = True
            self.command("start")
        elif action == "recording_hold_release":
            if self._held:
                self._held = False
                self.command("stop")
        elif action == "escape":
            self.command("cancel")
        # Consume every workflow shortcut while this safe destination is open.
        return True


def practice_readiness(settings, can_start):
    """Read persisted route readiness without testing credentials or capturing audio."""
    if (
        not can_start()
        or settings.microphoneTestBusy
        or settings.microphoneInventoryBusy
    ):
        return "practice_busy"
    if settings.dirty or settings.providerDirty or settings.onboardingRequired:
        return "practice_configuration"
    account = settings.accountState
    if account.get("busy") or account.get("pending") or settings.hotkeyCaptureAction:
        return "practice_busy"
    if account.get("managed") or account.get("signedIn"):
        # The provider/account owner revalidates session and quota on processing.
        return "" if account.get("signedIn") else "practice_session"
    config = settings.repositories.config.load()
    route = config.workflow("transcription")
    if not route.enabled or not route.model_id:
        return "practice_configuration"
    if route.provider_id == "local_asr":
        return (
            ""
            if settings.localAsrStatus == "installed" and not settings.localAsrBusy
            else "practice_model"
        )
    if not getattr(getattr(config, route.provider_id), "api_key", ""):
        return "practice_configuration"
    return ""
