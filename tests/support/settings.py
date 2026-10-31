"""Reusable settings fixtures. This module defines no test cases."""

from __future__ import annotations


import threading


from pathlib import Path


from repositories import (
    ApplicationRepositories,
    LocalConfigRepository,
    LocalUsageStatsRepository,
)

from secret_store import MemorySecretStore


ROOT = Path(__file__).resolve().parents[2]

SETTINGS = ROOT / "clarify" / "desktop" / "qml_settings.py"


def _repositories(directory: str) -> ApplicationRepositories:
    root = Path(directory)
    return ApplicationRepositories(
        config=LocalConfigRepository(
            root / "config.json",
            secret_store=MemorySecretStore(),
        ),
        usage_stats=LocalUsageStatsRepository(root / "usage_stats.json"),
    )


class _MicrophoneBackend:
    """Small QML-facing backend double that preserves typed inventory seams."""

    def __init__(self, inventory):
        self.inventory = inventory
        self.test_started = threading.Event()

    def supports_explicit_microphone_selection(self):
        return True

    def microphone_inventory(self):
        return self.inventory

    def selectable_microphone_devices(self, inventory):
        return inventory.available_devices

    def test_microphone(self, selection, inventory, **options):
        self.test_started.set()
        if options.get("on_level"):
            options["on_level"](0.42)
        return 0.42
