"""Индикатор силы мышцы (EMG) с градиентом и отметками порогов."""

from __future__ import annotations

from typing import Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets


class MuscleBar(QtWidgets.QWidget):
    """Горизонтальный бар: зелёный → жёлтый → красный, с отметками порогов."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None, thresholds: Optional[Tuple[float, float]] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(36)
        self._value = 0.0
        self.thresholds = thresholds or (0.4, 0.7)  # mid / high как доля MVC

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(1.0, value))
        self.update()

    def set_thresholds(self, mid: float, high: float) -> None:
        self.thresholds = (mid, high)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(6, 6, -6, -6)

        painter.setBrush(QtGui.QColor("#111827"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#1f2937"), 1))
        painter.drawRoundedRect(rect, 10, 10)

        fill_width = int(rect.width() * self._value)
        gradient = QtGui.QLinearGradient(QtCore.QPointF(rect.topLeft()), QtCore.QPointF(rect.topRight()))
        gradient.setColorAt(0.0, QtGui.QColor("#22c55e"))
        gradient.setColorAt(0.6, QtGui.QColor("#f59e0b"))
        gradient.setColorAt(1.0, QtGui.QColor("#ef4444"))
        fill_rect = QtCore.QRect(rect.left(), rect.top(), fill_width, rect.height())
        painter.setBrush(QtGui.QBrush(gradient))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawRoundedRect(fill_rect, 10, 10)

        painter.setPen(QtGui.QPen(QtGui.QColor("#9ca3af")))
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, f"{int(self._value*100)}%")

        # Пороговые линии
        mid, high = self.thresholds
        for level, color in ((mid, "#fbbf24"), (high, "#ef4444")):
            x = rect.left() + int(rect.width() * level)
            painter.setPen(QtGui.QPen(QtGui.QColor(color), 2, QtCore.Qt.PenStyle.DashLine))
            painter.drawLine(x, rect.top(), x, rect.bottom())

        painter.end()
