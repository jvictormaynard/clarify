"""Qt ownership for explicitly enabled personal mobile access.

The host owns TLS, pairing and devices. This adapter owns desktop consent,
one serial lifecycle worker and a short-lived QR image outside Settings state.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import io
import math
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import sqlite3
import subprocess
import threading
import time
from typing import Callable, Protocol

from PySide6.QtCore import QObject, Property, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface


def _windows_physical_interfaces() -> set[int] | None:
    if os.name != "nt":
        return None
    try:
        # Hyper-V adapters can report Ethernet to Qt. Query hardware identity
        # once per QR creation, on the lifecycle worker, with fixed arguments.
        executable = (
            Path(os.environ["SystemRoot"])
            / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        result = subprocess.run(
            [
                str(executable),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$ErrorActionPreference='Stop'; Get-NetAdapter -Physical -IncludeHidden | Select-Object -First 128 -ExpandProperty ifIndex",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if len(result.stdout) > 4096:
            return None
        lines = result.stdout.split()
        if len(lines) > 128 or any(not value.isdecimal() for value in lines):
            return None
        return {int(value) for value in lines}
    except (OSError, subprocess.SubprocessError, KeyError, ValueError):
        return None


def computer_addresses() -> list[str]:
    """Order active physical LAN interfaces before VPN and virtual routes."""
    physical = _windows_physical_interfaces()
    ranked = []
    for interface in QNetworkInterface.allInterfaces():
        flags = interface.flags()
        if (
            not flags & QNetworkInterface.IsUp
            or not flags & QNetworkInterface.IsRunning
            or flags & QNetworkInterface.IsLoopBack
            or interface.type() == QNetworkInterface.Loopback
        ):
            continue
        lan = interface.type() in (QNetworkInterface.Wifi, QNetworkInterface.Ethernet)
        if physical is not None:
            priority = 0 if interface.index() in physical and lan else 2
        else:
            # Qt can distinguish Wi-Fi from Ethernet on supported platforms.
            # Prefer it when hardware discovery cannot exclude virtual Ethernet.
            priority = (
                0 if interface.type() == QNetworkInterface.Wifi else (1 if lan else 2)
            )
        ranked.append((priority, interface))
    return [
        entry.ip().toString()
        for _, interface in sorted(ranked, key=lambda item: item[0])
        for entry in interface.addressEntries()
        if entry.ip().protocol() == QAbstractSocket.IPv4Protocol
    ]


class ComputerHost(Protocol):
    def start(self): ...
    def stop(self): ...
    def create_pairing(self) -> dict: ...
    def snapshot(self) -> dict: ...
    def revoke_device(self, device_id: str): ...


def qr_image(url: str) -> str:
    # SVG needs neither Pillow nor a remote QR service. The runtime dependency
    # is optional for source runs; a missing encoder fails closed in the panel.
    import qrcode
    from qrcode.image.svg import SvgPathImage

    output = io.BytesIO()
    qrcode.make(url, image_factory=SvgPathImage, border=4).save(output)
    return "data:image/svg+xml;base64," + base64.b64encode(output.getvalue()).decode()


def _timestamp(value) -> float:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (
            parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        ).timestamp()
    return float(value)


class QmlComputerController(QObject):
    changed = Signal()

    def __init__(
        self,
        state_path: Path,
        host_factory: Callable[[], ComputerHost],
        *,
        blocked: Callable[[], bool] = lambda: False,
        render_qr: Callable[[str], str] = qr_image,
        clock: Callable[[], float] = time.time,
        parent=None,
    ):
        super().__init__(parent)
        self.path = Path(state_path)
        self._factory = host_factory
        self._blocked = blocked
        self._account_transition = False
        self._last_blocked = bool(blocked())
        self._authorized = threading.Event()
        if not self._last_blocked:
            self._authorized.set()
        self._render_qr = render_qr
        self._clock = clock
        self._worker = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ClarifyComputer"
        )
        self._host: ComputerHost | None = None
        self._closed = False
        self._shutdown_succeeded = False
        self._initialized = False
        self._busy = False
        self._pending = 0
        self._refreshing = False
        self._enabled = False
        self._durable = False
        self._running = False
        self._relay_configured = False
        self._relay_connected = False
        self._devices: list[dict[str, str]] = []
        self._error = ""
        self._image = ""
        self._expires = 0.0
        self._panel_generation = 0
        self._results: SimpleQueue[dict] = SimpleQueue()
        self._result_timer = QTimer(self)
        self._result_timer.setInterval(25)
        self._result_timer.timeout.connect(self._drain)
        self._result_timer.start()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)

    def _read_durable(self):
        if not self.path.exists():
            return False
        with closing(sqlite3.connect(self.path)) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='desktop_access_preferences'"
            ).fetchone()
            if not exists:
                return False
            value = connection.execute(
                "SELECT durable FROM desktop_access_preferences WHERE id=1"
            ).fetchone()
            return value is not None and value[0] == 1

    def _write_durable(self, value):
        # Do not create host metadata before its protected identity exists.
        # A stop before the first activation has no persisted consent to revoke.
        if not value and (not self.path.exists() or not self.path.stat().st_size):
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS desktop_access_preferences (id INTEGER PRIMARY KEY CHECK (id=1), durable INTEGER NOT NULL CHECK (durable IN (0,1)))"
            )
            connection.execute(
                "INSERT OR REPLACE INTO desktop_access_preferences VALUES (1, ?)",
                (int(value),),
            )

    def initialize(self):
        """Only the application composition root calls this after primary startup."""
        if self._initialized or self._closed:
            return
        self._initialized = True
        self._timer.start()
        self._submit("restore")

    def snapshot(self):
        self._expire()
        blocked = self._is_blocked()
        return dict(
            enabled=self._enabled,
            running=self._running,
            relayConfigured=self._relay_configured,
            relayConnected=self._relay_connected,
            durable=self._durable,
            busy=self._busy,
            blocked=blocked,
            error=self._error,
            devices=list(self._devices),
            pairingReady=bool(self._image) and not blocked,
            pairingExpiresAt=self._expires if self._image and not blocked else 0,
        )

    @Property(str, notify=changed)
    def pairingImage(self):
        return self.pairing().get("image", "")

    def pairing(self):
        self._expire()
        if self._closed or self._is_blocked() or not self._image:
            return {}
        return {"image": self._image, "expiresAt": self._expires}

    def _clear_pairing(self):
        self._panel_generation += 1
        self._image = ""
        self._expires = 0.0

    def _expire(self):
        if self._image and self._clock() >= self._expires:
            self._clear_pairing()
            self.changed.emit()

    def command(self, action: str, value: str = "") -> bool:
        if type(action) is not str or type(value) is not str:
            raise ValueError("Invalid computer command")
        if action == "close" and not value:
            changed = bool(self._image)
            self._clear_pairing()
            if changed:
                self.changed.emit()
            return True
        if self._closed or action not in {
            "enable",
            "pair",
            "stop",
            "revoke",
            "durable",
        }:
            return False
        if action == "durable" and (
            value not in {"true", "false"} or not self._enabled
        ):
            return False
        if action == "revoke" and (not value or len(value) > 128):
            return False
        if action not in {"revoke", "durable"} and value:
            return False
        if self._is_blocked() and action not in {"stop", "revoke"}:
            self._clear_pairing()
            self.changed.emit()
            return False
        if action in {"enable", "pair", "stop"}:
            self._clear_pairing()
        if self._busy and action != "stop":
            return False
        if action == "pair" and not self._running:
            return False
        if action == "stop":
            self._authorized.clear()
        elif action == "enable":
            self._authorized.set()
        self._submit(action, value)
        return True

    def _is_blocked(self):
        return self._account_transition or bool(self._blocked())

    def refresh(self):
        self._expire()
        if self._closed:
            return
        blocked = self._is_blocked()
        if blocked != self._last_blocked:
            self._last_blocked = blocked
            if blocked:
                self._authorized.clear()
                self._clear_pairing()
            self.changed.emit()
        if self._busy or self._refreshing:
            return
        if blocked and self._enabled:
            self.command("stop")
        elif self._enabled:
            self._submit("refresh")

    def prepare_account_change(self):
        """Close personal access before the account worker mutates its owner."""
        self._account_transition = True
        self._authorized.clear()
        self._clear_pairing()
        self._last_blocked = True
        self.changed.emit()
        # A failed activation can retain a host whose drain is not confirmed.
        # Always put the barrier on its owning worker before changing accounts.
        return self._submit("stop")

    def finish_account_change(self):
        self._account_transition = False
        self.refresh()

    def _submit(self, action, value=""):
        if action == "refresh":
            self._refreshing = True
        else:
            self._pending += 1
            self._busy = True
            self._error = ""
        generation = self._panel_generation
        if action != "refresh":
            self.changed.emit()

        def run():
            result = {"action": action, "generation": generation}
            try:
                if action == "restore":
                    durable = self._read_durable()
                    result["durable"] = durable
                    if durable and self._authorized.is_set():
                        result["enabled"] = self._start_host()
                elif action == "enable":
                    result["enabled"] = self._start_host()
                elif action == "stop":
                    try:
                        self._write_durable(False)
                        result["durable"] = False
                    finally:
                        # Disk failure must not leave personal access listening.
                        if self._host is not None:
                            self._host.stop()
                            self._host = None
                        result.update(enabled=False, status={})
                elif action == "durable":
                    self._write_durable(value == "true")
                    result["durable"] = value == "true"
                elif action == "pair":
                    if self._host is None:
                        raise ValueError("Host is stopped")
                    pairing = self._host.create_pairing()
                    expires = _timestamp(pairing["expires_at"])
                    if (
                        not math.isfinite(expires)
                        or not 0 < expires - self._clock() <= 301
                    ):
                        raise ValueError("Expired pairing")
                    result.update(
                        image=self._render_qr(pairing["pairing_url"]), expires=expires
                    )
                elif action == "revoke":
                    if self._host is not None:
                        self._host.revoke_device(value)
                if self._host is not None:
                    result["status"] = self._host.snapshot()
                    result["status"]["ready"] = bool(
                        getattr(
                            self._host, "ready", result["status"].get("ready", False)
                        )
                    )
                else:
                    result["status"] = {}
            except ImportError:
                result["error"] = (
                    "qr_unavailable" if action == "pair" else "unavailable"
                )
            except Exception:
                # Host exceptions can contain network credentials. Never publish them.
                result["error"] = "failed"
                if self._host is not None:
                    # Keep Stop visible while this controller still owns a host
                    # whose cleanup has not confirmed that access is stopped.
                    result["enabled"] = True
                    try:
                        result["status"] = self._host.snapshot()
                    except Exception:
                        result["status"] = {}
            self._results.put(result)
            return result

        return self._worker.submit(run)

    def _start_host(self):
        if not self._authorized.is_set():
            return False
        if self._host is None:
            self._host = self._factory()
        candidate = self._host
        try:
            if self._authorized.is_set():
                candidate.start()
        except Exception:
            # Keep ownership when stop raises. The account barrier and shutdown
            # must still drain this candidate before shared providers can close.
            candidate.stop()
            self._host = None
            raise
        if not self._authorized.is_set():
            candidate.stop()
            self._host = None
            return False
        return True

    def _drain(self):
        while True:
            try:
                result = self._results.get_nowait()
            except Empty:
                break
            self._accept(result)

    def _accept(self, result):
        if self._closed:
            return
        if result["action"] == "refresh":
            self._refreshing = False
        else:
            self._pending -= 1
        self._busy = self._pending > 0
        if result["action"] != "refresh" or result.get("error"):
            self._error = result.get("error", "")
        self._enabled = result.get("enabled", self._enabled)
        self._durable = result.get("durable", self._durable)
        if "status" in result:
            status = result["status"]
            self._running = bool(status.get("enabled", False))
            self._relay_configured = bool(status.get("relay_configured", False))
            self._relay_connected = bool(status.get("relay_connected", False))
            self._devices = [
                {
                    "id": str(device.get("device_id", device.get("id", ""))),
                    "name": str(device.get("device_name", device.get("name", "")))[
                        :120
                    ],
                }
                for device in status.get("devices", [])
                if isinstance(device, dict) and not device.get("revoked_at")
            ]
        if (
            result.get("generation") == self._panel_generation
            and not self._is_blocked()
        ):
            self._image = result.get("image", self._image)
            self._expires = result.get("expires", self._expires)
        self._expire()
        self.changed.emit()
        if (
            self._is_blocked()
            and self._enabled
            and not self._busy
            and result["action"] != "stop"
        ):
            self.command("stop")

    def shutdown(self):
        if self._closed:
            return self._shutdown_succeeded
        self._closed = True
        self._authorized.clear()
        self._timer.stop()
        self._result_timer.stop()
        self._clear_pairing()

        def stop():
            try:
                if self._host is not None:
                    self._host.stop()
                    self._host = None
                return True
            except Exception:
                # Never propagate host exceptions through Qt: they can contain
                # credentials. The caller must keep shared providers alive if
                # mobile work has not confirmed its shutdown.
                return False

        # Drain mobile operations before the composition root closes shared providers.
        future = self._worker.submit(stop)
        self._worker.shutdown(wait=True)
        self._shutdown_succeeded = future.result()
        if not self._shutdown_succeeded:
            self._error = "failed"
        self._busy = False
        self._drain()
        return self._shutdown_succeeded


def create_computer_controller(runtime, parent=None):
    """Reuse the profile, secrets, dictionary and bounded provider registry."""
    state_path = Path(runtime.repositories.config.path).with_name("computer.sqlite3")

    def factory():
        from computer_host import ComputerHost as Host
        from computer_processing import ComputerProcessor
        from shared.computer_connect import relay_configuration

        try:
            from .qml_runtime import QtWorkflowConfig
        except ImportError:  # Frozen standalone entrypoint.
            from qml_runtime import QtWorkflowConfig  # type: ignore[no-redef]

        processor = ComputerProcessor(
            QtWorkflowConfig(runtime.repositories),
            runtime.dictionary_service,
            registry=runtime.provider_registry,
        )
        return Host(
            processor,
            runtime.repositories.config.secret_store,
            state_path,
            address_provider=computer_addresses,
            **relay_configuration(),
        )

    return QmlComputerController(
        state_path,
        factory,
        blocked=lambda: bool(
            runtime.account and (runtime.account.signed_in or runtime.account.managed)
        ),
        parent=parent,
    )
