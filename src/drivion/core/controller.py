"""The assistant controller: turns events into state transitions.

Threading model
---------------
The controller lives on the Qt main thread. Background threads must call
``post_event``, which queues the event onto the main thread's event loop.
Events are therefore handled one at a time, in order, on one thread, which
removes a whole class of race conditions (e.g. two wake words arriving at
once both starting a verification).

Events that make no sense in the current state are ignored and logged,
not treated as errors: a wake word heard while already ACTIVE is normal.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from drivion.core.events import Event, EventType
from drivion.core.services import ServiceManager
from drivion.core.state import AppState, StateMachine, Transition

log = logging.getLogger(__name__)


class AssistantController(QObject):
    state_changed = Signal(object)          # Transition
    notification = Signal(str, str)         # title, message (shown by the tray)
    raise_window_requested = Signal()
    shutdown_finished = Signal()

    _event_posted = Signal(object)

    def __init__(
        self,
        verification_timeout_s: float,
        services: ServiceManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._machine = StateMachine(AppState.STANDBY)
        self._machine.add_listener(self._on_transition)
        self._services = services or ServiceManager()
        self._attempt = 0

        self._verification_timer = QTimer(self)
        self._verification_timer.setSingleShot(True)
        self._verification_timer.setInterval(int(verification_timeout_s * 1000))
        self._verification_timer.timeout.connect(self._on_verification_timeout)

        # QueuedConnection: always handled later on this object's (main) thread.
        self._event_posted.connect(self.handle_event, Qt.ConnectionType.QueuedConnection)

        self._handlers = {
            EventType.WAKE_WORD_DETECTED: self._on_activation,
            EventType.ACTIVATION_REQUESTED: self._on_activation,
            EventType.VERIFICATION_SUCCEEDED: self._on_verification_succeeded,
            EventType.VERIFICATION_FAILED: self._on_verification_failed,
            EventType.SLEEP_REQUESTED: self._on_sleep_requested,
            EventType.FAILURE: self._on_failure,
            EventType.RECOVER_REQUESTED: self._on_recover,
            EventType.EXIT_REQUESTED: lambda event: self.shutdown(event.detail or "exit requested"),
        }

    # ----- public API ---------------------------------------------------

    @property
    def state(self) -> AppState:
        return self._machine.state

    @property
    def verification_attempt(self) -> int | None:
        """The id of the verification in progress, or None when not verifying."""
        return self._attempt if self.state is AppState.VERIFYING else None

    def start(self) -> None:
        """Start background services and settle in STANDBY."""
        try:
            self._services.start_all()
        except Exception as exc:
            self._on_failure(Event(EventType.FAILURE, "startup", f"service start failed: {exc}"))
            return
        self.notification.emit("Drivion", "Drivion is running in standby.")

    def post_event(self, event: Event) -> None:
        """Thread-safe: may be called from any thread."""
        self._event_posted.emit(event)

    def service_crashed(self, name: str, exc: BaseException) -> None:
        """Crash callback for ``ThreadedService``; runs in the crashed service's thread."""
        self.post_event(Event(EventType.FAILURE, name, f"{type(exc).__name__}: {exc}"))

    def handle_event(self, event: Event) -> None:
        """Main thread only. Prefer ``post_event`` from anywhere else."""
        log.debug("Event %s from %s in state %s", event.type, event.source, self.state)
        if self.state is AppState.SHUTTING_DOWN:
            log.debug("Ignoring %s: shutting down", event.type)
            return
        self._handlers[event.type](event)

    def shutdown(self, reason: str = "exit requested") -> None:
        """Stop everything. Safe to call more than once."""
        if self.state is AppState.SHUTTING_DOWN:
            return
        self._verification_timer.stop()
        self._machine.transition(AppState.SHUTTING_DOWN, reason)
        failed = self._services.stop_all()
        if failed:
            log.error("Services that did not stop cleanly: %s", ", ".join(failed))
        self.shutdown_finished.emit()

    # ----- event handlers -----------------------------------------------

    def _on_activation(self, event: Event) -> None:
        if self.state is AppState.STANDBY:
            self._attempt += 1
            self._machine.transition(AppState.VERIFYING, f"{event.type} from {event.source}")
            self._verification_timer.start()
        elif self.state is AppState.ACTIVE:
            self.raise_window_requested.emit()
        else:
            self._ignore(event)

    def _on_verification_succeeded(self, event: Event) -> None:
        if not self._is_current_attempt(event):
            return
        self._verification_timer.stop()
        self._machine.transition(AppState.ACTIVE, f"verified by {event.source}")

    def _on_verification_failed(self, event: Event) -> None:
        if not self._is_current_attempt(event):
            return
        self._verification_timer.stop()
        self._machine.transition(AppState.STANDBY, f"verification failed: {event.detail}")
        self.notification.emit("Access denied", "Face verification failed. Back to standby.")

    def _on_verification_timeout(self) -> None:
        if self.state is not AppState.VERIFYING:
            return
        # Fail closed: no answer means no access.
        self._machine.transition(AppState.STANDBY, "verification timed out")
        self.notification.emit("Verification timed out", "No face verification result. Back to standby.")

    def _on_sleep_requested(self, event: Event) -> None:
        if self.state is not AppState.ACTIVE:
            self._ignore(event)
            return
        self._machine.transition(AppState.SLEEPING, f"sleep requested by {event.source}")
        # Later milestones stop the camera / speech recogniser here.
        self._machine.transition(AppState.STANDBY, "active services stopped")

    def _on_failure(self, event: Event) -> None:
        if self.state is AppState.ERROR:
            log.warning("Additional failure while in ERROR: %s (%s)", event.source, event.detail)
            return
        self._verification_timer.stop()
        self._machine.transition(AppState.ERROR, f"{event.source}: {event.detail}")
        self.notification.emit("Drivion error", f"{event.source} failed. Use the tray menu to recover.")

    def _on_recover(self, event: Event) -> None:
        if self.state is not AppState.ERROR:
            self._ignore(event)
            return
        self._machine.transition(AppState.STANDBY, f"recovered by {event.source}")

    # ----- helpers --------------------------------------------------------

    def _is_current_attempt(self, event: Event) -> bool:
        if self.state is not AppState.VERIFYING or event.attempt != self._attempt:
            log.warning(
                "Discarding %s for attempt %s (state %s, current attempt %s)",
                event.type, event.attempt, self.state, self._attempt,
            )
            return False
        return True

    def _ignore(self, event: Event) -> None:
        log.info("Ignoring %s from %s in state %s", event.type, event.source, self.state)

    def _on_transition(self, transition: Transition) -> None:
        self.state_changed.emit(transition)
