"""Простой real-time график для EMG/MEMS без внешних зависимостей."""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Iterable, Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets


class SignalPlot(QtWidgets.QWidget):
    """Лёгкий виджет графика с авто-масштабом и опциональной демо-анимацией."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        max_points: int = 300,
        demo_mode: bool = False,
        thresholds: Optional[Tuple[float, float, float]] = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.values: deque[float] = deque(maxlen=max_points)
        self.thresholds = thresholds
        self.events: deque[Tuple[int, str]] = deque(maxlen=20)
        self._demo_mode = demo_mode
        self._demo_phase = 0.0

        if demo_mode:
            self._demo_timer = QtCore.QTimer(self)
            self._demo_timer.timeout.connect(self._add_demo_point)
            self._demo_timer.start(50)

    # Public API ----------------------------------------------------------
    def set_thresholds(self, low: float, mid: float, high: float) -> None:
        self.thresholds = (low, mid, high)
        self.update()

    def append_point(self, value: float, event: Optional[str] = None) -> None:
        self.values.append(value)
        if event:
            self.events.append((len(self.values) - 1, event))
        self.update()

    def extend(self, values: Iterable[float]) -> None:
        self.values.extend(values)
        self.update()

    # Painting ------------------------------------------------------------
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(10, 10, -10, -10)
        painter.fillRect(self.rect(), QtGui.QColor("#0b1224"))

        # Grid
        painter.setPen(QtGui.QPen(QtGui.QColor("#1f2937"), 1))
        for x in range(0, rect.width(), max(1, rect.width() // 8)):
            painter.drawLine(rect.left() + x, rect.top(), rect.left() + x, rect.bottom())
        for y in range(0, rect.height(), max(1, rect.height() // 4)):
            painter.drawLine(rect.left(), rect.top() + y, rect.right(), rect.top() + y)

        if not self.values:
            painter.end()
            return

        v_min = min(self.values)
        v_max = max(self.values)
        span = max(v_max - v_min, 1e-6)

        # thresholds
        if self.thresholds:
            painter.setPen(QtGui.QPen(QtGui.QColor("#22c55e"), 1, QtCore.Qt.PenStyle.DashLine))
            for level, color in zip(self.thresholds, ("#22c55e", "#f59e0b", "#ef4444")):
                y = rect.bottom() - (level - v_min) / span * rect.height()
                painter.setPen(QtGui.QPen(QtGui.QColor(color), 1, QtCore.Qt.PenStyle.DashLine))
                painter.drawLine(rect.left(), int(y), rect.right(), int(y))

        path = QtGui.QPainterPath()
        step_x = rect.width() / max(len(self.values) - 1, 1)
        for idx, val in enumerate(self.values):
            x = rect.left() + idx * step_x
            y = rect.bottom() - (val - v_min) / span * rect.height()
            if idx == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QtGui.QPen(QtGui.QColor("#60a5fa"), 2))
        painter.drawPath(path)

        # Events markers
        painter.setPen(QtGui.QPen(QtGui.QColor("#a855f7"), 1.5))
        for idx, name in self.events:
            x = rect.left() + idx * step_x
            painter.drawLine(x, rect.top(), x, rect.bottom())
            painter.drawText(int(x) + 4, rect.top() + 16, name)

        painter.end()

    # Demo ----------------------------------------------------------------
    def _add_demo_point(self) -> None:
        # Пульс + шум для живости
        self._demo_phase += 0.15
        value = 0.4 + 0.25 * (1 + math.cos(self._demo_phase)) + random.uniform(-0.05, 0.05)
        self.append_point(value)
