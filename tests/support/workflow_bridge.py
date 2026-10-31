"""Shared workflow bridge doubles. No runtime setup."""

from __future__ import annotations

from workflows import (
    WorkflowState,
    WorkflowPhase,
    StartDictation,
    StopDictation,
    CancelDictation,
    DismissMicrophoneUnavailable,
)


class DeterministicWorkflowService:
    """Small service double used only to exercise the bridge contract."""

    def __init__(self):
        self._state = WorkflowState()
        self._listeners = []
        self.commands = []
        self.finished = []

    @property
    def state(self):
        return self._state

    def subscribe(self, listener):
        self._listeners.append(listener)

    def publish(self, state):
        self._state = state
        for listener in tuple(self._listeners):
            listener(state)

    def dispatch(self, command):
        self.commands.append(command)
        operation_id = self._state.operation_id or 1
        if isinstance(command, StartDictation):
            self.publish(
                WorkflowState(
                    phase=WorkflowPhase.RECORDING,
                    operation_id=operation_id,
                    kind=command.__class__.__name__,
                )
            )
        elif isinstance(command, StopDictation):
            self.publish(
                WorkflowState(
                    phase=WorkflowPhase.PROCESSING,
                    operation_id=operation_id,
                )
            )
            self.publish(
                WorkflowState(
                    phase=WorkflowPhase.COMPLETED,
                    operation_id=operation_id,
                    result_text="Real result",
                )
            )
        elif isinstance(command, CancelDictation):
            self.publish(WorkflowState())
        elif isinstance(command, DismissMicrophoneUnavailable):
            self.publish(WorkflowState())
        return True

    def finish(self, operation_id):
        self.finished.append(operation_id)
        self.publish(WorkflowState())
        return True
