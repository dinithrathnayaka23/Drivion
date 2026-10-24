"""Dashboard building blocks: device chips, conversation card, history list."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
)

from drivion.core.activity import CommandRecord, Device, DeviceState, Outcome
from drivion.ui import theme

OUTCOME_LABELS: dict[Outcome, tuple[str, str]] = {
    Outcome.PENDING: ("…", theme.TEXT_MUTED),
    Outcome.SUCCESS: ("✓", theme.SUCCESS),
    Outcome.FAILED: ("✕", theme.DANGER),
    Outcome.REJECTED: ("⊘", theme.WARNING),
}

DEVICE_NAMES = {Device.MICROPHONE: "Microphone", Device.CAMERA: "Camera"}


class DeviceChip(QLabel):
    """Pill that lights up whenever the device is actually capturing."""

    def __init__(self, device: Device) -> None:
        super().__init__(objectName="deviceChip")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.device = device
        self.state = DeviceState.OFF
        self.set_state(DeviceState.OFF)

    def set_state(self, state: DeviceState) -> None:
        self.state = state
        word = {DeviceState.OFF: "off", DeviceState.ACTIVE: "ON", DeviceState.ERROR: "unavailable"}
        self.setText(f"● {DEVICE_NAMES[self.device]} {word[state]}")
        self.setAccessibleName(f"{DEVICE_NAMES[self.device]} {word[state]}")
        self.setProperty("deviceState", state.value)
        # Re-apply the stylesheet so the [deviceState=...] selector takes effect.
        self.style().unpolish(self)
        self.style().polish(self)


class ConversationCard(QFrame):
    """Shows the most recent command and Drivion's answer."""

    def __init__(self) -> None:
        super().__init__(objectName="card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)
        layout.addWidget(QLabel("CONVERSATION", objectName="cardTitle"))

        layout.addWidget(QLabel("YOU SAID", objectName="speaker"))
        self.utterance_label = QLabel("—", objectName="utterance", wordWrap=True)
        self.utterance_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.utterance_label)

        layout.addSpacing(6)
        layout.addWidget(QLabel("DRIVION", objectName="speaker"))
        self.reply_label = QLabel("—", objectName="reply", wordWrap=True)
        self.reply_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.reply_label)

        self._record_id: int | None = None

    def show_record(self, record: CommandRecord) -> None:
        self._record_id = record.id
        self.utterance_label.setText(f"“{record.command}”")
        self.reply_label.setText(record.response or "Working on it…")

    def update_record(self, record: CommandRecord) -> None:
        if record.id == self._record_id:  # only the command currently on display
            self.show_record(record)

    def clear(self) -> None:
        self._record_id = None
        self.utterance_label.setText("—")
        self.reply_label.setText("—")


class HistoryPanel(QFrame):
    """Newest-first list of commands with their outcome."""

    clear_requested = Signal()

    def __init__(self, limit: int) -> None:
        super().__init__(objectName="card")
        self.limit = limit
        self._items: dict[int, QListWidgetItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(QLabel("COMMAND HISTORY", objectName="cardTitle"))
        header.addStretch()
        self.clear_button = QPushButton("Clear", objectName="small")
        self.clear_button.setToolTip("Remove all commands from this session's history")
        self.clear_button.clicked.connect(self.clear_requested)
        header.addWidget(self.clear_button)
        layout.addLayout(header)

        self.list = QListWidget()
        self.list.setAccessibleName("Command history")
        self.list.setWordWrap(True)
        self.empty_label = QLabel(
            "No commands yet. Spoken commands will appear here.",
            objectName="muted", alignment=Qt.AlignmentFlag.AlignCenter, wordWrap=True,
        )
        self._stack = QStackedLayout()
        self._stack.addWidget(self.empty_label)
        self._stack.addWidget(self.list)
        layout.addLayout(self._stack)
        self._refresh_empty_state()

    @property
    def count(self) -> int:
        return self.list.count()

    def add_record(self, record: CommandRecord) -> None:
        item = QListWidgetItem()
        self._items[record.id] = item
        self._apply(item, record)
        self.list.insertItem(0, item)
        while self.list.count() > self.limit:
            oldest = self.list.takeItem(self.list.count() - 1)
            self._items = {k: v for k, v in self._items.items() if v is not oldest}
        self._refresh_empty_state()

    def update_record(self, record: CommandRecord) -> None:
        item = self._items.get(record.id)
        if item is not None:
            self._apply(item, record)

    def clear(self) -> None:
        self.list.clear()
        self._items.clear()
        self._refresh_empty_state()

    def item_text(self, row: int) -> str:
        return self.list.item(row).text()

    @staticmethod
    def _apply(item: QListWidgetItem, record: CommandRecord) -> None:
        symbol, color = OUTCOME_LABELS[record.outcome]
        line = f"{symbol}  {record.timestamp:%H:%M}   {record.command}"
        if record.response:
            line += f"\n      {record.response}"
        item.setText(line)
        item.setForeground(QColor(color if record.outcome is not Outcome.SUCCESS else theme.TEXT))
        item.setToolTip(f"{record.outcome.value.title()} at {record.timestamp:%H:%M:%S}")

    def _refresh_empty_state(self) -> None:
        self._stack.setCurrentWidget(self.list if self.list.count() else self.empty_label)
        self.clear_button.setEnabled(self.list.count() > 0)
