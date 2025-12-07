"""Круговой индикатор усталости 0-100% с трендом."""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets


class FatigueGauge(QtWidgets.QWidget):
    """Простой круговой индикатор: зелёный → жёлтый → красный."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(140, 140)
        self._value = 0
        self._trend = 0  # -1 восстановление, 0 стабильно, 1 растёт

    def set_value(self, value: int, trend: int = 0) -> None:
        self._value = max(0, min(100, value))
        self._trend = max(-1, min(1, trend))
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)

        painter.fillRect(self.rect(), QtGui.QColor("#0b1224"))

        # Фон круга
        painter.setPen(QtGui.QPen(QtGui.QColor("#1f2937"), 10))
        painter.drawEllipse(rect)

        # Цвет по уровню усталости
        if self._value < 40:
            color = "#22c55e"
        elif self._value < 70:
            color = "#f59e0b"
        else:
            color = "#ef4444"

        start_angle = -90 * 16
        span = int(-360 * 16 * (self._value / 100))
        painter.setPen(QtGui.QPen(QtGui.QColor(color), 10, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, start_angle, span)

        painter.setPen(QtGui.QColor("#e5e7eb"))
        font = painter.font()
        font.setPointSize(20)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, f"{self._value}%")

        trend_icon = "↗" if self._trend > 0 else "→" if self._trend == 0 else "↘"
        font.setPointSize(12)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QtGui.QColor("#9ca3af"))
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignBottom | QtCore.Qt.AlignmentFlag.AlignHCenter, f"Тренд {trend_icon}")

        painter.end()
