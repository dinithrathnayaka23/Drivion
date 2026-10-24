"""The animated Drivion indicator in the centre of the dashboard.

Each state has its own motion so it can be recognised at a glance:

* STANDBY / SLEEPING - slow, dim breathing
* VERIFYING          - amber scanning arcs
* ACTIVE             - cyan pulse with an outward ripple
* ERROR              - slow red throb

Performance: the frame timer only runs while the widget is visible, so a
hidden dashboard (standby) costs no CPU. With ``animated=False`` a static
frame is drawn instead (for users who prefer reduced motion).
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from drivion.core.state import AppState
from drivion.ui.theme import STATE_COLORS

FRAME_INTERVAL_MS = 33  # ~30 fps: smooth enough, cheap enough

# (breathing period in seconds, arc rotation in degrees per second, brightness)
_MOTION: dict[AppState, tuple[float, float, float]] = {
    AppState.STANDBY: (5.0, 12.0, 0.55),
    AppState.SLEEPING: (5.0, 8.0, 0.45),
    AppState.VERIFYING: (1.4, 220.0, 0.9),
    AppState.ACTIVE: (2.2, 40.0, 1.0),
    AppState.ERROR: (2.8, 0.0, 0.85),
    AppState.SHUTTING_DOWN: (6.0, 0.0, 0.3),
}


class StateOrb(QWidget):
    def __init__(self, animated: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.animated = animated
        self._state = AppState.STANDBY
        self._color = QColor(STATE_COLORS[self._state])
        self._start = time.monotonic()
        self._elapsed = 0.0

        self.setMinimumSize(160, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Drivion status indicator")

        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

        self._color_animation = QVariantAnimation(self)
        self._color_animation.setDuration(450)
        self._color_animation.valueChanged.connect(self._on_color_step)

    # ----- public API -----------------------------------------------------------

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def color(self) -> QColor:
        return QColor(self._color)

    @property
    def is_animating(self) -> bool:
        return self._timer.isActive()

    def set_state(self, state: AppState) -> None:
        self._state = state
        self.setAccessibleDescription(f"State {state}")
        target = QColor(STATE_COLORS[state])
        self._color_animation.stop()
        if self.animated and self.isVisible():
            self._color_animation.setStartValue(self._color)
            self._color_animation.setEndValue(target)
            self._color_animation.start()
        else:
            self._color = target
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(280, 280)

    # ----- animation lifecycle -------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.animated:
            self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()
        self._color_animation.stop()
        self._color = QColor(STATE_COLORS[self._state])

    def _tick(self) -> None:
        self._elapsed = time.monotonic() - self._start
        self.update()

    def _on_color_step(self, value: QColor) -> None:
        self._color = QColor(value)
        self.update()

    # ----- painting --------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        period, spin, brightness = _MOTION[self._state]
        t = self._elapsed if self.animated else 0.0
        wave = 0.5 + 0.5 * math.sin(2 * math.pi * t / period)  # 0..1

        side = min(self.width(), self.height())
        radius = side * 0.30
        center = QPointF(self.width() / 2, self.height() / 2)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        self._paint_glow(painter, center, radius, wave, brightness)
        if self._state is AppState.ACTIVE:
            self._paint_ripple(painter, center, radius, t, period)
        self._paint_ring(painter, center, radius, brightness)
        self._paint_arcs(painter, center, radius, t * spin, brightness)
        self._paint_core(painter, center, radius, wave, brightness)
        painter.end()

    def _with_alpha(self, alpha: float) -> QColor:
        color = QColor(self._color)
        color.setAlphaF(max(0.0, min(1.0, alpha)))
        return color

    def _paint_glow(self, p: QPainter, c: QPointF, r: float, wave: float, b: float) -> None:
        glow_r = r * (1.55 + 0.08 * wave)
        gradient = QRadialGradient(c, glow_r)
        gradient.setColorAt(0.0, self._with_alpha(0.35 * b))
        gradient.setColorAt(0.55, self._with_alpha(0.12 * b * (0.6 + 0.4 * wave)))
        gradient.setColorAt(1.0, self._with_alpha(0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(gradient)
        p.drawEllipse(c, glow_r, glow_r)

    def _paint_ripple(self, p: QPainter, c: QPointF, r: float, t: float, period: float) -> None:
        progress = (t % period) / period  # 0..1, restarts every period
        ripple_r = r * (1.05 + 0.5 * progress)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self._with_alpha(0.45 * (1 - progress)), max(1.0, r * 0.02)))
        p.drawEllipse(c, ripple_r, ripple_r)

    def _paint_ring(self, p: QPainter, c: QPointF, r: float, b: float) -> None:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self._with_alpha(0.35 * b), max(1.0, r * 0.025)))
        p.drawEllipse(c, r * 1.12, r * 1.12)

    def _paint_arcs(self, p: QPainter, c: QPointF, r: float, angle: float, b: float) -> None:
        arc_r = r * 1.25
        rect = QRectF(c.x() - arc_r, c.y() - arc_r, 2 * arc_r, 2 * arc_r)
        pen = QPen(self._with_alpha(0.85 * b), max(1.5, r * 0.045))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Qt angles are in 1/16th of a degree, counter-clockwise.
        for offset in (0, 180):
            p.drawArc(rect, int((-angle + offset) * 16), 55 * 16)

    def _paint_core(self, p: QPainter, c: QPointF, r: float, wave: float, b: float) -> None:
        core_r = r * (0.92 + 0.05 * wave)
        gradient = QRadialGradient(QPointF(c.x() - core_r * 0.25, c.y() - core_r * 0.3), core_r * 1.3)
        highlight = QColor(self._color).lighter(160)
        highlight.setAlphaF(0.95 * b)
        gradient.setColorAt(0.0, highlight)
        gradient.setColorAt(0.45, self._with_alpha(0.75 * b))
        gradient.setColorAt(1.0, QColor(10, 20, 40, 235))
        p.setPen(QPen(self._with_alpha(0.9 * b), max(1.0, r * 0.02)))
        p.setBrush(gradient)
        p.drawEllipse(c, core_r, core_r)
