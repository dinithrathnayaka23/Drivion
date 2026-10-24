"""System tray icon and menu.

The tray is how you reach Drivion while it is in standby: open it, put it to
sleep, recover from an error, or exit the background process completely.
With ``--simulate`` an extra menu fakes the events that real wake-word and
face-verification code will produce in later milestones.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from drivion.core.state import AppState
from drivion.ui.icons import state_icon


class TrayIcon(QSystemTrayIcon):
    open_requested = Signal()
    sleep_requested = Signal()
    recover_requested = Signal()
    exit_requested = Signal()
    simulate_wake_word = Signal()
    simulate_face_verified = Signal()
    simulate_face_rejected = Signal()
    simulate_failure = Signal()

    def __init__(self, simulate: bool = False) -> None:
        super().__init__()
        self._menu = QMenu()

        self.status_action = QAction("Drivion: STANDBY", self._menu, enabled=False)
        self.open_action = self._add("Open Drivion", self.open_requested)
        self.sleep_action = self._add("Go to sleep (standby)", self.sleep_requested)
        self.recover_action = self._add("Recover from error", self.recover_requested)
        self._menu.insertAction(self.open_action, self.status_action)
        self._menu.insertSeparator(self.open_action)

        self.simulation_actions: dict[str, QAction] = {}
        if simulate:
            sim = self._menu.addMenu("Simulate (developer)")
            for key, label, signal in [
                ("wake", "Wake word detected", self.simulate_wake_word),
                ("verified", "Face verified", self.simulate_face_verified),
                ("rejected", "Face rejected", self.simulate_face_rejected),
                ("failure", "Subsystem failure", self.simulate_failure),
            ]:
                action = sim.addAction(label)
                action.triggered.connect(signal)
                self.simulation_actions[key] = action

        self._menu.addSeparator()
        self.exit_action = self._add("Exit Drivion", self.exit_requested)

        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)
        self.set_state(AppState.STANDBY)

    def _add(self, label: str, signal: Signal) -> QAction:
        action = self._menu.addAction(label)
        action.triggered.connect(signal)
        return action

    def set_state(self, state: AppState) -> None:
        self.setIcon(state_icon(state))
        self.setToolTip(f"Drivion - {state}")
        self.status_action.setText(f"Drivion: {state}")
        self.open_action.setEnabled(state in (AppState.STANDBY, AppState.ACTIVE))
        self.sleep_action.setEnabled(state is AppState.ACTIVE)
        self.recover_action.setEnabled(state is AppState.ERROR)
        self.exit_action.setEnabled(state is not AppState.SHUTTING_DOWN)

        enabled_in = {
            "wake": {AppState.STANDBY},
            "verified": {AppState.VERIFYING},
            "rejected": {AppState.VERIFYING},
            "failure": {AppState.STANDBY, AppState.VERIFYING, AppState.ACTIVE},
        }
        for key, action in self.simulation_actions.items():
            action.setEnabled(state in enabled_in[key])

    def notify(self, title: str, message: str) -> None:
        if self.isVisible():
            self.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 4000)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()
