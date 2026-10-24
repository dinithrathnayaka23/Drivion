"""Connects the controller and activity feed to the window and tray.

The UI never changes state itself. Buttons and menu items post events to
the controller; the controller's ``state_changed`` signal and the activity
feed's signals then drive what the UI shows. This one-way flow keeps the
UI and the real state impossible to get out of sync.

Window visibility follows the state: the dashboard is shown only while
ACTIVE. If no system tray is available, the window stays visible in every
state, because otherwise there would be no way to reach or exit Drivion.
"""

from __future__ import annotations

import itertools
import logging

from PySide6.QtCore import QObject, QTimer

from drivion.core.activity import ActivityFeed, Device, DeviceState, Outcome
from drivion.core.controller import AssistantController
from drivion.core.events import Event, EventType
from drivion.core.state import AppState, Transition
from drivion.ui.main_window import MainWindow
from drivion.ui.tray import TrayIcon

log = logging.getLogger(__name__)

# Scripted commands for --simulate. Nothing is executed; they only exercise
# the dashboard until real speech and actions exist (Milestones 5-8).
SIMULATED_COMMANDS: list[tuple[str, str, Outcome]] = [
    ("open chrome", "Simulated: Chrome would open now.", Outcome.SUCCESS),
    ("set volume to 40 percent", "Simulated: volume would be set to 40%.", Outcome.SUCCESS),
    ("shut down the computer", "Simulated: shutdown needs your confirmation, so nothing was done.",
     Outcome.REJECTED),
    ("what's the weather tomorrow", "Simulated: no AI provider is configured yet.", Outcome.FAILED),
]
SIMULATED_REPLY_DELAY_MS = 700


class Shell(QObject):
    def __init__(
        self,
        controller: AssistantController,
        feed: ActivityFeed,
        window: MainWindow,
        tray: TrayIcon | None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._feed = feed
        self.window = window
        self.tray = tray
        self.window_always_visible = tray is None
        self._simulated_commands = itertools.cycle(SIMULATED_COMMANDS)

        controller.state_changed.connect(self._on_state_changed)
        controller.raise_window_requested.connect(self.window.show_and_raise)
        controller.notification.connect(self._on_notification)
        controller.shutdown_finished.connect(self._on_shutdown_finished)

        feed.device_changed.connect(window.set_device)
        feed.record_added.connect(window.add_record)
        feed.record_updated.connect(window.update_record)
        feed.history_cleared.connect(window.clear_history)
        for device in Device:
            window.set_device(device, feed.device_state(device))
        for record in feed.history:
            window.add_record(record)

        window.sleep_clicked.connect(lambda: self._post(EventType.SLEEP_REQUESTED, "window"))
        window.exit_clicked.connect(lambda: self._post(EventType.EXIT_REQUESTED, "window"))
        window.clear_history_clicked.connect(feed.clear_history)
        window.close_requested.connect(self._on_window_close_requested)

        if tray is not None:
            self._connect_tray(tray)

    def _connect_tray(self, tray: TrayIcon) -> None:
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
        tray.simulate_command.connect(self.simulate_command)
        tray.simulate_toggle_microphone.connect(lambda: self._toggle_device(Device.MICROPHONE))
        tray.simulate_toggle_camera.connect(lambda: self._toggle_device(Device.CAMERA))

    def show_initial(self) -> None:
        if self.tray is not None:
            self.tray.show()
        if self.window_always_visible:
            self.window.show_and_raise()

    def request_activation(self) -> None:
        """Called when a second Drivion launch asks this one to open."""
        self._post(EventType.ACTIVATION_REQUESTED, "second launch")

    def simulate_command(self) -> None:
        """Developer simulation: record a fake command, then a fake reply."""
        if self._controller.state is not AppState.ACTIVE:
            log.info("Ignoring simulated command outside ACTIVE")
            return
        command, reply, outcome = next(self._simulated_commands)
        record_id = self._feed.add_command(command)
        QTimer.singleShot(
            SIMULATED_REPLY_DELAY_MS,
            lambda: self._feed.complete_command(record_id, reply, outcome),
        )

    # ----- internals ------------------------------------------------------

    def _post(self, kind: EventType, source: str, detail: str = "") -> None:
        self._controller.post_event(Event(kind, source, detail))

    def _post_verification(self, kind: EventType, detail: str = "") -> None:
        # Tag the result with the attempt currently in progress.
        attempt = self._controller.verification_attempt
        self._controller.post_event(Event(kind, "simulator", detail, attempt=attempt))

    def _toggle_device(self, device: Device) -> None:
        current = self._feed.device_state(device)
        new = DeviceState.OFF if current is DeviceState.ACTIVE else DeviceState.ACTIVE
        self._feed.set_device(device, new)

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
