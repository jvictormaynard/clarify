"""Shared native shell doubles. No runtime setup."""

from __future__ import annotations


class FakeWindow:
    def __init__(self, *, visible: bool = False, handle: int = 123):
        self.visible = visible
        self.handle = handle
        self.calls: list[str] = []
        self.event_filters = []
        self.removed_event_filters = []

    def installEventFilter(self, filter_object) -> None:
        self.event_filters.append(filter_object)

    def removeEventFilter(self, filter_object) -> None:
        self.removed_event_filters.append(filter_object)

    def winId(self) -> int:
        return self.handle

    def show(self) -> None:
        self.visible = True
        self.calls.append("show")

    def hide(self) -> None:
        self.visible = False
        self.calls.append("hide")

    def isVisible(self) -> bool:
        return self.visible

    def raise_(self) -> None:
        self.calls.append("raise")

    def requestActivate(self) -> None:
        self.calls.append("activate")


class FakeNativeEventTarget:
    def __init__(self):
        self.installed = []
        self.removed = []

    def installNativeEventFilter(self, filter_object) -> None:
        self.installed.append(filter_object)

    def removeNativeEventFilter(self, filter_object) -> None:
        self.removed.append(filter_object)
