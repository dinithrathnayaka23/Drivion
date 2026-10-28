"""What the user should see happening: device usage and command history.

``ActivityFeed`` is the single source of truth for the dashboard's
microphone/camera indicators and its command history. Subsystems report
to it (the microphone service says "I'm recording", the command pipeline
says "heard X, answered Y") and the UI only displays what it is told.

Privacy notes:
* Indicators must reflect real hardware use, so only the code that opens
  a device should report its state.
* History is kept in memory only (bounded), never written to disk, and is
  gone when Drivion exits.

All mutating methods are thread-safe: calls from background threads are
queued onto the thread that owns the feed (the Qt main thread).
"""

from __future__ import annotations

import itertools
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from PySide6.QtCore import QObject, Qt, QThread, Signal


class Device(StrEnum):
    MICROPHONE = "MICROPHONE"
    CAMERA = "CAMERA"


class DeviceState(StrEnum):
    OFF = "OFF"
    ACTIVE = "ACTIVE"      # the device is capturing right now
    ERROR = "ERROR"        # missing, busy or failed


class VoiceStatus(StrEnum):
    """What the voice pipeline is doing while ACTIVE (shown on the dashboard)."""

    IDLE = "IDLE"
    LOADING = "LOADING"            # loading the speech-recognition model
    LISTENING = "LISTENING"        # waiting for you to speak
    HEARING = "HEARING"            # you are speaking
    TRANSCRIBING = "TRANSCRIBING"  # turning speech into text
    THINKING = "THINKING"          # waiting for the AI provider
    SPEAKING = "SPEAKING"          # Drivion is talking (input is ignored)


class Outcome(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REJECTED = "REJECTED"  # refused by policy, cancelled or not understood


@dataclass(frozen=True)
class CommandRecord:
    id: int
    command: str
    response: str = ""
    outcome: Outcome = Outcome.PENDING
    timestamp: datetime = field(default_factory=datetime.now)


class ActivityFeed(QObject):
    device_changed = Signal(object, object)  # Device, DeviceState
    record_added = Signal(object)            # CommandRecord
    record_updated = Signal(object)          # CommandRecord
    history_cleared = Signal()
    voice_status_changed = Signal(object)    # VoiceStatus

    _dispatch = Signal(object)

    def __init__(self, history_limit: int = 50, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._history: deque[CommandRecord] = deque(maxlen=history_limit)
        self._devices = {device: DeviceState.OFF for device in Device}
        self._voice_status = VoiceStatus.IDLE
        self._ids = itertools.count(1)
        self._id_lock = threading.Lock()
        self._dispatch.connect(lambda fn: fn(), Qt.ConnectionType.QueuedConnection)

    # ----- read access (main thread) -----------------------------------------

    @property
    def history(self) -> list[CommandRecord]:
        """Oldest first."""
        return list(self._history)

    def device_state(self, device: Device) -> DeviceState:
        return self._devices[device]

    @property
    def voice_status(self) -> VoiceStatus:
        return self._voice_status

    # ----- updates (any thread) ------------------------------------------------

    def set_device(self, device: Device, state: DeviceState) -> None:
        self._run(lambda: self._set_device(device, state))

    def set_voice_status(self, status: VoiceStatus) -> None:
        self._run(lambda: self._set_voice_status(status))

    def add_command(self, command: str) -> int:
        """Record a command as PENDING and return its id for ``complete_command``."""
        with self._id_lock:
            record_id = next(self._ids)
        self._run(lambda: self._add(CommandRecord(record_id, command)))
        return record_id

    def complete_command(self, record_id: int, response: str, outcome: Outcome) -> None:
        self._run(lambda: self._complete(record_id, response, outcome))

    def clear_history(self) -> None:
        self._run(self._clear)

    # ----- internals (always on the owning thread) ----------------------------

    def _run(self, fn: Callable[[], None]) -> None:
        if QThread.currentThread() is self.thread():
            fn()
        else:
            self._dispatch.emit(fn)

    def _set_device(self, device: Device, state: DeviceState) -> None:
        if self._devices[device] is state:
            return
        self._devices[device] = state
        self.device_changed.emit(device, state)

    def _set_voice_status(self, status: VoiceStatus) -> None:
        if self._voice_status is status:
            return
        self._voice_status = status
        self.voice_status_changed.emit(status)

    def _add(self, record: CommandRecord) -> None:
        self._history.append(record)
        self.record_added.emit(record)

    def _complete(self, record_id: int, response: str, outcome: Outcome) -> None:
        for index, record in enumerate(self._history):
            if record.id == record_id:
                updated = replace(record, response=response, outcome=outcome)
                self._history[index] = updated
                self.record_updated.emit(updated)
                return
        # Already evicted from the bounded history or cleared: nothing to update.

    def _clear(self) -> None:
        self._history.clear()
        self.history_cleared.emit()
