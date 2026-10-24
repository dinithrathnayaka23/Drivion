"""Icons drawn in code, so the app ships without image assets for now."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from drivion.core.state import AppState

STATE_COLORS: dict[AppState, str] = {
    AppState.STANDBY: "#3f6a9e",
    AppState.VERIFYING: "#f2b544",
    AppState.ACTIVE: "#4fd8ff",
    AppState.SLEEPING: "#3f6a9e",
    AppState.ERROR: "#ff5a6e",
    AppState.SHUTTING_DOWN: "#55657d",
}


def state_icon(state: AppState, size: int = 64) -> QIcon:
    color = QColor(STATE_COLORS[state])
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    margin = size * 0.08
    outer = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    painter.setBrush(QColor("#0a1428"))
    painter.setPen(QPen(color, size * 0.09))
    painter.drawEllipse(outer)
    core = size * 0.22
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QRectF(size / 2 - core / 2, size / 2 - core / 2, core, core))
    painter.end()
    return QIcon(pixmap)
