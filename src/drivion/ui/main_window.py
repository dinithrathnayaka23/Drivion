"""The Drivion dashboard window.

Layout (wide):                          Layout (narrow, < 820 px):
┌──────────────────────────────────┐    ┌────────────────┐
│ DRIVION           [Mic] [Camera] │    │ header         │
│ ┌──────────┐ ┌─────────────────┐ │    │ status + orb   │
│ │   orb    │ │ conversation    │ │    │ conversation   │
│ │  state   │ ├─────────────────┤ │    │ history        │
│ │listening │ │ history         │ │    │ buttons        │
│ └──────────┘ └─────────────────┘ │    └────────────────┘
│              [Go to sleep] [Exit]│
└──────────────────────────────────┘

The window only displays what it is told. Closing it with X does not quit
Drivion: it emits ``close_requested`` and the shell decides what happens.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from drivion import __version__
from drivion.core.activity import CommandRecord, Device, DeviceState
from drivion.core.state import AppState
from drivion.ui import theme
from drivion.ui.icons import state_icon
from drivion.ui.widgets.orb import StateOrb
from drivion.ui.widgets.panels import ConversationCard, DeviceChip, HistoryPanel

NARROW_WIDTH = 820


def listening_text(state: AppState, microphone: DeviceState,
                   wake_phrase: str = "Wake up, Drivion") -> str:
    """Describe honestly what Drivion is listening for right now."""
    if microphone is DeviceState.ERROR:
        return "Microphone unavailable"
    if microphone is DeviceState.OFF:
        return "Not listening (microphone off)"
    if state is AppState.STANDBY:
        return f"Listening for “{wake_phrase}”"
    if state is AppState.ACTIVE:
        return "Listening for commands"
    return "Microphone on"


class MainWindow(QMainWindow):
    sleep_clicked = Signal()
    exit_clicked = Signal()
    clear_history_clicked = Signal()
    close_requested = Signal()  # user pressed X; the shell decides what that means

    def __init__(self, history_limit: int = 50, animated: bool = True,
                 wake_phrase: str = "Wake up, Drivion") -> None:
        super().__init__()
        self._allow_close = False
        self._state = AppState.STANDBY
        self._wake_phrase = wake_phrase
        self.setWindowTitle("Drivion")
        self.resize(1000, 640)
        self.setMinimumSize(420, 560)
        self.setStyleSheet(theme.STYLESHEET)

        root = QWidget(objectName="root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        outer.addLayout(self._build_header())

        self.body = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.body.setSpacing(16)
        self.body.addWidget(self._build_status_card(animated), 5)
        self.body.addLayout(self._build_side_column(history_limit), 6)
        outer.addLayout(self.body, 1)

        outer.addLayout(self._build_footer())

        # If the window is smaller than the content (small screen, narrow
        # layout), scroll instead of squashing cards until text is clipped.
        scroll = QScrollArea(objectName="scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

        self.set_state(AppState.STANDBY)

    # ----- construction -----------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(QLabel("DRIVION", objectName="title"))
        titles.addWidget(QLabel(f"Personal desktop assistant · v{__version__}", objectName="subtitle"))
        header.addLayout(titles, 1)
        self.mic_chip = DeviceChip(Device.MICROPHONE)
        self.camera_chip = DeviceChip(Device.CAMERA)
        header.addWidget(self.mic_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.camera_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        return header

    def _build_status_card(self, animated: bool) -> QFrame:
        frame = QFrame(objectName="card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(4)
        self.orb = StateOrb(animated=animated)
        self.state_label = QLabel(objectName="state", alignment=Qt.AlignmentFlag.AlignCenter)
        self.listening_label = QLabel(objectName="listening", alignment=Qt.AlignmentFlag.AlignCenter)
        self.detail_label = QLabel(
            objectName="detail", alignment=Qt.AlignmentFlag.AlignCenter, wordWrap=True
        )
        layout.addWidget(self.orb, 1)
        layout.addWidget(self.state_label)
        layout.addWidget(self.listening_label)
        layout.addWidget(self.detail_label)
        return frame

    def _build_side_column(self, history_limit: int) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(16)
        self.conversation = ConversationCard()
        self.history = HistoryPanel(history_limit)
        self.history.setMinimumHeight(200)
        self.history.clear_requested.connect(self.clear_history_clicked)
        column.addWidget(self.conversation)
        column.addWidget(self.history, 1)
        return column

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.addStretch()
        self.sleep_button = QPushButton("Go to sleep")
        self.sleep_button.setToolTip("Close the dashboard and return to standby")
        self.exit_button = QPushButton("Exit Drivion", objectName="exit")
        self.exit_button.setToolTip("Stop Drivion completely, including the background listener")
        self.sleep_button.clicked.connect(self.sleep_clicked)
        self.exit_button.clicked.connect(self.exit_clicked)
        footer.addWidget(self.sleep_button)
        footer.addWidget(self.exit_button)
        return footer

    # ----- state and activity ------------------------------------------------------

    def set_state(self, state: AppState, detail: str = "") -> None:
        self._state = state
        self.orb.set_state(state)
        self.state_label.setText(state.value)
        self.state_label.setStyleSheet(f"color: {theme.STATE_COLORS[state]};")
        self.detail_label.setText(detail)
        self.sleep_button.setEnabled(state is AppState.ACTIVE)
        self.setWindowIcon(state_icon(state))
        self._refresh_listening()

    def set_device(self, device: Device, state: DeviceState) -> None:
        chip = self.mic_chip if device is Device.MICROPHONE else self.camera_chip
        chip.set_state(state)
        self._refresh_listening()

    def add_record(self, record: CommandRecord) -> None:
        self.conversation.show_record(record)
        self.history.add_record(record)

    def update_record(self, record: CommandRecord) -> None:
        self.conversation.update_record(record)
        self.history.update_record(record)

    def clear_history(self) -> None:
        self.conversation.clear()
        self.history.clear()

    def _refresh_listening(self) -> None:
        self.listening_label.setText(
            listening_text(self._state, self.mic_chip.state, self._wake_phrase)
        )

    # ----- window behaviour ------------------------------------------------------

    @property
    def is_narrow(self) -> bool:
        return self.body.direction() == QBoxLayout.Direction.TopToBottom

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        narrow = event.size().width() < NARROW_WIDTH
        self.body.setDirection(
            QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        )

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
