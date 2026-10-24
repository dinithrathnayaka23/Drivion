"""Drivion dashboard window (Milestone 2: state-aware placeholder).

The window shows the current state and offers "Go to sleep" and "Exit".
Closing it with X does not quit Drivion: it asks to return to standby,
and the background process keeps running in the tray.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from drivion import __version__
from drivion.core.state import AppState
from drivion.ui.icons import STATE_COLORS, state_icon

STYLESHEET = """
QMainWindow, QWidget#root { background-color: #0a1428; }
QLabel { color: #cfe8ff; font-family: 'Segoe UI'; }
QLabel#title { color: #4fd8ff; font-size: 32px; font-weight: 600; letter-spacing: 6px; }
QLabel#subtitle { color: #6f8db3; font-size: 12px; }
QLabel#state { font-size: 18px; font-weight: 600; }
QLabel#detail { color: #6f8db3; font-size: 12px; }
QFrame#card {
    background-color: #0f1e3a;
    border: 1px solid #1d3a66;
    border-radius: 12px;
}
QLabel[class="indicator"] { font-size: 13px; padding: 4px 10px; border-radius: 9px;
                            background-color: #13284a; color: #8aa4c8; }
QPushButton {
    color: #cfe8ff; background-color: #13284a; border: 1px solid #1d3a66;
    border-radius: 8px; padding: 8px 18px; font-family: 'Segoe UI'; font-size: 13px;
}
QPushButton:hover { border-color: #4fd8ff; }
QPushButton:disabled { color: #4a5d7a; border-color: #16294a; }
QPushButton#exit:hover { border-color: #ff5a6e; }
"""


class MainWindow(QMainWindow):
    sleep_clicked = Signal()
    exit_clicked = Signal()
    close_requested = Signal()  # user pressed X; the shell decides what that means

    def __init__(self) -> None:
        super().__init__()
        self._allow_close = False
        self.setWindowTitle("Drivion")
        self.resize(720, 460)
        self.setMinimumSize(480, 320)
        self.setStyleSheet(STYLESHEET)

        root = QWidget(objectName="root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(16)

        title = QLabel("DRIVION", objectName="title", alignment=Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel(
            f"Personal desktop assistant · v{__version__} · Milestone 2",
            objectName="subtitle",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        card = QFrame(objectName="card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        self.state_label = QLabel(objectName="state", alignment=Qt.AlignmentFlag.AlignCenter)
        self.detail_label = QLabel(objectName="detail", alignment=Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setWordWrap(True)
        card_layout.addWidget(self.state_label)
        card_layout.addWidget(self.detail_label)

        indicators = QHBoxLayout()
        indicators.addStretch()
        # Honest indicators: nothing captures audio or video yet.
        self.mic_label = self._indicator("Microphone: OFF")
        self.camera_label = self._indicator("Camera: OFF")
        indicators.addWidget(self.mic_label)
        indicators.addWidget(self.camera_label)
        indicators.addStretch()
        card_layout.addLayout(indicators)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.sleep_button = QPushButton("Go to sleep")
        self.exit_button = QPushButton("Exit Drivion", objectName="exit")
        self.sleep_button.clicked.connect(self.sleep_clicked)
        self.exit_button.clicked.connect(self.exit_clicked)
        buttons.addWidget(self.sleep_button)
        buttons.addWidget(self.exit_button)
        buttons.addStretch()

        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(card)
        layout.addLayout(buttons)
        layout.addStretch()
        self.setCentralWidget(root)

        self.set_state(AppState.STANDBY)

    @staticmethod
    def _indicator(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("class", "indicator")
        return label

    def set_state(self, state: AppState, detail: str = "") -> None:
        self.state_label.setText(f"State: {state}")
        self.state_label.setStyleSheet(f"color: {STATE_COLORS[state]};")
        self.detail_label.setText(detail)
        self.sleep_button.setEnabled(state is AppState.ACTIVE)
        self.setWindowIcon(state_icon(state))

    def show_and_raise(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def force_close(self) -> None:
        """Close for real (used only during shutdown)."""
        self._allow_close = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        self.close_requested.emit()
