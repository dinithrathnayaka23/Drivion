"""Prevent two Drivion processes from running at the same time.

Two mechanisms work together:

* ``SingleInstanceLock`` - a Windows *named mutex*. Creating it is atomic,
  so two processes starting at the same moment can't both succeed, and
  Windows releases it automatically if Drivion crashes (no stale lock files).
* ``ActivationServer`` / ``notify_running_instance`` - a local socket so a
  second launch can ask the first one to open, instead of failing silently.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183
_ACTIVATE_MESSAGE = b"activate\n"


def instance_id() -> str:
    """Base name for the lock and socket; tests override it to stay isolated."""
    return os.environ.get("DRIVION_INSTANCE_ID", "Drivion")


class SingleInstanceLock:
    def __init__(self, name: str) -> None:
        if sys.platform != "win32":
            raise RuntimeError("SingleInstanceLock is only implemented for Windows")
        # "Local\" scopes the mutex to the current Windows login session.
        self._name = f"Local\\{name}.SingleInstance"
        self._handle: int | None = None
        self.acquired = False

    def acquire(self) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        handle = kernel32.CreateMutexW(None, False, self._name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            # Another process (or another lock in this process) owns the name.
            self._close(handle)
            self.acquired = False
        else:
            self._handle = handle
            self.acquired = True
        return self.acquired

    def release(self) -> None:
        if self._handle is not None:
            self._close(self._handle)
            self._handle = None
        self.acquired = False

    @staticmethod
    def _close(handle: int) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle(handle)

    def __enter__(self) -> SingleInstanceLock:
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()


class ActivationServer(QObject):
    """Listens for "please open" messages from later launches."""

    activation_requested = Signal()

    def __init__(self, name: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        self._name = f"{name}.Activation"

    def listen(self) -> bool:
        QLocalServer.removeServer(self._name)
        ok = self._server.listen(self._name)
        if not ok:
            log.warning("Activation server could not listen: %s", self._server.errorString())
        return ok

    def close(self) -> None:
        self._server.close()

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            # The message is a few bytes sent right after connecting, so a short
            # blocking read is simpler and safer than juggling readyRead signals
            # on a socket the client may already have closed.
            if not socket.bytesAvailable():
                socket.waitForReadyRead(500)
            data = bytes(socket.readAll().data())
            socket.abort()
            socket.deleteLater()
            # Only one fixed message is understood; anything else is ignored.
            if data.startswith(_ACTIVATE_MESSAGE.strip()):
                log.info("Activation requested by another Drivion launch")
                self.activation_requested.emit()


def notify_running_instance(name: str, timeout_ms: int = 3000) -> bool:
    # Generous timeout: the running copy may be busy (e.g. still starting up)
    # and only accepts the connection once its event loop is running.
    """Ask an already-running Drivion to open. Returns True if it was reached."""
    socket = QLocalSocket()
    socket.connectToServer(f"{name}.Activation")
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(_ACTIVATE_MESSAGE)
    ok = socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    return ok
