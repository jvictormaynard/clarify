"""Reusable recording controls fixtures. This module defines no test cases."""

from workflows import (
    WorkflowState,
)


class Service:
    def __init__(self):
        self.state = WorkflowState()
        self.commands = []

    def subscribe(self, listener):
        self.listener = listener

    def publish(self, phase):
        self.state = WorkflowState(phase=phase)
        self.listener(self.state)

    def dispatch(self, command):
        self.commands.append(command)
