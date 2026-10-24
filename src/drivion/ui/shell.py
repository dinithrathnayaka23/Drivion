"""Connects the controller to the window and tray.

The UI never changes state itself. Buttons and menu items post events to
the controller; the controller's ``state_changed`` signal then drives what
the UI shows. This one-way flow keeps the UI and the state impossible to
get out of sync.

Window visibility follows the state: the dashboard is shown only while
ACTIVE. If no system tray is available, the window stays visible in every
state, because otherwise there would be no way to reach or exit Drivion.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject

from drivion.core.controller import AssistantController
from drivion.core.events import Event, EventType
from drivion.core.state import AppState, Transition
from drivion.ui.main_window import MainWindow
from drivion.ui.tray import TrayIcon

log = logging.getLogger(__name__)


class Shell(QObject):
    def __init__(
        self,
        controller: AssistantController,
        window: MainWindow,
        tray: TrayIcon | None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self.window = window
        self.tray = tray
        self.window_always_visible = tray is None

        controller.state_changed.connect(self._on_state_changed)
        controller.raise_window_requested.connect(self.window.show_and_raise)
        controller.notification.connect(self._on_notification)
        controller.shutdown_finished.connect(self._on_shutdown_finished)

        window.sleep_clicked.connect(lambda: self._post(EventType.SLEEP_REQUESTED, "window"))
        window.exit_clicked.connect(lambda: self._post(EventType.EXIT_REQUESTED, "window"))
        window.close_requested.connect(self._on_window_close_requested)

        if tray is not None:
            tray.open_requested.connect(lambda: self._post(EventType.ACTIVATION_REQUESTED, "tray"))
            tray.sleep_requested.connect(lambda: self._post(EventType.SLEEP_REQUESTED, "tray"))
            tray.recover_requested.connect(lambda: self._post(EventType.RECOVER_REQUESTED, "tray"))
            tray.exit_requested.connect(lambda: self._post(EventType.EXIT_REQUESTED, "tray"))
            tray.simulate_wake_word.connect(
                lambda: self._post(EventType.WAKE_WORD_DETECTED, "simulator"))
            tray.simulate_face_verified.connect(
                lambda: self._post_verification(EventType.VERIFICATION_SUCCEEDED))
            tray.simulate_face_rejected.connect(
                lambda: self._post_verification(EventType.VERIFICATION_FAILED, "unknown face"))
            tray.simulate_failure.connect(
                lambda: self._post(EventType.FAILURE, "simulator", "simulated failure"))

    def show_initial(self) -> None:
        if self.tray is not None:
            self.tray.show()
        if self.window_always_visible:
            self.window.show_and_raise()

    def request_activation(self) -> None:
        """Called when a second Drivion launch asks this one to open."""
        self._post(EventType.ACTIVATION_REQUESTED, "second launch")

    # ----- internals ------------------------------------------------------

    def _post(self, kind: EventType, source: str, detail: str = "") -> None:
        self._controller.post_event(Event(kind, source, detail))

    def _post_verification(self, kind: EventType, detail: str = "") -> None:
        # Tag the result with the attempt currently in progress.
        attempt = self._controller.verification_attempt
        self._controller.post_event(Event(kind, "simulator", detail, attempt=attempt))

    def _on_state_changed(self, transition: Transition) -> None:
        self.window.set_state(transition.new, transition.reason)
        if self.tray is not None:
            self.tray.set_state(transition.new)

        if transition.new is AppState.ACTIVE:
            self.window.show_and_raise()
        elif transition.old is AppState.ACTIVE and not self.window_always_visible:
            self.window.hide()

    def _on_window_close_requested(self) -> None:
        if self.window_always_visible:
            # No tray to fall back to, so X has to mean exit.
            self._post(EventType.EXIT_REQUESTED, "window closed (no tray)")
        elif self._controller.state is AppState.ACTIVE:
            self._post(EventType.SLEEP_REQUESTED, "window closed")
        else:
            self.window.hide()

    def _on_notification(self, title: str, message: str) -> None:
        log.info("Notification: %s - %s", title, message)
        if self.tray is not None:
            self.tray.notify(title, message)

    def _on_shutdown_finished(self) -> None:
        self.window.force_close()
        if self.tray is not None:
            self.tray.hide()
