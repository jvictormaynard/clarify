"""Qt adapter for optional portable update checks, downloads, and restart."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time

from PySide6.QtCore import QObject, Property, QTimer, Qt, Signal, Slot

from portable_updates import PortableReleaseTransport, PortableUpdateError, load_policy
from portable_update_windows import (
    is_portable_installation,
    prepare_portable_update,
    prune_portable_cache,
    update_cache_root,
)
from version import __version__


class QmlUpdateController(QObject):
    changed = Signal()
    _finished = Signal(int, str, object, object)
    _progress = Signal(int, int)

    def __init__(
        self,
        *,
        transport=None,
        supported=None,
        automatic=False,
        cache_root=None,
        can_restart=lambda: False,
        restart=lambda: None,
        prepare=None,
        run_worker=None,
        parent=None,
    ):
        super().__init__(parent)
        self._supported = (
            is_portable_installation() if supported is None else supported is True
        )
        self._automatic = automatic is True
        self._transport = transport
        self._cache_root = (
            Path(cache_root)
            if cache_root is not None
            else (update_cache_root() if self._supported else None)
        )
        self._can_restart = can_restart
        self._restart = restart
        self._prepare = prepare or prepare_portable_update
        self._run_worker = run_worker or self._thread
        self._phase = "idle"
        self._status = (
            ""
            if self._supported
            else "A atualização requer a versão portátil para Windows."
        )
        self._release = None
        self._downloaded = None
        self._percentage = 0
        self._manual = False
        self._generation = 0
        self._cancel = threading.Event()
        self._closed = False
        self._prepared = None
        self._prepare_started = 0
        self._handoff = False
        self._finished.connect(self._finish, Qt.ConnectionType.QueuedConnection)
        self._progress.connect(self._set_progress, Qt.ConnectionType.QueuedConnection)
        self._check_timer = QTimer(self)
        self._check_timer.setInterval(6 * 60 * 60 * 1000)
        self._check_timer.timeout.connect(self.check)
        self._initial_timer = QTimer(self)
        self._initial_timer.setSingleShot(True)
        self._initial_timer.timeout.connect(self.check)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(250)
        self._poll_timer.timeout.connect(self._poll)

    @staticmethod
    def _thread(action):
        threading.Thread(target=action, daemon=True, name="clarify-update").start()

    @Property(bool, notify=changed)
    def available(self):
        return self._release is not None

    @Property(bool, notify=changed)
    def busy(self):
        return self._phase in {
            "checking",
            "downloading",
            "cancelling",
            "preparing",
            "restarting",
        }

    @Property(bool, notify=changed)
    def installing(self):
        return self._phase in {"preparing", "restarting"}

    @Property(bool, constant=True)
    def supported(self):
        return self._supported

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(str, notify=changed)
    def version(self):
        return self._release.version if self._release is not None else ""

    @Property(int, notify=changed)
    def progress(self):
        return self._percentage

    def _state(self, phase, status):
        self._phase, self._status = phase, status
        self.changed.emit()

    def start(self):
        if self._supported and not self._closed:
            self._initial_timer.start(30000)
            self._check_timer.start()
            self._poll_timer.start()

    def _transport_instance(self):
        if self._transport is None:
            self._transport = PortableReleaseTransport(load_policy())
        return self._transport

    def _work(self, kind, action):
        self._generation += 1
        generation = self._generation
        cancel = self._cancel = threading.Event()

        def execute():
            result = error = None
            try:
                result = action(cancel, generation)
            except PortableUpdateError as failure:
                error = str(failure)
            except Exception:
                error = (
                    "Não foi possível atualizar. Verifique a conexão e tente novamente."
                )
            if self._closed:
                if kind == "prepare" and result is not None:
                    result.cancel()
                return
            try:
                self._finished.emit(generation, kind, result, error)
            except RuntimeError:
                if kind == "prepare" and result is not None:
                    result.cancel()

        self._run_worker(execute)

    @Slot(result=bool)
    def check(self):
        if not self._supported or self._closed or self.busy or self._phase == "ready":
            return False
        self._state("checking", "Verificando atualizações…")

        def check_latest(cancel, _generation):
            prune_portable_cache(self._cache_root)
            return self._transport_instance().latest(__version__, cancel)

        self._work("check", check_latest)
        return True

    @Slot(result=bool)
    def install(self):
        if (
            not self._supported
            or self._closed
            or self._release is None
            or self.installing
        ):
            return False
        if self.busy and self._phase != "downloading":
            return False
        self._manual = True
        if self._phase == "ready":
            self._poll()
        elif not self.busy:
            self._download()
        return True

    @Slot(bool)
    def setAutomatic(self, value):
        self._automatic = value is True
        if self._closed:
            return
        if not self._automatic and not self._manual and self._phase == "downloading":
            self._cancel.set()
            self._state("cancelling", "Cancelando o download automático…")
        elif not self._automatic and not self._manual and self._phase == "preparing":
            self._generation += 1
            self._cancel.set()
            if self._prepared is not None:
                self._prepared.cancel()
            self._prepared = None
            self._state(
                "ready", "Atualização pronta. Instale pelo menu quando desejar."
            )
        elif self._automatic and self._phase == "available":
            self._download()

    def _download(self):
        release = self._release
        self._percentage = 0
        self._state("downloading", "Baixando a atualização…")

        def download(cancel, generation):
            self._cache_root.mkdir(parents=True, exist_ok=True)
            directory = Path(
                tempfile.mkdtemp(
                    prefix=f"update-{release.version}-", dir=self._cache_root
                )
            )
            return self._transport_instance().download(
                release,
                directory,
                cancel,
                lambda value: self._progress.emit(generation, value),
            )

        self._work("download", download)

    @Slot(int, int)
    def _set_progress(self, generation, percentage):
        if (
            generation == self._generation
            and not self._closed
            and self._phase == "downloading"
        ):
            self._percentage = max(0, min(100, percentage))
            self._status = f"Baixando a atualização… {self._percentage}%"
            self.changed.emit()

    def _failed_version(self):
        try:
            path = self._cache_root / "failed-version.json"
            if path.is_symlink() or path.stat().st_size > 1024:
                return None
            value = json.loads(path.read_text("utf-8"))
            return value.get("version") if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    @Slot(int, str, object, object)
    def _finish(self, generation, kind, result, error):
        if generation != self._generation or self._closed:
            if kind == "prepare" and result is not None:
                result.cancel()
            return
        if kind == "download" and self._cancel.is_set():
            self._state("available", "Uma nova versão está disponível.")
            if self._automatic or self._manual:
                self._download()
            return
        if error:
            self._state("failed", error)
            return
        if kind == "check":
            self._release = result
            self._manual = False
            if result is None:
                self._state("idle", "Você está usando a versão mais recente.")
            elif result.version == self._failed_version():
                self._state(
                    "failed",
                    "A atualização anterior falhou. A versão anterior foi mantida. Tente instalar novamente pelo menu.",
                )
            else:
                self._state("available", f"A versão {result.version} está disponível.")
                if self._automatic:
                    self._download()
        elif kind == "download":
            self._downloaded = result
            self._state(
                "ready",
                "Atualização pronta. Conclua as tarefas e feche os Settings para reiniciar.",
            )
        elif kind == "prepare":
            self._prepared = result

    def _poll(self):
        if self._closed:
            return
        if (
            self._phase == "ready"
            and (self._automatic or self._manual)
            and self._can_restart()
        ):
            self._prepare_started = time.monotonic()
            self._prepared = None
            self._state("preparing", "Preparando a instalação…")
            self._work(
                "prepare",
                lambda _cancel, _generation: self._prepare(
                    self._release, self._downloaded, __version__
                ),
            )
        if self._phase != "preparing" or self._prepared is None:
            return
        if self._prepared.armed() and self._can_restart():
            self._handoff = True
            self._state("restarting", "Reiniciando para aplicar a atualização…")
            self._stop_timers()
            self._restart()
        elif (
            self._prepared.process.poll() is not None
            or time.monotonic() - self._prepare_started > 60
        ):
            self._prepared.cancel()
            self._state(
                "failed",
                "Não foi possível preparar a instalação. Tente novamente pelo menu.",
            )

    def _stop_timers(self):
        for timer in (self._initial_timer, self._check_timer, self._poll_timer):
            timer.stop()

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        self._cancel.set()
        self._stop_timers()
        if self._prepared is not None and not self._handoff:
            self._prepared.cancel()
