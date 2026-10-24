"""Minimal Drivion dashboard window (Milestone 1 placeholder).

It only displays static status. Live state, the animated indicator,
command history and the tray icon arrive in later milestones.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QVBoxLayout, QWidget

from drivion import __version__

STYLESHEET = """
QMainWindow, QWidget#root { background-color: #0a1428; }
QLabel { color: #cfe8ff; font-family: 'Segoe UI'; }
QLabel#title { color: #4fd8ff; font-size: 32px; font-weight: 600; letter-spacing: 6px; }
QLabel#subtitle { color: #6f8db3; font-size: 12px; }
QLabel#state { color: #4fd8ff; font-size: 18px; font-weight: 600; }
QFrame#card {
    background-color: #0f1e3a;
    border: 1px solid #1d3a66;
    border-radius: 12px;
}
QLabel[class="indicator"] { font-size: 13px; padding: 4px 10px; border-radius: 9px;
                   background-color: #13284a; color: #8aa4c8; }
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
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
            f"Personal desktop assistant · v{__version__} · Milestone 1",
            objectName="subtitle",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        card = QFrame(objectName="card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        self.state_label = QLabel(
            "State: STANDBY", objectName="state", alignment=Qt.AlignmentFlag.AlignCenter
        )
        card_layout.addWidget(self.state_label)

        indicators = QHBoxLayout()
        indicators.addStretch()
        # Honest indicators: nothing captures audio or video in Milestone 1.
        self.mic_label = self._indicator("Microphone: OFF")
        self.camera_label = self._indicator("Camera: OFF")
        indicators.addWidget(self.mic_label)
        indicators.addWidget(self.camera_label)
        indicators.addStretch()
        card_layout.addLayout(indicators)

        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(card)
        layout.addStretch()
        self.setCentralWidget(root)

    @staticmethod
    def _indicator(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("class", "indicator")
        return label
